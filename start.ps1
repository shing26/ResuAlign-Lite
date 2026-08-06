param(
  [int]$Port = 8000,
  [string]$HostName = "127.0.0.1"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$env:PYTHONPATH = Join-Path $Root "src"

if ($env:RESUALIGN_PORT) { $Port = [int]$env:RESUALIGN_PORT }
if ($env:RESUALIGN_HOST) { $HostName = $env:RESUALIGN_HOST }

if (-not (Test-Path (Join-Path $Root ".env"))) {
  Write-Warning "No .env found. Copy .env.example to .env and set DEEPSEEK_API_KEY for LLM features."
}

Write-Host "ResuAlign starting at http://${HostName}:${Port}"
# Single process only: the analysis job queue and import/session state live
# in process memory. Never pass --workers > 1 (see docs/deployment-security.md).
python -m uvicorn resualign.api:app --host $HostName --port $Port --workers 1 --app-dir (Join-Path $Root "src")
