param(
    [switch]$CheckOnly
)

$ErrorActionPreference = "Stop"

& (Join-Path $PSScriptRoot "dev_infra.ps1") -CheckOnly:$CheckOnly

Write-Host ""
Write-Host "Run these in two separate terminals for visible logs:"
Write-Host "  powershell -NoProfile -ExecutionPolicy Bypass -File scripts/dev_backend.ps1"
Write-Host "  powershell -NoProfile -ExecutionPolicy Bypass -File scripts/dev_frontend.ps1"
Write-Host ""
Write-Host "Open:"
Write-Host "  http://127.0.0.1:8000/analysis"
