@echo off
setlocal
set ROOT=%~dp0
cd /d "%ROOT%"

call ".venv\Scripts\activate.bat"
if errorlevel 1 exit /b 1

if "%TICKER%"=="" set TICKER=ASELS

echo [60_demo_flow] Running demo flow for %TICKER% ...
python scripts/demo_flow.py --ticker %TICKER%
if errorlevel 1 exit /b 1

echo [60_demo_flow] Completed.
exit /b 0

