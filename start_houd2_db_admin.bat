@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Python environment is missing. Run scripts\setup.ps1 first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" "run_houd2_db_admin.py"
endlocal
