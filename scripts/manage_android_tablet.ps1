[CmdletBinding()]
param(
    [ValidateSet("Audit", "Configure", "Verify")]
    [string]$Action = "Audit",

    [Parameter(Mandatory)]
    [ValidateRange(1, 9)]
    [int]$SeatId,

    [string]$Serial = "",
    [string]$AdbPath = "",
    [string]$ApkPath = "",
    [string]$ExpectedVersion = "",
    [string]$ExpectedWifiSsid = "",
    [string]$ReportPath = "",
    [switch]$SkipInstall,
    [switch]$Apply
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$packageName = "com.smartdesk.tablet"
$activityName = "$packageName/.MainActivity"
$gradleFile = Join-Path $repoRoot (
    "android_tablet\android-app\app\build.gradle.kts"
)

function Get-ExpectedVersion {
    if ($ExpectedVersion.Trim()) {
        return $ExpectedVersion.Trim()
    }
    if (-not (Test-Path -LiteralPath $gradleFile)) {
        throw (
            "Android build.gradle.kts is unavailable; pass " +
            "-ExpectedVersion when using the packaged verifier."
        )
    }
    $gradle = Get-Content -LiteralPath $gradleFile -Encoding UTF8 -Raw
    $match = [regex]::Match($gradle, 'versionName\s*=\s*"([^"]+)"')
    if (-not $match.Success) {
        throw "Unable to read Android versionName from $gradleFile"
    }
    return $match.Groups[1].Value
}

function Resolve-Adb {
    if ($AdbPath) {
        if (-not (Test-Path -LiteralPath $AdbPath)) {
            throw "ADB not found: $AdbPath"
        }
        return [IO.Path]::GetFullPath($AdbPath)
    }
    $command = Get-Command adb -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }
    foreach ($sdk in @(
        $env:ANDROID_HOME,
        (Join-Path $env:LOCALAPPDATA "Android\Sdk"),
        "D:\Android\Sdk"
    ) | Where-Object { $_ }) {
        $candidate = Join-Path $sdk "platform-tools\adb.exe"
        if (Test-Path -LiteralPath $candidate) {
            return $candidate
        }
    }
    throw "ADB not found. Install Android platform-tools or pass -AdbPath."
}

function Invoke-Adb {
    param(
        [Parameter(Mandatory)]
        [string[]]$Arguments
    )
    $output = & $script:ResolvedAdb @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        $joined = $output -join [Environment]::NewLine
        throw "ADB command failed: adb $($Arguments -join ' ') $joined"
    }
    return ($output -join [Environment]::NewLine)
}

function Resolve-Serial {
    $devices = Invoke-Adb -Arguments @("devices")
    $connected = @(
        $devices -split "\r?\n" |
            Select-String "^\S+\s+device$" |
            ForEach-Object { ($_ -split "\s+")[0] }
    )
    if ($Serial) {
        if ($Serial -notin $connected) {
            throw "Requested Android serial is not connected: $Serial"
        }
        return $Serial
    }
    if ($connected.Count -ne 1) {
        throw "Connect exactly one unlocked Android tablet (found $($connected.Count))."
    }
    return $connected[0]
}

function Get-SafeLog {
    param([string]$Text)
    return $Text -replace (
        '(?i)((?:authorization|deviceToken|provisioningToken|' +
        'maintenancePin|pin|password|token)\s*[=:]\s*)' +
        '(?:Bearer\s+)?\S+'
    ), '$1[REDACTED]'
}

function Add-Result {
    param(
        [string]$Name,
        [bool]$Passed,
        [string]$Detail
    )
    $script:Results.Add([PSCustomObject]@{
        name = $Name
        status = if ($Passed) { "PASS" } else { "FAIL" }
        detail = $Detail
    })
}

$expectedVersion = Get-ExpectedVersion
if (-not $ApkPath) {
    $ApkPath = Join-Path $repoRoot (
        "android_tablet\android-app\app\build\outputs\apk\debug\app-debug.apk"
    )
}

if ($Action -eq "Configure" -and -not $Apply) {
    Write-Output "DRY RUN: configure SmartDesk tablet as Seat $SeatId"
    if (-not $SkipInstall) {
        Write-Output "  install shared APK: $ApkPath"
    }
    Write-Output "  grant CAMERA and RECORD_AUDIO"
    Write-Output "  set SmartDesk as default HOME"
    Write-Output "  keep screen awake while powered and disable blocking lock screen"
    Write-Output "  whitelist SmartDesk from standard Android battery idle"
    Write-Output "  launch the app; complete Seat $SeatId provisioning on the tablet"
    Write-Output "Re-run with -Apply to make these device changes."
    exit 0
}

if ($Apply -and $Action -ne "Configure") {
    throw "-Apply is valid only with -Action Configure."
}

$script:ResolvedAdb = Resolve-Adb
$resolvedSerial = Resolve-Serial
$prefix = @("-s", $resolvedSerial)

