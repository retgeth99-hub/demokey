@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop.ps1"
if errorlevel 1 (
  echo.
  echo Stop failed. Keep this window open and check the error above.
  pause
  exit /b 1
)
pause
