using BepInEx;
using BepInEx.Configuration;
using BepInEx.Unity.IL2CPP;
using HarmonyLib;
using Il2CppInterop.Runtime.Injection;
using UnityEngine;

namespace BigWalk.EvalBridge;

/// <summary>
/// Bridge between the eval game server (Python) and the game. Listens on
/// 127.0.0.1 for line-delimited JSON commands and runs each one on the Unity
/// main thread. Needs big-walk-practice for bodies and slot switching.
/// Host-only. NEEDS GAME for everything past compile.
/// </summary>
[BepInPlugin(Guid, "Big Walk — Eval Bridge", Version)]
[BepInDependency(Practice.Guid)]
public class Plugin : BasePlugin
{
    public const string Guid = "com.bigwalk.evalbridge";
    public const string Version = "0.1.0";

    internal static BepInEx.Logging.ManualLogSource Trace;

    internal static ConfigEntry<int> Port;
    internal static ConfigEntry<int> MaxCommandsPerFrame;
    internal static ConfigEntry<int> CommandTimeoutFrames;
    internal static ConfigEntry<int> SpawnSettleFrames;

    private BridgeServer _server;
    private Harmony _harmony;

    public override void Load()
    {
        Trace = Log;

        Port = Config.Bind("Server", "Port", 47800,
            "TCP port on 127.0.0.1 for the eval game server.");
        MaxCommandsPerFrame = Config.Bind("Server", "MaxCommandsPerFrame", 8,
            "Commands started per frame on the main thread.");
        CommandTimeoutFrames = Config.Bind("Server", "CommandTimeoutFrames", 1200,
            "Frames a multi-frame command (switch, spawn, screenshot) may take before it fails.");
        SpawnSettleFrames = Config.Bind("Server", "SpawnSettleFrames", 40,
            "Frames to wait after the last spawn. The practice mod moves a new body back to " +
            "its formation spot 30 frames after spawning, which would undo a teleport.");

        ClassInjector.RegisterTypeInIl2Cpp<BridgeBehaviour>();

        var host = new GameObject("BigWalk.EvalBridge");
        host.hideFlags = HideFlags.HideAndDontSave;
        Object.DontDestroyOnLoad(host);
        host.AddComponent<BridgeBehaviour>();

        _harmony = new Harmony(Guid);
        GameEvents.Install(_harmony);

        _server = new BridgeServer(Port.Value);
        _server.Start();

        Log.LogInfo($"Loaded. Listening on 127.0.0.1:{Port.Value}.");
    }

    public override bool Unload()
    {
        _server?.Stop();
        _harmony?.UnpatchSelf();
        return true;
    }
}
