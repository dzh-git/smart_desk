[CmdletBinding()]
param([switch]$RemoveData)

$ErrorActionPreference = "Stop"
$installDir = Split-Path -Parent $PSScriptRoot
$settingsPath = Join-Path $installDir "install-settings.json"
$settings = if (Test-Path -LiteralPath $settingsPath) {
    Get-Content -LiteralPath $settingsPath -Encoding UTF8 | ConvertFrom-Json
} else { $null }
if ($settings) {
    $pidFile = Join-Path $settings.dataDir "logs\running-processes.json"
    if (Test-Path -LiteralPath $pidFile) {
        @(Get-Content -LiteralPath $pidFile -Encoding UTF8 |
            ConvertFrom-Json) | ForEach-Object {
            Stop-Process -Id $_.pid -Force -ErrorAction SilentlyContinue
        }
    }
}
$shortcut = Join-Path ([Environment]::GetFolderPath("Startup")) (
    "SmartDesk Internal Demo.lnk"
)
if (Test-Path -LiteralPath $shortcut) {
    Remove-Item -LiteralPath $shortcut -Force
}
$isAdmin = (
    [Security.Principal.WindowsPrincipal](
        [Security.Principal.WindowsIdentity]::GetCurrent()
    )
).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if ($isAdmin) {
    & netsh advfirewall firewall delete rule name="SmartDesk Internal Demo" |
        Out-Null
}
foreach ($child in @("versions", "runtime", "current.txt", "install-settings.json")) {
    $target = Join-Path $installDir $child
    if (Test-Path -LiteralPath $target) {
        Remove-Item -LiteralPath $target -Recurse -Force
    }
}
if ($RemoveData -and $settings -and (
    Test-Path -LiteralPath $settings.dataDir
)) {
    Remove-Item -LiteralPath $settings.dataDir -Recurse -Force
    Write-Host "UNINSTALL PASS: application and data removed."
}
else {
    Write-Host "UNINSTALL PASS: database and backups preserved."
    if ($settings) { Write-Host "Preserved: $($settings.dataDir)" }
}
