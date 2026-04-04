@echo off
setlocal
set ROOT=%~dp0
cd /d "%ROOT%"

call 70_stop_services.bat
if errorlevel 1 exit /b 1

echo [101_stop_app] Completed.
exit /b 0

