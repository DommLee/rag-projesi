@echo off
setlocal
set ROOT=%~dp0
cd /d "%ROOT%"

if not exist "data\auto_ingest_sources.production.json" (
  echo Production auto-ingest config not found.
  exit /b 1
)

copy /Y "data\auto_ingest_sources.production.json" "data\auto_ingest_sources.json" >nul
if errorlevel 1 (
  echo Failed to copy production config.
  exit /b 1
)

echo Production auto-ingest config copied to data\auto_ingest_sources.json
call 24_auto_ingest_configure.bat
exit /b %errorlevel%

