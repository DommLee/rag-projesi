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
if "%API_AUTH_TOKEN%"=="" set API_AUTH_TOKEN=

echo [23_auto_ingest_stop] API=http://localhost:%API_HOST_PORT%
python scripts/auto_ingest_ctl.py --base-url http://localhost:%API_HOST_PORT% --action stop --token "%API_AUTH_TOKEN%"
if errorlevel 1 exit /b 1

echo [23_auto_ingest_stop] Completed.
exit /b 0
