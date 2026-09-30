using System;
using System.Collections;
using System.Linq;
using System.Text.Json.Nodes;
using BepInEx.Unity.IL2CPP.Utils.Collections;
using UnityEngine;

namespace BigWalk.EvalBridge;

/// <summary>
/// Capture what the player sees at the end of a frame, scale it to
/// width x height, and return a base64 PNG. Run the game windowed at the
/// target size (1366 x 768) so the scale is 1:1 and the aspect ratio is
/// right. Turn off the practice mod's ShowNameOverlay. NEEDS GAME.
/// </summary>
internal sealed class Screenshot : IPending
{
    private readonly int _width;
    private readonly int _height;
    private string _png;
    private Exception _error;

    public Screenshot(int width, int height)
    {
        _width = width;
        _height = height;
        BridgeBehaviour.Instance.StartCoroutine(Capture().WrapToIl2Cpp());
    }

    public bool Poll(out JsonNode result)
    {
        result = null;
        if (_error != null) throw _error;
        if (_png == null) return false;
        result = new JsonObject { ["png_base64"] = _png };
        return true;
    }

    private IEnumerator Capture()
    {
        yield return new WaitForEndOfFrame();
        try
        {
            var screen = ScreenCapture.CaptureScreenshotAsTexture();
            try
            {
                _png = Images.ScaledPng(screen, _width, _height);
            }
            finally
            {
                UnityEngine.Object.Destroy(screen);
            }
        }
        catch (Exception e)
        {
            _error = e;
        }
    }
}

/// <summary>Render a free camera at a position, looking at a point. For replays and spot checks. NEEDS GAME.</summary>
internal static class OverviewShot
{
    public static JsonNode Run(JsonObject args)
    {
        if (args["position"] == null || args["look_at"] == null)
        {
            return new JsonObject { ["png_base64"] = null };
        }

        var width = Json.Int(args, "width");
        var height = Json.Int(args, "height");
        var go = new GameObject("EvalBridge.OverviewCamera");
        var rt = RenderTexture.GetTemporary(width, height, 24);
        try
        {
            var cam = go.AddComponent<Camera>();
            cam.enabled = false;
            cam.fieldOfView = 60f;
            go.transform.position = Json.ToVec(args["position"]);
            go.transform.LookAt(Json.ToVec(args["look_at"]));
            cam.targetTexture = rt;
            // NEEDS GAME: if the game uses a scriptable render pipeline, Camera.Render
            // may need RenderPipeline.SubmitRenderRequest instead.
            cam.Render();
            cam.targetTexture = null;
            return new JsonObject { ["png_base64"] = Images.ReadPng(rt, width, height) };
        }
        finally
        {
            RenderTexture.ReleaseTemporary(rt);
            UnityEngine.Object.Destroy(go);
        }
    }
}

internal static class Images
{
    public static string ScaledPng(Texture source, int width, int height)
    {
        var rt = RenderTexture.GetTemporary(width, height, 0);
        try
        {
            Graphics.Blit(source, rt);
            return ReadPng(rt, width, height);
        }
        finally
        {
            RenderTexture.ReleaseTemporary(rt);
        }
    }

    public static string ReadPng(RenderTexture rt, int width, int height)
    {
        var previous = RenderTexture.active;
        var tex = new Texture2D(width, height, TextureFormat.RGB24, false);
        try
        {
            RenderTexture.active = rt;
            tex.ReadPixels(new Rect(0, 0, width, height), 0, 0);
            tex.Apply();
            // EncodeToPNG returns an Il2Cpp array; ToArray copies it into a managed byte[].
            return Convert.ToBase64String(ImageConversion.EncodeToPNG(tex).ToArray());
        }
        finally
        {
            RenderTexture.active = previous;
            UnityEngine.Object.Destroy(tex);
        }
    }
}
