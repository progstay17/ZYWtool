param([string]$InstallDir = (Join-Path $env:LOCALAPPDATA 'Programs\ZYWtool'))
$ErrorActionPreference = 'Stop'
$Source = Join-Path $PSScriptRoot 'ZYWtool'
if (-not (Test-Path (Join-Path $Source 'ZYWtool.exe'))) { throw 'Folder ZYWtool portable tidak ditemukan. Extract paket terlebih dahulu.' }
# Python runtime and pinned Python packages are bundled. Install the external VC++ runtime if missing.
$RuntimeKey = 'HKLM:\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64'
$RuntimeInstalled = $false
try { $RuntimeInstalled = ((Get-ItemProperty -Path $RuntimeKey -Name Installed -ErrorAction Stop).Installed -eq 1) } catch { $RuntimeInstalled = $false }
if (-not $RuntimeInstalled) {
    $Winget = Get-Command winget.exe -ErrorAction SilentlyContinue
    if ($Winget) {
        & $Winget.Source install --id Microsoft.VCRedist.2015+.x64 --exact --silent --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -notin @(0, 3010)) { throw "Visual C++ Redistributable installation failed: $LASTEXITCODE" }
    } else {
        $TempInstaller = Join-Path $env:TEMP 'ZYWtool-vc_redist.x64.exe'
        Invoke-WebRequest -Uri 'https://aka.ms/vs/17/release/vc_redist.x64.exe' -OutFile $TempInstaller
        $Signature = Get-AuthenticodeSignature -FilePath $TempInstaller
        if ($Signature.Status -ne 'Valid' -or $Signature.SignerCertificate.Subject -notmatch 'Microsoft') {
            Remove-Item $TempInstaller -Force -ErrorAction SilentlyContinue
            throw 'Microsoft runtime installer signature validation failed.'
        }
        $Proc = Start-Process -FilePath $TempInstaller -ArgumentList '/install','/quiet','/norestart' -Wait -PassThru
        Remove-Item $TempInstaller -Force -ErrorAction SilentlyContinue
        if ($Proc.ExitCode -notin @(0, 3010)) { throw "Visual C++ Redistributable installation failed: $($Proc.ExitCode)" }
    }
}
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
Copy-Item -Path (Join-Path $Source '*') -Destination $InstallDir -Recurse -Force
$ConfigDir = Join-Path $env:APPDATA 'ZYWtool'
New-Item -ItemType Directory -Force -Path $ConfigDir | Out-Null
$Config = Join-Path $ConfigDir 'zyw_config.json'
if (-not (Test-Path $Config)) { Copy-Item (Join-Path $Source 'zyw_config.example.json') $Config }
$Wsh = New-Object -ComObject WScript.Shell
$Shortcut = $Wsh.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Desktop')) 'ZYWtool.lnk'))
$Shortcut.TargetPath = Join-Path $InstallDir 'ZYWtool.exe'
$Shortcut.WorkingDirectory = $InstallDir
$Shortcut.Save()
Write-Host "Installed: $InstallDir"
Write-Host "Config: $Config"
Write-Host 'Python and application dependencies are bundled in the portable package.'
Write-Host 'The Hand Check model is downloaded and checksum-verified on first use.'
Write-Host 'Workbook, source recordings, reports and reference data were not copied or modified.'
