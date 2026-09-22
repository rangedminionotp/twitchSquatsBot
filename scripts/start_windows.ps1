$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectDir

$PythonCommand = Get-Command python -ErrorAction SilentlyContinue
if (-not $PythonCommand) {
    $PythonCommand = Get-Command py -ErrorAction SilentlyContinue
}
if (-not $PythonCommand) {
    Write-Host "Python 3 is required. Install it from https://www.python.org/downloads/windows/" -ForegroundColor Yellow
    exit 1
}

$VirtualPython = Join-Path $ProjectDir ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $VirtualPython)) {
    Write-Host "Creating local Python environment..."
    & $PythonCommand.Source -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Could not create Python environment. Install Python from python.org and retry." }
}

& $VirtualPython -m squat_capture.startup_check --repair
if ($LASTEXITCODE -ne 0) { throw "Startup checks failed. See the repair instructions above." }

$AppPort = if ($env:PORT) { $env:PORT } else { "8080" }
Write-Host "Squat Capture control panel: http://127.0.0.1:$AppPort/control" -ForegroundColor Green
& $VirtualPython -m squat_capture
