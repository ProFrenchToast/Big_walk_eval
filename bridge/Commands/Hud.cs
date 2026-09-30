using System;
using HarmonyLib;

namespace BigWalk.EvalBridge;

/// <summary>
/// Hide HUD that is noise for the eval. BadConnectionWarning shows "reconnection
/// in progress" after the game has been paused for a while (the EOS lobby link
/// is fine), and it would appear in the agents' screenshots.
/// </summary>
internal static class Hud
{
    public static void Install(Harmony harmony)
    {
        if (!Plugin.HideConnectionWarning.Value) return;
        try
        {
            harmony.Patch(AccessTools.Method(typeof(BadConnectionWarning), nameof(BadConnectionWarning.Update)),
                prefix: new HarmonyMethod(typeof(Hud), nameof(HideWarningPrefix)));
        }
        catch (Exception e)
        {
            Plugin.Trace.LogWarning($"Could not hide the connection warning: {e.Message}");
        }
    }

    private static bool HideWarningPrefix(BadConnectionWarning __instance)
    {
        try
        {
            if (__instance.warningDisplayObject != null && __instance.warningDisplayObject.gameObject.activeSelf)
                __instance.warningDisplayObject.gameObject.SetActive(false);
        }
        catch
        {
            // Cosmetic only.
        }

        return false;
    }
}
