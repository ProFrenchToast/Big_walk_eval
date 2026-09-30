using System.Text.Json.Nodes;
using Mirror;
using UnityEngine;

namespace BigWalk.EvalBridge;

internal static class StateReader
{
    public static JsonNode Read()
    {
        var bodies = new JsonArray();
        var slots = Practice.Slots;
        for (var i = 0; i < slots.Count; i++)
        {
            if (!Practice.TryGetIdentity(slots[i], out var identity)) continue;
            var pc = identity.GetComponent<PlayerCharacter>();
            if (pc == null) continue;
            bodies.Add(Body(i + 1, pc));
        }

        var local = NetworkClient.localPlayer;
        return new JsonObject
        {
            ["paused"] = Time.timeScale == 0f,
            ["active_slot"] = local != null ? Practice.SlotOf(local.netId) : 0,
            ["time_s"] = Time.timeAsDouble,
            ["camera_vfov_deg"] = Camera.main != null ? (float?)Camera.main.fieldOfView : null,
            ["bodies"] = bodies,
        };
    }

    private static JsonObject Body(int slot, PlayerCharacter pc)
    {
        var position = pc.rb != null ? pc.rb.position : pc.transform.position;
        var look = pc.cameraTransform != null ? pc.cameraTransform : pc.transform;
        var euler = look.eulerAngles;
        return new JsonObject
        {
            ["slot"] = slot,
            ["position"] = Json.Vec(position),
            ["yaw_deg"] = Json.Angle(euler.y),
            ["pitch_deg"] = Json.Angle(euler.x),
            ["held"] = HeldItems.Read(pc),
            ["pose"] = Pose(pc),
        };
    }

    /// <summary>Crouch, sit, jump and arm state, to check that actions took effect. Not shown to agents.</summary>
    private static JsonObject Pose(PlayerCharacter pc)
    {
        var pose = new JsonObject();
        try
        {
            if (pc.croucher != null) pose["crouch"] = System.Math.Round(pc.croucher.localTrueCrouchness, 3);
            if (pc.sitter != null) pose["sitting"] = pc.sitter.isSittingLocal;
            if (pc.jumper != null) pose["jump"] = System.Math.Round(pc.jumper.Jumpness, 3);
            if (pc.gestures != null)
            {
                pose["left_arm_pointing"] = pc.gestures.leftArmPointing;
                pose["right_arm_pointing"] = pc.gestures.rightArmPointing;
                pose["left_arm_waving"] = pc.gestures.leftArmWavingState.isActive;
                pose["right_arm_waving"] = pc.gestures.rightArmWavingState.isActive;
            }
        }
        catch (System.Exception e)
        {
            pose["error"] = e.Message;
        }

        return pose;
    }
}

internal static class HeldItems
{
    /// <summary>
    /// What the body holds: {"hand", "item_id", "item_type", "is_reward"}.
    /// The game has one held slot per body (PlayerHands.heldProp or
    /// heldCharacter), carried in both hands, so "hand" is always "right".
    /// </summary>
    public static JsonArray Read(PlayerCharacter pc)
    {
        var held = new JsonArray();
        var hands = pc.hands;
        if (hands == null) return held;

        var prop = hands.heldProp;
        if (prop != null)
        {
            held.Add(Describe(prop));
        }
        else if (hands.heldCharacter != null)
        {
            var other = hands.heldCharacter;
            var slot = Practice.SlotOf(other.netId);
            held.Add(new JsonObject
            {
                ["hand"] = "right",
                ["item_id"] = $"player:{other.netId}",
                ["item_type"] = slot > 0 ? $"PlayerCharacter:slot{slot}" : "PlayerCharacter",
                ["is_reward"] = false,
            });
        }

        return held;
    }

    public static JsonObject Describe(Prop prop) => new()
    {
        ["hand"] = "right",
        ["item_id"] = prop.networkIdentity != null ? prop.networkIdentity.netId.ToString() : prop.name,
        ["item_type"] = TypeName(prop),
        ["is_reward"] = prop.GetComponent<RewardGourd>() != null,
    };

    /// <summary>The prefab name: the GameObject name without Unity's "(Clone)" suffix.</summary>
    public static string TypeName(Prop prop) => prop.name.Replace("(Clone)", "").Trim();
}
