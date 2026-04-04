@echo off
setlocal
set ROOT=%~dp0
cd /d "%ROOT%"

if not exist ".venv\Scripts\python.exe" (
  echo [100_run_app] Virtualenv not found. Running setup first...
  call 00_setup.bat
  if errorlevel 1 exit /b 1
)

call ".venv\Scripts\activate.bat"
if errorlevel 1 exit /b 1

if "%ALLOW_LOCAL_FALLBACK%"=="" set ALLOW_LOCAL_FALLBACK=1
if "%SKIP_OLLAMA_PULL%"=="" set SKIP_OLLAMA_PULL=1

echo [100_run_app] Launching local application...
python scripts\run_application.py --seed-eval-if-empty %*
if errorlevel 1 exit /b 1

echo [100_run_app] Completed.
exit /b 0

