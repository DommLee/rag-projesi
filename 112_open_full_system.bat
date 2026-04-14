@echo off
setlocal
set ROOT=%~dp0
cd /d "%ROOT%"

set UI_PORT=3311
set API_PORT=
if not "%WEB_UI_PORT%"=="" set UI_PORT=%WEB_UI_PORT%
if exist "logs\.runtime_api_port" (
  for /f "usebackq delims=" %%P in ("logs\.runtime_api_port") do set API_PORT=%%P
)
if "%API_PORT%"=="" set API_PORT=18000

echo [112_open_full_system] Checking current system state...
if /I "%FORCE_LOCAL_API%"=="1" goto start_now
curl.exe -fsS --max-time 3 "http://127.0.0.1:%API_PORT%/v1/health" >nul 2>nul
set API_OK=%ERRORLEVEL%
curl.exe -fsS --max-time 3 "http://127.0.0.1:%UI_PORT%" >nul 2>nul
set UI_OK=%ERRORLEVEL%

if "%API_OK%"=="0" if "%UI_OK%"=="0" goto :open_now

:start_now
echo [112_open_full_system] Full system is not fully ready. Starting it now...
call "%ROOT%110_run_modern_app.bat"
if errorlevel 1 (
  echo [112_open_full_system] Full startup failed.
  echo [112_open_full_system] If Python is missing, first run 00_setup.bat after installing Python 3.11 or 3.12.
  pause
  exit /b 1
)

:open_now
echo [112_open_full_system] Opening full system...
echo [112_open_full_system] UI : http://127.0.0.1:%UI_PORT%
echo [112_open_full_system] API: http://127.0.0.1:%API_PORT%
rundll32.exe url.dll,FileProtocolHandler "http://127.0.0.1:%UI_PORT%"
if errorlevel 1 (
  echo [112_open_full_system] Browser otomatik acilamadi. URL'yi elle ac:
  echo http://127.0.0.1:%UI_PORT%
)
pause
exit /b 0
