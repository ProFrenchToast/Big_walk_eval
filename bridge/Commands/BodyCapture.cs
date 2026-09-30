using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Text.Json.Nodes;
using System.Threading;
using UnityEngine;
using Object = UnityEngine.Object;

namespace BigWalk.EvalBridge;

/// <summary>
/// Record each body's own view while game time runs, for replay videos.
///
/// capture_start {directory, fps, width, height, slots} makes one hidden camera
/// per body. Each frame, <see cref="Tick"/> checks the scaled game time. For each
/// 1/fps step that passed, it renders every camera, reads the pixels, and sends
/// the raw RGBA bytes to one ffmpeg process per body. ffmpeg writes
/// directory\slot&lt;N&gt;\000000.jpg and on. If one game frame covers more than one
/// step, the same image goes out again, so frame k is always at start + k / fps.
/// No game time passes while paused, so the pauses between actions are not in
/// the frames. capture_stop {} finishes the files and returns frames and
/// start_time_s. The game server writes capture.json.
///
/// Tested in the game (2026-10-01, footy_walkabout, 3 bodies at 683x384 and 30 fps):
/// each camera follows its own body's head also while that body is inactive, the
/// frames match the agents' screenshots (without the HUD), and there is no head
/// mesh in view. The frame rate was fine with 3 cameras. Not checked: many more
/// bodies, or larger frames.
/// </summary>
internal static class BodyCapture
{
    private sealed class BodyStream
    {
        public int Slot;
        public Camera Camera;
        public RenderTexture Target;
        public Texture2D Pixels;
        public Process Ffmpeg;
        public BlockingCollection<byte[]> Queue;
        public Thread Writer;
    }

    private static readonly List<BodyStream> Streams = new();
    private static double _start;
    private static int _fps;
    private static int _frames;

    public static bool Active => Streams.Count > 0;

    public static JsonNode Start(JsonObject args)
    {
        if (Active) Stop();

        var directory = args["directory"]?.GetValue<string>()
                        ?? throw new ArgumentException("capture_start needs directory");
        _fps = Json.Int(args, "fps");
        var width = Json.Int(args, "width");
        var height = Json.Int(args, "height");
        if (_fps <= 0) throw new ArgumentException("fps must be positive");

        var slots = new List<int>();
        foreach (var node in args["slots"]?.AsArray() ?? new JsonArray())
        {
            slots.Add(node.GetValue<int>());
        }

        if (slots.Count == 0) throw new ArgumentException("capture_start needs slots");

        try
        {
            foreach (var slot in slots)
            {
                if (!Practice.TryGetSlotIdentity(slot, out _))
                {
                    throw new ArgumentException($"no body in slot {slot}");
                }

                var folder = Path.Combine(directory, $"slot{slot}");
                Directory.CreateDirectory(folder);
                Streams.Add(Open(slot, folder, width, height));
            }
        }
        catch
        {
            Stop();
            throw;
        }

        _start = Time.timeAsDouble;
        _frames = 0;
        Tick();
        return new JsonObject();
    }

    public static JsonNode Stop()
    {
        var start = _start;
        var frames = _frames;
        foreach (var stream in Streams) Close(stream);
        Streams.Clear();
        _frames = 0;
        return new JsonObject { ["frames"] = frames, ["start_time_s"] = start };
    }

    /// <summary>Called from BridgeBehaviour.LateUpdate, after the bodies and cameras moved.</summary>
    public static void Tick()
    {
        if (!Active) return;
        var due = 0;
        while (Time.timeAsDouble - _start >= (_frames + due) / (double)_fps) due++;
        if (due == 0) return;

        foreach (var stream in Streams)
        {
            var bytes = Render(stream);
            for (var i = 0; i < due; i++) stream.Queue.Add(bytes);
        }

        _frames += due;
    }

