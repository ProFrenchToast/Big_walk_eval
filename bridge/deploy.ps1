# Build the bridge, install it, and (re)start the game through Steam.
#   powershell -NoProfile -ExecutionPolicy Bypass -File bridge\deploy.ps1 [-GamePath <dir>] [-NoLaunch]
# Returns when the bridge listens on 127.0.0.1:47800. The game is then at the title
# screen; the game server hosts a walk on the first /reset (auto_host), or run
#   uv run python -m server.host_walk
param(
    [string]$GamePath = "C:\Program Files (x86)\Steam\steamapps\common\Big Walk",
    [string]$SteamExe = "C:\Program Files (x86)\Steam\steam.exe",
    [int]$Port = 47800,
    [switch]$NoLaunch
)
$ErrorActionPreference = "Stop"
$bridge = $PSScriptRoot

dotnet build "$bridge\BigWalk.EvalBridge.csproj" -c Release /p:GamePath="$GamePath" | Out-Host
if ($LASTEXITCODE -ne 0) { throw "build failed" }

$old = Get-Process "Big Walk" -ErrorAction SilentlyContinue
if ($old) {
    $old | Stop-Process -Force
    $old | Wait-Process -Timeout 60 -ErrorAction SilentlyContinue
}

$target = "$GamePath\BepInEx\plugins\BigWalk.EvalBridge"
New-Item -ItemType Directory -Force $target | Out-Null
# The old process can hold the DLL for a few seconds after it exits.
$copied = $false
for ($i = 0; $i -lt 30 -and -not $copied; $i++) {
    try {
        Copy-Item "$bridge\bin\Release\BigWalk.EvalBridge.dll" $target -Force
        $copied = $true
    } catch {
        Start-Sleep 2
    }
}
if (-not $copied) { throw "could not replace $target\BigWalk.EvalBridge.dll" }
if ($NoLaunch) { return }

# Launch through Steam. A direct launch of the exe loads BepInEx and the bridge,
# then Steam restarts the game, which kills that first bridge.
Start-Process -FilePath $SteamExe -ArgumentList "-applaunch", "1478500"
$owner = 0
for ($i = 0; $i -lt 90; $i++) {
    Start-Sleep 2
    $c = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    $now = if ($c) { $c.OwningProcess } else { 0 }
    # Ready when the same process has held the port for two polls in a row.
    if ($now -ne 0 -and $now -eq $owner) {
        "Bridge listening on 127.0.0.1:$Port (game pid $owner)."
        return
    }
    $owner = $now
}
throw "the bridge did not start listening on port $Port"
