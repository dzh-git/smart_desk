[CmdletBinding()]
param()

$ErrorActionPreference = "Continue"
$installDir = Split-Path -Parent $PSScriptRoot
$settingsPath = Join-Path $installDir "install-settings.json"
$results = [System.Collections.Generic.List[object]]::new()
function Add-Result($Name, $Status, $Detail) {
    $results.Add([PSCustomObject]@{
        name = $Name; status = $Status; detail = $Detail
    })
}
if (-not (Test-Path -LiteralPath $settingsPath)) {
    Add-Result "installation" "FAIL" "Run INSTALL.bat first."
}
else {
    $settings = Get-Content -LiteralPath $settingsPath -Encoding UTF8 |
        ConvertFrom-Json
    $installationStatus = if (
        Test-Path -LiteralPath $settings.currentVersionPath
    ) { "PASS" } else { "FAIL" }
    Add-Result "installation" $installationStatus (
        "Internal demo version pointer"
    )
    foreach ($item in @(
        @("runtime config", $settings.configPath),
        @("protected ESP32 token registry", $settings.tokensPath),
        @("Python runtime", $settings.python),
        @("Android APK", (
            Join-Path $settings.currentVersionPath "android\SmartDeskTablet-debug.apk"
        ))
    )) {
        $presenceStatus = if (
            Test-Path -LiteralPath $item[1]
        ) { "PASS" } else { "FAIL" }
        Add-Result $item[0] $presenceStatus (
            "Presence only; secret values are never reported."
        )
    }
    foreach ($port in @(5173, 8000, 8766)) {
        $open = Test-NetConnection 127.0.0.1 -Port $port `
            -InformationLevel Quiet -WarningAction SilentlyContinue
        $portStatus = if ($open) { "PASS" } else { "WARN" }
        $portDetail = if ($open) {
            "Listening"
        } else { "Not listening; run START.bat." }
        Add-Result "port $port" $portStatus $portDetail
    }
    $gestureRoot = Join-Path $settings.currentVersionPath (
        "smartdesk_gesture_controller"
    )
    $gestureStatus = if (Test-Path -LiteralPath (
        Join-Path $gestureRoot "hand_landmarker.task"
    )) { "PASS" } else { "HARDWARE_REQUIRED" }
    Add-Result "gesture models" $gestureStatus (
        "Add controlled local models when gesture validation is scheduled."
    )
    $solidWorksStatus = if (
        Get-Command SLDWORKS.exe -ErrorAction SilentlyContinue
    ) { "PASS" } else { "HARDWARE_REQUIRED" }
    Add-Result "SolidWorks" $solidWorksStatus (
        "Validate on the final host that has SolidWorks."
    )
    $adb = Get-Command adb -ErrorAction SilentlyContinue
    $androidStatus = if ($adb) { "WARN" } else { "HARDWARE_REQUIRED" }
    Add-Result "Android USB" $androidStatus (
        "Connect and unlock the tablet, then run the field quick-start."
    )
    Add-Result "ESP32/PIR/distance/lights" "HARDWARE_REQUIRED" (
        "Connect one wired seat before physical validation."
    )
    $reportDir = Join-Path $settings.dataDir "logs"
    New-Item -ItemType Directory -Force -Path $reportDir | Out-Null
    [PSCustomObject]@{
        generatedAt = [DateTimeOffset]::Now.ToString("o")
        results = $results
    } | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (
        Join-Path $reportDir "doctor-latest.json"
    ) -Encoding UTF8
}
$results | Format-Table name, status, detail -AutoSize
if (@($results | Where-Object status -eq "FAIL").Count -gt 0) { exit 1 }
exit 0
