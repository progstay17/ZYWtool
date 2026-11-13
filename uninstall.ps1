param(
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA 'Programs\ZYWtool')
)
$ErrorActionPreference = 'Stop'
$Shortcut = Join-Path ([Environment]::GetFolderPath('Desktop')) 'ZYWtool.lnk'
if (Test-Path $Shortcut) { Remove-Item -LiteralPath $Shortcut -Force }
if (Test-Path $InstallDir) { Remove-Item -LiteralPath $InstallDir -Recurse -Force }
Write-Host "Application removed: $InstallDir"
Write-Host 'User config under AppData and all external workbook/data folders were preserved.'
