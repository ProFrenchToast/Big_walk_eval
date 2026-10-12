using System;
using System.Text.Json.Nodes;
using Mirror;
using UnityEngine;

namespace BigWalk.EvalBridge;

/// <summary>
/// Switch control to a slot through the practice mod. The practice mod
/// finishes a switch in its own Update (camera, listener, looks), so this
/// waits until NetworkClient.localPlayer is the target and no switch is pending.
/// </summary>
internal sealed class SwitchSlot : IPending
{
    private readonly int _slot;
    private bool _requested;

    public SwitchSlot(int slot)
    {
        _slot = slot;
    }

    public bool Poll(out JsonNode result)
    {
        result = null;
        if (!Practice.TryGetSlotIdentity(_slot, out var target))
        {
            throw new ArgumentException($"no body in slot {_slot}");
        }

        var local = NetworkClient.localPlayer;
        if (local == null || Practice.PendingSwitchId != 0) return false;

        if (local.netId == target.netId)
        {
            ChatSync.Tick();
            result = new JsonObject { ["active_slot"] = _slot };
            GameEvents.Push("switched", _slot, null);
            return true;
        }

        if (!_requested)
        {
            Practice.SelectSlot(local, _slot);
            _requested = true;
        }

        return false;
    }
}

/// <summary>
/// Make sure at least n bodies exist, spawning one per frame through the
/// practice mod. Spawning also switches control to the new body. Waits
/// SpawnSettleFrames after the last spawn, because the practice mod moves a
/// new body back to its formation spot 30 frames after spawning.
/// Works while paused.
/// </summary>
internal sealed class SpawnBodies : IPending
{
    private readonly int _n;
    private int _settleUntil = -1;

    public SpawnBodies(int n)
    {
        _n = n;
    }

    public bool Poll(out JsonNode result)
    {
        result = null;
        var local = NetworkClient.localPlayer;
        if (local == null || Practice.PendingSwitchId != 0) return false;
        // Wait until the practice mod has put the host body in a slot, else the
        // first spawn takes slot 2 and the host body is left without a slot.
        if (Practice.SlotOf(local.netId) == 0) return false;

        var count = Practice.BodyCount();
        if (count < _n)
        {
            var slot = Practice.FindFirstEmptySlot();
            if (slot <= 1)
            {
                throw new InvalidOperationException(
                    $"cannot spawn body {count + 1}: raise MaxExtraBodies in com.bigwalk.practice.cfg");
            }

            // The practice mod ignores the spawn while the world is still loading; the next poll retries.
            Practice.SpawnAndSelect(local, slot);
            _settleUntil = Time.frameCount + Plugin.SpawnSettleFrames.Value;
            return false;
        }

        if (Time.frameCount < _settleUntil) return false;
        result = new JsonObject { ["count"] = count };
        return true;
    }
}

/// <summary>Move a whole body and set its facing. Uses the game's own teleport, as the practice mod does.</summary>
internal static class Teleport
{
    public static JsonNode Run(JsonObject args)
    {
        var slot = Json.Int(args, "slot");
        if (!Practice.TryGetSlotIdentity(slot, out var identity))
        {
            throw new ArgumentException($"no body in slot {slot}");
        }

        var pc = identity.GetComponent<PlayerCharacter>();
        var position = Json.ToVec(args["position"]);
        var rotation = Quaternion.Euler(0f, Json.Float(args, "yaw_deg"), 0f);
        if (pc.grease != null)
        {
            pc.grease.Teleport(position, rotation);
        }
        else if (pc.rb != null)
        {
            pc.rb.position = position;
            pc.rb.rotation = rotation;
        }
        else
        {
            pc.transform.SetPositionAndRotation(position, rotation);
        }

        if (pc.rb != null)
        {
            pc.rb.linearVelocity = Vector3.zero;
            pc.rb.angularVelocity = Vector3.zero;
        }

        BodyAlign.Fold(pc);
        return new JsonObject();
    }
}

/// <summary>
/// Turns each body to face where its camera faces. A mouse look turns the body's
/// "kernal" child (between the body and the camera) first, and the body follows only
/// part of the way, so the kernal keeps a yaw offset. Walking follows the body, so with
/// an offset W walks sideways while the view looks straight ahead (found 2026-10-12:
/// offsets up to 150 degrees, and they survive reset). Folding the offset into the
/// body keeps the camera where it is.
/// </summary>
internal static class BodyAlign
{
    public static JsonNode Run(JsonObject args)
    {
        var folded = new JsonArray();
        var slots = Practice.Slots;
        for (var i = 0; i < slots.Count; i++)
        {
            if (!Practice.TryGetIdentity(slots[i], out var identity)) continue;
            var pc = identity.GetComponent<PlayerCharacter>();
            if (pc == null) continue;
            folded.Add(new JsonObject { ["slot"] = i + 1, ["yaw_deg"] = Fold(pc) });
        }

        return new JsonObject { ["folded"] = folded };
    }

    /// <summary>Moves the kernal's yaw into the body. Returns the yaw moved, in degrees.</summary>
    public static float Fold(PlayerCharacter pc)
    {
        var kernal = Kernal(pc);
        if (kernal == null) return 0f;
        var local = kernal.localEulerAngles;
        var offset = Mathf.DeltaAngle(0f, local.y);
        if (Mathf.Abs(offset) < 0.01f) return 0f;

        var rotation = Quaternion.Euler(0f, pc.transform.eulerAngles.y + offset, 0f);
        pc.transform.rotation = rotation;
        if (pc.rb != null) pc.rb.rotation = rotation;
        kernal.localEulerAngles = new Vector3(local.x, 0f, local.z);
        return offset;
    }

    public static Transform Kernal(PlayerCharacter pc)
    {
        var t = pc.transform;
        for (var i = 0; i < t.childCount; i++)
        {
            var child = t.GetChild(i);
            if (child.name.EndsWith(" kernal")) return child;
        }

        return null;
    }
}
