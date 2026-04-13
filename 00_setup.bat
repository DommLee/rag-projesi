@echo off
setlocal EnableDelayedExpansion
set ROOT=%~dp0
cd /d "%ROOT%"

set BOOTSTRAP_PYTHON=
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -c "import sys; print(sys.version)" >nul 2>nul
  if not errorlevel 1 set BOOTSTRAP_PYTHON=.venv\Scripts\python.exe
)
if "%BOOTSTRAP_PYTHON%"=="" (
  where python >nul 2>nul
  if not errorlevel 1 set BOOTSTRAP_PYTHON=python
)
if "%BOOTSTRAP_PYTHON%"=="" (
  where py >nul 2>nul
  if not errorlevel 1 set BOOTSTRAP_PYTHON=py -3.12
)
if "%BOOTSTRAP_PYTHON%"=="" (
  echo [00_setup] No working Python runtime found.
  echo [00_setup] Install Python 3.12 or 3.11 first, then rerun this file.
  echo [00_setup] After Python install, use:
  echo [00_setup]   1. 00_setup.bat
  echo [00_setup]   2. 110_run_modern_app.bat
  exit /b 1
)

echo [00_setup] Creating virtual environment...
if not exist ".venv\Scripts\python.exe" (
  %BOOTSTRAP_PYTHON% -m venv .venv
  if errorlevel 1 exit /b 1
)

call ".venv\Scripts\activate.bat"
if errorlevel 1 exit /b 1

echo [00_setup] Installing dependencies...
python -m pip install --upgrade pip
if errorlevel 1 exit /b 1
pip install -r requirements.txt
if errorlevel 1 exit /b 1

echo [00_setup] Validating Docker...
docker --version
if errorlevel 1 exit /b 1

echo [00_setup] Validating API keys...
if not exist ".env" (
  echo [WARN] .env not found. Copy .env.example to .env before production runs.
)

where ollama >nul 2>nul
if errorlevel 1 (
  echo [WARN] Ollama not found in PATH. Skipping model pull.
) else (
  if /I "%SKIP_OLLAMA_PULL%"=="1" (
    echo [00_setup] SKIP_OLLAMA_PULL=1 set. Skipping model pull.
  ) else (
    if "!OLLAMA_MODEL!"=="" set OLLAMA_MODEL=llama3.1:8b
    echo [00_setup] Pulling Ollama model !OLLAMA_MODEL! ...
    ollama pull !OLLAMA_MODEL!
    if errorlevel 1 (
      echo [WARN] Ollama pull failed. Continuing with fallback providers.
    )
  )
)

where npm >nul 2>nul
if errorlevel 1 (
  echo [WARN] npm not found in PATH. Skipping frontend dependency install.
) else (
  if exist "frontend\package.json" (
    echo [00_setup] Installing frontend dependencies...
    pushd frontend
    call npm install
    if errorlevel 1 (
      popd
      exit /b 1
    )
    popd
  )
)

echo [00_setup] Completed.
exit /b 0
