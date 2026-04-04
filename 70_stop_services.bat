@echo off
setlocal
set ROOT=%~dp0
cd /d "%ROOT%"

echo [70_stop_services] Stopping local API/worker processes if running...
if exist ".venv\Scripts\python.exe" (
  .venv\Scripts\python scripts\stop_local_services.py --logs-dir logs
) else (
  echo [70_stop_services] Virtualenv not found. Skipping local PID cleanup.
)

echo [70_stop_services] Attempting to stop docker api/worker services (best effort)...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p = Start-Process -FilePath docker -ArgumentList @('compose','stop','api','worker') -PassThru -WindowStyle Hidden; if(-not $p.WaitForExit(30000)){ try { $p.Kill() } catch {}; exit 0 }; exit 0"

echo [70_stop_services] Completed.
exit /b 0

