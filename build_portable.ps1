$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
$Build = Join-Path $Root "build\pyinstaller"
$ReleaseRoot = Join-Path $Root "release"
$Release = Join-Path $ReleaseRoot "ZYWtool"
$Venv = Join-Path $Root ".venv-build"
if (-not (Get-Command uv.exe -ErrorAction SilentlyContinue)) { throw "uv is required to provision the pinned Python 3.12 build environment." }
uv python install 3.12
if (-not (Test-Path (Join-Path $Venv "Scripts\python.exe"))) { uv venv $Venv --python 3.12 }
$Python = Join-Path $Venv "Scripts\python.exe"
uv pip install --python $Python -r (Join-Path $Root "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed." }
if (Test-Path $ReleaseRoot) { Remove-Item -Recurse -Force $ReleaseRoot }
New-Item -ItemType Directory -Force -Path $Build, $Release | Out-Null
& $Python -m PyInstaller --noconfirm --clean --windowed --onedir --name ZYWtool --manifest "$Root\app.manifest" --distpath "$Build\main" --workpath "$Build\work-main" --collect-all mediapipe --collect-all av --collect-all cv2 --exclude-module mediapipe.tasks.python.test --exclude-module pandas --exclude-module pytest zywtool.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }
Copy-Item -Recurse -Force "$Build\main\ZYWtool\*" $Release
Copy-Item -Force "$Root\README.md", "$Root\LICENSE", "$Root\MODEL.md", "$Root\THIRD_PARTY_NOTICES.md" $ReleaseRoot
Set-Content -Path (Join-Path $ReleaseRoot "VERSION.txt") -Value "1.0.6" -Encoding ascii
$Archive = Join-Path $ReleaseRoot "ZYWtool-Windows-Portable.zip"
Compress-Archive -Path (Join-Path $ReleaseRoot "README.md"), (Join-Path $ReleaseRoot "LICENSE"), (Join-Path $ReleaseRoot "MODEL.md"), (Join-Path $ReleaseRoot "THIRD_PARTY_NOTICES.md"), (Join-Path $ReleaseRoot "VERSION.txt"), $Release -DestinationPath $Archive -CompressionLevel Optimal
if ($LASTEXITCODE -ne 0) { throw "Portable ZIP creation failed with exit code $LASTEXITCODE" }
Write-Host "BUILD_COMPLETE=$Release"
Write-Host "PORTABLE_ZIP=$Archive"