    private static BodyStream Open(int slot, string folder, int width, int height)
    {
        var go = new GameObject($"EvalBridge.BodyCamera{slot}");
        go.hideFlags = HideFlags.HideAndDontSave;
        var camera = go.AddComponent<Camera>();
        camera.enabled = false;
        camera.nearClipPlane = 0.2f;
        camera.fieldOfView = Camera.main != null ? Camera.main.fieldOfView : 60f;
        var target = new RenderTexture(width, height, 24);
        camera.targetTexture = target;

        var output = Path.Combine(folder, "%06d.jpg");
        var ffmpeg = Process.Start(new ProcessStartInfo
        {
            FileName = Plugin.FfmpegPath.Value,
            Arguments = $"-y -loglevel error -f rawvideo -pix_fmt rgba -s {width}x{height} " +
                        $"-r {_fps} -i - -vf vflip -q:v 3 -start_number 0 \"{output}\"",
            UseShellExecute = false,
            RedirectStandardInput = true,
            CreateNoWindow = true,
        }) ?? throw new InvalidOperationException($"cannot start {Plugin.FfmpegPath.Value}");

        var stream = new BodyStream
        {
            Slot = slot,
            Camera = camera,
            Target = target,
            Pixels = new Texture2D(width, height, TextureFormat.RGBA32, false),
            Ffmpeg = ffmpeg,
            Queue = new BlockingCollection<byte[]>(Plugin.CaptureQueueFrames.Value),
        };
        // The writer thread only touches managed bytes and the process pipe, never Unity or Il2Cpp.
        stream.Writer = new Thread(() => Write(stream)) { IsBackground = true, Name = $"EvalBridge.Capture{slot}" };
        stream.Writer.Start();
        return stream;
    }

    private static byte[] Render(BodyStream stream)
    {
        var look = Look(stream.Slot);
        if (look != null)
        {
            stream.Camera.transform.SetPositionAndRotation(look.position, look.rotation);
        }

        stream.Camera.Render();
        var previous = RenderTexture.active;
        try
        {
            RenderTexture.active = stream.Target;
            stream.Pixels.ReadPixels(new Rect(0, 0, stream.Target.width, stream.Target.height), 0, 0);
            return CopyPixels(stream.Pixels);
        }
        finally
        {
            RenderTexture.active = previous;
        }
    }

    /// <summary>
    /// Copy the texture's CPU-side pixels into a managed byte[]. GetRawTextureData()
    /// returns an Il2Cpp byte array, and unmarshalling it fails in this interop build
    /// (see Screenshot). GetWritableImageData returns a plain pointer to the same
    /// memory that GetRawTextureData&lt;T&gt; wraps, so nothing is unmarshalled.
    /// </summary>
    private static byte[] CopyPixels(Texture2D texture)
    {
        var size = (long)texture.GetImageDataSize();
        var expected = (long)texture.width * texture.height * 4;
        if (size < expected) throw new InvalidOperationException($"texture has {size} bytes, need {expected}");
        var pointer = texture.GetWritableImageData(0);
        if (pointer == IntPtr.Zero) throw new InvalidOperationException("texture has no CPU data");
        var bytes = new byte[expected];
        Marshal.Copy(pointer, bytes, 0, bytes.Length);
        return bytes;
    }

    private static Transform Look(int slot)
    {
        if (!Practice.TryGetSlotIdentity(slot, out var identity)) return null;
        var pc = identity.GetComponent<PlayerCharacter>();
        if (pc == null) return null;
        // NEEDS GAME: same fallback as StateReader.Body.
        return pc.cameraTransform != null ? pc.cameraTransform : pc.transform;
    }

    private static void Write(BodyStream stream)
    {
        try
        {
            var pipe = stream.Ffmpeg.StandardInput.BaseStream;
            foreach (var frame in stream.Queue.GetConsumingEnumerable())
            {
                pipe.Write(frame, 0, frame.Length);
            }

            pipe.Flush();
        }
        catch (Exception e)
        {
            Plugin.Trace.LogError($"capture slot {stream.Slot}: {e.Message}");
        }
    }

    private static void Close(BodyStream stream)
    {
        stream.Queue.CompleteAdding();
        stream.Writer.Join(TimeSpan.FromSeconds(30));
        try
        {
            stream.Ffmpeg.StandardInput.Close();
            if (!stream.Ffmpeg.WaitForExit(30_000)) stream.Ffmpeg.Kill();
        }
        catch (Exception e)
        {
            Plugin.Trace.LogError($"capture slot {stream.Slot}: ffmpeg did not finish: {e.Message}");
        }

        stream.Camera.targetTexture = null;
        stream.Target.Release();
        Object.Destroy(stream.Target);
        Object.Destroy(stream.Pixels);
        Object.Destroy(stream.Camera.gameObject);
    }
}
