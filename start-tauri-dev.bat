@echo off
setlocal

cd /d "%~dp0"

where npm.cmd >nul 2>nul
if errorlevel 1 (
  echo npm.cmd not found. Please install Node.js and npm first.
  pause
  exit /b 1
)

echo Starting UnrealImageMaker Tauri dev...
echo Project: %cd%
echo.

echo Checking stale backend on 127.0.0.1:8765...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$connections = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue; foreach ($connection in $connections) { Write-Host ('Stopping stale backend PID ' + $connection.OwningProcess); Stop-Process -Id $connection.OwningProcess -Force -ErrorAction SilentlyContinue }"
echo.

npm.cmd run tauri -- dev %*
set EXIT_CODE=%ERRORLEVEL%

if not "%EXIT_CODE%"=="0" (
  echo.
  echo Tauri dev exited with code %EXIT_CODE%.
  pause
)

exit /b %EXIT_CODE%
