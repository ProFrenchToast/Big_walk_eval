using System;
using System.Collections.Generic;
using System.Reflection;
using BepInEx.Unity.IL2CPP;
using Mirror;

namespace BigWalk.EvalBridge;

/// <summary>
/// Access to big-walk-practice's PracticeController by reflection. Its slot
/// table, spawn, and switch logic are private, so this binds to member names
/// of practice 0.6.0 (PracticeController.cs). If those change, this fails
/// loudly at the first command. A small public API in a fork of the practice
/// mod would remove the reflection.
///
/// Slots: the harness uses 1-based slots; practice index = slot - 1
/// (slot 1 = key "1" = practice index 0 = the original player).
/// </summary>
internal static class Practice
{
    public const string Guid = "com.bigwalk.practice";

    private const BindingFlags Private = BindingFlags.NonPublic | BindingFlags.Instance;
    private const BindingFlags PrivateStatic = BindingFlags.NonPublic | BindingFlags.Static;

    private static Type _type;

    private static Type ControllerType =>
        _type ??= Type.GetType("BigWalk.Practice.PracticeController, BigWalk.Practice")
                  ?? throw new InvalidOperationException("BigWalk.Practice is not loaded");

    private static object Instance =>
        ControllerType.GetField("_instance", PrivateStatic)?.GetValue(null)
        ?? throw new InvalidOperationException("PracticeController has not started yet");

    private static T Field<T>(string name) =>
        (T)(ControllerType.GetField(name, Private)
            ?? throw new MissingFieldException("PracticeController", name)).GetValue(Instance);

    private static object Call(string name, params object[] args) =>
        (ControllerType.GetMethod(name, Private)
         ?? throw new MissingMethodException("PracticeController", name)).Invoke(Instance, args);

    /// <summary>netId per practice index; 0 = empty.</summary>
    public static List<uint> Slots => Field<List<uint>>("_slots");

    /// <summary>netId of a switch the practice mod has started but not finished; 0 = none.</summary>
    public static uint PendingSwitchId => Field<uint>("_pendingId");

    public static string Version =>
        IL2CPPChainloader.Instance.Plugins.TryGetValue(Guid, out var info)
            ? info.Metadata.Version.ToString()
            : null;

    public static bool TryGetIdentity(uint netId, out NetworkIdentity identity)
    {
        identity = null;
        return netId != 0
               && NetworkServer.spawned != null
               && NetworkServer.spawned.TryGetValue(netId, out identity)
               && identity != null;
    }

    public static bool TryGetSlotIdentity(int slot, out NetworkIdentity identity)
    {
        identity = null;
        var slots = Slots;
        var index = slot - 1;
        return index >= 0 && index < slots.Count && TryGetIdentity(slots[index], out identity);
    }

    public static int SlotOf(uint netId)
    {
        var slots = Slots;
        for (var i = 0; i < slots.Count; i++)
        {
            if (slots[i] == netId) return i + 1;
        }

        return 0;
    }

    public static int BodyCount()
    {
        var count = 0;
        foreach (var id in Slots)
        {
            if (id != 0 && TryGetIdentity(id, out _)) count++;
        }

        return count;
    }

    public static void SelectSlot(NetworkIdentity current, int slot) => Call("SelectSlot", current, slot - 1);

    public static int FindFirstEmptySlot() => (int)Call("FindFirstEmptySlot") + 1;

    public static void SpawnAndSelect(NetworkIdentity current, int slot) => Call("SpawnAndSelect", current, slot - 1);
}
