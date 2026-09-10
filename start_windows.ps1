$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
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
    & $VirtualPython -m pip install -r requirements.txt
}

Write-Host "Squat Capture control panel: http://127.0.0.1:8080/control" -ForegroundColor Green
& $VirtualPython twitch_eventsub_listener.py
