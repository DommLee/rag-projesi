@echo off
setlocal
set ROOT=%~dp0
cd /d "%ROOT%"

if not exist ".venv\Scripts\python.exe" (
  echo [130_build_desktop_exe] Virtualenv not found. Running setup first...
  call 00_setup.bat
  if errorlevel 1 exit /b 1
)

call ".venv\Scripts\activate.bat"
if errorlevel 1 exit /b 1

echo [130_build_desktop_exe] Installing/refreshing PyInstaller...
pip install pyinstaller >nul
if errorlevel 1 exit /b 1

if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"

echo [130_build_desktop_exe] Building desktop executable (--onedir)...
pyinstaller desktop.spec --noconfirm
if errorlevel 1 exit /b 1

set OUTDIR=releases\desktop
if not exist "%OUTDIR%" mkdir "%OUTDIR%"
if exist "%OUTDIR%\BISTAgenticRAGDesktop" rmdir /s /q "%OUTDIR%\BISTAgenticRAGDesktop"

xcopy /e /i /y "dist\BISTAgenticRAGDesktop" "%OUTDIR%\BISTAgenticRAGDesktop" >nul
copy /y ".env.example" "%OUTDIR%\.env.example" >nul
if exist "releases\desktop\README_EXE.md" (
  copy /y "releases\desktop\README_EXE.md" "%OUTDIR%\README_EXE.md" >nul
)

echo [130_build_desktop_exe] Completed. Output: %OUTDIR%\BISTAgenticRAGDesktop
exit /b 0

