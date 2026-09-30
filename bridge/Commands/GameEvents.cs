using System.Collections.Concurrent;
using System.Text.Json.Nodes;
using HarmonyLib;
using UnityEngine;

namespace BigWalk.EvalBridge;

/// <summary>
/// Event queue returned and cleared by the "events" command. Each event:
/// {"type": str, "slot": int|null, "t_ms": int, "data": {...}}.
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

    /// <summary>
    /// TODO(dump): Harmony postfixes for reward spawn, item pickup and drop,
    /// and puzzle completion. Find the methods first:
    ///   rg -n "class .*(Gourd|Reward|Puzzle)" out/dummy/Assembly-CSharp
    ///   rg -n "void (Grab|Pick|Hold|Release|Drop)" out/dummy/Assembly-CSharp
    /// Then patch them here and call Push("item_picked_up", slot, {...}) etc.,
    /// with the same event names FakeGame uses.
    /// </summary>
    public static void Install(Harmony harmony)
    {
    }
}
