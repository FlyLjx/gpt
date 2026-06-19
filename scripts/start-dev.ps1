$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$backendScript = Join-Path $PSScriptRoot "start-backend.ps1"
$frontendScript = Join-Path $PSScriptRoot "start-frontend.ps1"

if (-not (Test-Path -LiteralPath $backendScript)) {
  throw "Missing backend script: $backendScript"
}

if (-not (Test-Path -LiteralPath $frontendScript)) {
  throw "Missing frontend script: $frontendScript"
}

Start-Process powershell -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-File", "`"$backendScript`"" -WorkingDirectory $projectRoot
Start-Process powershell -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-File", "`"$frontendScript`"" -WorkingDirectory $projectRoot

Write-Host "Backend window started."
Write-Host "Frontend window started."
Write-Host "Backend: http://127.0.0.1:8000"
Write-Host "Frontend: http://127.0.0.1:3000"
