using System.Text.Json.Nodes;
using UnityEngine;

namespace BigWalk.EvalBridge;

internal static class Json
{
    public static JsonArray Vec(Vector3 v) => new(v.x, v.y, v.z);

    public static Vector3 ToVec(JsonNode node)
    {
        var a = node.AsArray();
        return new Vector3(a[0].GetValue<float>(), a[1].GetValue<float>(), a[2].GetValue<float>());
    }

    /// <summary>Unity euler angle (0..360) to -180..180.</summary>
    public static float Angle(float degrees) => Mathf.DeltaAngle(0f, degrees);

    public static int Int(JsonObject args, string name) =>
        args[name]?.GetValue<int>() ?? throw new System.ArgumentException($"missing argument {name}");

    public static float Float(JsonObject args, string name) =>
        args[name]?.GetValue<float>() ?? throw new System.ArgumentException($"missing argument {name}");
}
