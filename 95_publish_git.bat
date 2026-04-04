@echo off
setlocal
set ROOT=%~dp0
cd /d "%ROOT%"

if not exist ".venv\Scripts\python.exe" (
  echo [95_publish_git] Virtualenv not found. Run 00_setup.bat first.
  exit /b 1
)

if "%REMOTE_NAME%"=="" set REMOTE_NAME=origin

if "%REPO_URL%"=="" (
  echo [95_publish_git] REPO_URL not set. Will use existing remote if configured.
  .venv\Scripts\python scripts\publish_to_remote.py --remote "%REMOTE_NAME%"
) else (
  echo [95_publish_git] Using REPO_URL=%REPO_URL%
  .venv\Scripts\python scripts\publish_to_remote.py --repo-url "%REPO_URL%" --remote "%REMOTE_NAME%"
)
if errorlevel 1 exit /b 1

echo [95_publish_git] Completed.
exit /b 0

