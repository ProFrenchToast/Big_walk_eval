using System;
using System.Text.Json.Nodes;
using Il2CppInterop.Runtime;
using UnityEngine;

namespace BigWalk.EvalBridge;

/// <summary>
/// Text chat state, to find out where a message shows and to whom: every
/// TextChatSource (a body's head text or the screen text), each body's texter,
/// and the shared input field. For diagnosing only. Not an agent tool.
/// </summary>
internal static class ChatDebug
{
    public static JsonNode Run(JsonObject args)
    {
        if (args["sync"]?.GetValue<bool>() ?? false) ChatSync.AfterSwitch();
        var viewSlot = args["view_slot"]?.GetValue<int>() ?? 0;
        if (viewSlot == 0) return Report(Camera.main != null ? Camera.main.transform.position : null);

        var viewer = BodyCapture.Body(viewSlot) ?? throw new ArgumentException($"no body in slot {viewSlot}");
        var look = BodyCapture.Look(viewer);
        var undo = CaptureView.Apply(viewer, look.position, look.rotation);
        try
        {
            return Report(look.position);
        }
        finally
        {
            CaptureView.Undo(undo);
        }
    }

    /// <summary>
    /// <paramref name="eye"/> is the camera to estimate readability from: the main
    /// camera, or with view_slot that body's capture camera, with the scene set up as
    /// for its capture.
    /// </summary>
    private static JsonNode Report(Vector3? eye)
    {
        var bodies = new JsonArray();
        foreach (var pc in PlayerCharacter.allPlayerCharacters)
        {
            if (pc == null) continue;
            var entry = new JsonObject
            {
                ["slot"] = Practice.SlotOf(pc.netId),
                ["net_id"] = pc.netId,
                ["is_local_player"] = pc.isLocalPlayer,
            };
            Try(entry, "locally_readable", () => TextChatSource.IsPlayerTextLocallyReadable(pc));
            var texter = pc.texter;
            if (texter != null)
            {
                entry["source"] = Id(texter.source);
                entry["global_output"] = Id(texter.globalTextChatOutput);
                entry["is_player_text_chatting"] = texter.isPlayerTextChatting;
                entry["is_local_player_text_chatting"] = texter.isLocalPlayerTextChatting;
            }
            bodies.Add(entry);
        }

        var sources = new JsonArray();
        foreach (var obj in Resources.FindObjectsOfTypeAll(Il2CppType.Of<TextChatSource>()))
        {
            var s = obj.TryCast<TextChatSource>();
            if (s == null || !s.gameObject.scene.IsValid()) continue;
            sources.Add(Describe(s, eye));
        }

        var active = new JsonArray();
        if (TextChatSource.activeSources != null)
            foreach (var s in TextChatSource.activeSources) active.Add(Id(s));

        var input = new JsonObject();
        var instance = TextChatInput.instance;
        if (instance != null)
        {
            input["input_is_open"] = instance.inputIsOpen;
            Try(input, "char_limit", () => TextChatInput.CHARLIMIT);
            Try(input, "field_char_limit", () => instance.inputField != null ? instance.inputField.characterLimit : -1);
            Try(input, "output_text", () => instance.output != null ? instance.output.text : null);
            Try(input, "output_active", () => instance.output != null && instance.output.gameObject.activeInHierarchy);
            Try(input, "field_text", () => instance.inputField != null ? instance.inputField.text : null);
            var recent = new JsonArray();
            if (instance.recentMessages != null)
                foreach (var m in instance.recentMessages) recent.Add(m);
            input["recent_messages"] = recent;
        }

        return new JsonObject
        {
            ["bodies"] = bodies,
            ["sources"] = sources,
            ["active_sources"] = active,
            ["input"] = input,
            ["hud"] = Hud(),
        };
    }

