@echo off
setlocal
set ROOT=%~dp0
cd /d "%ROOT%"

call ".venv\Scripts\activate.bat"
if errorlevel 1 exit /b 1

if "%API_HOST_PORT%"=="" (
  if exist "logs\.runtime_api_port" (
    set /p API_HOST_PORT=<logs\.runtime_api_port
  )
)
if "%API_HOST_PORT%"=="" set API_HOST_PORT=18000

echo [40_smoke_test] Running smoke tests...
python scripts/smoke_test.py --base-url http://localhost:%API_HOST_PORT%
if errorlevel 1 exit /b 1

echo [40_smoke_test] Completed.
exit /b 0
