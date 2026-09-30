using System;
using System.Text.Json.Nodes;
using Il2CppInterop.Runtime;
using UnityEngine;

namespace BigWalk.EvalBridge;

/// <summary>
/// Move a prop during reset: the nearest active prop of item_type to "near"
/// (default: the target position). Stands in for loading a save snapshot.
/// Fails if a body holds the prop; the game server drops it first.
/// </summary>
internal static class PlaceProp
{
    public static JsonNode Run(JsonObject args)
    {
        var type = args["item_type"]?.GetValue<string>() ?? throw new ArgumentException("missing argument item_type");
        var position = Json.ToVec(args["position"]);
        var near = args["near"] != null ? Json.ToVec(args["near"]) : position;

        Prop best = null;
        var bestDistance = float.MaxValue;
        foreach (var obj in Resources.FindObjectsOfTypeAll(Il2CppType.Of<Prop>()))
        {
            var prop = obj.TryCast<Prop>();
            if (prop == null || !prop.gameObject.activeInHierarchy || HeldItems.TypeName(prop) != type) continue;
            var distance = Vector3.Distance(prop.transform.position, near);
            if (distance < bestDistance)
            {
                best = prop;
                bestDistance = distance;
            }
        }

        if (best == null) throw new ArgumentException($"no prop of type {type}");
        var holder = PropList.HolderSlot(best);
        if (holder != null) throw new InvalidOperationException($"{type} is held by slot {holder}; drop it first");

        var moved = Vector3.Distance(best.transform.position, position);
        if (best.rb != null)
        {
            best.rb.position = position;
            best.rb.linearVelocity = Vector3.zero;
            best.rb.angularVelocity = Vector3.zero;
        }

        best.transform.position = position;
        var result = HeldItems.Describe(best);
        result.Remove("hand");
        result["moved_m"] = Math.Round(moved, 2);
        return result;
    }
}
