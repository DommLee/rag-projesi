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
if "%PROVIDER_PREF%"=="" set PROVIDER_PREF=ollama
if "%PROVIDER_OVERRIDES_JSON%"=="" set PROVIDER_OVERRIDES_JSON=
if "%API_AUTH_TOKEN%"=="" set API_AUTH_TOKEN=

echo [31_validate_provider] API=http://localhost:%API_HOST_PORT%
echo [31_validate_provider] provider=%PROVIDER_PREF%
python scripts/provider_validate.py --base-url http://localhost:%API_HOST_PORT% --provider "%PROVIDER_PREF%" --overrides "%PROVIDER_OVERRIDES_JSON%" --token "%API_AUTH_TOKEN%"
if errorlevel 1 exit /b 1

echo [31_validate_provider] Completed.
exit /b 0
