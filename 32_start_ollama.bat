@echo off
setlocal

where ollama >nul 2>nul
if errorlevel 1 (
  echo [32_start_ollama] ollama command not found. Install Ollama first.
  exit /b 1
)

set MODEL=llama3.1:8b
if not "%OLLAMA_MODEL%"=="" set MODEL=%OLLAMA_MODEL%

echo [32_start_ollama] Checking Ollama service...
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $r=Invoke-WebRequest -UseBasicParsing http://127.0.0.1:11434/api/tags -TimeoutSec 3; if($r.StatusCode -eq 200){ exit 0 } else { exit 1 } } catch { exit 1 }"
if not errorlevel 1 goto pull_model

echo [32_start_ollama] Starting ollama serve...
start "Ollama Serve" /min ollama serve
timeout /t 2 >nul

powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $r=Invoke-WebRequest -UseBasicParsing http://127.0.0.1:11434/api/tags -TimeoutSec 8; if($r.StatusCode -eq 200){ exit 0 } else { exit 1 } } catch { exit 1 }"
if errorlevel 1 (
  echo [32_start_ollama] Failed to start Ollama service.
  exit /b 1
)

:pull_model
echo [32_start_ollama] Pulling model %MODEL% (if missing)...
ollama pull %MODEL%
if errorlevel 1 (
  echo [32_start_ollama] Model pull failed.
  exit /b 1
)

echo [32_start_ollama] Ollama is ready at http://127.0.0.1:11434
exit /b 0

