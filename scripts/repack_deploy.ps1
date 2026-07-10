# ============================================================================
# repack_deploy.ps1
# Regenerate deployment packages (smart_desk_devided) from source (new_coding_desk).
#
# What it does:
#   1. Build frontend dist
#   2. Sync backend / frontend_dist / gesture / host_services / seat_agent
#   3. Copy arduino_manager.py into seat_terminal/seat_agent and rewrite import
#   4. Write central/config (deploy_mode=distributed)
#
# Preserved (per-machine configs, NEVER overwritten):
#   - seat_terminal/frontend_dist/app-config.js   (central IP)
#   - seat_terminal/seat_agent_config.json        (seat_id + COM + central IP)
#   - central/models                              (2.5GB; skipped if present)
#
# Usage:  scripts\repack_deploy.bat   (or double-click)
# ============================================================================

[CmdletBinding()]
param(
    [string]$Src     = "D:\Ai_project\smart_desktop\new_coding_desk",
    [string]$Gesture = "D:\Ai_project\smart_desktop\smartdesk_gesture_controller",
    [string]$Dst     = "D:\Ai_project\smart_desk_devided"
)

$ErrorActionPreference = "Stop"
function Step($m) { Write-Host "`n=== $m ===" -ForegroundColor Cyan }
function Robo($src, $dst, [string[]]$xd = @(), [string[]]$xf = @()) {
    $a = @($src, $dst, "/E", "/NFL", "/NDL", "/NJH", "/NJS", "/NP", "/NC", "/NS")
    if ($xd) { $a += "/XD"; $a += $xd }
    if ($xf) { $a += "/XF"; $a += $xf }
    & robocopy @a | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy failed ($LASTEXITCODE): $src -> $dst" }
}

# 0. checks
Step "0. check paths"
foreach ($p in @($Src, "$Src\backend", "$Src\frontend", $Gesture)) {
    if (-not (Test-Path $p)) { throw "source missing: $p" }
}
foreach ($p in @("$Dst\central", "$Dst\seat_terminal")) { New-Item -ItemType Directory -Force -Path $p | Out-Null }
Write-Host "src: $Src"
Write-Host "dst: $Dst"

# 1. build frontend
Step "1. build frontend (npm run build)"
Push-Location "$Src\frontend"
try {
    & npm run build
    if ($LASTEXITCODE -ne 0) { throw "frontend build failed" }
    if (-not (Test-Path "$Src\frontend\dist\index.html")) { throw "dist\index.html not found after build" }
    Write-Host "frontend built"
} finally { Pop-Location }

# 2. backend -> central/backend
Step "2. sync backend -> central/backend"
Robo "$Src\backend" "$Dst\central\backend" @("__pycache__", ".pytest_cache") @("*.pyc")

# 3. frontend_dist
Step "3. sync frontend_dist"
# central: full copy (app-config empty = relative = OK for /display)
Robo "$Src\frontend\dist" "$Dst\central\frontend_dist"
# seat_terminal: exclude app-config.js (keep machine's central-IP config)
Robo "$Src\frontend\dist" "$Dst\seat_terminal\frontend_dist" @() @("app-config.js")
$termCfg = "$Dst\seat_terminal\frontend_dist\app-config.js"
if (-not (Test-Path $termCfg)) {
    Copy-Item "$Src\frontend\dist\app-config.js" $termCfg
    Write-Host "first deploy: app-config.js template placed; edit it to set central IP"
}

# 4. gesture / host_services -> central
Step "4. sync gesture / host_services"
Robo $Gesture "$Dst\central\gesture" @("__pycache__", "logs") @("*.pyc")
if (Test-Path "$Src\host_services") {
    Robo "$Src\host_services" "$Dst\central\host_services" @("__pycache__") @("*.pyc")
}

# 5. seat_agent -> seat_terminal/seat_agent (self-contained)
Step "5. sync seat_agent (make self-contained)"
Robo "$Src\seat_agent" "$Dst\seat_terminal\seat_agent" @("__pycache__") @("*.pyc")
$amSrc = "$Src\backend\hardware\arduino_manager.py"
$amDst = "$Dst\seat_terminal\seat_agent\arduino_manager.py"
Copy-Item $amSrc $amDst -Force
$agent = "$Dst\seat_terminal\seat_agent\agent.py"
if (Test-Path $agent) {
    $t = Get-Content $agent -Raw -Encoding UTF8
    $t2 = $t -replace 'from backend\.hardware\.arduino_manager import ArduinoManager', 'from seat_agent.arduino_manager import ArduinoManager'
    if ($t -ne $t2) { Set-Content $agent $t2 -Encoding UTF8 -NoNewline; Write-Host "agent.py import rewritten to self-contained" }
}

# 6. central/config (distributed)
Step "6. write central/config (distributed)"
$cfgDir = "$Dst\central\config"; New-Item -ItemType Directory -Force -Path $cfgDir | Out-Null
$cfg = @'
{
  "deploy_mode": "distributed",
  "arduino": {
    "enabled": false,
    "baudrate": 115200,
    "seats": {
      "1": "COM5", "2": "COM6", "3": "COM7", "4": "COM8",
      "5": "COM9", "6": "COM10", "7": "COM11", "8": "COM12", "9": "COM13"
    }
  },
  "seats_total": 9,
  "gesture": { "enabled": true, "status_ws_url": "ws://127.0.0.1:8765" }
}
'@
Set-Content "$cfgDir\smartdesk.integration.json" $cfg -Encoding UTF8

# 7. models (2.5GB; skip if present)
Step "7. check models"
if (Test-Path "$Dst\central\models") {
    Write-Host "central/models exists, skipped (delete it to force refresh)"
} else {
    Write-Host "first time: copying models (2.5GB, ~30s)..."
    Robo "$Src\models" "$Dst\central\models" @("__pycache__") @("*.pyc")
    Write-Host "models copied"
}

# 8. done
Step "8. done"
Write-Host "Repack complete. Per-machine configs preserved (verify they are still correct):"
Write-Host "  - seat_terminal\frontend_dist\app-config.js   (central IP)"
Write-Host "  - seat_terminal\seat_agent_config.json        (seat_id + COM + central IP)"
Write-Host ""
Write-Host "Next: copy central\ or seat_terminal\ to the target machine to deploy."
