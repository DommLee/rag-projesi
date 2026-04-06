@echo off
setlocal
set ROOT=%~dp0
cd /d "%ROOT%"

call ".venv\Scripts\activate.bat"
if errorlevel 1 exit /b 1

if "%API_HOST_PORT%"=="" (
  if exist "logs\.runtime_api_port" (
    set /p API_HOST_PORT=<logs\.runtime_api_port
  )
)
if "%API_HOST_PORT%"=="" set API_HOST_PORT=18000

set BIST_API_BASE=http://localhost:%API_HOST_PORT%
echo [35_run_streamlit] Starting Streamlit at http://localhost:8501 (API=%BIST_API_BASE%)
streamlit run streamlit_app.py --server.port 8501
exit /b 0

