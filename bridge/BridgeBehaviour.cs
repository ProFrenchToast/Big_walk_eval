using System;
using System.Collections;
using System.Collections.Generic;
using BepInEx.Unity.IL2CPP.Utils.Collections;
using System.Text.Json.Nodes;
using UnityEngine;

namespace BigWalk.EvalBridge;

/// <summary>A command that needs more than one frame. Polled once per frame on the main thread.</summary>
internal interface IPending
{
    /// <summary>Return true and set <paramref name="result"/> when done. Throw to fail.</summary>
    bool Poll(out JsonNode result);
}

/// <summary>
/// Main-thread dispatcher. Update still runs at Time.timeScale = 0, so the
/// queue drains while the game is paused.
/// </summary>
public class BridgeBehaviour : MonoBehaviour
{
    public BridgeBehaviour(IntPtr ptr) : base(ptr) { }

    internal static BridgeBehaviour Instance { get; private set; }

    private readonly List<(Request request, IPending pending, int deadline)> _pending = new();

    private void Awake()
    {
        Instance = this;
    }

    private void Start()
    {
        StartCoroutine(EndOfFrames().WrapToIl2Cpp());
    }

    private static IEnumerator EndOfFrames()
    {
        var wait = new WaitForEndOfFrame();
        while (true)
        {
            yield return wait;
            try
            {
                BodyCapture.EndOfFrame();
            }
            catch (Exception e)
            {
                Plugin.Trace.LogError($"capture end of frame failed: {e}");
            }
        }
    }

    private void Update()
    {
        try
        {
            CaptureDiagnostics.Frame();
        }
        catch (Exception e)
        {
            Plugin.Trace.LogDebug($"Capture diagnostics failed: {e.Message}");
        }

        try
        {
            ChatSync.Tick();
        }
        catch (Exception e)
        {
            Plugin.Trace.LogDebug($"Chat sync failed: {e.Message}");
        }

        if (Time.frameCount % 120 == 0)
        {
            try
            {
                if (Time.frameCount % 1200 == 0) Plugin.Trace.LogInfo($"Bridge server: {Plugin.ServerStatus()}");
                Plugin.EnsureServer();
                // Reading the slot table repairs it if the practice mod emptied it.
                if (Mirror.NetworkServer.activeHost) _ = Practice.Slots;
            }
            catch (Exception e)
            {
                Plugin.Trace.LogError($"Bridge server restart failed: {e.Message}");
            }
        }

        var budget = Plugin.MaxCommandsPerFrame.Value;
        while (budget-- > 0 && BridgeServer.Queue.TryDequeue(out var request))
        {
            try
            {
                var outcome = Commands.Run(request.Cmd, request.Args);
                if (outcome is IPending pending)
                {
                    _pending.Add((request, pending, Time.frameCount + Plugin.CommandTimeoutFrames.Value));
                }
                else
                {
                    request.Done.TrySetResult(outcome as JsonNode ?? new JsonObject());
                }
            }
            catch (Exception e)
            {
                Plugin.Trace.LogWarning($"{request.Cmd} failed: {e}");
                request.Done.TrySetException(e);
            }
        }

        for (var i = _pending.Count - 1; i >= 0; i--)
        {
            var (request, pending, deadline) = _pending[i];
            try
            {
                if (pending.Poll(out var result))
                {
                    request.Done.TrySetResult(result ?? new JsonObject());
                }
                else if (Time.frameCount > deadline)
                {
                    request.Done.TrySetException(new TimeoutException($"{request.Cmd} did not finish in time"));
                }
                else
                {
                    continue;
                }
            }
            catch (Exception e)
            {
                Plugin.Trace.LogWarning($"{request.Cmd} failed: {e}");
                request.Done.TrySetException(e);
            }

            _pending.RemoveAt(i);
        }
    }

    private void LateUpdate()
    {
        try
        {
            BodyCapture.Tick();
        }
        catch (Exception e)
        {
            Plugin.Trace.LogError($"capture stopped: {e}");
            BodyCapture.Stop();
        }
    }
}
