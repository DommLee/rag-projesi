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
if "%AUTO_INGEST_CONFIG_FILE%"=="" set AUTO_INGEST_CONFIG_FILE=data\auto_ingest_sources.json
if "%API_AUTH_TOKEN%"=="" set API_AUTH_TOKEN=

echo [24_auto_ingest_configure] API=http://localhost:%API_HOST_PORT%
echo [24_auto_ingest_configure] Config=%AUTO_INGEST_CONFIG_FILE%
python scripts/auto_ingest_ctl.py --base-url http://localhost:%API_HOST_PORT% --action set-config --config-path "%AUTO_INGEST_CONFIG_FILE%" --token "%API_AUTH_TOKEN%"
if errorlevel 1 exit /b 1

echo [24_auto_ingest_configure] Completed.
exit /b 0
