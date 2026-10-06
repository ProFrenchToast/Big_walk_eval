using System;
using System.Collections.Generic;
using System.Text.Json.Nodes;
using Il2CppInterop.Runtime;
using UnityEngine;

namespace BigWalk.EvalBridge;

/// <summary>
/// Keeps the text chat right under hot-swap. The game sets a body's head text
/// (TextChatSource.isLocalPlayer) when the body spawns, and the practice mod spawns
/// each body as the local player. Then every head text counts as "mine" and stays
/// hidden, and the one HUD echo of the typed message (TextChatInput.output) shows the
/// last body's message to whoever is active. After a switch: only the active body's
/// head text is local, and the HUD echo shows the active body's own last message.
/// Tested in the game (2026-10-01): the message then shows over the speaker's head
/// to the other bodies, and not on their HUD.
/// </summary>
internal static class ChatSync
{
    private static readonly Dictionary<uint, string> EchoByBody = new();
    private static uint _echoOwner;
    private static uint _lastLocal;

    /// <summary>Sync once each time the local body changes. Runs every frame.</summary>
    public static void Tick()
    {
        var local = Mirror.NetworkClient.localPlayer;
        var id = local != null ? local.netId : 0;
        if (id == 0 || id == _lastLocal) return;
        _lastLocal = id;
        AfterSwitch();
    }

    /// <summary>Remove every chat message from the heads and the HUD, for a new episode.</summary>
    public static JsonNode Clear()
    {
        var cleared = 0;
        foreach (var obj in Resources.FindObjectsOfTypeAll(Il2CppType.Of<TextChatSource>()))
        {
            var source = obj.TryCast<TextChatSource>();
            // A source the game never initialized has no message list, and clearing it throws.
            if (source == null || !source.gameObject.scene.IsValid() || source.activeMessages == null) continue;
            try
            {
                source.ClearMesssages();
                cleared++;
            }
            catch (Exception e)
            {
                Plugin.Trace.LogWarning($"Chat clear failed for {SceneFind.PathOf(source.transform)}: {e.Message}");
            }
        }

        EchoByBody.Clear();
        var input = TextChatInput.instance;
        if (input != null)
        {
            if (input.inputIsOpen) input.CloseInput();
            if (input.output != null) input.output.text = "";
            if (input.inputField != null) input.inputField.text = "";
        }

        return new JsonObject { ["cleared_sources"] = cleared };
    }

    /// <summary>
    /// The local player's chat box. The box is one field for the local player, and its
    /// open state also lives in the body's texter, so the server closes it before a switch.
    /// </summary>
    public static JsonNode Input()
    {
        var input = TextChatInput.instance;
        return new JsonObject
        {
            ["open"] = input != null && input.inputIsOpen,
            ["text"] = input != null && input.inputField != null ? input.inputField.text : "",
        };
    }

    public static void AfterSwitch()
    {
        PlayerCharacter local = null;
        foreach (var pc in PlayerCharacter.allPlayerCharacters)
        {
            if (pc == null || pc.texter == null) continue;
            var isLocal = pc.isLocalPlayer;
            if (isLocal) local = pc;
            var source = pc.texter.source;
            if (source != null && source.isLocalPlayer != isLocal)
            {
                source.isLocalPlayer = isLocal;
                Plugin.Trace.LogInfo($"Chat: body {pc.netId} head text local={isLocal}");
            }
        }

        var input = TextChatInput.instance;
        if (input == null || input.output == null || local == null) return;
        try
        {
            if (_echoOwner != 0) EchoByBody[_echoOwner] = input.output.text;
            _echoOwner = local.netId;
            input.output.text = EchoByBody.TryGetValue(local.netId, out var echo) ? echo : "";
        }
        catch (Exception e)
        {
            Plugin.Trace.LogWarning($"Chat echo swap failed: {e.Message}");
        }
    }
}
