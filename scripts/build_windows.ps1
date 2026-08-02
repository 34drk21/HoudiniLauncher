$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Run scripts\setup.ps1 before building."
}

& $Python -m pip install ".[build]"
Push-Location $ProjectRoot
try {
    & $Python -m PyInstaller `
        --noconfirm `
        --clean `
        --windowed `
        --name HouD2Launcher `
        --add-data "src\houd2launcher\resources;houd2launcher\resources" `
        --add-data "src\houd2launcher\admin\static;houd2launcher\admin\static" `
        --add-data "houdini;houdini" `
        --paths "src" `
        "run_houd2launcher.py"
}
finally {
    Pop-Location
}

Write-Output "Build complete: $ProjectRoot\dist\HouD2Launcher"
