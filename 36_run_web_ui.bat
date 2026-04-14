@echo off
setlocal
set ROOT=%~dp0
cd /d "%ROOT%\frontend"

set API_BASE=http://127.0.0.1:18002
set UI_PORT=3311
set RUNTIME_PORT=
if exist "%ROOT%logs\.runtime_api_port" (
  for /f "usebackq delims=" %%P in ("%ROOT%logs\.runtime_api_port") do set RUNTIME_PORT=%%P
)
if not "%RUNTIME_PORT%"=="" set API_BASE=http://127.0.0.1:%RUNTIME_PORT%

if not "%WEB_UI_PORT%"=="" set UI_PORT=%WEB_UI_PORT%
set NEXT_PUBLIC_API_BASE=%API_BASE%

if not exist "public" mkdir public
powershell -NoProfile -ExecutionPolicy Bypass -Command "$cfg = @{ apiBase = '%API_BASE%'; apiCandidates = @('%API_BASE%','http://127.0.0.1:18000','http://127.0.0.1:18002','http://127.0.0.1:18001','http://127.0.0.1:8088'); generatedAt = (Get-Date).ToString('o') }; ('window.__BIST_RUNTIME_CONFIG__ = ' + ($cfg | ConvertTo-Json -Compress) + ';') | Set-Content -Path 'public/runtime-config.js' -Encoding UTF8"

if not exist "node_modules" (
  echo Installing frontend dependencies...
  call npm install
  if errorlevel 1 exit /b 1
)

set NEED_BUILD=0
if not exist ".next\BUILD_ID" set NEED_BUILD=1
if exist ".next\BUILD_ID" (
  powershell -NoProfile -ExecutionPolicy Bypass -Command "$build=(Get-Item '.next/BUILD_ID').LastWriteTimeUtc; $newer=Get-ChildItem -Path app,public -Recurse -File -ErrorAction SilentlyContinue | Where-Object { $_.LastWriteTimeUtc -gt $build } | Select-Object -First 1; if($newer){ exit 2 } else { exit 0 }"
  if errorlevel 2 set NEED_BUILD=1
)
if "%NEED_BUILD%"=="1" (
  echo [36_run_web_ui] Frontend source changed or build missing. Rebuilding Next.js UI...
  call npm run build
  if errorlevel 1 exit /b 1
)

if exist ".next\\BUILD_ID" goto prod

echo [36_run_web_ui] Production build not available. Starting Next.js UI in local dev mode on http://127.0.0.1:%UI_PORT%
powershell -NoProfile -ExecutionPolicy Bypass -Command "npm.cmd run dev -- -H 127.0.0.1 -p %UI_PORT%"
exit /b %errorlevel%

:prod
echo [36_run_web_ui] Existing production build detected.
echo Starting Next.js UI on http://127.0.0.1:%UI_PORT% (production, API: %NEXT_PUBLIC_API_BASE%)
powershell -NoProfile -ExecutionPolicy Bypass -Command "npm.cmd run start -- -H 127.0.0.1 -p %UI_PORT%"
exit /b %errorlevel%
