using System.Text.Json.Nodes;
using Mirror;

namespace BigWalk.EvalBridge;

/// <summary>Raw practice-mod and Mirror state, for diagnosing spawn and switch problems.</summary>
internal static class DebugInfo
{
    public static JsonNode Practice()
    {
        var slots = new JsonArray();
        foreach (var id in EvalBridge.Practice.Slots) slots.Add(id);
        var local = NetworkClient.localPlayer;
        return new JsonObject
        {
            ["slots"] = slots,
            ["pending_id"] = EvalBridge.Practice.PendingSwitchId,
            ["local_net_id"] = local != null ? local.netId : 0,
            ["active_host"] = NetworkServer.activeHost,
            ["local_connection"] = NetworkServer.localConnection != null,
            ["spawned"] = NetworkServer.spawned != null ? NetworkServer.spawned.Count : -1,
            ["player_characters"] = PlayerCharacter.allPlayerCharacters != null ? PlayerCharacter.allPlayerCharacters.Count : -1,
        };
    }
}

/// <summary>
/// Props near a body, nearest first: {name, item_id, position, distance, is_reward, held_by_slot}.
/// For authoring puzzle configs and scripted runs. Not an agent tool.
/// </summary>
internal static class PropList
{
    public static JsonNode Run(JsonObject args)
    {
        var slot = args["slot"]?.GetValue<int>() ?? 0;
        var radius = args["radius"]?.GetValue<float>() ?? 30f;
        var limit = args["limit"]?.GetValue<int>() ?? 40;
        UnityEngine.Vector3 origin;
        if (slot > 0 && EvalBridge.Practice.TryGetSlotIdentity(slot, out var identity))
            origin = identity.transform.position;
        else if (NetworkClient.localPlayer != null)
            origin = NetworkClient.localPlayer.transform.position;
        else
            throw new System.InvalidOperationException("no body to measure from");

        var found = new System.Collections.Generic.List<(float, JsonObject)>();
        foreach (var obj in UnityEngine.Resources.FindObjectsOfTypeAll(Il2CppInterop.Runtime.Il2CppType.Of<Prop>()))
        {
            var prop = obj.TryCast<Prop>();
            if (prop == null || !prop.gameObject.activeInHierarchy) continue;
            var position = prop.transform.position;
            var distance = UnityEngine.Vector3.Distance(origin, position);
            if (distance > radius) continue;
            var entry = HeldItems.Describe(prop);
            entry.Remove("hand");
            entry["position"] = Json.Vec(position);
            entry["distance"] = System.Math.Round(distance, 2);
            entry["held_by_slot"] = HolderSlot(prop);
            found.Add((distance, entry));
        }

        found.Sort((a, b) => a.Item1.CompareTo(b.Item1));
        var props = new JsonArray();
        for (var i = 0; i < found.Count && i < limit; i++) props.Add(found[i].Item2);
        return new JsonObject { ["origin"] = Json.Vec(origin), ["count"] = found.Count, ["props"] = props };
    }

    internal static int? HolderSlot(Prop prop)
    {
        foreach (var id in EvalBridge.Practice.Slots)
        {
            if (!EvalBridge.Practice.TryGetIdentity(id, out var identity)) continue;
            var pc = identity.GetComponent<PlayerCharacter>();
            if (pc != null && pc.hands != null && pc.hands.heldProp != null && pc.hands.heldProp.Pointer == prop.Pointer)
                return EvalBridge.Practice.SlotOf(id);
        }

        return null;
    }
}

/// <summary>Every position the game keeps for one body, to debug teleports.</summary>
internal static class BodyDebug
{
    public static JsonNode Run(JsonObject args)
    {
        var slot = Json.Int(args, "slot");
        if (!EvalBridge.Practice.TryGetSlotIdentity(slot, out var identity))
            throw new System.ArgumentException($"no body in slot {slot}");
        var pc = identity.GetComponent<PlayerCharacter>();
        return new JsonObject
        {
            ["local"] = NetworkClient.localPlayer != null && NetworkClient.localPlayer.netId == identity.netId,
            ["rb"] = pc.rb != null ? Json.Vec(pc.rb.position) : null,
            ["transform"] = Json.Vec(pc.transform.position),
            ["kernal"] = pc.kernal != null ? Json.Vec(pc.kernal.position) : null,
            ["cached_kernal"] = pc.mover != null ? Json.Vec(pc.mover.cachedKernalPos) : null,
            ["rb_kinematic"] = pc.rb != null && pc.rb.isKinematic,
        };
    }
}
