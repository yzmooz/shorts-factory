$ErrorActionPreference = 'Stop'
$projectDir = Split-Path -Parent $PSScriptRoot
$pythonExe = Join-Path $projectDir '.venv\Scripts\python.exe'
$configFile = Join-Path $projectDir 'config.toml'
try {
    Invoke-RestMethod 'http://127.0.0.1:8790/api/heroes' | Out-Null
} catch {
    Start-Process -FilePath $pythonExe -ArgumentList @('-m', 'shorts_factory.map_editor', '--config', ('"' + $configFile + '"')) -WorkingDirectory $projectDir -WindowStyle Hidden
}
Start-Process 'http://127.0.0.1:8790'
