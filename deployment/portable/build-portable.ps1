[CmdletBinding()]
param(
    [string]$OutputDirectory = "",
    [string]$SpeechModelsDirectory = "",
    [string]$GestureModelsDirectory = "",
    [string]$WheelhouseDirectory = "",
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$commit = (& git -C $repoRoot rev-parse --short=12 HEAD).Trim()
if ($LASTEXITCODE -ne 0) {
    throw "Unable to resolve Git commit."
}
$version = "0.9.0-internal+$commit"
$artifactRoot = Join-Path $repoRoot "artifacts"
if (-not $OutputDirectory) {
    $OutputDirectory = Join-Path $artifactRoot "SmartDesk-$commit"
}
$fullOutput = [IO.Path]::GetFullPath($OutputDirectory)
$fullArtifacts = [IO.Path]::GetFullPath($artifactRoot)
if (-not $fullOutput.StartsWith($fullArtifacts, [StringComparison]::OrdinalIgnoreCase)) {
    throw "OutputDirectory must stay inside $fullArtifacts"
}

function Copy-SourceTree {
    param([string]$Source, [string]$Destination)
    $blockedDirectories = @(
        ".git", ".gradle", ".pio", ".pytest_cache", ".venv",
        "__pycache__", "build", "dist", "logs", "node_modules"
    )
    Get-ChildItem -LiteralPath $Source -Recurse -File | ForEach-Object {
        $relative = $_.FullName.Substring($Source.Length).TrimStart("\")
        $segments = $relative -split "[\\/]"
        if (@($segments | Where-Object { $_ -in $blockedDirectories }).Count -gt 0) {
            return
        }
        if ($_.Extension -in @(
            ".db", ".log", ".pyc",
            ".tflite", ".task", ".onnx", ".pt", ".pth", ".ckpt"
        )) {
            return
        }
        $target = Join-Path $Destination $relative
        New-Item -ItemType Directory -Force -Path (
            Split-Path -Parent $target
        ) | Out-Null
        Copy-Item -LiteralPath $_.FullName -Destination $target -Force
    }
}

if (-not $SkipBuild) {
    Push-Location (Join-Path $repoRoot "new_coding_desk\frontend")
    try {
        npm run build
        if ($LASTEXITCODE -ne 0) { throw "Frontend build failed." }
    }
    finally { Pop-Location }

    $gradle = Join-Path $repoRoot "android_tablet\android-app\gradlew.bat"
    if (Test-Path -LiteralPath $gradle) {
        Push-Location (Split-Path -Parent $gradle)
        try {
            & $gradle assembleDebug --no-daemon --console=plain
            if ($LASTEXITCODE -ne 0) { throw "Android APK build failed." }
        }
        finally { Pop-Location }
    }
}

$frontendDist = Join-Path $repoRoot "new_coding_desk\frontend\dist"
$apk = Join-Path $repoRoot (
    "android_tablet\android-app\app\build\outputs\apk\debug\app-debug.apk"
)
foreach ($required in @($frontendDist, $apk)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "Required build output is missing: $required"
    }
}

if (Test-Path -LiteralPath $fullOutput) {
    Remove-Item -LiteralPath $fullOutput -Recurse -Force
}
$payload = Join-Path $fullOutput "payload"
New-Item -ItemType Directory -Force -Path $payload | Out-Null

$deskDestination = Join-Path $payload "new_coding_desk"
Copy-SourceTree (
    Join-Path $repoRoot "new_coding_desk\backend"
) (Join-Path $deskDestination "backend")
Copy-SourceTree (
    Join-Path $repoRoot "new_coding_desk\host_services"
) (Join-Path $deskDestination "host_services")
Copy-SourceTree (
    Join-Path $repoRoot "new_coding_desk\tests"
) (Join-Path $deskDestination "tests")
New-Item -ItemType Directory -Force -Path (
    Join-Path $deskDestination "frontend"
) | Out-Null
Copy-Item -LiteralPath $frontendDist -Destination (
    Join-Path $deskDestination "frontend\dist"
) -Recurse -Force
foreach ($file in @(
    "frontend_server.py", "migrate_database.py", "requirements.txt"
)) {
    Copy-Item -LiteralPath (Join-Path $repoRoot "new_coding_desk\$file") `
        -Destination (Join-Path $deskDestination $file) -Force
}

Copy-SourceTree (
    Join-Path $repoRoot "smartdesk_gesture_controller"
) (Join-Path $payload "smartdesk_gesture_controller")
Copy-SourceTree (
    Join-Path $repoRoot "esp32_seat_controller"
) (Join-Path $payload "esp32_seat_controller")
Copy-SourceTree (
    Join-Path $repoRoot "arduino_nano_controller"
) (Join-Path $payload "arduino_nano_controller")
Copy-SourceTree (
    Join-Path $repoRoot "scripts"
) (Join-Path $payload "validation")
Copy-Item -LiteralPath (
    Join-Path $repoRoot "config\smartdesk.integration.esp32.example.json"
) -Destination (Join-Path $payload "smartdesk.integration.example.json")
New-Item -ItemType Directory -Force -Path (
    Join-Path $payload "android"
) | Out-Null
Copy-Item -LiteralPath $apk -Destination (
    Join-Path $payload "android\SmartDeskTablet-debug.apk"
)

if ($SpeechModelsDirectory) {
    Copy-SourceTree ([IO.Path]::GetFullPath($SpeechModelsDirectory)) (
        Join-Path $deskDestination "models"
    )
}
if ($GestureModelsDirectory) {
    Get-ChildItem -LiteralPath $GestureModelsDirectory -File | Where-Object {
        $_.Name -in @("hand_landmarker.task", "gesture_recognizer.task")
    } | Copy-Item -Destination (
        Join-Path $payload "smartdesk_gesture_controller"
    ) -Force
}
if ($WheelhouseDirectory) {
    Copy-SourceTree ([IO.Path]::GetFullPath($WheelhouseDirectory)) (
        Join-Path $fullOutput "wheelhouse"
    )
}

Copy-Item -Path (Join-Path $PSScriptRoot "package\*") `
    -Destination $fullOutput -Recurse -Force
[PSCustomObject]@{
    product = "SmartDesk"
    channel = "INTERNAL_DEMO"
    version = $version
    commit = $commit
    generatedAt = [DateTimeOffset]::Now.ToString("o")
    commercialReleaseApproved = $false
} | ConvertTo-Json | Set-Content -LiteralPath (
    Join-Path $fullOutput "package-manifest.json"
) -Encoding UTF8

$zipPath = "$fullOutput.zip"
if (Test-Path -LiteralPath $zipPath) {
    Remove-Item -LiteralPath $zipPath -Force
}
Compress-Archive -Path (Join-Path $fullOutput "*") `
    -DestinationPath $zipPath -CompressionLevel Optimal
Write-Host "Portable package: $fullOutput"
Write-Host "Archive: $zipPath"
