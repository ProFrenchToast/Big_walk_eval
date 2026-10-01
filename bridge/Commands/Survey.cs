using System;
using System.Collections.Generic;
using System.Text.Json.Nodes;
using Il2CppInterop.Runtime;
using UnityEngine;

namespace BigWalk.EvalBridge;

/// <summary>
/// For writing the puzzle catalogue (scripts/survey_puzzles.py). Not an agent tool.
///   survey: every reward gourd (save name, start home, house number), every dev
///     teleport point, and every puzzle mechanism of the types in <see cref="Mechanisms"/>,
///     each with its world position and its map coordinates (the numbers the in-game
///     GPS device and the paper map show).
///   map_coords {positions}: world positions to map coordinates.
///   ground {positions, up?, down?}: the first surface below each position.
/// </summary>
internal static class Survey
{
    // Component types that tell what a puzzle needs: simultaneous presses, blocked
    // voice, headsets (sound), masks and blindfolds, telescopes, timers, counting.
    private static readonly string[] Mechanisms =
    {
        "SimPressController", "SimPressSwitch", "PeckLogicSimPressOld", "SpeechlessZone",
        "VoiceBlockedAudio", "PeckEffectHeadset", "PitchDetector", "PeckEffectMask", "BlindfoldPopper",
        "PeckEffectTelescope", "PlayerSpecificTurnstile", "PeckEffectTimer", "PeckEffectTimerNetworked",
        "TimerDialController", "CountingController", "PegTileValidator", "PegTileSequenceGenerator",
        "PressInOrder", "ConductorPanel", "ProgressTracker", "BroadcastStation", "FlareDriver",
        "PeckEffectTeleporter", "PeckLogicRadioListener", "PeckLogicScrambler", "PeckEffectLaunchProp",
        "SweeperBrain", "Maypole", "MedalPlatforming", "MedalZone", "KeyDependantPeckSwitch",
        "StreetNumber", "GPSTracker", "CoordinatesHelper", "NetworkedTrain", "SecretZoneController",
    };

    public static JsonNode Run(JsonObject args)
    {
        var gourds = new JsonArray();
        foreach (var obj in Resources.FindObjectsOfTypeAll(Il2CppType.Of<RewardGourd>()))
        {
            var gourd = obj.TryCast<RewardGourd>();
            if (gourd == null || !gourd.gameObject.scene.IsValid()) continue;
            var prop = gourd.prop ?? gourd.GetComponent<Prop>();
            var entry = Entry(gourd.transform);
            entry["active"] = gourd.gameObject.activeInHierarchy;
            entry["gourd_state"] = gourd.gourdState.ToString();
            entry["variant_challenge"] = gourd.isVariantChallenge;
            if (prop != null)
            {
                entry["save_name"] = prop.saveablePropName.ToString();
                entry["house_number"] = Try(() => StreetNumber.GetHouseNumber(prop.saveablePropName));
                if (prop.startHome != null) entry["start_home"] = Entry(prop.startHome.transform);
            }

            gourds.Add(entry);
        }

        var teleports = new JsonArray();
        foreach (var obj in Resources.FindObjectsOfTypeAll(Il2CppType.Of<TeleportPoint>()))
        {
            var point = obj.TryCast<TeleportPoint>();
            if (point == null || !point.gameObject.scene.IsValid()) continue;
            var entry = Entry(point.transform);
            entry["custom_name"] = point.customName;
            entry["cheat_code"] = point.cheatCode;
            teleports.Add(entry);
        }

        var wanted = new HashSet<string>(Mechanisms);
        var mechanisms = new JsonArray();
        foreach (var obj in Resources.FindObjectsOfTypeAll(Il2CppType.Of<Component>()))
        {
            var c = obj.TryCast<Component>();
            if (c == null || !c.gameObject.scene.IsValid()) continue;
            var type = c.GetIl2CppType().Name;
            if (!wanted.Contains(type)) continue;
            var entry = Entry(c.transform);
            entry["type"] = type;
            entry["active"] = c.gameObject.activeInHierarchy;
            Details(c, type, entry);
            mechanisms.Add(entry);
        }

        return new JsonObject { ["gourds"] = gourds, ["teleport_points"] = teleports, ["mechanisms"] = mechanisms };
    }

    /// <summary>The children of every scene object with this exact name. args: name, include_inactive?</summary>
    public static JsonNode Children(JsonObject args)
    {
        var name = args["name"]?.GetValue<string>() ?? throw new ArgumentException("missing argument name");
        var includeInactive = args["include_inactive"]?.GetValue<bool>() ?? true;
        var parents = new JsonArray();
        foreach (var obj in Resources.FindObjectsOfTypeAll(Il2CppType.Of<GameObject>()))
        {
            var go = obj.TryCast<GameObject>();
            if (go == null || go.name != name || !go.scene.IsValid()) continue;
            var children = new JsonArray();
            for (var i = 0; i < go.transform.childCount; i++)
            {
                var child = go.transform.GetChild(i);
                if (!includeInactive && !child.gameObject.activeInHierarchy) continue;
                var entry = Entry(child);
                entry["name"] = child.name;
                entry["active"] = child.gameObject.activeInHierarchy;
                children.Add(entry);
            }

            var parent = Entry(go.transform);
            parent["children"] = children;
            parents.Add(parent);
        }

        return new JsonObject { ["parents"] = parents };
    }

