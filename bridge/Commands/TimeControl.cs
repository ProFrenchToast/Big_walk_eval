using System.Text.Json.Nodes;
using UnityEngine;

namespace BigWalk.EvalBridge;

/// <summary>
/// Pause and resume with Time.timeScale. Update keeps running at 0 with
/// deltaTime = 0; FixedUpdate stops. time_s is scaled game time, so the game
/// server measures unpaused time as the difference between resume and pause.
/// NEEDS GAME: check 3 must show that physics, props, and puzzle timers stop
/// and restart cleanly (some may use unscaled time).
/// </summary>
internal static class TimeControl
{
    public static JsonNode Pause()
    {
        Time.timeScale = 0f;
        return Now();
    }

    public static JsonNode Resume()
    {
        Time.timeScale = 1f;
        return Now();
    }

    private static JsonNode Now() => new JsonObject { ["time_s"] = Time.timeAsDouble };
}
