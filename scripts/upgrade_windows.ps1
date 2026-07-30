param(
    [Parameter(Mandatory = $true)]
    [string]$NewRelease,
    [Parameter(Mandatory = $true)]
    [string]$ExistingInstallation,
    [Parameter(Mandatory = $true)]
    [string]$Destination
)

$ErrorActionPreference = "Stop"
$repository = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $repository
$pytestCommand = Get-Command pytest
$python = (Resolve-Path (Join-Path (Split-Path $pytestCommand.Source -Parent) "..\python.exe")).Path
& $python scripts\release_tool.py upgrade `
    --new-release $NewRelease `
    --existing $ExistingInstallation `
    --destination $Destination
if ($LASTEXITCODE -ne 0) {
    throw "Upgrade preparation failed."
}
Write-Host "Upgrade prepared in a new versioned directory: $Destination"
