@echo off
setlocal EnableDelayedExpansion
set ROOT=%~dp0
cd /d "%ROOT%"

echo [00_setup] Creating virtual environment...
if not exist ".venv\Scripts\python.exe" (
  python -m venv .venv
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

echo [00_setup] Completed.
exit /b 0
