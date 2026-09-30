using System;
using System.Text.Json.Nodes;
using Il2CppInterop.Runtime;
using Mirror;
using UnityEngine;

namespace BigWalk.EvalBridge;

/// <summary>
/// Drive the start menus without a mouse, so the game server can get from the
/// title screen into a hosted walk on its own. Each action calls the game's own
/// menu method, as a click would.
///   status                        which menus are open, and whether a walk is hosted
///   title_host, new_game          title screen -> host menu -> new save
///   host_confirm {name}           on the save confirm screen: set the save name and start
///   load_save {name}              on the host select screen: open an existing save
///   player_count {n}              on the player count screen: pick 2, 3 or 4 and play
/// </summary>
internal static class Menus
{
    public static JsonNode Run(JsonObject args)
    {
        var action = args["action"]?.GetValue<string>() ?? "status";
        switch (action)
        {
            case "status":
                return Status();
            case "title_host":
                (Find<TitleMenu>() ?? throw new InvalidOperationException("the title menu is not open")).GoToHostMenu();
                return Status();
            case "new_game":
                (Find<HostMenuSelect>() ?? throw new InvalidOperationException("the host select menu is not open")).StartNewGame();
                return Status();
            case "host_confirm":
            {
                var menu = Find<HostMenuConfirm>() ?? throw new InvalidOperationException("the host confirm menu is not open");
                var name = args["name"]?.GetValue<string>();
                if (!string.IsNullOrEmpty(name) && menu.gameNameField != null) menu.gameNameField.text = name;
                // Local eval session: no lobby password. The join code still gates who can join.
                menu.passwordRequired = false;
                menu.ActionStart();
                return Status();
            }
            case "load_save":
            {
                var menu = Find<HostMenuSelect>() ?? throw new InvalidOperationException("the host select menu is not open");
                var name = args["name"]?.GetValue<string>() ?? throw new ArgumentException("missing argument name");
                foreach (var card in menu.cards)
                {
                    if (card != null && card.saveData != null && card.saveData.slotName == name)
                    {
                        menu.ActionSelectSaveData(card.saveData);
                        return Status();
                    }
                }

                throw new ArgumentException($"no save named {name}");
            }
            case "player_count":
            {
                // Picks the puzzle variant (2, 3 or 4+ players). It does not limit the number of bodies.
                var menu = Find<PlayerCountMenu>() ?? throw new InvalidOperationException("the player count menu is not open");
                var n = args["n"]?.GetValue<int>() ?? 2;
                if (n >= 4) menu.settingsRow.ActionSelect2();
                else if (n == 3) menu.settingsRow.ActionSelect1();
                else menu.settingsRow.ActionSelect0();
                menu.PlayButton.GetComponent<UnityEngine.UI.Button>().onClick.Invoke();
                return Status();
            }
            default:
                throw new ArgumentException($"unknown menu action {action}");
        }
    }

    private static JsonNode Status()
    {
        var open = new JsonArray();
        foreach (var (name, found) in new (string, bool)[]
                 {
                     ("title", Find<TitleMenu>() != null),
                     ("host_select", Find<HostMenuSelect>() != null),
                     ("host_confirm", Find<HostMenuConfirm>() != null),
                     ("player_count", Find<PlayerCountMenu>() != null),
                     ("loading", Find<LoadingMenu>() != null),
                 })
        {
            if (found) open.Add(name);
        }

        // Reading the slot table repairs it if the practice mod emptied it (see Practice.Slots).
        if (NetworkServer.activeHost) _ = Practice.Slots;
        var hnm = NetworkManager.singleton != null ? NetworkManager.singleton.TryCast<HouseNetworkManager>() : null;
        return new JsonObject
        {
            ["open_menus"] = open,
            ["hosting"] = NetworkServer.activeHost,
            ["local_player"] = NetworkClient.localPlayer != null,
            ["local_player_ready"] = hnm != null && hnm.LocalPlayerFullyReady,
        };
    }

    /// <summary>The first active instance of T. FindFirstObjectByType is stripped in this build.</summary>
    private static T Find<T>() where T : MonoBehaviour
    {
        foreach (var obj in Resources.FindObjectsOfTypeAll(Il2CppType.Of<T>()))
        {
            var component = obj.TryCast<T>();
            if (component != null && component.isActiveAndEnabled) return component;
        }

        return null;
    }
}
