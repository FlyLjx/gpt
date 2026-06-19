$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$webRoot = Join-Path $projectRoot "web"
Set-Location $webRoot

$nodeCmd = "C:\Program Files\nodejs"
if (Test-Path -LiteralPath $nodeCmd) {
  $env:PATH = "$nodeCmd;$env:PATH"
}

$bunCmd = "C:\Users\Admin\.bun\bin"
if (Test-Path -LiteralPath $bunCmd) {
  $env:PATH = "$bunCmd;$env:PATH"
}

$npmCmd = "C:\Program Files\nodejs\npm.cmd"
if (-not (Test-Path -LiteralPath $npmCmd)) {
  throw "npm.cmd not found: $npmCmd"
}

& $npmCmd run dev
