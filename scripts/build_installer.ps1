param(
    [string]$Version = "",
    [string]$IsccPath = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$DistDir = Join-Path $ProjectRoot "dist\HouD2Launcher"
$OutputDir = Join-Path $ProjectRoot "dist\installer"
$Icon = Join-Path $ProjectRoot "build\windows\houd2.ico"
$Definition = Join-Path $ProjectRoot "packaging\windows\HouD2Launcher.iss"

Push-Location $ProjectRoot
try {
    if (-not $Version) {
        $Version = & $Python -c "import sys; sys.path.insert(0, 'src'); import houd2launcher; print(houd2launcher.__version__)"
    }
    if (-not (Test-Path -LiteralPath (Join-Path $DistDir "HouD2Launcher.exe"))) {
        throw "Build the PyInstaller application first with scripts\build_windows.ps1."
    }
    if (-not $IsccPath) {
        $command = Get-Command iscc.exe -ErrorAction SilentlyContinue
        if ($command) {
            $IsccPath = $command.Source
        } else {
            $candidates = @(
                (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"),
                "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
                "C:\Program Files\Inno Setup 6\ISCC.exe"
            )
            $IsccPath = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
        }
    }
    if (-not $IsccPath -or -not (Test-Path -LiteralPath $IsccPath)) {
        throw "Inno Setup 6 is required. Install it or pass -IsccPath."
    }

    New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
    $env:HOUD2_BUILD_VERSION = $Version
    $env:HOUD2_BUILD_SOURCE = $DistDir
    $env:HOUD2_BUILD_OUTPUT = $OutputDir
    $env:HOUD2_BUILD_ICON = $Icon
    & $IsccPath $Definition
    if ($LASTEXITCODE -ne 0) {
        throw "Inno Setup build failed."
    }
    Write-Output "Installer complete: $OutputDir\HouD2Launcher-$Version-Setup.exe"
}
finally {
    Pop-Location
}
