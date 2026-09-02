[CmdletBinding()]
param(
    [ValidateRange(0, 9)]
    [int]$SeatId = 0,
    [string]$CentralHost = "",
    [string]$ExpectedWifiSsid = "",
    [string]$Serial = "",
    [string]$AdbPath = "",
    [switch]$ConfirmTarget,
    [switch]$SkipManualWait,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$packageRoot = Split-Path -Parent $PSScriptRoot
$manifest = Get-Content -LiteralPath (
    Join-Path $packageRoot "package-manifest.json"
) -Encoding UTF8 -Raw | ConvertFrom-Json
$defaults = Get-Content -LiteralPath (
    Join-Path $packageRoot "deployment-defaults.json"
) -Encoding UTF8 -Raw | ConvertFrom-Json
$apk = Join-Path $packageRoot "payload\SmartDeskTablet.apk"
if (-not (Test-Path -LiteralPath $apk)) {
    throw "Missing package file: $apk"
}
$expectedApkHash = [string]$manifest.apkSha256
if ($expectedApkHash -notmatch '^[0-9A-Fa-f]{64}$') {
    throw "Package manifest is missing a valid APK SHA-256 hash."
}
$apkStream = [IO.File]::OpenRead($apk)
try {
    $sha256 = [Security.Cryptography.SHA256]::Create()
    try {
        $actualApkHash = -join (
            $sha256.ComputeHash($apkStream) | ForEach-Object { $_.ToString("x2") }
        )
    }
    finally { $sha256.Dispose() }
}
finally { $apkStream.Dispose() }
if (-not $actualApkHash.Equals($expectedApkHash, [StringComparison]::OrdinalIgnoreCase)) {
    throw "APK SHA-256 integrity check failed; do not install this package."
}

function Read-SeatId {
    while ($true) {
        $value = Read-Host "请输入席位编号 Seat ID（1-9，Seat 1 为主持人）"
        $parsed = 0
        if ([int]::TryParse($value, [ref]$parsed) -and $parsed -in 1..9) {
            return $parsed
        }
        Write-Host "席位必须为 1 到 9。" -ForegroundColor Yellow
    }
}

function Normalize-CentralHost([string]$Value) {
    $candidate = $Value.Trim().TrimEnd("/")
    if (-not $candidate.Contains("://")) { $candidate = "http://$candidate" }
    $uri = $null
    if (-not [Uri]::TryCreate($candidate, [UriKind]::Absolute, [ref]$uri)) {
        throw "中央主机地址无效：$Value"
    }
    if ($uri.Scheme -notin @("http", "https") -or $uri.UserInfo -or -not $uri.IsDefaultPort) {
        throw "中央主机只能是无端口、无凭据的 http/https 主机地址。"
    }
    if ($uri.AbsolutePath -ne "/" -or $uri.Query -or $uri.Fragment) {
        throw "中央主机不得包含路径、查询参数或片段。"
    }
    return "$($uri.Scheme)://$($uri.Host)"
}

if ($SeatId -eq 0) { $SeatId = Read-SeatId }
if (-not $CentralHost) {
    $suggested = [string]$defaults.centralHost
    $entered = Read-Host "中央主机地址（直接回车使用 $suggested）"
    $CentralHost = if ($entered.Trim()) { $entered } else { $suggested }
}
$CentralHost = Normalize-CentralHost $CentralHost
if (-not $ExpectedWifiSsid) {
    $ExpectedWifiSsid = [string]$defaults.expectedWifiSsid
}

Write-Host ""
Write-Host "SmartDesk tablet deployment preview"
Write-Host "  Seat $SeatId"
Write-Host "  Central host: $CentralHost"
Write-Host "  Expected Wi-Fi: $(if ($ExpectedWifiSsid) { $ExpectedWifiSsid } else { '(not enforced)' })"
Write-Host "  The provisioning password and maintenance PIN are entered only on the tablet."
Write-Host "  No device token or secret is accepted by this script."
if ($DryRun) {
    Write-Host "DRY RUN PASS: no tablet was changed."
    exit 0
}

$adb = if ($AdbPath) {
    [IO.Path]::GetFullPath($AdbPath)
} else {
    Join-Path $packageRoot "platform-tools\adb.exe"
}
$manager = Join-Path $PSScriptRoot "manage_android_tablet.ps1"
foreach ($required in @($adb, $apk, $manager)) {
    if (-not (Test-Path -LiteralPath $required)) { throw "Missing package file: $required" }
}

$deviceLines = @(& $adb devices | Select-Object -Skip 1 | Where-Object { $_ -match "\sdevice$" })
if ($Serial) {
    if (-not ($deviceLines -match "^$([regex]::Escape($Serial))\s")) {
        throw "Requested tablet is not connected and authorized: $Serial"
    }
} elseif ($deviceLines.Count -eq 1) {
    $Serial = ($deviceLines[0] -split "\s+")[0]
} else {
    throw "Connect and authorize exactly one tablet; detected $($deviceLines.Count)."
}

$manufacturer = (& $adb -s $Serial shell getprop ro.product.manufacturer).Trim()
$model = (& $adb -s $Serial shell getprop ro.product.model).Trim()
Write-Host ""
Write-Host "Target tablet: $manufacturer $model ($Serial) -> Seat $SeatId"
if (-not $ConfirmTarget) {
    $confirmation = Read-Host "输入 YES 确认安装并配置该平板"
    if ($confirmation -cne "YES") { throw "Deployment cancelled before device changes." }
}

$reports = Join-Path $packageRoot "reports"
New-Item -ItemType Directory -Force -Path $reports | Out-Null
$common = @{
    SeatId = $SeatId
    Serial = $Serial
    AdbPath = $adb
    ExpectedVersion = [string]$manifest.versionName
    ExpectedWifiSsid = $ExpectedWifiSsid
}
& $manager -Action Configure -Apply -ApkPath $apk `
    -ReportPath (Join-Path $reports ("seat-{0:D2}-configure.json" -f $SeatId)) `
    @common
if ($LASTEXITCODE -ne 0) { throw "Tablet system configuration failed." }

& $adb -s $Serial shell am force-stop com.smartdesk.tablet | Out-Null
& $adb -s $Serial shell am start -n com.smartdesk.tablet/.MainActivity `
    --ei com.smartdesk.tablet.extra.DEPLOYMENT_SEAT_ID $SeatId `
    --es com.smartdesk.tablet.extra.DEPLOYMENT_CENTRAL_HOST $CentralHost | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Unable to open SmartDesk setup on the tablet." }

Write-Host ""
Write-Host "请在平板中央配置页输入服务器预配口令和维护 PIN，然后保存。"
Write-Host "小米/MIUI 设备还需人工设置：允许自启动、后台无限制。"
if (-not $SkipManualWait) {
    [void](Read-Host "正式 Seat 页面出现后，回到此窗口按 Enter 开始验收")
}

& $manager -Action Verify `
    -ReportPath (Join-Path $reports ("seat-{0:D2}.json" -f $SeatId)) `
    @common
if ($LASTEXITCODE -ne 0) { throw "Tablet verification failed; see the report directory." }

Write-Host ""
Write-Host "DEPLOYMENT PASS: Seat $SeatId"
Write-Host "Report: $(Join-Path $reports ("seat-{0:D2}.json" -f $SeatId))"
