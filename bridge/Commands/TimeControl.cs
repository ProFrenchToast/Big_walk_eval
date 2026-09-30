using System.Text.Json.Nodes;
using UnityEngine;

namespace BigWalk.EvalBridge;

/// <summary>
/// Pause and resume with Time.timeScale. Update keeps running at 0 with
/// deltaTime = 0; FixedUpdate stops. time_s is scaled game time, so the game
/// server measures unpaused time as the difference between resume and pause.
/// Bodies stop while paused. NEEDS GAME: check that puzzle timers stop too
/// (some may use unscaled time).
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
