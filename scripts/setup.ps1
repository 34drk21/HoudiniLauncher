$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $VenvPython)) {
    py -3.11 -m venv (Join-Path $ProjectRoot ".venv")
}

& $VenvPython -m pip install -r (Join-Path $ProjectRoot "requirements.txt")
Write-Output "HouD2Launcher setup complete. Run start_houd2launcher.bat."

