@echo off
setlocal
set ROOT=%~dp0
cd /d "%ROOT%"

echo [10_start_infra] Checking Docker daemon...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p = Start-Process -FilePath docker -ArgumentList @('ps','--format','{{.ID}}') -PassThru -WindowStyle Hidden; if(-not $p.WaitForExit(30000)){ try { $p.Kill() } catch {}; exit 1 }; exit $p.ExitCode"
if errorlevel 1 (
  if /I "%ALLOW_LOCAL_FALLBACK%"=="1" (
    echo [10_start_infra] Docker daemon not responding. Continuing in local fallback mode.
    exit /b 0
  )
  echo [10_start_infra] Docker daemon is not responding. Please start/restart Docker Desktop or set ALLOW_LOCAL_FALLBACK=1.
  exit /b 1
)

echo [10_start_infra] Starting infrastructure services...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p = Start-Process -FilePath docker -ArgumentList @('compose','up','-d','redis','weaviate') -PassThru -WindowStyle Hidden; if(-not $p.WaitForExit(600000)){ try { $p.Kill() } catch {}; exit 1 }; exit $p.ExitCode"
if errorlevel 1 exit /b 1

echo [10_start_infra] Waiting for Weaviate health endpoint...
set /a MAX_RETRY=120
set /a RETRY=0

:wait_loop
set /a RETRY+=1
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { (Invoke-WebRequest -UseBasicParsing -Uri 'http://localhost:8080/v1/.well-known/ready' -TimeoutSec 5) | Out-Null; exit 0 } catch { exit 1 }"
if not errorlevel 1 goto ready
if %RETRY% GEQ %MAX_RETRY% (
  echo [10_start_infra] Weaviate not ready after retries.
  exit /b 1
)
timeout /t 2 /nobreak >nul
goto wait_loop

:ready
echo [10_start_infra] Infra is ready.
exit /b 0
