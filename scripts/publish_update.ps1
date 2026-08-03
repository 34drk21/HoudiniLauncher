param(
    [Parameter(Mandatory = $true)][string]$ChannelPath,
    [Parameter(Mandatory = $true)][string]$InstallerPath,
    [Parameter(Mandatory = $true)][string]$Version,
    [string]$ReleaseNotes = ""
)

$ErrorActionPreference = "Stop"
if ($Version -notmatch '^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$') {
    throw "Version must use major.minor.patch."
}
$source = (Resolve-Path -LiteralPath $InstallerPath).Path
$channel = [System.IO.Path]::GetFullPath($ChannelPath)
New-Item -ItemType Directory -Path $channel -Force | Out-Null
$filename = [System.IO.Path]::GetFileName($source)
$destination = Join-Path $channel $filename
$temporaryInstaller = "$destination.part"
Copy-Item -LiteralPath $source -Destination $temporaryInstaller -Force
$sourceHash = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant()
$copiedHash = (Get-FileHash -LiteralPath $temporaryInstaller -Algorithm SHA256).Hash.ToLowerInvariant()
if ($sourceHash -ne $copiedHash) {
    Remove-Item -LiteralPath $temporaryInstaller -Force
    throw "Copied Installer checksum does not match."
}
Move-Item -LiteralPath $temporaryInstaller -Destination $destination -Force
$file = Get-Item -LiteralPath $destination
$manifest = [ordered]@{
    format = "houd2.update"
    schema_version = 1
    version = $Version
    published_at = (Get-Date).ToUniversalTime().ToString("o")
    installer_file = $filename
    size_bytes = $file.Length
    sha256 = $sourceHash
    release_notes = $ReleaseNotes
}
$manifestPart = Join-Path $channel "latest.json.part"
$manifestPath = Join-Path $channel "latest.json"
$manifestJson = $manifest | ConvertTo-Json -Depth 5
[System.IO.File]::WriteAllText(
    $manifestPart,
    $manifestJson,
    (New-Object System.Text.UTF8Encoding($false))
)
Move-Item -LiteralPath $manifestPart -Destination $manifestPath -Force
Write-Output "Published HouD2Launcher $Version to $channel"
