using System;
using System.Text.Json.Nodes;

namespace BigWalk.EvalBridge;

/// <summary>
/// Commands that need names from the Cpp2IL dump. Each fails with a clear
/// error until it is written. The game server has fallbacks for look
/// (mouse input) and switching (slot keys); snapshots and held items have none.
/// </summary>
internal static class Unfinished
{
    /// <summary>
    /// Turn the active camera by an exact angle.
    /// TODO(dump): the head/look state. The practice mod touches
    /// PlayerCharacter.head.runningTotalLookSpin and head.SetHeadStateLocal().
    ///   rg -n "class PlayerHead" -A 60 out/dummy/Assembly-CSharp
    /// </summary>
    public static JsonNode Look(JsonObject args) =>
        throw new NotSupportedException("look is not written yet (TODO(dump)); use look_mode: mouse");

    /// <summary>
    /// TODO(dump): the save and load entry points and the save file location.
    ///   rg -n "class .*Save|LoadGame|SaveGame|PlayerPrefs" out/dummy/Assembly-CSharp
    /// </summary>
    public static JsonNode LoadSnapshot(JsonObject args) =>
        throw new NotSupportedException("load_snapshot is not written yet (TODO(dump))");

    public static JsonNode SaveSnapshot(JsonObject args) =>
        throw new NotSupportedException("save_snapshot is not written yet (TODO(dump))");

    /// <summary>
    /// Backend B: inject input into one body's Rewired player
    /// (PlayerCharacter.inputPlayer) with a Rewired CustomController per body.
    /// TODO(dump): the Rewired action names the game reads.
    ///   rg -n "GetButton|GetAxis" out/isil/Assembly-CSharp   (ISIL output)
    /// </summary>
    public static JsonNode Input(JsonObject args) =>
        throw new NotSupportedException("input (Backend B) is not written yet (TODO(dump))");
}
