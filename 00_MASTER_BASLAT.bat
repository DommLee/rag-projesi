@echo off
title BIST RAG - Master Baslatici (Docker + API)
setlocal
set ROOT=%~dp0
cd /d "%ROOT%"

echo =======================================================
echo.
echo         BIST AGENTIC RAG - SISTEM BASLATICISI
echo.
echo =======================================================
echo.
echo Adim 1: Veritabanlari ve Alt Servisler DOCKER uzerinden kaldiriliyor...
echo Lutfen bekleyin...
docker-compose up -d

if errorlevel 1 (
  echo.
  echo [HATA] Docker baslatilamadi!
  echo Lutfen Docker Desktop uygulamasinin arka planda acik oldugundan emin ol.
  pause
  exit /b 1
)

echo.
echo Adim 2: Veritabanlarinin kendine gelmesi icin kisaca bekleniyor...
timeout /t 5 /nobreak >nul

echo.
echo Adim 3: Sistem API'leri ve Web Arayuzu aciliyor...
echo.
call "%ROOT%112_open_full_system.bat"

echo.
echo Islemler tamamlandi. Arayuzunuz tarayicida acildi!
pause