if ($Action -eq "Configure") {
    if (-not $SkipInstall) {
        $fullApk = [IO.Path]::GetFullPath($ApkPath)
        if (-not (Test-Path -LiteralPath $fullApk)) {
            throw "APK not found: $fullApk"
        }
        $install = Invoke-Adb -Arguments (
            $prefix + @("install", "-r", $fullApk)
        )
        if ($install -notmatch "Success") {
            throw "APK install did not report success: $install"
        }
    }
    foreach ($permission in @(
        "android.permission.CAMERA",
        "android.permission.RECORD_AUDIO"
    )) {
        Invoke-Adb -Arguments (
            $prefix + @("shell", "pm", "grant", $packageName, $permission)
        ) | Out-Null
    }
    Invoke-Adb -Arguments (
        $prefix + @(
            "shell", "cmd", "package", "set-home-activity", $activityName
        )
    ) | Out-Null
    Invoke-Adb -Arguments (
        $prefix + @(
            "shell", "settings", "put", "global",
            "stay_on_while_plugged_in", "7"
        )
    ) | Out-Null
    Invoke-Adb -Arguments (
        $prefix + @("shell", "locksettings", "set-disabled", "true")
    ) | Out-Null
    Invoke-Adb -Arguments (
        $prefix + @(
            "shell", "dumpsys", "deviceidle",
            "whitelist", "+$packageName"
        )
    ) | Out-Null
    Invoke-Adb -Arguments (
        $prefix + @("shell", "am", "force-stop", $packageName)
    ) | Out-Null
    Invoke-Adb -Arguments (
        $prefix + @("shell", "am", "start", "-n", $activityName)
    ) | Out-Null
    Write-Output "CONFIGURE PASS: system policy applied for Seat $SeatId."
    Write-Output (
        "Complete in-app Seat $SeatId provisioning, then confirm the " +
        "manufacturer auto-start/background-unrestricted switches."
    )
    exit 0
}

$package = Invoke-Adb -Arguments (
    $prefix + @("shell", "dumpsys", "package", $packageName)
)
$resolvedHomeActivity = Invoke-Adb -Arguments (
    $prefix + @(
        "shell", "cmd", "package", "resolve-activity", "--brief",
        "-a", "android.intent.action.MAIN",
        "-c", "android.intent.category.HOME"
    )
)
$stayAwake = Invoke-Adb -Arguments (
    $prefix + @(
        "shell", "settings", "get", "global",
        "stay_on_while_plugged_in"
    )
)
$lockDisabled = Invoke-Adb -Arguments (
    $prefix + @("shell", "locksettings", "get-disabled")
)
$idleWhitelist = Invoke-Adb -Arguments (
    $prefix + @("shell", "dumpsys", "deviceidle", "whitelist")
)
$wifi = Invoke-Adb -Arguments (
    $prefix + @("shell", "cmd", "wifi", "status")
)
$activity = Invoke-Adb -Arguments (
    $prefix + @("shell", "dumpsys", "activity", "activities")
)
$rawLog = Invoke-Adb -Arguments (
    $prefix + @(
        "shell", "logcat", "-d", "-s",
        "SmartDeskTablet:I", "AndroidRuntime:E", "*:S"
    )
)
$safeLog = Get-SafeLog -Text $rawLog

$script:Results = [System.Collections.Generic.List[object]]::new()
Add-Result "APK version" (
    $package -match "versionName=$([regex]::Escape($expectedVersion))(?:\s|$)"
) "expected=$expectedVersion"
Add-Result "Camera permission" (
    $package -match "android\.permission\.CAMERA: granted=true"
) "CAMERA must be granted"
Add-Result "Microphone permission" (
    $package -match "android\.permission\.RECORD_AUDIO: granted=true"
) "RECORD_AUDIO must be granted"
Add-Result "Default HOME" (
    $resolvedHomeActivity -match [regex]::Escape($activityName)
) $resolvedHomeActivity.Trim()
Add-Result "Powered screen policy" (
    $stayAwake.Trim() -eq "7"
) "stay_on_while_plugged_in=$($stayAwake.Trim())"
Add-Result "Blocking lock screen" (
    $lockDisabled.Trim() -match "(?i)^true$"
) "locksettings disabled=$($lockDisabled.Trim())"
Add-Result "Battery idle whitelist" (
    $idleWhitelist -match [regex]::Escape($packageName)
) "standard Android whitelist"
if ($ExpectedWifiSsid) {
    Add-Result "Wi-Fi SSID" (
        $wifi -match [regex]::Escape($ExpectedWifiSsid)
    ) "expected=$ExpectedWifiSsid"
}
Add-Result "MainActivity" (
    $activity -match [regex]::Escape($activityName)
) "activity resumed"
$expectedPath = if ($SeatId -eq 1) { "/host" } else { "/seat/$SeatId" }
Add-Result "Seat page" (
    $safeLog -match [regex]::Escape($expectedPath)
) "expected path=$expectedPath"

if (-not $ReportPath) {
    $ReportPath = Join-Path $repoRoot (
        "logs\hardware\android-latest\seat-{0:D2}.json" -f $SeatId
    )
}
$fullReportPath = [IO.Path]::GetFullPath($ReportPath)
New-Item -ItemType Directory -Force -Path (
    Split-Path -Parent $fullReportPath
) | Out-Null
$report = [PSCustomObject]@{
    schemaVersion = 1
    generatedAt = [DateTimeOffset]::Now.ToString("o")
    action = $Action
    seatId = $SeatId
    serial = $resolvedSerial
    expectedVersion = $expectedVersion
    expectedWifiSsid = $ExpectedWifiSsid
    results = $script:Results
    diagnosticLog = $safeLog
}
$report | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (
    $fullReportPath
) -Encoding UTF8
$script:Results | Format-Table name, status, detail -AutoSize
Write-Output "Report: $fullReportPath"

if (
    $Action -eq "Verify" -and
    @($script:Results | Where-Object status -eq "FAIL").Count -gt 0
) {
    exit 1
}
exit 0
