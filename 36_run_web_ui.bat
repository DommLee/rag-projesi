@echo off
setlocal
set ROOT=%~dp0
cd /d "%ROOT%\frontend"

set API_BASE=http://127.0.0.1:18002
if exist "%ROOT%\logs\.runtime_api_port" (
  set /p RUNTIME_PORT=<"%ROOT%\logs\.runtime_api_port"
  if not "%RUNTIME_PORT%"=="" set API_BASE=http://127.0.0.1:%RUNTIME_PORT%
)

set NEXT_PUBLIC_API_BASE=%API_BASE%

if not exist "node_modules" (
  echo Installing frontend dependencies...
  call npm install
  if errorlevel 1 exit /b 1
)

echo Starting Next.js UI on http://127.0.0.1:3000 (API: %NEXT_PUBLIC_API_BASE%)
call npm run dev -- -p 3000
exit /b %errorlevel%

