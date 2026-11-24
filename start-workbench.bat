@echo off
setlocal
cd /d "%~dp0"
title Daydream Dispatch

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Python virtual environment not found.
  echo Run setup-workbench.bat first.
  pause
  exit /b 1
)

if not exist "sau_frontend\dist\index.html" (
  echo [INFO] Frontend build not found. Building it now...
  pushd sau_frontend
  call npm install
  if errorlevel 1 goto :build_error
  call npm run build
  if errorlevel 1 goto :build_error
  popd
)

echo.
echo Daydream Dispatch is starting...
echo Open: http://127.0.0.1:5409
echo Keep this window open while Daydream Dispatch monitors your accounts.
echo.
set "SAU_OPEN_BROWSER=1"
set "SAU_BILIUP_ROOT=%~dp0.local\tools\biliup"
".venv\Scripts\python.exe" workbench_server.py
exit /b %errorlevel%

:build_error
popd
echo [ERROR] Frontend build failed.
pause
exit /b 1
