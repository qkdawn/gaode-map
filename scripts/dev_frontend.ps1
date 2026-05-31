param(
    [switch]$CheckOnly
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$FrontendRoot = Join-Path $RepoRoot "frontend"
$NodeModules = Join-Path $FrontendRoot "node_modules"

function Test-ContainerRunning {
    param([string]$Name)
    $line = docker ps --filter "name=^/$Name$" --format "{{.Names}}" 2>$null
    return [bool]$line
}

function Get-PortOwner {
    param([int]$Port)
    $listeners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if (-not $listeners) {
        return $null
    }
    $owners = @()
    foreach ($listener in $listeners) {
        $process = Get-Process -Id $listener.OwningProcess -ErrorAction SilentlyContinue
        $owners += [pscustomobject]@{
            ProcessId = $listener.OwningProcess
            ProcessName = if ($process) { $process.ProcessName } else { "unknown" }
        }
    }
    return $owners
}

if (Test-ContainerRunning "gaode-map-frontend-1") {
    if ($CheckOnly) {
        Write-Host "[check] Docker frontend container is running on port 5173. Run scripts/dev_infra.ps1 before starting frontend."
    } else {
        throw "Docker frontend container is running on port 5173. Run scripts/dev_infra.ps1 first."
    }
}

$owners = Get-PortOwner 5173
if ($owners) {
    $ownerText = ($owners | ForEach-Object { "$($_.ProcessId):$($_.ProcessName)" }) -join ", "
    if ($CheckOnly) {
        Write-Host "[check] Port 5173 is currently in use by $ownerText."
    } else {
        throw "Port 5173 is already in use by $ownerText."
    }
}

$env:VITE_BACKEND_ORIGIN = "http://127.0.0.1:8000"

Write-Host "Frontend local environment"
Write-Host "  VITE_BACKEND_ORIGIN=$env:VITE_BACKEND_ORIGIN"

if ($CheckOnly) {
    if (Test-Path $NodeModules) {
        Write-Host "[check] node_modules exists; would run npm run dev -- --host 127.0.0.1"
    } else {
        Write-Host "[check] node_modules missing; would run npm install, then npm run dev -- --host 127.0.0.1"
    }
    exit 0
}

Push-Location $FrontendRoot
try {
    if (-not (Test-Path $NodeModules)) {
        npm install
        if ($LASTEXITCODE -ne 0) {
            throw "npm install failed"
        }
    }
    npm run dev -- --host 127.0.0.1
} finally {
    Pop-Location
}
