using System;
using System.Text.Json.Nodes;
using Enviro;

namespace BigWalk.EvalBridge;

/// <summary>
/// Lock the Enviro 3 sky to one time of day. The game clock otherwise runs
/// while the game is unpaused, and a long session reaches night.
/// The lock stops Enviro's own clock (Settings.simulate) and puts the time
/// back each frame if something moves it. The host's LobbyEnviroNetworking
/// syncs syncTime, syncDate and isSimulating to clients, and may write them
/// back into Enviro (not checked), so one set at reset may not hold.
/// NEEDS GAME: the whole command. Check that the sky stays at the hour for a
/// long unpaused run, and that clearing the lock lets the clock run again.
/// </summary>
internal static class TimeOfDay
{
    private const float Tolerance = 0.01f;

    private static float? _lockedHours;

    /// <summary>
    /// Args: hours (0 to 24) locks the time there; hours null clears the lock.
    /// No hours key: only report.
    /// </summary>
    public static JsonNode Set(JsonObject args)
    {
        if (args != null && args.ContainsKey("hours"))
        {
            var node = args["hours"];
            if (node == null)
            {
                _lockedHours = null;
                var time = Module();
                if (time != null) time.Settings.simulate = true;
            }
            else
            {
                var hours = node.GetValue<float>();
                if (hours < 0f || hours > 24f) throw new ArgumentException($"hours must be 0 to 24, not {hours}");
                _lockedHours = hours;
                Apply();
            }
        }

        return Report();
    }

    /// <summary>Called every frame. Holds the lock against Enviro and the network sync.</summary>
    public static void Tick()
    {
        if (_lockedHours != null) Apply();
    }

    private static void Apply()
    {
        var time = Module();
        if (time == null) return;
        var target = _lockedHours.Value;
        if (time.Settings.simulate) time.Settings.simulate = false;
        if (Math.Abs(time.GetTimeOfDay() - target) > Tolerance) time.SetTimeOfDay(target);
    }

    private static EnviroTimeModule Module()
    {
        var manager = EnviroManager.instance;
        return manager == null ? null : manager.Time;
    }

    private static JsonNode Report()
    {
        var time = Module();
        return new JsonObject
        {
            ["locked_hours"] = _lockedHours,
            ["enviro_found"] = time != null,
            ["hours"] = time == null ? null : time.GetTimeOfDay(),
            ["simulate"] = time == null ? null : time.Settings.simulate,
        };
    }
}
