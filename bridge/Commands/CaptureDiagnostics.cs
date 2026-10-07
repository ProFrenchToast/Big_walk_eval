using System;
using System.Diagnostics;
using System.Text.Json.Nodes;
using BepInEx.Configuration;
using Mirror;
using UnityEngine;

namespace BigWalk.EvalBridge;

/// <summary>
/// Logs for the pickup bug with Capture.PerBodyView on (config Capture.Diagnostics).
///
/// Each second of unscaled time in which game time ran, one "capture stats" line: frames,
/// mean and max frame time, and the time the bridge spent in each capture step (camera
/// renders, CaptureView apply and undo, pixel reads, screen copies, waits on a full ffmpeg
/// queue). Each frame in which the active body's Rewired "use" button changes, one
/// "use" line, so the log shows whether a click reached the game and in how many frames.
/// The item_picked_up postfix logs a "pickup" line.
///
/// NEEDS GAME: not run in the game yet.
/// </summary>
internal static class CaptureDiagnostics
{
    public enum Step
    {
        Render,
        View,
        Read,
        Screen,
        QueueWait,
    }

    private static readonly double[] StepMs = new double[Enum.GetValues(typeof(Step)).Length];
    private static double _windowStart = -1;
    private static int _frames;
    private static double _frameMsSum;
    private static double _frameMsMax;
    private static int _captureTicks;
    private static bool _useHeld;
    private static int _useDownFrame = -1;

    public static bool On => Plugin.CaptureDiagnostics.Value;

    public static long Start() => On ? Stopwatch.GetTimestamp() : 0;

    public static void Stop(Step step, long start)
    {
        if (start == 0) return;
        StepMs[(int)step] += (Stopwatch.GetTimestamp() - start) * 1000.0 / Stopwatch.Frequency;
    }

    public static void CaptureTicked() => _captureTicks++;

    /// <summary>
    /// capture_config {per_body_view?, looks?, own_text?, other_text?, active_from_screen?, diagnostics?}
    /// sets the capture switches without a game restart, and returns all of them. BepInEx
    /// also saves them to the config file.
    /// </summary>
    public static JsonNode Configure(JsonObject args)
    {
        var entries = new (string Name, ConfigEntry<bool> Entry)[]
        {
            ("per_body_view", Plugin.CapturePerBodyView),
            ("looks", Plugin.CaptureViewLooks),
            ("own_text", Plugin.CaptureViewOwnText),
            ("other_text", Plugin.CaptureViewOtherText),
            ("active_from_screen", Plugin.CaptureActiveFromScreen),
            ("diagnostics", Plugin.CaptureDiagnostics),
        };
        var result = new JsonObject();
        foreach (var (name, entry) in entries)
        {
            if (args?[name] != null) entry.Value = args[name].GetValue<bool>();
            result[name] = entry.Value;
        }

        Plugin.Trace.LogInfo($"capture config: {result.ToJsonString()}");
        return result;
    }

    /// <summary>Called from BridgeBehaviour.Update.</summary>
    public static void Frame()
    {
        if (!On) return;
        WatchUse();
        if (Time.timeScale == 0f)
        {
            Flush();
            return;
        }

        var ms = Time.unscaledDeltaTime * 1000.0;
        if (_windowStart < 0) _windowStart = Time.unscaledTimeAsDouble;
        _frames++;
        _frameMsSum += ms;
        _frameMsMax = Math.Max(_frameMsMax, ms);
        if (Time.unscaledTimeAsDouble - _windowStart >= 1.0) Flush();
    }

    public static void Pickup(int? slot, string what)
    {
        if (!On) return;
        Plugin.Trace.LogInfo($"diag pickup: frame {Time.frameCount} slot {slot} {what}");
    }

    private static void Flush()
    {
        if (_frames == 0) return;
        Plugin.Trace.LogInfo(
            $"diag capture stats: {_frames} frames in {Time.unscaledTimeAsDouble - _windowStart:F2} s, " +
            $"frame mean {_frameMsSum / _frames:F1} ms max {_frameMsMax:F1} ms, " +
            $"capture ticks {_captureTicks} (active {BodyCapture.Active}, per-body view {Plugin.CapturePerBodyView.Value}), " +
            $"render {StepMs[(int)Step.Render]:F0} ms, view {StepMs[(int)Step.View]:F0} ms, " +
            $"read {StepMs[(int)Step.Read]:F0} ms, screen {StepMs[(int)Step.Screen]:F0} ms, " +
            $"queue wait {StepMs[(int)Step.QueueWait]:F0} ms");
        Array.Clear(StepMs);
        _windowStart = -1;
        _frames = 0;
        _frameMsSum = 0;
        _frameMsMax = 0;
        _captureTicks = 0;
    }

    private static void WatchUse()
    {
        var pc = NetworkClient.localPlayer != null ? NetworkClient.localPlayer.GetComponent<PlayerCharacter>() : null;
        var input = pc != null ? pc.inputPlayer : null;
        if (input == null) return;
        // NEEDS GAME: Rewired keeps button state per frame; a press and release inside one
        // frame may show as down and up together, or not at all.
        var held = input.GetButton("use");
        var down = input.GetButtonDown("use");
        var up = input.GetButtonUp("use");
        if (held == _useHeld && !down && !up) return;

        var slot = Practice.SlotOf(pc.netId);
        var holding = pc.hands != null && pc.hands.heldProp != null ? pc.hands.heldProp.name : "nothing";
        var frames = down || _useDownFrame < 0 ? "" : $", held {Time.frameCount - _useDownFrame} frames";
        Plugin.Trace.LogInfo(
            $"diag use: frame {Time.frameCount} slot {slot} held {held} down {down} up {up}{frames}, " +
            $"dt {Time.unscaledDeltaTime * 1000:F1} ms, timeScale {Time.timeScale}, holding {holding}");
        if (down) _useDownFrame = Time.frameCount;
        if (!held) _useDownFrame = -1;
        _useHeld = held;
    }
}
