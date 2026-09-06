$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$venvPath = Join-Path $projectRoot ".venv"

py -3.11 -m venv $venvPath
$pythonPath = Join-Path $venvPath "Scripts\python.exe"
& $pythonPath -m pip install --upgrade pip
& $pythonPath -m pip install -e "$projectRoot[dev]"

if (-not (Test-Path -LiteralPath (Join-Path $projectRoot "config.toml"))) {
    Copy-Item -LiteralPath (Join-Path $projectRoot "config.example.toml") -Destination (Join-Path $projectRoot "config.toml")
}

Write-Host "Setup complete. Running environment check:"
& $pythonPath -m shorts_factory.cli --config (Join-Path $projectRoot "config.toml") doctor
