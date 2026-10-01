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
///
/// The game draws the scene for the active body only (head text faces its camera,
/// its own head is hidden). For each idle body's camera, <see cref="CaptureView"/>
/// sets the scene up as that body would see it and undoes it after the render
/// (config Capture.PerBodyView). The active body's frames are a copy of the screen
/// at the end of the frame (<see cref="EndOfFrame"/>, config Capture.ActiveFromScreen),
/// so they have the HUD that the agent's screenshots have: the crosshair, the chat
/// input while it types, and the echo of its own message. Tested in the game
/// (2026-10-01): text_chat_circle, footy_walkabout, cave_telescope; exactly one view
/// has the HUD in each frame, also across switches.
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
    private static RenderTexture _screen;
    private static BodyStream _screenStream;
    private static int _screenDue;
    private static int _screenFrame;
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
        _screenStream = null;
        _screenDue = 0;
        if (_screen != null)
        {
            _screen.Release();
            Object.Destroy(_screen);
            _screen = null;
        }

        _frames = 0;
        return new JsonObject { ["frames"] = frames, ["start_time_s"] = start };
    }

    /// <summary>Called from BridgeBehaviour.LateUpdate, after the bodies and cameras moved.</summary>
    public static void Tick()
    {
        if (!Active) return;
        var active = Plugin.CaptureActiveFromScreen.Value ? ActiveSlot() : 0;
        // The end of an earlier frame never came, or another body became active since:
        // render the waiting frame with the camera instead.
        if (_screenStream != null && (_screenFrame != Time.frameCount || _screenStream.Slot != active))
        {
            Send(_screenStream, Render(_screenStream), TakeScreenDue());
        }

        var due = 0;
        while (Time.timeAsDouble - _start >= (_frames + due) / (double)_fps) due++;
        if (due == 0) return;

        foreach (var stream in Streams)
        {
            if (stream.Slot == active)
            {
                // The screen is complete only at the end of the frame (EndOfFrame).
                _screenStream = stream;
                _screenDue += due;
                _screenFrame = Time.frameCount;
                continue;
            }

            Send(stream, Render(stream), due);
        }

        _frames += due;
    }

    /// <summary>
    /// Called from BridgeBehaviour at the end of each frame. The active body's frame is
    /// the screen itself, so it has the HUD the agent sees (crosshair, chat input, the
    /// echo of its own message), which no camera renders.
    /// </summary>
    public static void EndOfFrame()
    {
        if (_screenStream == null) return;
        var stream = _screenStream;
        var due = TakeScreenDue();
        if (!Streams.Contains(stream)) return;
        byte[] bytes;
        try
        {
            bytes = ReadScreen(stream);
        }
        catch (Exception e)
        {
            Plugin.Trace.LogWarning($"capture slot {stream.Slot}: screen copy failed, using its camera: {e.Message}");
            bytes = Render(stream);
        }

        Send(stream, bytes, due);
    }

    private static int TakeScreenDue()
    {
        var due = _screenDue;
        _screenStream = null;
        _screenDue = 0;
        return due;
    }

    private static void Send(BodyStream stream, byte[] bytes, int count)
    {
        for (var i = 0; i < count; i++) stream.Queue.Add(bytes);
    }

    private static int ActiveSlot()
    {
        var local = Mirror.NetworkClient.localPlayer;
        return local != null ? Practice.SlotOf(local.netId) : 0;
    }

    private static byte[] ReadScreen(BodyStream stream)
    {
        if (_screen == null || _screen.width != Screen.width || _screen.height != Screen.height)
        {
            if (_screen != null)
            {
                _screen.Release();
                Object.Destroy(_screen);
            }

            _screen = new RenderTexture(Screen.width, Screen.height, 0, RenderTextureFormat.ARGB32);
        }

        ScreenCapture.CaptureScreenshotIntoRenderTexture(_screen);
        // The screen copy is upside down compared with a camera's render texture (D3D12),
        // and ffmpeg flips every frame.
        Graphics.Blit(_screen, stream.Target, new Vector2(1, -1), new Vector2(0, 1));
        return ReadTarget(stream);
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
        var body = Body(stream.Slot);
        var look = Look(body);
        if (look != null)
        {
            stream.Camera.transform.SetPositionAndRotation(look.position, look.rotation);
        }

        var undo = Plugin.CapturePerBodyView.Value && look != null
            ? CaptureView.Apply(body, look.position, look.rotation)
            : null;
        try
        {
            stream.Camera.Render();
        }
        finally
        {
            if (undo != null) CaptureView.Undo(undo);
        }

        return ReadTarget(stream);
    }

    private static byte[] ReadTarget(BodyStream stream)
    {
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
    internal static byte[] CopyPixels(Texture2D texture)
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

    internal static PlayerCharacter Body(int slot) =>
        Practice.TryGetSlotIdentity(slot, out var identity) ? identity.GetComponent<PlayerCharacter>() : null;

    internal static Transform Look(PlayerCharacter pc)
    {
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
