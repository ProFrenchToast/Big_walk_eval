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
        // NEEDS GAME: check that cameraTransform follows each body's own look,
        // also for inactive bodies. Fall back to the body transform if not.
        var look = pc.cameraTransform != null ? pc.cameraTransform : pc.transform;
        var euler = look.eulerAngles;
        return new JsonObject
        {
            ["slot"] = slot,
            ["position"] = Json.Vec(position),
            ["yaw_deg"] = Json.Angle(euler.y),
            ["pitch_deg"] = Json.Angle(euler.x),
            ["held"] = HeldItems.Read(pc),
        };
    }
}

internal static class HeldItems
{
    /// <summary>
    /// One entry per hand that holds something:
    /// {"hand": "left"|"right", "item_id": str, "item_type": str, "is_reward": bool (optional)}.
    ///
    /// TODO(dump): find where each hand keeps its held object and the reward (gourd) class.
    /// Lead: NOTES-phase1.md in big-walk-practice lists `PlayerHands` (field
    /// `PlayerCharacter.hands`) with a `dragJoint` ConfigurableJoint. Grep the dump:
    ///   rg -n "class PlayerHands|class PlayerArms" out/dummy
    ///   rg -n "Grab|Hold|held|Gourd|Reward" out/dummy/Assembly-CSharp
    /// Until then this returns an empty list, so the scorer cannot see a held gourd.
    /// </summary>
    public static JsonArray Read(PlayerCharacter pc) => new();
}
