$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
$Build = Join-Path $Root "build\pyinstaller"
$Release = Join-Path $Root "release\ZYWtool"
New-Item -ItemType Directory -Force -Path $Build, $Release | Out-Null
python -m PyInstaller --noconfirm --clean --windowed --onedir --name ZYWtool --distpath "$Build\main" --workpath "$Build\work-main" --collect-all mediapipe --collect-all av --collect-all cv2 --exclude-module mediapipe.tasks.python.test --exclude-module pandas --exclude-module pytest zywtool.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }
Copy-Item -Recurse -Force "$Build\main\ZYWtool\*" $Release
Copy-Item -Force "$Root\zyw_config.example.json" "$Release\"
Copy-Item -Force "$Root\requirements.txt" "$Release\"
Write-Host "BUILD_COMPLETE=$Release"

