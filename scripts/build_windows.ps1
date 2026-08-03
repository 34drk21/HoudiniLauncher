$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$Hda = Join-Path $ProjectRoot "houdini\otls\houd2_cache.hda"
$BrandIcon = Join-Path $ProjectRoot "src\houd2launcher\resources\icons\houd2_launcher.jpg"
$Icon = Join-Path $ProjectRoot "build\windows\houd2.ico"
$TaskPlaceholder = Join-Path $ProjectRoot "src\houd2launcher\resources\icons\houd2_task_placeholder.jpg"
$VersionFile = Join-Path $ProjectRoot "build\windows\version_info.txt"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Run scripts\setup.ps1 before building."
}
if ((Test-Path -LiteralPath $Hda) -and (Get-Item -LiteralPath $Hda).Length -le 0) {
    throw "Commercial HDA is empty: $Hda"
}

Push-Location $ProjectRoot
try {
    & $Python -c "import PyInstaller" 2>$null
    if ($LASTEXITCODE -ne 0) {
        & $Python -m pip install "pyinstaller>=6.10"
        if ($LASTEXITCODE -ne 0) {
            throw "Cannot install PyInstaller."
        }
    }
    $Version = & $Python -c "import sys; sys.path.insert(0, 'src'); import houd2launcher; print(houd2launcher.__version__)"
    if ($LASTEXITCODE -ne 0 -or -not $Version) {
        throw "Cannot resolve HouD2Launcher version."
    }
    & $Python "scripts\generate_windows_assets.py" $BrandIcon $Icon $TaskPlaceholder $VersionFile $Version
    if ($LASTEXITCODE -ne 0) {
        throw "Cannot generate Windows build assets."
    }
    $pyinstallerArguments = @(
        "--noconfirm",
        "--clean",
        "--onedir",
        "--windowed",
        "--noupx",
        "--contents-directory", "_internal",
        "--name", "HouD2Launcher",
        "--icon", $Icon,
        "--version-file", $VersionFile,
        "--add-data", "src\houd2launcher\resources;houd2launcher\resources",
        "--add-data", "src\houd2launcher\admin\static;houd2launcher\admin\static",
        "--add-data", "src\houd2launcher\houdini\apply_launch_settings.py;houd2launcher\houdini",
        "--add-data", "src\houd2launcher\houdini\cache_probe.py;houd2launcher\houdini",
        "--add-data", "houdini\python;houdini\python",
        "--add-data", "houdini\scripts\build_cache_hdas.py;houdini\scripts",
        "--add-data", "docs;docs",
        "--paths", "src"
    )
    if (Test-Path -LiteralPath $Hda) {
        $pyinstallerArguments += @("--add-data", "houdini\otls\houd2_cache.hda;houdini\otls")
        Write-Output "Including optional Commercial Cache HDA: $Hda"
    } else {
        Write-Output "Commercial Cache HDA not found; building Launcher without HDA definitions."
    }
    $pyinstallerArguments += "run_houd2launcher.py"
    & $Python -m PyInstaller @pyinstallerArguments
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller build failed."
    }
}
finally {
    Pop-Location
}

Write-Output "Build complete: $ProjectRoot\dist\HouD2Launcher"
