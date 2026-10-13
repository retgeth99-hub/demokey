$ErrorActionPreference = "Stop"

Set-Location -LiteralPath $PSScriptRoot

if (-not (Test-Path -LiteralPath ".env")) {
    Copy-Item -LiteralPath ".env.example" -Destination ".env"
    Write-Host "Created .env from .env.example. Add API keys for the full experience." -ForegroundColor Yellow
}

docker compose up --build -d
if ($LASTEXITCODE -ne 0) {
    throw "Docker Compose failed with exit code $LASTEXITCODE."
}

Write-Host ""
Write-Host "PubMed Research Intelligence is running:" -ForegroundColor Green
Write-Host "  Web: http://127.0.0.1:5173/"
Write-Host "  API: http://127.0.0.1:8000/docs"
Write-Host "  Status: docker compose ps"
