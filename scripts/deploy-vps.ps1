param(
    [string]$SshHost = "comfy",
    [string]$IdentityFile = "",
    [switch]$RunNow
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$required = @(".env", "config.toml", "client_secret.json", "youtube_token.json")
foreach ($name in $required) {
    $path = Join-Path $projectRoot $name
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Missing required file: $path"
    }
}

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$archive = Join-Path ([System.IO.Path]::GetTempPath()) "shorts-factory-$stamp.tar.gz"
$remoteArchive = "/tmp/shorts-factory-$stamp.tar.gz"
$sshOptions = @("-o", "KexAlgorithms=curve25519-sha256")
if ($IdentityFile) {
    $resolvedIdentity = (Resolve-Path -LiteralPath $IdentityFile).Path
    $sshOptions += @("-i", $resolvedIdentity, "-o", "IdentitiesOnly=yes")
}

try {
    & tar.exe -czf $archive `
        --exclude=.git `
        --exclude=.venv `
        --exclude=.pytest_cache `
        --exclude=.ruff_cache `
        --exclude=.test-temp `
        --exclude=.test-tmp-* `
        --exclude=output `
        --exclude=__pycache__ `
        -C $projectRoot .
    if ($LASTEXITCODE -ne 0) { throw "Could not create deployment archive" }

    & scp.exe @sshOptions $archive "${SshHost}:$remoteArchive"
    if ($LASTEXITCODE -ne 0) { throw "Could not upload deployment archive" }

    $remote = @"
set -euo pipefail
app=/opt/shorts-factory
archive='$remoteArchive'
if [ -d "`$app" ]; then
  backup="/opt/shorts-factory.backup-$stamp"
  mv -- "`$app" "`$backup"
  echo "Previous deployment backed up at `$backup"
fi
install -d -m 0755 "`$app"
tar -xzf "`$archive" -C "`$app"
rm -f -- "`$archive"
bash "`$app/deploy/install-vps.sh"
"@
    $remote = $remote -replace "`r", ""
    & ssh.exe @sshOptions $SshHost $remote
    if ($LASTEXITCODE -ne 0) { throw "Remote installation failed" }

    if ($RunNow) {
        & ssh.exe @sshOptions $SshHost "systemctl start shorts-factory.service && journalctl -u shorts-factory.service -n 80 --no-pager"
        if ($LASTEXITCODE -ne 0) { throw "The first publication run failed" }
    }
}
finally {
    if (Test-Path -LiteralPath $archive) {
        Remove-Item -LiteralPath $archive -Force
    }
}

Write-Host "Shorts Factory is installed on $SshHost. ChatGPT and this PC are no longer required."
