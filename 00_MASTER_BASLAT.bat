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
if "%START_DOCKER_INFRA%"=="" set START_DOCKER_INFRA=0

echo Adim 1: Altyapi kontrol ediliyor...
echo Not: Varsayilan demo modu local API/UI acilisidir. Docker icin START_DOCKER_INFRA=1 kullan.
if not "%START_DOCKER_INFRA%"=="1" (
  echo [INFO] Docker altyapisi atlandi. Local uygulama acilacak.
  goto start_app
)

echo Docker altyapisi istenmis. Redis ve Weaviate baslatiliyor...
where docker >nul 2>nul
if errorlevel 1 (
  echo [UYARI] Docker komutu bulunamadi. Local fallback ile devam ediliyor.
  goto start_app
)

docker compose up -d redis weaviate

if errorlevel 1 (
  echo.
  echo [UYARI] Docker altyapisi baslatilamadi veya yetki yok.
  echo [UYARI] Docker Desktop'i admin calistirabilir veya bu uyariyi yok sayip local fallback kullanabilirsin.
  echo [UYARI] Uygulama simdi local API/UI fallback ile acilacak.
)

echo.
echo Adim 2: Veritabanlarinin kendine gelmesi icin kisaca bekleniyor...
timeout /t 5 /nobreak >nul

:start_app
echo.
echo Adim 3: Sistem API'leri ve Web Arayuzu aciliyor...
echo.
call "%ROOT%112_open_full_system.bat"

echo.
echo Islemler tamamlandi. Arayuzunuz tarayicida acildi!
pause
