using System;
using System.Collections.Generic;
using Il2CppInterop.Runtime.InteropTypes.Arrays;
using UnityEngine;

namespace BigWalk.EvalBridge;

/// <summary>
/// Makes the scene look as it does from one idle body, for one capture render.
/// The game draws the scene for the active (local) body only, and every capture
/// camera inherits that:
///
/// - Head text (TextChatSource.RefreshOpacityAndRotation) turns to face Camera.main,
///   so other cameras see it edge-on or from behind. It is hidden for the active
///   body, because that body is the local player. Its alpha comes from the audio
///   occlusion from the active body's listener.
/// - The active body is in the "local" look (PlayerLooks): its normal head and body
///   renderers only cast shadows, and its first-person arms are shown.
///
/// <see cref="Apply"/> sets every head text and the active body's renderers for one
/// viewer, and returns the changes; <see cref="Undo"/> puts them back right after the
/// render, so the main camera and the agents' screenshots do not change. For the
/// viewer, the text alpha is an estimate (<see cref="Readability"/>): the game's own
/// occlusion is smoothed over many frames and only runs for the listener.
///
/// Tested in the game (2026-10-01): in text_chat_circle every view shows the other
/// bodies' messages and the active body's head; footy_walkabout and cave_telescope
/// still score C with capture on. The estimate matches the game at 6 m (1) and for
/// two texts behind a ledge at 12 m and 18 m (0). Not checked: the estimate at
/// 10 to 20 m with a clear line, a speaker that moves (the game damps the text
/// position, this does not), and crouching or sitting speakers.
/// </summary>
internal static class CaptureView
{
    /// <summary>Head text sits this far above TextChatSource.transform (measured, 1.5.1).</summary>
    private const float TextLift = 0.25f;

    /// <summary>Rays from the viewer to points this far around the speaker's text.</summary>
    private const float RaySpread = 0.3f;

    /// <summary>Rays stop this short of the speaker, so the speaker's own collider does not block them.</summary>
    private const float RayStopShort = 0.5f;

    public static List<Action> Apply(PlayerCharacter viewer, Vector3 cameraPosition, Quaternion cameraRotation)
    {
        var undo = new List<Action>();
        var active = Mirror.NetworkClient.localPlayer != null
            ? Mirror.NetworkClient.localPlayer.GetComponent<PlayerCharacter>()
            : null;
        if (viewer == null || active == null || viewer == active) return undo;

        try
        {
            if (Plugin.CaptureViewLooks.Value) ShowAsRemote(active.looks, undo);
            foreach (var pc in PlayerCharacter.allPlayerCharacters)
            {
                if (pc == null) continue;
                var source = pc.texter != null ? pc.texter.source : null;
                if (source == null || source.textField == null) continue;
                if (pc == viewer)
                {
                    // A player never sees its own head text.
                    if (Plugin.CaptureViewOwnText.Value) SetActive(source.textField.gameObject, false, undo);
                }
                else if (Plugin.CaptureViewOtherText.Value)
                {
                    ShowText(source, cameraPosition, cameraRotation, undo);
                }
            }
        }
        catch
        {
            Undo(undo);
            throw;
        }

        return undo;
    }

    public static void Undo(List<Action> undo)
    {
        for (var i = undo.Count - 1; i >= 0; i--)
        {
            try
            {
                undo[i]();
            }
            catch (Exception e)
            {
                Plugin.Trace.LogWarning($"Capture view undo failed: {e.Message}");
            }
        }

        undo.Clear();
    }

    /// <summary>
    /// How readable a head text is from <paramref name="from"/>, 0 to 1: the source's
    /// opacity curve over distance, times the share of five rays to the text that the
    /// source's occlusion layers do not block.
    /// </summary>
    public static float Readability(TextChatSource source, Vector3 from, Vector3 text)
    {
        var distance = Vector3.Distance(from, text);
        var opacity = source.opacityCurve != null ? Mathf.Clamp01(source.opacityCurve.Evaluate(distance)) : 1f;
        if (opacity <= 0f || distance <= RayStopShort) return opacity;

        var layers = source.occlusionConfig != null ? source.occlusionConfig.Layers.value : Physics.DefaultRaycastLayers;
        var direction = (text - from) / distance;
        var right = Vector3.Cross(Vector3.up, direction);
        right = right.sqrMagnitude < 1e-6f ? Vector3.right : right.normalized;
        var up = Vector3.Cross(direction, right);
        Span<Vector3> offsets = stackalloc Vector3[] { Vector3.zero, right, -right, up, -up };
        var clear = 0;
        foreach (var offset in offsets)
        {
            var target = text + offset * RaySpread;
            var end = target - (target - from).normalized * RayStopShort;
            if (!Physics.Linecast(from, end, layers, QueryTriggerInteraction.Ignore)) clear++;
        }

        return opacity * clear / offsets.Length;
    }

    private static void ShowText(
        TextChatSource source, Vector3 cameraPosition, Quaternion cameraRotation, List<Action> undo)
    {
        var text = source.textField;
        // The game hides the active body's text (it is the local player), and may hide a text
        // the active body cannot hear, but the source keeps its messages.
        if (source.activeMessages == null || source.activeMessages.Count == 0 || string.IsNullOrEmpty(text.text)) return;
        SetActive(text.gameObject, true, undo);
        if (!text.gameObject.activeInHierarchy) return;

        var t = text.transform;
        var position = t.position;
        var rotation = t.rotation;
        var scale = t.localScale;
        var alpha = text.alpha;
        undo.Add(() =>
        {
            t.SetPositionAndRotation(position, rotation);
            t.localScale = scale;
            text.alpha = alpha;
        });

        var at = source.transform.position + Vector3.up * TextLift;
        // Same size rule as the game: textScalar * (1 + distanceScalar * distance).
        var size = source.textScalar * (1f + source.distanceScalar * Vector3.Distance(cameraPosition, at));
        var parent = t.parent != null ? t.parent.lossyScale.x : 1f;
        t.SetPositionAndRotation(at, cameraRotation);
        t.localScale = Vector3.one * (size / (Mathf.Abs(parent) > 1e-6f ? parent : 1f));
        text.alpha = Readability(source, cameraPosition, at);
    }

    private static void ShowAsRemote(PlayerLooks looks, List<Action> undo)
    {
        if (looks == null) return;
        ShowAsRemote(looks.headRenderers, undo);
        ShowAsRemote(looks.torsoRenderers, undo);
        ShowAsRemote(looks.legsRenderers, undo);
    }

    private static void ShowAsRemote(Il2CppReferenceArray<PlayerLooks.LooksRenderer> renderers, List<Action> undo)
    {
        if (renderers == null) return;
        foreach (var looks in renderers)
        {
            var renderer = looks != null ? looks.renderer : null;
            if (renderer == null) continue;
            if (looks.remote && renderer.shadowCastingMode == UnityEngine.Rendering.ShadowCastingMode.ShadowsOnly)
            {
                renderer.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.On;
                undo.Add(() => renderer.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.ShadowsOnly);
            }
            else if (looks.local && !looks.remote && !renderer.forceRenderingOff)
            {
                renderer.forceRenderingOff = true;
                undo.Add(() => renderer.forceRenderingOff = false);
            }
        }
    }

    private static void SetActive(GameObject go, bool active, List<Action> undo)
    {
        if (go.activeSelf == active) return;
        go.SetActive(active);
        undo.Add(() => go.SetActive(!active));
    }
}
