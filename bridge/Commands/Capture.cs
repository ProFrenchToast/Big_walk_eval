using System;
using System.IO;
using System.Text.Json.Nodes;
using UnityEngine;

namespace BigWalk.EvalBridge;

/// <summary>
/// Capture what the player sees and return it as a base64 PNG, with the
/// screen size. Unity writes the file at the end of the frame (also while
/// paused), and this reads it back with plain .NET. EncodeToPNG and every
/// other call that returns a Unity byte array fail in this interop build
/// ("Instances of abstract classes cannot be created"), so the file is the
/// way out. The game server scales the image if the window is not at the
/// requested size. Turn off the practice mod's ShowNameOverlay.
/// </summary>
internal sealed class Screenshot : IPending
{
    private static int _counter;
    private readonly string _path;

    public Screenshot()
    {
        _path = Path.Combine(Path.GetTempPath(), $"bigwalk-eval-{Environment.ProcessId}-{++_counter}.png");
        if (File.Exists(_path)) File.Delete(_path);
        ScreenCapture.CaptureScreenshot(_path, 1);
    }

    public bool Poll(out JsonNode result)
    {
        result = null;
        if (!File.Exists(_path)) return false;
        byte[] png;
        try
        {
            png = File.ReadAllBytes(_path);
        }
        catch (IOException)
        {
            return false;
        }

        if (!EndsWithIend(png)) return false;
        File.Delete(_path);
        result = new JsonObject
        {
            ["png_base64"] = Convert.ToBase64String(png),
            ["width"] = Screen.width,
            ["height"] = Screen.height,
        };
        return true;
    }

    /// <summary>True when the file holds a whole PNG: it ends with the IEND chunk.</summary>
    private static bool EndsWithIend(byte[] png) =>
        png.Length > 12
        && png[^8] == (byte)'I' && png[^7] == (byte)'E' && png[^6] == (byte)'N' && png[^5] == (byte)'D';
}

/// <summary>
/// Free camera shot for replays. Not written: it needs a render-to-texture
/// readback, and EncodeToPNG fails in this interop build (see Screenshot).
/// With no position it returns null, which the harness treats as "no overview".
/// </summary>
internal static class OverviewShot
{
    public static JsonNode Run(JsonObject args)
    {
        if (args["position"] == null || args["look_at"] == null)
        {
            return new JsonObject { ["png_base64"] = null };
        }

        throw new NotSupportedException("overview_shot is not supported: EncodeToPNG fails in this interop build");
    }
}