    /// <summary>The screen-edge blips (TextChatHud) that point at speakers out of view.</summary>
    private static JsonArray Hud()
    {
        var huds = new JsonArray();
        foreach (var obj in Resources.FindObjectsOfTypeAll(Il2CppType.Of<TextChatHud>()))
        {
            var hud = obj.TryCast<TextChatHud>();
            if (hud == null || !hud.gameObject.scene.IsValid()) continue;
            var o = new JsonObject
            {
                ["path"] = SceneFind.PathOf(hud.transform),
                ["active"] = hud.gameObject.activeInHierarchy,
                ["enabled"] = hud.enabled,
            };
            var tracked = new JsonArray();
            Try(o, "n_hud_sources", () =>
            {
                if (hud._hudSources == null) return -1;
                foreach (var h in hud._hudSources)
                    tracked.Add(new JsonObject { ["source"] = Id(h.textChatSource), ["direction"] = h.blipDirectionType.ToString() });
                return hud._hudSources.Count;
            });
            o["hud_sources"] = tracked;
            o["left"] = Group(hud.blipGroupLeft);
            o["right"] = Group(hud.blipGroupRight);
            o["up"] = Group(hud.blipGroupUp);
            o["down"] = Group(hud.blipGroupDown);
            huds.Add(o);
        }
        return huds;
    }

    private static JsonObject Group(TextChatHud.BlipGroup g)
    {
        var o = new JsonObject();
        if (g == null) return o;
        Try(o, "n_sources", () => g._sources != null ? g._sources.Count : -1);
        var blips = new JsonArray();
        Try(o, "n_blips", () =>
        {
            if (g.blips == null) return -1;
            foreach (var b in g.blips)
                if (b != null)
                    blips.Add(new JsonObject { ["active"] = b.gameObject.activeInHierarchy, ["icon"] = b._blipIcon.ToString() });
            return g.blips.Length;
        });
        o["blips"] = blips;
        return o;
    }

    private static JsonObject Describe(TextChatSource s, Vector3? eye)
    {
        var o = new JsonObject
        {
            ["id"] = Id(s),
            ["path"] = SceneFind.PathOf(s.transform),
            ["active"] = s.gameObject.activeInHierarchy,
            ["enabled"] = s.enabled,
            ["is_local_player"] = s.isLocalPlayer,
            ["is_visible"] = s.isVisible,
            ["position"] = Json.Vec(s.transform.position),
        };
        Try(o, "audibility", () => Math.Round(s.audibility, 3));
        Try(o, "custom_aim", () => s.customAimTransform != null ? SceneFind.PathOf(s.customAimTransform) : null);
        Try(o, "damped", () => s.dampedTransform != null ? SceneFind.PathOf(s.dampedTransform) : null);
        Try(o, "n_active_messages", () => s.activeMessages != null ? s.activeMessages.Count : -1);
        Try(o, "combined", () => s.GetCombinedString());
        Try(o, "recent_message", () => s.mostRecentMessage.message);
        Try(o, "recent_sender_slot", () =>
            s.mostRecentMessage.sendingPlayer != null ? Practice.SlotOf(s.mostRecentMessage.sendingPlayer.netId) : 0);
        var text = s.textField;
        if (text != null)
        {
            Try(o, "text", () => text.text);
            Try(o, "text_go_active", () => text.gameObject.activeInHierarchy);
            Try(o, "text_enabled", () => text.enabled);
            Try(o, "text_alpha", () => Math.Round(text.alpha, 3));
            Try(o, "text_position", () => Json.Vec(text.transform.position));
            // TextMeshPro: world space (at a head). TextMeshProUGUI: screen space (on the HUD).
            Try(o, "text_type", () => text.GetIl2CppType().Name);
            Try(o, "text_euler", () => Json.Vec(text.transform.eulerAngles));
            Try(o, "text_scale", () => Math.Round(text.transform.lossyScale.x, 3));
            if (eye is { } from && text.gameObject.activeInHierarchy)
            {
                Try(o, "eye_distance", () => Math.Round(Vector3.Distance(from, text.transform.position), 2));
                Try(o, "estimated_readability", () => Math.Round(CaptureView.Readability(s, from, text.transform.position), 3));
            }
        }
        return o;
    }

    private static string Id(TextChatSource s) => s != null ? s.GetInstanceID().ToString() : null;

    private static void Try(JsonObject o, string key, Func<object> read)
    {
        try
        {
            var value = read();
            o[key] = value as JsonNode ?? JsonValue.Create(value);
        }
        catch (Exception e)
        {
            o[key] = $"error: {e.Message}";
        }
    }
}
