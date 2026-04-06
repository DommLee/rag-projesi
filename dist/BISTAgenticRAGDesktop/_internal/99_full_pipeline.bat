@echo off
setlocal
set ROOT=%~dp0
cd /d "%ROOT%"
if "%ALLOW_LOCAL_FALLBACK%"=="" set ALLOW_LOCAL_FALLBACK=1
if "%SKIP_OLLAMA_PULL%"=="" set SKIP_OLLAMA_PULL=1

for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmm"') do set TS=%%i
set LOGDIR=logs\%TS%
if not exist "%LOGDIR%" mkdir "%LOGDIR%"

echo [99_full_pipeline] Logs: %LOGDIR%

call 00_setup.bat >> "%LOGDIR%\00_setup.log" 2>&1
if errorlevel 1 exit /b 1

call 70_stop_services.bat >> "%LOGDIR%\70_stop_pre.log" 2>&1
if errorlevel 1 exit /b 1

call 10_start_infra.bat >> "%LOGDIR%\10_start_infra.log" 2>&1
if errorlevel 1 exit /b 1

call 20_ingest_live.bat >> "%LOGDIR%\20_ingest_live.log" 2>&1
if errorlevel 1 exit /b 1

call 25_seed_eval_corpus.bat >> "%LOGDIR%\25_seed_eval_corpus.log" 2>&1
if errorlevel 1 exit /b 1

call 30_run_api.bat >> "%LOGDIR%\30_run_api.log" 2>&1
if errorlevel 1 exit /b 1

call 40_smoke_test.bat >> "%LOGDIR%\40_smoke_test.log" 2>&1
if errorlevel 1 exit /b 1

call 50_eval.bat >> "%LOGDIR%\50_eval.log" 2>&1
if errorlevel 1 exit /b 1

call 60_demo_flow.bat >> "%LOGDIR%\60_demo_flow.log" 2>&1
if errorlevel 1 exit /b 1

call 70_stop_services.bat >> "%LOGDIR%\70_stop_post.log" 2>&1
if errorlevel 1 exit /b 1

set RUN_LOGDIR=%LOGDIR%
call 80_release_bundle.bat >> "%LOGDIR%\80_release_bundle.log" 2>&1
if errorlevel 1 exit /b 1

call 90_github_ready.bat >> "%LOGDIR%\90_github_ready.log" 2>&1
if errorlevel 1 exit /b 1

echo [99_full_pipeline] Completed successfully.
echo [99_full_pipeline] Profiles available: fast_demo.bat and full_eval.bat
exit /b 0
