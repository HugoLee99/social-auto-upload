@echo off
setlocal
cd /d "%~dp0"
title SAU Creator Workbench

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
echo SAU Creator Workbench is starting...
echo Open: http://127.0.0.1:5409
echo Keep this window open for account monitoring.
echo.
set "SAU_OPEN_BROWSER=1"
".venv\Scripts\python.exe" workbench_server.py
exit /b %errorlevel%

:build_error
popd
echo [ERROR] Frontend build failed.
pause
exit /b 1
