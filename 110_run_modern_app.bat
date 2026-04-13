@echo off
setlocal
set ROOT=%~dp0
cd /d "%ROOT%"

if "%ALLOW_LOCAL_FALLBACK%"=="" set ALLOW_LOCAL_FALLBACK=1
if "%SKIP_OLLAMA_PULL%"=="" set SKIP_OLLAMA_PULL=1

echo [110_run_modern_app] Starting API...
call 30_run_api.bat
if errorlevel 1 exit /b 1

set API_PORT=18002
set UI_PORT=3311
if exist "logs\.runtime_api_port" (
  for /f "usebackq delims=" %%P in ("logs\.runtime_api_port") do set API_PORT=%%P
)
if not "%WEB_UI_PORT%"=="" set UI_PORT=%WEB_UI_PORT%

echo [110_run_modern_app] Starting web UI in stable mode...
start "" cmd /c "%ROOT%36_run_web_ui.bat"

echo [110_run_modern_app] Waiting for UI...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ok=$false; for($i=0;$i -lt 120;$i++){ try{ $r=Invoke-WebRequest -UseBasicParsing ('http://127.0.0.1:%UI_PORT%') -TimeoutSec 2; if($r.StatusCode -eq 200){ $ok=$true; break } } catch {}; Start-Sleep -Seconds 1 }; if(-not $ok){ exit 1 }"
if errorlevel 1 (
  echo [110_run_modern_app] UI did not become ready in time.
  exit /b 1
)

echo [110_run_modern_app] API: http://127.0.0.1:%API_PORT%
echo [110_run_modern_app] UI : http://127.0.0.1:%UI_PORT%
start "" "http://127.0.0.1:%UI_PORT%"
exit /b 0
