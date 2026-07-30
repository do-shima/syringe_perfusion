$ErrorActionPreference = "Stop"
$repository = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $repository

if (-not $IsWindows -and $env:OS -ne "Windows_NT") {
    throw "The release build must run on Windows."
}

$status = git status --porcelain
if ($LASTEXITCODE -ne 0) {
    throw "Git status failed."
}
if ($status) {
    throw "Release build requires a clean source tree."
}

& (Join-Path $PSScriptRoot "generate_build_info.ps1") `
    -BuildType "release-candidate" `
    -RequireClean
if ($LASTEXITCODE -ne 0) {
    throw "Build identity generation failed."
}

$pytestOutput = pytest -q 2>&1
$pytestOutput | ForEach-Object { Write-Host $_ }
if ($LASTEXITCODE -ne 0) {
    throw "Tests failed."
}
$testSummary = [string]($pytestOutput | Select-Object -Last 1)
if (-not $testSummary) {
    $testSummary = "pytest: all tests passed"
}

git diff --check
if ($LASTEXITCODE -ne 0) {
    throw "git diff --check failed."
}

$env:A4_RELEASE_BUILD = "1"
try {
    cmd /c scripts\build_windows.bat
    if ($LASTEXITCODE -ne 0) {
        throw "Windows one-folder build failed."
    }
} finally {
    Remove-Item Env:\A4_RELEASE_BUILD -ErrorAction SilentlyContinue
}

$stage = Join-Path $repository "build\pyinstaller-dist"
$cli = Join-Path $stage "a4ctl\a4ctl.exe"
$gui = Join-Path $stage "A4PumpGUI\A4PumpGUI.exe"
if (-not (Test-Path -LiteralPath $cli) -or -not (Test-Path -LiteralPath $gui)) {
    throw "Packaged executables are missing."
}

& $cli --version
if ($LASTEXITCODE -ne 0) {
    throw "Packaged --version smoke failed."
}
& $cli --config-dir (Join-Path $repository "config") config-path --json *> $null
if ($LASTEXITCODE -ne 0) {
    throw "Packaged config-path smoke failed."
}
& $cli --config-dir (Join-Path $repository "config") preflight --json *> $null
if ($LASTEXITCODE -notin @(0, 2)) {
    throw "Packaged preflight smoke failed."
}
& $cli --config-dir (Join-Path $repository "config") validation-status --json *> $null
if ($LASTEXITCODE -ne 0) {
    throw "Packaged validation-status smoke failed."
}
& $cli --config-dir (Join-Path $repository "config") recent-runs --limit 20 --json *> $null
if ($LASTEXITCODE -ne 0) {
    throw "Packaged recent-runs smoke failed."
}
& $cli --config-dir (Join-Path $repository "config") diagnostics-summary *> $null
if ($LASTEXITCODE -ne 0) {
    throw "Packaged diagnostics-summary smoke failed."
}
$diagnosticSmoke = Join-Path $repository "build\release-diagnostics-smoke.zip"
& $cli --config-dir (Join-Path $repository "config") export-diagnostics --output $diagnosticSmoke *> $null
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $diagnosticSmoke)) {
    throw "Packaged export-diagnostics smoke failed."
}

$smokeConfig = Join-Path $repository "build\release-gui-smoke-config"
if (Test-Path -LiteralPath $smokeConfig) {
    Remove-Item -LiteralPath $smokeConfig -Recurse -Force
}
New-Item -ItemType Directory -Path $smokeConfig | Out-Null
Copy-Item -LiteralPath @(
    (Join-Path $repository "config\pumps.json"),
    (Join-Path $repository "config\profiles.json"),
    (Join-Path $repository "config\syringes.json"),
    (Join-Path $repository "config\recipes.json")
) -Destination $smokeConfig
$env:A4PUMP_CONFIG_DIR = $smokeConfig
try {
    $guiProcess = Start-Process -FilePath $gui -WindowStyle Hidden -PassThru
    Start-Sleep -Seconds 3
    if ($guiProcess.HasExited) {
        throw "Packaged GUI exited during smoke test."
    }
    Stop-Process -Id $guiProcess.Id
} finally {
    Remove-Item Env:\A4PUMP_CONFIG_DIR -ErrorAction SilentlyContinue
}

$pytestCommand = Get-Command pytest
$python = (Resolve-Path (Join-Path (Split-Path $pytestCommand.Source -Parent) "..\python.exe")).Path
& $python scripts\release_tool.py assemble `
    --repo $repository `
    --stage $stage `
    --release-root (Join-Path $repository "release") `
    --test-summary $testSummary
if ($LASTEXITCODE -ne 0) {
    throw "Release assembly failed."
}
& $python scripts\release_tool.py verify `
    --release-root (Join-Path $repository "release")
if ($LASTEXITCODE -ne 0) {
    throw "Release verification failed."
}

Write-Host "Release candidate artifacts:"
Get-ChildItem (Join-Path $repository "release") -File |
    Where-Object { $_.Name -match "A4PumpControl|SHA256|manifest|RELEASE_NOTES" } |
    ForEach-Object { Write-Host $_.FullName }
