@echo off
setlocal
set ROOT=%~dp0
cd /d "%ROOT%"

if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" scripts\run_modern_app.py --api-port 18002 --ui-port 3000
) else (
  python scripts\run_modern_app.py --api-port 18002 --ui-port 3000
)

exit /b %errorlevel%

