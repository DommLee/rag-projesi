@echo off
setlocal
set ROOT=%~dp0
cd /d "%ROOT%"

call ".venv\Scripts\activate.bat"
if errorlevel 1 exit /b 1

if not exist logs mkdir logs

if exist requirements-eval.txt (
  echo [50_eval] Installing optional eval dependencies...
  pip install -r requirements-eval.txt >nul 2>nul
)

echo [50_eval] Running evaluation suite...
python scripts/run_eval.py --mode heuristic --provider auto --sample-size 15 --dataset-path datasets/eval_questions.json --store-artifacts --output-path logs/eval_report.json
if errorlevel 1 exit /b 1

python scripts/export_latest_summary.py --eval-report logs/eval_report.json --output docs/latest_run_summary.md
if errorlevel 1 exit /b 1

echo [50_eval] Completed.
exit /b 0
