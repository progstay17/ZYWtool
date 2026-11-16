$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
$Build = Join-Path $Root "build\pyinstaller"
$ReleaseRoot = Join-Path $Root "release"
$Release = Join-Path $ReleaseRoot "ZYWtool"
if (Test-Path $ReleaseRoot) { Remove-Item -Recurse -Force $ReleaseRoot }
New-Item -ItemType Directory -Force -Path $Build, $Release | Out-Null
python -m PyInstaller --noconfirm --clean --windowed --onedir --name ZYWtool --distpath "$Build\main" --workpath "$Build\work-main" --collect-all mediapipe --collect-all av --collect-all cv2 --exclude-module mediapipe.tasks.python.test --exclude-module pandas --exclude-module pytest zywtool.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }
Copy-Item -Recurse -Force "$Build\main\ZYWtool\*" $Release
Copy-Item -Force "$Root\zyw_config.example.json" "$Release\"
Copy-Item -Force "$Root\requirements.txt" "$Release\"
Copy-Item -Force "$Root\install.ps1", "$Root\uninstall.ps1", "$Root\README.md", "$Root\LICENSE", "$Root\MODEL.md", "$Root\THIRD_PARTY_NOTICES.md" $ReleaseRoot
Set-Content -Path (Join-Path $ReleaseRoot "VERSION.txt") -Value "1.0.1" -Encoding ascii
$Archive = Join-Path $ReleaseRoot "ZYWtool-Windows-Portable.zip"
Compress-Archive -Path (Join-Path $ReleaseRoot "install.ps1"), (Join-Path $ReleaseRoot "uninstall.ps1"), (Join-Path $ReleaseRoot "README.md"), (Join-Path $ReleaseRoot "LICENSE"), (Join-Path $ReleaseRoot "MODEL.md"), (Join-Path $ReleaseRoot "THIRD_PARTY_NOTICES.md"), (Join-Path $ReleaseRoot "VERSION.txt"), $Release -DestinationPath $Archive -CompressionLevel Optimal
if ($LASTEXITCODE -ne 0) { throw "Portable ZIP creation failed with exit code $LASTEXITCODE" }
Write-Host "BUILD_COMPLETE=$Release"
Write-Host "PORTABLE_ZIP=$Archive"