$ErrorActionPreference = "Stop"

Set-Location -LiteralPath $PSScriptRoot
docker compose stop
if ($LASTEXITCODE -ne 0) {
    throw "Docker Compose failed with exit code $LASTEXITCODE."
}
Write-Host "PubMed Research Intelligence services stopped." -ForegroundColor Green
