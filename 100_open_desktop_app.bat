@echo off
setlocal
set ROOT=%~dp0
cd /d "%ROOT%"
set DESKTOP_AUTOSTART=1

set EXE_PATH=releases\desktop\BISTAgenticRAGDesktop\BISTAgenticRAGDesktop.exe

if exist "%EXE_PATH%" (
  start "" "%ROOT%%EXE_PATH%"
  exit /b 0
)

if exist ".venv\Scripts\pythonw.exe" (
  start "" ".venv\Scripts\pythonw.exe" "scripts\desktop_app.py"
  exit /b 0
)

if exist ".venv\Scripts\python.exe" (
  start "" ".venv\Scripts\python.exe" "scripts\desktop_app.py"
  exit /b 0
)

python scripts\desktop_app.py
exit /b %errorlevel%
