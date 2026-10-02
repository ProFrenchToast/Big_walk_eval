using System;
using System.IO;
using System.Text.Json.Nodes;
using UnityEngine;
using Object = UnityEngine.Object;

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
/// Free camera shot, for replays and for writing puzzle files.
///   args: position, look_at, width? (960), height? (540), fov_deg? (60, vertical)
/// A hidden camera renders into a texture. The pixels come back through a pointer
/// (BodyCapture.CopyPixels), and the PNG is encoded here, because EncodeToPNG fails
/// in this interop build (see Screenshot). With no position it returns null, which
/// the harness treats as "no overview". The game culls house interiors by the
/// player's zone (HouseCulling), so a far camera can miss what is inside a building.
/// </summary>
internal static class OverviewShot
{
    private static Camera _camera;

    public static JsonNode Run(JsonObject args)
    {
        if (args["position"] == null || args["look_at"] == null)
        {
            return new JsonObject { ["png_base64"] = null };
        }

        var position = Json.ToVec(args["position"]);
        var lookAt = Json.ToVec(args["look_at"]);
        var width = args["width"]?.GetValue<int>() ?? 960;
        var height = args["height"]?.GetValue<int>() ?? 540;
        if (_camera == null)
        {
            var go = new GameObject("EvalBridge.OverviewCamera") { hideFlags = HideFlags.HideAndDontSave };
            _camera = go.AddComponent<Camera>();
            _camera.enabled = false;
            _camera.nearClipPlane = 0.2f;
            _camera.farClipPlane = 3000f;
        }

        _camera.fieldOfView = args["fov_deg"]?.GetValue<float>() ?? 60f;
        _camera.transform.SetPositionAndRotation(position, Quaternion.LookRotation(lookAt - position, Vector3.up));
        var target = new RenderTexture(width, height, 24);
        var pixels = new Texture2D(width, height, TextureFormat.RGBA32, false);
        var previous = RenderTexture.active;
        byte[] rgba;
        try
        {
            _camera.targetTexture = target;
            _camera.Render();
            RenderTexture.active = target;
            pixels.ReadPixels(new Rect(0, 0, width, height), 0, 0);
            rgba = BodyCapture.CopyPixels(pixels);
        }
        finally
        {
            RenderTexture.active = previous;
            _camera.targetTexture = null;
            target.Release();
            Object.Destroy(target);
            Object.Destroy(pixels);
        }

        return new JsonObject
        {
            ["png_base64"] = Convert.ToBase64String(Png.Encode(rgba, width, height, flip: true)),
            ["width"] = width,
            ["height"] = height,
        };
    }
}

/// <summary>A minimal RGBA PNG encoder (no filtering), in managed code.</summary>
internal static class Png
{
    public static byte[] Encode(byte[] rgba, int width, int height, bool flip)
    {
        var stride = width * 4;
        var raw = new byte[(stride + 1) * height];
        for (var y = 0; y < height; y++)
        {
            var source = flip ? height - 1 - y : y;
            Buffer.BlockCopy(rgba, source * stride, raw, y * (stride + 1) + 1, stride);
        }

        using var compressed = new MemoryStream();
        using (var z = new System.IO.Compression.ZLibStream(compressed, System.IO.Compression.CompressionLevel.Fastest, true))
            z.Write(raw, 0, raw.Length);

        using var png = new MemoryStream();
        png.Write(new byte[] { 137, 80, 78, 71, 13, 10, 26, 10 });
        var header = new byte[13];
        WriteInt(header, 0, width);
        WriteInt(header, 4, height);
        header[8] = 8; // bit depth
        header[9] = 6; // RGBA
        Chunk(png, "IHDR", header);
        Chunk(png, "IDAT", compressed.ToArray());
        Chunk(png, "IEND", Array.Empty<byte>());
        return png.ToArray();
    }

    private static void Chunk(Stream s, string type, byte[] data)
    {
        var buffer = new byte[4];
        WriteInt(buffer, 0, data.Length);
        s.Write(buffer);
        var typeBytes = System.Text.Encoding.ASCII.GetBytes(type);
        s.Write(typeBytes);
        s.Write(data);
        var crc = Crc(typeBytes, data);
        WriteInt(buffer, 0, (int)crc);
        s.Write(buffer);
    }

    private static void WriteInt(byte[] b, int at, int v)
    {
        b[at] = (byte)(v >> 24);
        b[at + 1] = (byte)(v >> 16);
        b[at + 2] = (byte)(v >> 8);
        b[at + 3] = (byte)v;
    }

    private static uint[] _table;

    private static uint Crc(byte[] type, byte[] data)
    {
        if (_table == null)
        {
            _table = new uint[256];
            for (uint n = 0; n < 256; n++)
            {
                var c = n;
                for (var k = 0; k < 8; k++) c = (c & 1) != 0 ? 0xEDB88320u ^ (c >> 1) : c >> 1;
                _table[n] = c;
            }
        }

        var crc = 0xFFFFFFFFu;
        foreach (var b in type) crc = _table[(crc ^ b) & 0xFF] ^ (crc >> 8);
        foreach (var b in data) crc = _table[(crc ^ b) & 0xFF] ^ (crc >> 8);
        return crc ^ 0xFFFFFFFFu;
    }
}
