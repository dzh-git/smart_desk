[CmdletBinding()]
param([switch]$SkipGesture, [switch]$SkipScreenStream)

$ErrorActionPreference = "Stop"
$installDir = Split-Path -Parent $PSScriptRoot
$settingsPath = Join-Path $installDir "install-settings.json"
if (-not (Test-Path -LiteralPath $settingsPath)) {
    throw "Run INSTALL.bat first."
}
$settings = Get-Content -LiteralPath $settingsPath -Encoding UTF8 |
    ConvertFrom-Json
$app = $settings.currentVersionPath
$python = $settings.python
$env:SMARTDESK_CONFIG_PATH = $settings.configPath
$env:SMARTDESK_DATA_DIR = $settings.dataDir
$env:SMARTDESK_ESP32_DEVICE_TOKENS_FILE = $settings.tokensPath
$logs = Join-Path $settings.dataDir "logs"
New-Item -ItemType Directory -Force -Path $logs | Out-Null
$processes = [System.Collections.Generic.List[object]]::new()

function Start-SmartDeskProcess {
    param(
        [string]$Name,
        [string]$FilePath,
        [string[]]$Arguments,
        [string]$WorkingDirectory
    )
    $stdout = Join-Path $logs "$Name.out.log"
    $stderr = Join-Path $logs "$Name.err.log"
    $process = Start-Process -FilePath $FilePath -ArgumentList $Arguments `
        -WorkingDirectory $WorkingDirectory -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    $processes.Add([PSCustomObject]@{ name = $Name; pid = $process.Id })
}

$desk = Join-Path $app "new_coding_desk"
Start-SmartDeskProcess "backend" $python @(
    "-m", "uvicorn", "backend.main:app",
    "--host", "0.0.0.0", "--port", "8000"
) $desk
Start-SmartDeskProcess "frontend" $python @(
    "-m", "uvicorn", "frontend_server:app",
    "--host", "0.0.0.0", "--port", "5173"
) $desk
Start-SmartDeskProcess "display-agent" $python @("agent.py") (
    Join-Path $desk "host_services\display_agent"
)

$gesture = Join-Path $app "smartdesk_gesture_controller"
if (-not $SkipGesture -and (
    Test-Path -LiteralPath (Join-Path $gesture "hand_landmarker.task")
)) {
    Start-SmartDeskProcess "gesture" $python @(
        "-m", "hands.gesture_controller"
    ) $gesture
}
if (-not $SkipScreenStream) {
    $stream = Join-Path $desk "host_services\screen_stream\start_screen_stream.bat"
    if (Test-Path -LiteralPath $stream) {
        Start-SmartDeskProcess "screen-stream" $stream @() (
            Split-Path -Parent $stream
        )
    }
}
$processes | ConvertTo-Json | Set-Content -LiteralPath (
    Join-Path $logs "running-processes.json"
) -Encoding UTF8

$deadline = (Get-Date).AddSeconds(30)
do {
    Start-Sleep -Milliseconds 500
    try {
        $backend = Invoke-RestMethod "http://127.0.0.1:8000/api/health" `
            -TimeoutSec 2
        $frontend = Invoke-RestMethod "http://127.0.0.1:5173/health" `
            -TimeoutSec 2
        if ($backend -and $frontend.status -eq "ok") {
            Write-Host "START PASS: http://127.0.0.1:5173"
            exit 0
        }
    }
    catch {}
} while ((Get-Date) -lt $deadline)
throw "Services did not become healthy. Run DOCTOR.bat."
