@echo off
setlocal
set ROOT=%~dp0
cd /d "%ROOT%"

if not exist ".venv\Scripts\python.exe" (
  echo [120_desktop_app] Virtualenv not found. Running setup first...
  call 00_setup.bat
  if errorlevel 1 exit /b 1
)

if "%ALLOW_LOCAL_FALLBACK%"=="" set ALLOW_LOCAL_FALLBACK=1
if "%SKIP_OLLAMA_PULL%"=="" set SKIP_OLLAMA_PULL=1

echo [120_desktop_app] Launching desktop application...
if exist ".venv\Scripts\pythonw.exe" (
  start "BIST Agentic RAG Desktop" ".venv\Scripts\pythonw.exe" scripts\desktop_app.py
) else (
  start "BIST Agentic RAG Desktop" ".venv\Scripts\python.exe" scripts\desktop_app.py
)

exit /b 0

