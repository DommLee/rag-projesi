@echo off
setlocal
set ROOT=%~dp0
cd /d "%ROOT%"
if "%ALLOW_LOCAL_FALLBACK%"=="" set ALLOW_LOCAL_FALLBACK=1
if "%SKIP_OLLAMA_PULL%"=="" set SKIP_OLLAMA_PULL=1

echo [fast_demo] Starting fast demo profile...
call 00_setup.bat
if errorlevel 1 exit /b 1
call 70_stop_services.bat
if errorlevel 1 exit /b 1
call 10_start_infra.bat
if errorlevel 1 exit /b 1
call 30_run_api.bat
if errorlevel 1 exit /b 1
call 40_smoke_test.bat
if errorlevel 1 exit /b 1
call 60_demo_flow.bat
if errorlevel 1 exit /b 1
call 70_stop_services.bat
if errorlevel 1 exit /b 1

echo [fast_demo] Completed.
exit /b 0
