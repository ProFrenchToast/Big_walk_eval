using System;
using System.Text.Json.Nodes;
using Mirror;
using Rewired;

namespace BigWalk.EvalBridge;

/// <summary>
/// The keyboard and mouse bindings of every game action, read from Rewired
/// (saved user bindings, else the defaults). The harness uses this to write
/// the controls into the system prompt.
/// </summary>
internal static class Controls
{
    private static readonly string[] Actions =
    {
        "moveX", "moveY", "use", "drop", "jump", "sprint", "crouch", "sit",
        "waveLeft", "waveRight", "textChat", "mute", "start", "select",
    };

    public static JsonNode Run()
    {
        var playerId = 0;
        var pc = NetworkClient.localPlayer != null
            ? NetworkClient.localPlayer.GetComponent<PlayerCharacter>()
            : null;
        if (pc != null && pc.inputPlayer != null) playerId = pc.inputPlayer.id;

        var keyboard = ReInput.mapping.GetKeyboardMapInstanceSavedOrDefault(playerId, "Default", "Default");
        var mouse = ReInput.mapping.GetMouseMapInstanceSavedOrDefault(playerId, "Default", "Default");
        var result = new JsonObject { ["player_id"] = playerId };
        foreach (var action in Actions)
        {
            var bindings = new JsonArray();
            Add(bindings, "keyboard", keyboard, action);
            Add(bindings, "mouse", mouse, action);
            result[action] = bindings;
        }

        return result;
    }

    private static void Add(JsonArray into, string device, ControllerMap map, string action)
    {
        if (map == null) return;
        foreach (var aem in map.GetElementMapsWithAction(action))
        {
            into.Add(new JsonObject
            {
                ["device"] = device,
                ["element"] = aem.elementIdentifierName,
                ["pole"] = aem.axisContribution == Pole.Positive ? "+" : "-",
                ["enabled"] = aem.enabled,
            });
        }
    }
}
