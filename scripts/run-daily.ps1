$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
Set-Location -LiteralPath $projectRoot
& $pythonPath -m shorts_factory.cli --config (Join-Path $projectRoot "config.toml") run-once
exit $LASTEXITCODE

