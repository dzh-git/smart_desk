[CmdletBinding()]
param(
    [string]$OutputDirectory = "",
    [string]$PlatformToolsDirectory = "",
    [string]$ApkPath = "",
    [string]$DefaultCentralHost = "192.168.137.1",
    [string]$DefaultWifiSsid = "",
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$artifactRoot = Join-Path $repoRoot "artifacts"
$commit = (& git -C $repoRoot rev-parse --short=12 HEAD).Trim()
if ($LASTEXITCODE -ne 0) { throw "Unable to resolve Git commit." }

if (-not $OutputDirectory) {
    $OutputDirectory = Join-Path $artifactRoot "SmartDesk-Tablet-Deploy-$commit"
}
$fullOutput = [IO.Path]::GetFullPath($OutputDirectory)
$fullArtifacts = [IO.Path]::GetFullPath($artifactRoot)
$artifactPrefix = $fullArtifacts.TrimEnd(
    [IO.Path]::DirectorySeparatorChar,
    [IO.Path]::AltDirectorySeparatorChar
) + [IO.Path]::DirectorySeparatorChar
if (-not $fullOutput.StartsWith($artifactPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "OutputDirectory must stay inside $fullArtifacts"
}

if (-not $PlatformToolsDirectory) {
    $candidates = @(
        $(if ($env:ANDROID_HOME) { Join-Path $env:ANDROID_HOME "platform-tools" }),
        $(if ($env:LOCALAPPDATA) { Join-Path $env:LOCALAPPDATA "Android\Sdk\platform-tools" }),
        "D:\Android\Sdk\platform-tools"
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
    $PlatformToolsDirectory = $candidates | Select-Object -First 1
}
if (-not $PlatformToolsDirectory) {
    throw "Android platform-tools not found; pass -PlatformToolsDirectory."
}
$PlatformToolsDirectory = [IO.Path]::GetFullPath($PlatformToolsDirectory)

if (-not $SkipBuild) {
    Push-Location (Join-Path $repoRoot "android_tablet\diagnostic-web")
    try {
        npm.cmd run build:android
        if ($LASTEXITCODE -ne 0) { throw "Android diagnostic web build failed." }
    }
    finally { Pop-Location }

    Push-Location (Join-Path $repoRoot "android_tablet\android-app")
    try {
        & ".\gradlew.bat" assembleDebug --no-daemon --console=plain
        if ($LASTEXITCODE -ne 0) { throw "Android APK build failed." }
    }
    finally { Pop-Location }
}

if (-not $ApkPath) {
    $ApkPath = Join-Path $repoRoot (
        "android_tablet\android-app\app\build\outputs\apk\debug\app-debug.apk"
    )
}
$ApkPath = [IO.Path]::GetFullPath($ApkPath)
if (-not (Test-Path -LiteralPath $ApkPath)) {
    throw "APK not found: $ApkPath"
}

$requiredPlatformFiles = @(
    "adb.exe", "AdbWinApi.dll", "AdbWinUsbApi.dll", "NOTICE.txt"
)
foreach ($name in $requiredPlatformFiles) {
    $candidate = Join-Path $PlatformToolsDirectory $name
    if (-not (Test-Path -LiteralPath $candidate)) {
        throw "Required platform-tools file missing: $candidate"
    }
}

$gradleFile = Join-Path $repoRoot (
    "android_tablet\android-app\app\build.gradle.kts"
)
$gradle = Get-Content -LiteralPath $gradleFile -Encoding UTF8 -Raw
$versionMatch = [regex]::Match($gradle, 'versionName\s*=\s*"([^"]+)"')
if (-not $versionMatch.Success) { throw "Unable to read Android versionName." }
$versionName = $versionMatch.Groups[1].Value

if (Test-Path -LiteralPath $fullOutput) {
    Remove-Item -LiteralPath $fullOutput -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $fullOutput | Out-Null
Copy-Item -Path (Join-Path $PSScriptRoot "package\*") `
    -Destination $fullOutput -Recurse -Force

$payload = Join-Path $fullOutput "payload"
$platformTarget = Join-Path $fullOutput "platform-tools"
$scriptsTarget = Join-Path $fullOutput "scripts"
New-Item -ItemType Directory -Force -Path $payload, $platformTarget, $scriptsTarget | Out-Null
Copy-Item -LiteralPath $ApkPath -Destination (
    Join-Path $payload "SmartDeskTablet.apk"
) -Force
foreach ($name in $requiredPlatformFiles) {
    Copy-Item -LiteralPath (Join-Path $PlatformToolsDirectory $name) `
        -Destination (Join-Path $platformTarget $name) -Force
}
Copy-Item -LiteralPath (Join-Path $repoRoot "scripts\manage_android_tablet.ps1") `
    -Destination (Join-Path $scriptsTarget "manage_android_tablet.ps1") -Force

[PSCustomObject]@{
    centralHost = $DefaultCentralHost
    expectedWifiSsid = $DefaultWifiSsid
} | ConvertTo-Json | Set-Content -LiteralPath (
    Join-Path $fullOutput "deployment-defaults.json"
) -Encoding UTF8

$apkHash = (Get-FileHash -LiteralPath $ApkPath -Algorithm SHA256).Hash.ToLowerInvariant()
[PSCustomObject]@{
    product = "SmartDesk Tablet Deploy"
    channel = "INTERNAL_DEMO"
    commit = $commit
    versionName = $versionName
    generatedAt = [DateTimeOffset]::Now.ToString("o")
    apkSha256 = $apkHash
    platformToolsBundled = $true
    secretsIncluded = $false
} | ConvertTo-Json | Set-Content -LiteralPath (
    Join-Path $fullOutput "package-manifest.json"
) -Encoding UTF8

$zipPath = "$fullOutput.zip"
if (Test-Path -LiteralPath $zipPath) {
    Remove-Item -LiteralPath $zipPath -Force
}
Compress-Archive -Path (Join-Path $fullOutput "*") `
    -DestinationPath $zipPath -CompressionLevel Optimal
Write-Host "Tablet deploy package: $fullOutput"
Write-Host "Archive: $zipPath"
