@echo off
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" "run_houd2launcher.py"
    exit /b 0
)

py -3.11 "run_houd2launcher.py"

