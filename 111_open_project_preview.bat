@echo off
setlocal
set ROOT=%~dp0
cd /d "%ROOT%"

set UI_PORT=3311
if not "%WEB_UI_PORT%"=="" set UI_PORT=%WEB_UI_PORT%

echo [111_open_project_preview] Checking API...
set API_READY=0
for %%P in (18000 18001 18002 8088) do (
  curl.exe -fsS --max-time 2 "http://127.0.0.1:%%P/v1/health" >nul 2>nul
  if not errorlevel 1 (
    set API_READY=1
    echo [111_open_project_preview] API detected at http://127.0.0.1:%%P
    goto :api_checked
  )
)

:api_checked
if "%API_READY%"=="0" (
  echo [WARN] API is not running. Preview mode will open the modern UI only.
  echo [WARN] Full data-backed application still requires a working Python runtime and 110_run_modern_app.bat.
)

echo [111_open_project_preview] Starting web UI...
start "BIST UI Preview" cmd /c "%ROOT%36_run_web_ui.bat"

echo [111_open_project_preview] Waiting for UI on http://127.0.0.1:%UI_PORT% ...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ok=$false; for($i=0;$i -lt 120;$i++){ try{ $r=Invoke-WebRequest -UseBasicParsing ('http://127.0.0.1:%UI_PORT%') -TimeoutSec 2; if($r.StatusCode -eq 200){ $ok=$true; break } } catch {}; Start-Sleep -Seconds 1 }; if(-not $ok){ exit 1 }"
if errorlevel 1 (
  echo [111_open_project_preview] UI did not become ready in time.
  echo [111_open_project_preview] Check frontend dependencies and try again.
  pause
  exit /b 1
)

echo [111_open_project_preview] Opening browser...
start "" "http://127.0.0.1:%UI_PORT%"

echo.
echo [111_open_project_preview] UI opened at http://127.0.0.1:%UI_PORT%
if "%API_READY%"=="0" (
  echo [111_open_project_preview] Running in preview mode. Some live data panels may show API connection warnings.
)
echo.
echo [111_open_project_preview] Project root: %ROOT%
pause
exit /b 0
