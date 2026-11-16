@echo off
setlocal
cd /d "%~dp0"
title Setup SAU Creator Workbench

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] .venv is missing. Create the project environment first.
  pause
  exit /b 1
)

echo [1/3] Installing local web dependencies...
uv pip install --python ".venv\Scripts\python.exe" -e ".[web]"
if errorlevel 1 goto :error

echo [2/3] Installing frontend dependencies...
pushd sau_frontend
call npm install
if errorlevel 1 goto :frontend_error

echo [3/3] Building frontend...
call npm run build
if errorlevel 1 goto :frontend_error
popd

echo.
echo Setup complete. Double-click start-workbench.bat next time.
pause
exit /b 0

:frontend_error
popd
:error
echo [ERROR] Setup failed. Review the message above.
pause
exit /b 1
