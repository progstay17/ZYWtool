@echo off
setlocal
cd /d "%~dp0"
echo ==========================================
echo   ZYWtool - Optional Windows Installation
echo ==========================================
echo.
if not exist "%~dp0install.ps1" (
  echo ERROR: install.ps1 was not found beside this file.
  pause
  exit /b 2
)
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
set "RC=%ERRORLEVEL%"
echo.
if not "%RC%"=="0" (
  echo Installation failed with exit code %RC%.
) else (
  echo Installation completed successfully.
)
echo.
pause
exit /b %RC%
