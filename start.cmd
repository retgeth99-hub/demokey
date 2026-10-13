@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1"
if errorlevel 1 (
  echo.
  echo Startup failed. Keep this window open and check the error above.
  pause
  exit /b 1
)
echo.
echo Startup completed. Open http://127.0.0.1:5173/
pause
