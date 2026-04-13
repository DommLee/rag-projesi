@echo off
setlocal
set ROOT=%~dp0
cd /d "%ROOT%"

set PYTHON_BIN=.venv\Scripts\python.exe
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
  set FALLBACK_PYTHON=%LOCALAPPDATA%\Programs\Python\Python312\python.exe
)

echo [70_stop_services] Stopping local API/worker processes if running...
if exist "%PYTHON_BIN%" (
  "%PYTHON_BIN%" --version >nul 2>nul
)
if not errorlevel 1 (
  "%PYTHON_BIN%" scripts\stop_local_services.py --logs-dir logs
) else if defined FALLBACK_PYTHON (
  "%FALLBACK_PYTHON%" scripts\stop_local_services.py --logs-dir logs
) else (
  echo [70_stop_services] Python runtime unavailable. Falling back to direct PID cleanup.
  powershell -NoProfile -ExecutionPolicy Bypass -Command "$logs = Join-Path (Resolve-Path '.') 'logs'; foreach($name in 'api_local.pid','worker_local.pid'){ $pidFile = Join-Path $logs $name; if(Test-Path $pidFile){ try { $pid = [int](Get-Content $pidFile -Raw).Trim(); taskkill /PID $pid /T /F | Out-Null } catch {}; Remove-Item $pidFile -Force -ErrorAction SilentlyContinue } }; foreach($marker in 'api_local.latest','worker_local.latest','api_local.err.latest','worker_local.err.latest'){ Remove-Item (Join-Path $logs $marker) -Force -ErrorAction SilentlyContinue }"
)

echo [70_stop_services] Attempting to stop docker api/worker services (best effort)...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p = Start-Process -FilePath docker -ArgumentList @('compose','stop','api','worker') -PassThru -WindowStyle Hidden; if(-not $p.WaitForExit(30000)){ try { $p.Kill() } catch {}; exit 0 }; exit 0"

echo [70_stop_services] Completed.
exit /b 0
