using System;
using System.Reflection;
using HarmonyLib;
using UnityEngine;

namespace BigWalk.EvalBridge;

/// <summary>
/// Stops text chat from spawning bodies. Practice 0.6.0's IsSpawnPressed is
/// GetKeyDown(SpawnKey) || GetKeyDown(KeypadPlus) || Input.inputString contains '+'.
/// inputString holds every typed character (WM_CHAR), so a "+" in a chat message
/// spawns a body even though the server types with KEYEVENTF_UNICODE and SpawnKey
/// is rebound. This replaces the check with the two key checks only, and none
/// while the chat box is open. The bridge spawns by calling SpawnAndSelect, so
/// the harness does not use the key.
/// </summary>
internal static class SpawnGuard
{
    private static object _spawnKeyEntry;
    private static PropertyInfo _spawnKeyValue;

    public static void Install(Harmony harmony)
    {
        try
        {
            var controller = Type.GetType("BigWalk.Practice.PracticeController, BigWalk.Practice");
            var target = controller != null ? AccessTools.Method(controller, "IsSpawnPressed") : null;
            if (target == null)
            {
                Plugin.Trace.LogWarning("Spawn guard: PracticeController.IsSpawnPressed not found; '+' in chat will spawn bodies.");
                return;
            }

            var plugin = Type.GetType("BigWalk.Practice.Plugin, BigWalk.Practice");
            _spawnKeyEntry = plugin?.GetField("SpawnKey", BindingFlags.NonPublic | BindingFlags.Static)?.GetValue(null);
            _spawnKeyValue = _spawnKeyEntry?.GetType().GetProperty("Value");

            harmony.Patch(target, prefix: new HarmonyMethod(typeof(SpawnGuard), nameof(IsSpawnPressedPrefix)));
        }
        catch (Exception e)
        {
            Plugin.Trace.LogWarning($"Spawn guard failed: {e.Message}");
        }
    }

    // NEEDS GAME: that the patch applies to the injected type and a typed "+" no longer spawns.
    private static bool IsSpawnPressedPrefix(ref bool __result)
    {
        __result = false;
        try
        {
            var input = TextChatInput.instance;
            if (input != null && input.inputIsOpen) return false;
            if (Input.GetKeyDown(KeyCode.KeypadPlus)) __result = true;
            else if (_spawnKeyValue?.GetValue(_spawnKeyEntry) is KeyCode key && key != KeyCode.None)
                __result = Input.GetKeyDown(key);
        }
        catch
        {
            // Never let the practice mod's tick fail on this.
        }

        return false;
    }
}
