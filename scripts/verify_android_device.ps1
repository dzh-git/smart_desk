[CmdletBinding()]
param(
    [string]$ApkPath = (
        "android_tablet\android-app\app\build\outputs\apk\debug\app-debug.apk"
    )
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$reportRoot = Join-Path $repoRoot "logs\hardware\android-latest"
New-Item -ItemType Directory -Force -Path $reportRoot | Out-Null
$adb = Get-Command adb -ErrorAction SilentlyContinue
if (-not $adb) {
    $sdkCandidates = @(
        $env:ANDROID_HOME,
        (Join-Path $env:LOCALAPPDATA "Android\Sdk"),
        "D:\Android\Sdk"
    ) | Where-Object { $_ }
    foreach ($sdk in $sdkCandidates) {
        $candidate = Join-Path $sdk "platform-tools\adb.exe"
        if (Test-Path -LiteralPath $candidate) {
            $adb = $candidate
            break
        }
    }
}
if (-not $adb) { throw "ADB not found." }
$adbPath = if ($adb -is [string]) { $adb } else { $adb.Source }
$devices = & $adbPath devices
$serials = @(
    $devices | Select-String "^\S+\s+device$" | ForEach-Object {
        ($_ -split "\s+")[0]
    }
)
if ($serials.Count -ne 1) {
    throw "Connect exactly one unlocked Android device (found $($serials.Count))."
}
$serial = $serials[0]
$apk = [IO.Path]::GetFullPath((Join-Path $repoRoot $ApkPath))
if (-not (Test-Path -LiteralPath $apk)) {
    throw "APK not found: $apk"
}
$window = (& $adbPath -s $serial shell dumpsys window policy) -join "`n"
if ($window -match "mShowingLockscreen=true|isStatusBarKeyguard=true") {
    throw "Device is locked. Unlock it and keep the screen on."
}

& $adbPath -s $serial logcat -c
$install = & $adbPath -s $serial install -r $apk 2>&1
if ($LASTEXITCODE -ne 0 -or ($install -join "`n") -notmatch "Success") {
    throw "APK install failed: $($install -join ' ')"
}
$permissionGrantStatus = "PASS"
foreach ($permission in @(
    "android.permission.CAMERA", "android.permission.RECORD_AUDIO"
)) {
    $previousAction = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $grantOutput = & $adbPath -s $serial shell pm grant `
            com.smartdesk.tablet $permission 2>&1
        if ($LASTEXITCODE -ne 0 -or (
            ($grantOutput -join "`n") -match "SecurityException"
        )) {
            $permissionGrantStatus = "HARDWARE_REQUIRED"
        }
    }
    finally { $ErrorActionPreference = $previousAction }
}
& $adbPath -s $serial shell am force-stop com.smartdesk.tablet
& $adbPath -s $serial shell am start -n (
    "com.smartdesk.tablet/.MainActivity"
) | Out-Null
Start-Sleep -Seconds 8
$package = (& $adbPath -s $serial shell dumpsys package com.smartdesk.tablet) `
    -join "`n"
$activity = (& $adbPath -s $serial shell dumpsys activity activities) `
    -join "`n"
$log = (& $adbPath -s $serial logcat -d -s `
    "SmartDeskTablet:I" "AndroidRuntime:E" "*:S") -join "`n"
$safeLog = $log `
    -replace '(?i)(authorization|deviceToken|token)[=: ]+\S+', '$1=[REDACTED]'
$safeLog | Set-Content -LiteralPath (
    Join-Path $reportRoot "smartdesk-tablet.log"
) -Encoding UTF8
$cameraGranted = (
    $package -match "android\.permission\.CAMERA: granted=true"
)
$microphoneGranted = (
    $package -match "android\.permission\.RECORD_AUDIO: granted=true"
)
if ($cameraGranted -and $microphoneGranted) {
    $permissionGrantStatus = "PASS"
}
$permissionDetail = (
    "camera={0}; microphone={1}; MIUI may require visible confirmation" -f
    $cameraGranted, $microphoneGranted
)
$versionStatus = if ($package -match "versionName=0\.8\.0") {
    "PASS"
} else { "FAIL" }
$activityStatus = if (
    $activity -match "com\.smartdesk\.tablet/(?:\.|com\.)?.*MainActivity"
) { "PASS" } else { "FAIL" }
$webViewStatus = if (
    $safeLog -match "WebView loaded:.*\/seat\/[1-9]"
) { "PASS" } else { "HARDWARE_REQUIRED" }

$results = @(
    [PSCustomObject]@{
        name = "APK install"; status = "PASS"; detail = "adb install -r"
    },
    [PSCustomObject]@{
        name = "Version"; status = $versionStatus
        detail = "Expected versionName 0.8.0"
    },
    [PSCustomObject]@{
        name = "MainActivity"; status = $activityStatus
        detail = "Activity started"
    },
    [PSCustomObject]@{
        name = "WebView"; status = $webViewStatus
        detail = "Requires configured reachable central frontend"
    },
    [PSCustomObject]@{
        name = "Runtime permissions"; status = $permissionGrantStatus
        detail = $permissionDetail
    },
    [PSCustomObject]@{
        name = "Bridge/camera/heartbeat/recovery"
        status = "HARDWARE_REQUIRED"
        detail = "One short visible check remains; see FIELD_VALIDATION_QUICKSTART.md"
    }
)
[PSCustomObject]@{
    schemaVersion = 1
    generatedAt = [DateTimeOffset]::Now.ToString("o")
    device = "connected-android-device"
    results = $results
} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (
    Join-Path $reportRoot "android-device-validation.json"
) -Encoding UTF8
$results | Format-Table name, status, detail -AutoSize
if (@($results | Where-Object status -eq "FAIL").Count -gt 0) { exit 1 }
exit 0
