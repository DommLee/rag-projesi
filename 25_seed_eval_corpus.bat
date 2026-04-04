@echo off
setlocal
set ROOT=%~dp0
cd /d "%ROOT%"

if not exist ".venv\\Scripts\\python.exe" (
  echo [25_seed_eval_corpus] Virtualenv not found. Run 00_setup.bat first.
  exit /b 1
)

echo [25_seed_eval_corpus] Seeding evaluation fixtures (only if corpus is empty)...
.venv\Scripts\python scripts\seed_eval_corpus.py --dataset-path datasets/eval_questions.json --only-if-empty
if errorlevel 1 exit /b 1

exit /b 0

