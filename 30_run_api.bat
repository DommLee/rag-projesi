@echo off
setlocal
set ROOT=%~dp0
cd /d "%ROOT%"

set SELECTED_PORT=
for %%P in (18000 18001 18002 8088) do (
  powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $c = New-Object Net.Sockets.TcpClient('localhost',%%P); $c.Close(); exit 1 } catch { exit 0 }"
  if not errorlevel 1 (
    set SELECTED_PORT=%%P
    goto :port_ready
  )
)

:port_ready
if "%SELECTED_PORT%"=="" (
  echo [30_run_api] No free port from fallback matrix.
  exit /b 1
)

set API_HOST_PORT=%SELECTED_PORT%
echo [30_run_api] Using API_HOST_PORT=%API_HOST_PORT%
if not exist "logs" mkdir logs
echo %API_HOST_PORT%> logs\.runtime_api_port

echo [30_run_api] Checking Docker daemon...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p = Start-Process -FilePath docker -ArgumentList @('ps','--format','{{.ID}}') -PassThru -WindowStyle Hidden; if(-not $p.WaitForExit(20000)){ try { $p.Kill() } catch {}; exit 1 }; exit $p.ExitCode"
if errorlevel 1 goto local_fallback

echo [30_run_api] Starting API and worker containers...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p = Start-Process -FilePath docker -ArgumentList @('compose','up','-d','api','worker') -PassThru -WindowStyle Hidden; if(-not $p.WaitForExit(600000)){ try { $p.Kill() } catch {}; exit 1 }; exit $p.ExitCode"
if errorlevel 1 exit /b 1

echo [30_run_api] API should be available at http://localhost:%API_HOST_PORT%
exit /b 0

:local_fallback
if /I not "%ALLOW_LOCAL_FALLBACK%"=="1" (
  echo [30_run_api] Docker daemon not responding. Start Docker Desktop or set ALLOW_LOCAL_FALLBACK=1.
  exit /b 1
)

echo [30_run_api] Docker unavailable. Starting local API and worker processes...
if not exist ".venv\Scripts\python.exe" (
  echo [30_run_api] Virtualenv missing. Run 00_setup.bat first.
  exit /b 1
)
if not exist "logs" mkdir logs

echo [30_run_api] Launching local services with Python process manager...
.venv\Scripts\python scripts\start_local_services.py --port %API_HOST_PORT% --timeout-seconds 30
if errorlevel 1 (
  echo [30_run_api] Local API did not start in time. Check logs\api_local.log
  exit /b 1
)
echo [30_run_api] Local API is available at http://localhost:%API_HOST_PORT%
echo %API_HOST_PORT%> logs\.runtime_api_port
exit /b 0
