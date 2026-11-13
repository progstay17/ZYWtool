param(
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA 'Programs\ZYWtool')
)
$ErrorActionPreference = 'Stop'
$Source = Join-Path $PSScriptRoot 'ZYWtool'
if (-not (Test-Path (Join-Path $Source 'ZYWtool.exe'))) { throw 'Folder ZYWtool portable tidak ditemukan. Extract paket terlebih dahulu.' }
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
Copy-Item -Path (Join-Path $Source '*') -Destination $InstallDir -Recurse -Force
$ConfigDir = Join-Path $env:APPDATA 'ZYWtool'
New-Item -ItemType Directory -Force -Path $ConfigDir | Out-Null
$Config = Join-Path $ConfigDir 'zyw_config.json'
if (-not (Test-Path $Config)) {
    Copy-Item (Join-Path $Source 'zyw_config.example.json') $Config
}
$Wsh = New-Object -ComObject WScript.Shell
$Shortcut = $Wsh.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Desktop')) 'ZYWtool.lnk'))
$Shortcut.TargetPath = Join-Path $InstallDir 'ZYWtool.exe'
$Shortcut.WorkingDirectory = $InstallDir
$Shortcut.Save()
Write-Host "Installed: $InstallDir"
Write-Host "Config: $Config"
Write-Host 'Workbook, source recordings, reports and reference data were not copied or modified.'