    /// <summary>
    /// A profile of each puzzle: for every child of the named parents (the puzzle
    /// roots, such as LandmarksPlayerCountAny), the count of each component type
    /// under it, and the position of each world switch (PeckSwitch), prop home and
    /// prop. args: parents (names), include_inactive? (false)
    /// </summary>
    public static JsonNode Roots(JsonObject args)
    {
        var includeInactive = args["include_inactive"]?.GetValue<bool>() ?? false;
        var wanted = new HashSet<string>();
        foreach (var p in args["parents"]?.AsArray() ?? throw new ArgumentException("missing argument parents"))
            wanted.Add(p.GetValue<string>());

        var roots = new JsonArray();
        foreach (var obj in Resources.FindObjectsOfTypeAll(Il2CppType.Of<GameObject>()))
        {
            var go = obj.TryCast<GameObject>();
            if (go == null || !wanted.Contains(go.name) || !go.scene.IsValid()) continue;
            for (var i = 0; i < go.transform.childCount; i++)
            {
                var root = go.transform.GetChild(i);
                if (!includeInactive && !root.gameObject.activeInHierarchy) continue;
                roots.Add(Profile(root, includeInactive));
            }
        }

        return new JsonObject { ["roots"] = roots };
    }

    private static JsonObject Profile(Transform root, bool includeInactive)
    {
        var counts = new SortedDictionary<string, int>();
        var switches = new JsonArray();
        var homes = new JsonArray();
        var props = new JsonArray();
        foreach (var c in root.GetComponentsInChildren(Il2CppType.Of<Component>(), includeInactive))
        {
            var type = c.GetIl2CppType().Name;
            if (type == "Transform") continue;
            counts[type] = counts.TryGetValue(type, out var n) ? n + 1 : 1;
            var position = Json.Vec(c.transform.position);
            var path = Relative(c.transform, root);
            switch (type)
            {
                case "PeckSwitch":
                    switches.Add(new JsonObject { ["path"] = path, ["position"] = position });
                    break;
                case "PropHome":
                    homes.Add(new JsonObject { ["path"] = path, ["position"] = position });
                    break;
                case "Prop":
                    props.Add(new JsonObject
                    {
                        ["type"] = HeldItems.TypeName(c.TryCast<Prop>()),
                        ["path"] = path,
                        ["position"] = position,
                    });
                    break;
            }
        }

        var countsJson = new JsonObject();
        foreach (var (type, n) in counts) countsJson[type] = n;
        var entry = Entry(root);
        entry["name"] = root.name;
        entry["parent"] = root.parent.name;
        entry["counts"] = countsJson;
        entry["switches"] = switches;
        entry["homes"] = homes;
        entry["props"] = props;
        return entry;
    }

    private static string Relative(Transform t, Transform root)
    {
        var parts = new List<string>();
        for (; t != null && t != root; t = t.parent) parts.Insert(0, t.name);
        return string.Join("/", parts);
    }

    public static JsonNode MapCoords(JsonObject args)
    {
        var result = new JsonArray();
        foreach (var p in args["positions"]?.AsArray() ?? throw new ArgumentException("missing argument positions"))
            result.Add(Map(Json.ToVec(p)));
        return new JsonObject { ["map"] = result };
    }

    public static JsonNode Ground(JsonObject args)
    {
        var up = args["up"]?.GetValue<float>() ?? 2f;
        var down = args["down"]?.GetValue<float>() ?? 60f;
        var result = new JsonArray();
        foreach (var p in args["positions"]?.AsArray() ?? throw new ArgumentException("missing argument positions"))
        {
            var origin = Json.ToVec(p) + Vector3.up * up;
            if (Physics.Raycast(origin, Vector3.down, out var hit, up + down, Physics.DefaultRaycastLayers,
                    QueryTriggerInteraction.Ignore))
                result.Add(new JsonObject
                {
                    ["point"] = Json.Vec(hit.point),
                    ["collider"] = SceneFind.PathOf(hit.collider.transform),
                    ["normal_y"] = Math.Round(hit.normal.y, 3),
                });
            else
                result.Add(null);
        }

        return new JsonObject { ["ground"] = result };
    }

    private static JsonObject Entry(Transform t) => new()
    {
        ["path"] = SceneFind.PathOf(t),
        ["position"] = Json.Vec(t.position),
        ["yaw_deg"] = Math.Round(Json.Angle(t.eulerAngles.y), 1),
        ["map"] = Map(t.position),
    };

    private static JsonArray Map(Vector3 p) => new(GPSTracker.GetX(p), GPSTracker.GetZ(p));

    private static void Details(Component c, string type, JsonObject entry)
    {
        switch (type)
        {
            case "SpeechlessZone":
                var zone = c.TryCast<SpeechlessZone>();
                entry["outer_radius"] = zone.outerRadius;
                entry["inner_radius"] = zone.innerRadius;
                break;
            case "PeckEffectMask":
                entry["mask_type"] = c.TryCast<PeckEffectMask>().maskType.ToString();
                break;
            case "PeckEffectTelescope":
                entry["mask_type"] = c.TryCast<PeckEffectTelescope>().maskType.ToString();
                break;
            case "PeckEffectTimer":
                entry["duration_s"] = c.TryCast<PeckEffectTimer>().duration;
                break;
            case "ProgressTracker":
                entry["required_increments"] = c.TryCast<ProgressTracker>().requiredIncrements;
                break;
            case "StreetNumber":
                entry["save_name"] = c.TryCast<StreetNumber>().saveablePropName.ToString();
                break;
            case "PeckLogicSimPressOld":
                entry["notes"] = c.TryCast<PeckLogicSimPressOld>().notes;
                break;
        }
    }

    private static string Try(Func<string> f)
    {
        try { return f(); }
        catch (Exception e) { return "error: " + e.Message; }
    }
}
