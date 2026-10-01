using System;
using System.Collections.Generic;
using System.Text.Json.Nodes;
using Il2CppInterop.Runtime;
using UnityEngine;

namespace BigWalk.EvalBridge;

/// <summary>
/// Find scene objects by GameObject name or component type name (substring,
/// case-insensitive), nearest to "near" first. For authoring puzzle files: it
/// finds switches, telescopes and gourds without walking there. Not an agent tool.
///   args: name?, component?, near?, radius?, limit?, include_inactive?, components?
/// </summary>
internal static class SceneFind
{
    public static JsonNode Run(JsonObject args)
    {
        var name = args["name"]?.GetValue<string>();
        var component = args["component"]?.GetValue<string>();
        if (string.IsNullOrEmpty(name) && string.IsNullOrEmpty(component))
            throw new ArgumentException("give name or component");
        Vector3? near = args["near"] != null ? Json.ToVec(args["near"]) : null;
        var radius = args["radius"]?.GetValue<float>() ?? float.MaxValue;
        var limit = args["limit"]?.GetValue<int>() ?? 40;
        var includeInactive = args["include_inactive"]?.GetValue<bool>() ?? false;
        var listComponents = args["components"]?.GetValue<bool>() ?? true;

        var seen = new HashSet<IntPtr>();
        var found = new List<(float, GameObject)>();
        void Consider(GameObject go)
        {
            if (go == null || !seen.Add(go.Pointer)) return;
            if (!go.scene.IsValid()) return; // prefab assets, not scene objects
            if (!includeInactive && !go.activeInHierarchy) return;
            var distance = near.HasValue ? Vector3.Distance(near.Value, go.transform.position) : 0f;
            if (distance > radius) return;
            found.Add((distance, go));
        }

        if (!string.IsNullOrEmpty(component))
        {
            foreach (var obj in Resources.FindObjectsOfTypeAll(Il2CppType.Of<Component>()))
            {
                var c = obj.TryCast<Component>();
                if (c == null || !Contains(c.GetIl2CppType().Name, component)) continue;
                if (!string.IsNullOrEmpty(name) && !Contains(c.gameObject.name, name)) continue;
                Consider(c.gameObject);
            }
        }
        else
        {
            foreach (var obj in Resources.FindObjectsOfTypeAll(Il2CppType.Of<GameObject>()))
            {
                var go = obj.TryCast<GameObject>();
                if (go != null && Contains(go.name, name)) Consider(go);
            }
        }

        found.Sort((a, b) => a.Item1.CompareTo(b.Item1));
        var objects = new JsonArray();
        for (var i = 0; i < found.Count && i < limit; i++)
        {
            var (distance, go) = found[i];
            var entry = new JsonObject
            {
                ["name"] = go.name,
                ["path"] = PathOf(go.transform),
                ["position"] = Json.Vec(go.transform.position),
                ["yaw_deg"] = Math.Round(Json.Angle(go.transform.eulerAngles.y), 1),
                ["active"] = go.activeInHierarchy,
            };
            var gourd = go.GetComponent<RewardGourd>();
            if (gourd != null) entry["gourd_state"] = gourd.gourdState.ToString();
            if (near.HasValue) entry["distance"] = Math.Round(distance, 2);
            if (listComponents)
            {
                var names = new JsonArray();
                foreach (var c in go.GetComponents(Il2CppType.Of<Component>()))
                {
                    var type = c.GetIl2CppType().Name;
                    if (type != "Transform") names.Add(type);
                }

                entry["components"] = names;
            }

            objects.Add(entry);
        }

        return new JsonObject { ["count"] = found.Count, ["objects"] = objects };
    }

    private static bool Contains(string text, string part) =>
        text != null && text.IndexOf(part, StringComparison.OrdinalIgnoreCase) >= 0;

