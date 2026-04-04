@echo off
setlocal
set ROOT=%~dp0
cd /d "%ROOT%"

if not exist ".venv\Scripts\python.exe" (
  echo [90_github_ready] Virtualenv not found. Run 00_setup.bat first.
  exit /b 1
)

echo [90_github_ready] Generating GitHub readiness report...
.venv\Scripts\python scripts\github_ready_check.py --output docs/github_ready_status.md
if errorlevel 1 exit /b 1

echo [90_github_ready] Completed.
exit /b 0

