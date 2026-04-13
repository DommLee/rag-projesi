@echo off
setlocal
set ROOT=%~dp0
cd /d "%ROOT%"

set SELECTED_PORT=
set EXISTING_HEALTHY=0
for %%P in (18000 18001 18002 8088) do (
  curl.exe -fsS --max-time 2 "http://127.0.0.1:%%P/v1/health" >nul 2>nul
  if not errorlevel 1 (
    set SELECTED_PORT=%%P
    set EXISTING_HEALTHY=1
    goto :port_ready
  )
)

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

if "%EXISTING_HEALTHY%"=="1" (
  echo [30_run_api] Existing healthy API detected on http://localhost:%API_HOST_PORT%
  exit /b 0
)

echo [30_run_api] Checking Docker daemon...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p = Start-Process -FilePath docker -ArgumentList @('ps','--format','{{.ID}}') -PassThru -WindowStyle Hidden; if(-not $p.WaitForExit(20000)){ try { $p.Kill() } catch {}; exit 1 }; exit $p.ExitCode"
if errorlevel 1 goto local_fallback

echo [30_run_api] Starting API and worker containers (build enabled)...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p = Start-Process -FilePath docker -ArgumentList @('compose','up','-d','--build','api','worker') -PassThru -WindowStyle Hidden; if(-not $p.WaitForExit(1200000)){ try { $p.Kill() } catch {}; exit 1 }; exit $p.ExitCode"
if errorlevel 1 exit /b 1

echo [30_run_api] API should be available at http://localhost:%API_HOST_PORT%
exit /b 0

:local_fallback
if /I not "%ALLOW_LOCAL_FALLBACK%"=="1" (
  echo [30_run_api] Docker daemon not responding. Start Docker Desktop or set ALLOW_LOCAL_FALLBACK=1.
  exit /b 1
)

echo [30_run_api] Docker unavailable. Starting local API and worker processes...
set PYTHON_BIN=.venv\Scripts\python.exe
set FALLBACK_PYTHON=
if not exist "%PYTHON_BIN%" if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
  set FALLBACK_PYTHON=%LOCALAPPDATA%\Programs\Python\Python312\python.exe
)
if not exist "%PYTHON_BIN%" if not defined FALLBACK_PYTHON if exist ".venv\pyvenv.cfg" (
  for /f "usebackq tokens=1,* delims==" %%A in (".venv\pyvenv.cfg") do (
    if /I "%%A"=="executable " set FALLBACK_PYTHON=%%B
  )
)
if defined FALLBACK_PYTHON (
  for /f "tokens=* delims= " %%I in ("%FALLBACK_PYTHON%") do set FALLBACK_PYTHON=%%I
)
if defined FALLBACK_PYTHON if not exist "%FALLBACK_PYTHON%" set FALLBACK_PYTHON=

set START_PYTHON=
if exist "%PYTHON_BIN%" (
  set START_PYTHON=%PYTHON_BIN%
) else if defined FALLBACK_PYTHON (
  set START_PYTHON=%FALLBACK_PYTHON%
) else (
  echo [30_run_api] No working Python runtime found. Run 00_setup.bat first.
  exit /b 1
)
call :validate_python "%START_PYTHON%"
if errorlevel 1 (
  if defined FALLBACK_PYTHON if /I not "%START_PYTHON%"=="%FALLBACK_PYTHON%" (
    call :validate_python "%FALLBACK_PYTHON%"
    if not errorlevel 1 set START_PYTHON=%FALLBACK_PYTHON%
  )
)
call :validate_python "%START_PYTHON%"
if errorlevel 1 (
  echo [30_run_api] Selected Python runtime is not executable: %START_PYTHON%
  echo [30_run_api] Recreate .venv or install a working Python 3.11/3.12 interpreter, then rerun 00_setup.bat.
  exit /b 1
)
if not exist "logs" mkdir logs

if defined FALLBACK_PYTHON (
  for %%I in ("%FALLBACK_PYTHON%") do set FALLBACK_PYTHON=%%~fI
)
if /I not "%START_PYTHON%"=="%PYTHON_BIN%" (
  if exist "%ROOT%.venv\Lib\site-packages" (
    if defined PYTHONPATH (
      set PYTHONPATH=%ROOT%.venv\Lib\site-packages;%ROOT%;%PYTHONPATH%
    ) else (
      set PYTHONPATH=%ROOT%.venv\Lib\site-packages;%ROOT%
    )
  )
)

echo [30_run_api] Launching local services with Python process manager...
"%START_PYTHON%" scripts\start_local_services.py --port %API_HOST_PORT% --timeout-seconds 30
if errorlevel 1 (
  echo [30_run_api] Local API did not start in time. Check logs\api_local.log
  exit /b 1
)
echo [30_run_api] Local API is available at http://localhost:%API_HOST_PORT%
echo %API_HOST_PORT%> logs\.runtime_api_port
exit /b 0

:validate_python
"%~1" -c "import sys; print(sys.version)" >nul 2>nul
exit /b %errorlevel%
