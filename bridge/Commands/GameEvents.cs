using System;
using System.Collections.Concurrent;
using System.Text.Json.Nodes;
using HarmonyLib;
using UnityEngine;

namespace BigWalk.EvalBridge;

/// <summary>
/// Event queue returned and cleared by the "events" command. Each event:
/// {"type": str, "slot": int|null, "t_ms": int, "data": {...}}.
/// Event names match FakeGame: item_picked_up, item_dropped, reward_state, text_chat.
/// text_chat_sent is real-game only: the local body sent a chat message.
/// </summary>
internal static class GameEvents
{
    private static readonly ConcurrentQueue<JsonObject> Queue = new();

    public static void Push(string type, int? slot, JsonObject data)
    {
        Queue.Enqueue(new JsonObject
        {
            ["type"] = type,
            ["slot"] = slot,
            ["t_ms"] = (long)(Time.timeAsDouble * 1000),
            ["data"] = data ?? new JsonObject(),
        });
    }

    public static JsonNode Drain()
    {
        var events = new JsonArray();
        while (Queue.TryDequeue(out var e)) events.Add(e);
        return new JsonObject { ["events"] = events };
    }

    public static void Install(Harmony harmony)
    {
        Patch(harmony, AccessTools.Method(typeof(PlayerHands), nameof(PlayerHands.PickUp)),
            nameof(PickUpPostfix));
        Patch(harmony, AccessTools.Method(typeof(PlayerHands), nameof(PlayerHands.Drop)),
            nameof(DropPrefix), prefix: true);
        Patch(harmony, AccessTools.Method(typeof(RewardGourd), nameof(RewardGourd.OnChangeGourdState)),
            nameof(GourdStatePostfix));
        // Tested: CompleteInput and TextChatSource.AddMessage run once per message, for the
        // body that sent it. PlayerTexter.DisplayMessage never runs (probably inlined).
        Patch(harmony, AccessTools.Method(typeof(PlayerTexter), nameof(PlayerTexter.CompleteInput)),
            nameof(ChatSentPostfix));
        Patch(harmony, AccessTools.Method(typeof(TextChatSource), nameof(TextChatSource.AddMessage)),
            nameof(ChatShownPostfix));
    }

    private static void Patch(Harmony harmony, System.Reflection.MethodBase target, string hook, bool prefix = false)
    {
        if (target == null)
        {
            Plugin.Trace.LogWarning($"Event hook {hook}: target method not found.");
            return;
        }

        try
        {
            var method = new HarmonyMethod(typeof(GameEvents), hook);
            if (prefix) harmony.Patch(target, prefix: method);
            else harmony.Patch(target, postfix: method);
        }
        catch (Exception e)
        {
            Plugin.Trace.LogWarning($"Event hook {hook} failed: {e.Message}");
        }
    }

    private static int? SlotOf(PlayerCharacter pc)
    {
        try
        {
            var slot = pc != null ? Practice.SlotOf(pc.netId) : 0;
            return slot > 0 ? slot : null;
        }
        catch
        {
            return null;
        }
    }

    private static void PickUpPostfix(PlayerHands __instance, Prop prop)
    {
        try
        {
            Push("item_picked_up", SlotOf(__instance.playerCharacter), HeldItems.Describe(prop));
        }
        catch (Exception e)
        {
            Plugin.Trace.LogDebug($"PickUp event failed: {e.Message}");
        }
    }

    private static void DropPrefix(PlayerHands __instance)
    {
        try
        {
            var prop = __instance.heldProp;
            Push("item_dropped", SlotOf(__instance.playerCharacter),
                prop != null ? HeldItems.Describe(prop) : null);
        }
        catch (Exception e)
        {
            Plugin.Trace.LogDebug($"Drop event failed: {e.Message}");
        }
    }

    private static void GourdStatePostfix(RewardGourd __instance, GourdFlag.GourdState newValue)
    {
        try
        {
            Push("reward_state", null, new JsonObject
            {
                ["item_id"] = __instance.netId.ToString(),
                ["state"] = newValue.ToString(),
            });
        }
        catch (Exception e)
        {
            Plugin.Trace.LogDebug($"Gourd event failed: {e.Message}");
        }
    }

    private static void ChatSentPostfix(PlayerTexter __instance, string message, ref bool messageSent)
    {
        if (!messageSent) return;
        try
        {
            Push("text_chat_sent", SlotOf(__instance.playerCharacter), new JsonObject { ["message"] = message });
        }
        catch (Exception e)
        {
            Plugin.Trace.LogDebug($"Chat sent event failed: {e.Message}");
        }
    }

    /// <summary>The message shows in the game, so the other bodies can read it.</summary>
    private static void ChatShownPostfix(TextChatSource __instance)
    {
        try
        {
            var m = __instance.mostRecentMessage;
            Push("text_chat", SlotOf(m.sendingPlayer), new JsonObject { ["message"] = m.message });
        }
        catch (Exception e)
        {
            Plugin.Trace.LogDebug($"Chat event failed: {e.Message}");
        }
    }
}
