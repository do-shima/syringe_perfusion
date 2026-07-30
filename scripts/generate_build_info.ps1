param(
    [Parameter(Mandatory = $true)]
    [string]$BuildType,
    [switch]$RequireClean
)

$ErrorActionPreference = "Stop"
$repository = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $repository

function Resolve-PythonExecutable {
    $candidates = @()
    $pytestCommand = Get-Command pytest -ErrorAction SilentlyContinue
    if ($pytestCommand) {
        $candidates += (Join-Path (Split-Path $pytestCommand.Source -Parent) "..\python.exe")
    }
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCommand) {
        $candidates += $pythonCommand.Source
    }
    foreach ($candidate in $candidates) {
        if (-not (Test-Path -LiteralPath $candidate)) {
            continue
        }
        $probe = Start-Process `
            -FilePath $candidate `
            -ArgumentList "--version" `
            -Wait `
            -PassThru `
            -WindowStyle Hidden
        if ($probe.ExitCode -eq 0) {
            return (Resolve-Path $candidate).Path
        }
    }
    throw "A working Python interpreter was not found."
}

$python = Resolve-PythonExecutable
$arguments = @(
    "scripts\write_build_info.py",
    "--output", "build\generated\build_info.json",
    "--build-type", $BuildType
)
if ($RequireClean) {
    $arguments += "--require-clean"
}
& $python @arguments
if ($LASTEXITCODE -ne 0) {
    throw "Build identity generation failed."
}
