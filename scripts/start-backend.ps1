$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

$gitCmd = "C:\Program Files\Git\cmd"
if (Test-Path -LiteralPath $gitCmd) {
  $env:PATH = "$gitCmd;$env:PATH"
}

$nodeCmd = "C:\Program Files\nodejs"
if (Test-Path -LiteralPath $nodeCmd) {
  $env:PATH = "$nodeCmd;$env:PATH"
}

$bunCmd = "C:\Users\Admin\.bun\bin"
if (Test-Path -LiteralPath $bunCmd) {
  $env:PATH = "$bunCmd;$env:PATH"
}

$pythonExe = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $pythonExe)) {
  throw "Python virtualenv not found: $pythonExe"
}

& $pythonExe -m uvicorn main:app --host 0.0.0.0 --port 8000 --access-log
