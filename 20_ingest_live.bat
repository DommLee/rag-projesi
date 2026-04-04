@echo off
setlocal
set ROOT=%~dp0
cd /d "%ROOT%"

call ".venv\Scripts\activate.bat"
if errorlevel 1 exit /b 1

if "%TICKER%"=="" set TICKER=ASELS
if "%INSTITUTION%"=="" set INSTITUTION=BIST-Collector

if "%KAP_URLS%"=="" set KAP_URLS=https://www.kap.org.tr/tr/sirket-bilgileri/genel/209-aselsan-elektronik-sanayi-ve-ticaret-a-s
if "%NEWS_URLS%"=="" set NEWS_URLS=https://www.aa.com.tr/tr/rss/default?cat=ekonomi
if "%REPORT_URLS%"=="" set REPORT_URLS=
if "%DELTA_MODE%"=="" set DELTA_MODE=true
if "%MAX_DOCS%"=="" set MAX_DOCS=100

echo [20_ingest_live] Running live ingestion for %TICKER% ...
python scripts/ingest_live.py ^
  --ticker "%TICKER%" ^
  --institution "%INSTITUTION%" ^
  --kap-urls "%KAP_URLS%" ^
  --news-urls "%NEWS_URLS%" ^
  --report-urls "%REPORT_URLS%" ^
  --delta-mode "%DELTA_MODE%" ^
  --max-docs "%MAX_DOCS%"
if errorlevel 1 exit /b 1

echo [20_ingest_live] Completed.
exit /b 0
