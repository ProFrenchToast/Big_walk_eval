using System;
using System.Text.Json.Nodes;

namespace BigWalk.EvalBridge;

/// <summary>
/// Command router. Each command returns a JsonNode (done this frame) or an
/// <see cref="IPending"/> (done in a later frame). Throw to fail the request.
/// The protocol is documented in bridge/README.md.
/// </summary>
internal static class Commands
{
    public static object Run(string cmd, JsonObject args) => cmd switch
    {
        "hello" => Hello(),
        "pause" => TimeControl.Pause(),
        "resume" => TimeControl.Resume(),
        "get_state" => StateReader.Read(),
        "switch_slot" => new SwitchSlot(Json.Int(args, "slot")),
        "spawn_bodies" => new SpawnBodies(Json.Int(args, "n")),
        "teleport" => Teleport.Run(args),
        "place_prop" => PlaceProp.Run(args),
        "screenshot" => new Screenshot(),
        "overview_shot" => OverviewShot.Run(args),
        "events" => GameEvents.Drain(),
        "controls" => Controls.Run(),
        "menu" => Menus.Run(args),
        "debug_practice" => DebugInfo.Practice(),
        "list_props" => PropList.Run(args),
        "find_objects" => SceneFind.Run(args),
        "peck_states" => PeckStates.Run(args),
        "release_switches" => ReleaseSwitches.Run(args),
        "debug_body" => BodyDebug.Run(args),
        "capture_start" => BodyCapture.Start(args),
        "capture_stop" => BodyCapture.Stop(),
        "look" => Unfinished.Look(args),
        "load_snapshot" => Unfinished.LoadSnapshot(args),
        "save_snapshot" => Unfinished.SaveSnapshot(args),
        "chat" => Unfinished.Chat(args),
        "input" => Unfinished.Input(args),
        _ => throw new ArgumentException($"unknown command {cmd}"),
    };

    private static JsonNode Hello() => new JsonObject
    {
        ["game_version"] = UnityEngine.Application.version,
        ["bridge_version"] = Plugin.Version,
        ["practice_version"] = Practice.Version,
    };
}
