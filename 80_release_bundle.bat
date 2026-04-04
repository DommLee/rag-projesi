@echo off
setlocal
set ROOT=%~dp0
cd /d "%ROOT%"

if not exist ".venv\Scripts\python.exe" (
  echo [80_release_bundle] Virtualenv not found. Run 00_setup.bat first.
  exit /b 1
)

if "%RUN_LOGDIR%"=="" (
  echo [80_release_bundle] Building release bundle with latest logs...
  .venv\Scripts\python scripts\build_release_bundle.py --output-root releases
) else (
  echo [80_release_bundle] Building release bundle with run log dir: %RUN_LOGDIR%
  .venv\Scripts\python scripts\build_release_bundle.py --run-log-dir "%RUN_LOGDIR%" --output-root releases
)
if errorlevel 1 exit /b 1

echo [80_release_bundle] Completed.
exit /b 0