    internal static string PathOf(Transform t)
    {
        var parts = new List<string>();
        for (var i = 0; t != null && i < 6; i++, t = t.parent) parts.Insert(0, t.name);
        return string.Join("/", parts);
    }
}

/// <summary>
/// Puzzle state near a point: each TrackedPeckState (state int, for doors,
/// boxes and buttons) and each PeckSwitch that a body holds down.
///   args: near, radius?, include_inactive?
/// </summary>
internal static class PeckStates
{
    public static JsonNode Run(JsonObject args)
    {
        var near = Json.ToVec(args["near"] ?? throw new ArgumentException("missing argument near"));
        var radius = args["radius"]?.GetValue<float>() ?? 10f;
        var includeInactive = args["include_inactive"]?.GetValue<bool>() ?? false;

        var states = new JsonArray();
        foreach (var obj in Resources.FindObjectsOfTypeAll(Il2CppType.Of<TrackedPeckState>()))
        {
            var s = obj.TryCast<TrackedPeckState>();
            if (!InRange(s, near, radius, includeInactive)) continue;
            states.Add(new JsonObject
            {
                ["path"] = SceneFind.PathOf(s.transform),
                ["label"] = s.label,
                ["state"] = s.currentPeckContext.state,
            });
        }

        var held = new JsonArray();
        foreach (var obj in Resources.FindObjectsOfTypeAll(Il2CppType.Of<PeckSwitch>()))
        {
            var sw = obj.TryCast<PeckSwitch>();
            if (!InRange(sw, near, radius, includeInactive) || sw.playerHoldingThis == null) continue;
            held.Add(new JsonObject
            {
                ["path"] = SceneFind.PathOf(sw.transform),
                ["slot"] = Practice.SlotOf(sw.playerHoldingThis.netId),
            });
        }

        return new JsonObject { ["states"] = states, ["held_switches"] = held };
    }

    private static bool InRange(Component c, Vector3 near, float radius, bool includeInactive) =>
        c != null && c.gameObject.scene.IsValid() && (includeInactive || c.gameObject.activeInHierarchy)
        && Vector3.Distance(near, c.transform.position) <= radius;
}

/// <summary>
/// Make bodies let go of the world switches they hold down (PeckSwitch.playerHoldingThis).
/// A held switch stays held when its body becomes inactive, and a later OS button
/// release does not reach it, so reset calls this. args: slots? (default: every body).
/// Result: the released switches.
/// </summary>
internal static class ReleaseSwitches
{
    public static JsonNode Run(JsonObject args)
    {
        HashSet<int> slots = null;
        if (args["slots"] is JsonArray wanted)
        {
            slots = new HashSet<int>();
            foreach (var s in wanted) slots.Add(s.GetValue<int>());
        }

        var released = new JsonArray();
        foreach (var obj in Resources.FindObjectsOfTypeAll(Il2CppType.Of<PeckSwitch>()))
        {
            var sw = obj.TryCast<PeckSwitch>();
            var holder = sw?.playerHoldingThis;
            if (holder == null || !sw.gameObject.scene.IsValid()) continue;
            var slot = Practice.SlotOf(holder.netId);
            if (slots != null && !slots.Contains(slot)) continue;
            released.Add(new JsonObject
            {
                ["path"] = SceneFind.PathOf(sw.transform),
                ["slot"] = slot,
            });
            Release(sw, holder);
        }

        return new JsonObject { ["released"] = released };
    }

    /// <summary>
    /// Peck the switch's up-switch, as a release does. Tested with an inactive holder:
    /// PlayerNetworking.ServerForceLetGoSwitch and the server side of CmdReleaseHeldSwitch
    /// leave the switch held.
    /// </summary>
    private static void Release(PeckSwitch sw, PlayerCharacter holder)
    {
        var context = new PeckContext { playerIdentity = holder.netIdentity, state = 0 };
        if (sw.upSwitch != null) sw.upSwitch.Peck(context);
        sw.playerHoldingThis = null;
    }
}
