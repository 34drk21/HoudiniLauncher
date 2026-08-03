param(
    [string]$IsccPath = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot

& (Join-Path $PSScriptRoot "build_windows.ps1")
if ($LASTEXITCODE -ne 0) {
    throw "HouD2Launcher application build failed."
}

$installerArguments = @{}
if ($IsccPath) {
    $installerArguments.IsccPath = $IsccPath
}
& (Join-Path $PSScriptRoot "build_installer.ps1") @installerArguments
if ($LASTEXITCODE -ne 0) {
    throw "HouD2Launcher Installer build failed."
}

Write-Output "Release build complete: $ProjectRoot\dist\installer"
