[CmdletBinding()]
param([Parameter(Mandatory = $true)][string]$PackageRoot)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$testRoot = Join-Path $repoRoot ".smartdesk-packaging\lifecycle-test"
$testFull = [IO.Path]::GetFullPath($testRoot)
$allowedRoot = [IO.Path]::GetFullPath(
    (Join-Path $repoRoot ".smartdesk-packaging")
)
if (-not $testFull.StartsWith(
    $allowedRoot + [IO.Path]::DirectorySeparatorChar,
    [StringComparison]::OrdinalIgnoreCase
)) {
    throw "Unsafe lifecycle test path."
}
if (Test-Path -LiteralPath $testFull) {
    Remove-Item -LiteralPath $testFull -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $testFull | Out-Null
$installDir = Join-Path $testFull "install"
$dataDir = Join-Path $testFull "data"
$packageOne = [IO.Path]::GetFullPath($PackageRoot)
$packageTwo = Join-Path $testFull "package-upgrade"
$packageFail = Join-Path $testFull "package-failure"

function Set-PackageVersion {
    param([string]$Root, [string]$Version)
    $manifestPath = Join-Path $Root "package-manifest.json"
    $manifest = Get-Content -LiteralPath $manifestPath -Encoding UTF8 |
        ConvertFrom-Json
    $manifest.version = $Version
    $manifest | ConvertTo-Json | Set-Content -LiteralPath $manifestPath `
        -Encoding UTF8
}

function Invoke-Install {
    param([string]$Root)
    & (Join-Path $Root "scripts\INSTALL.ps1") `
        -InstallDir $installDir -DataDir $dataDir `
        -SkipDependencies -SkipFirewall -SkipStartup
    if ($LASTEXITCODE -ne 0) { throw "Installer returned $LASTEXITCODE" }
}

try {
    Invoke-Install $packageOne
    $firstPointer = (
        Get-Content -LiteralPath (Join-Path $installDir "current.txt") `
            -Encoding UTF8 -Raw
    ).Trim()
    $databasePath = Join-Path $dataDir "smart_desk.db"
    if (-not (Test-Path -LiteralPath $databasePath)) {
        throw "Fresh install did not create the database."
    }

    Copy-Item -LiteralPath $packageOne -Destination $packageTwo `
        -Recurse -Force
    Set-PackageVersion $packageTwo "0.9.1-internal+lifecycle"
    Invoke-Install $packageTwo
    $upgradePointer = (
        Get-Content -LiteralPath (Join-Path $installDir "current.txt") `
            -Encoding UTF8 -Raw
    ).Trim()
    if ($upgradePointer -eq $firstPointer) {
        throw "Upgrade did not switch the active version."
    }
    $backupCount = @(
        Get-ChildItem -LiteralPath (Join-Path $dataDir "backups") `
            -Filter *.db -ErrorAction SilentlyContinue
    ).Count
    if ($backupCount -lt 1) {
        throw "Upgrade did not create a database backup."
    }

    Copy-Item -LiteralPath $packageTwo -Destination $packageFail `
        -Recurse -Force
    Set-PackageVersion $packageFail "0.9.2-internal+failure"
    Remove-Item -LiteralPath (
        Join-Path $packageFail "payload\new_coding_desk\migrate_database.py"
    ) -Force
    $failedAsExpected = $false
    try { Invoke-Install $packageFail }
    catch { $failedAsExpected = $true }
    if (-not $failedAsExpected) {
        throw "Injected migration failure was not detected."
    }
    $rollbackPointer = (
        Get-Content -LiteralPath (Join-Path $installDir "current.txt") `
            -Encoding UTF8 -Raw
    ).Trim()
    if ($rollbackPointer -ne $upgradePointer) {
        throw "Failed upgrade did not restore the previous pointer."
    }

    & (Join-Path $installDir "scripts\UNINSTALL.ps1")
    if (-not (Test-Path -LiteralPath $databasePath)) {
        throw "Default uninstall removed the preserved database."
    }
    [PSCustomObject]@{
        schemaVersion = 1
        generatedAt = [DateTimeOffset]::Now.ToString("o")
        freshInstall = "PASS"
        upgrade = "PASS"
        failedUpgradeRollback = "PASS"
        uninstallPreservedData = "PASS"
        backupCount = $backupCount
    } | ConvertTo-Json | Set-Content -LiteralPath (
        Join-Path $repoRoot "logs\verification\portable-lifecycle.json"
    ) -Encoding UTF8
    Write-Host "PORTABLE_LIFECYCLE_PASS"
}
finally {
    if (Test-Path -LiteralPath $testFull) {
        $testToken = Join-Path $testFull (
            "data\config\esp32-device-tokens.json"
        )
        if (Test-Path -LiteralPath $testToken) {
            & icacls $testToken /grant:r "$env:USERNAME`:(F)" | Out-Null
        }
        Remove-Item -LiteralPath $testFull -Recurse -Force
    }
}
