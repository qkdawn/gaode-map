param(
    [switch]$CheckOnly
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$PythonPath = Join-Path $RepoRoot ".venv\Scripts\python.exe"

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

if (-not (Test-Path $PythonPath)) {
    throw "Missing Python venv: $PythonPath. Create it before running the backend."
}

if (Test-ContainerRunning "gaode-map-app") {
    if ($CheckOnly) {
        Write-Host "[check] Docker app container is running on port 8000. Run scripts/dev_infra.ps1 before starting backend."
    } else {
        throw "Docker app container is running on port 8000. Run scripts/dev_infra.ps1 first."
    }
}

$owners = Get-PortOwner 8000
if ($owners) {
    $ownerText = ($owners | ForEach-Object { "$($_.ProcessId):$($_.ProcessName)" }) -join ", "
    if ($CheckOnly) {
        Write-Host "[check] Port 8000 is currently in use by $ownerText."
    } else {
        throw "Port 8000 is already in use by $ownerText."
    }
}

$env:FRONTEND_MODE = "dev"
$env:FRONTEND_DEV_ORIGIN = "http://127.0.0.1:5173"
$env:LOCAL_QUERY_BASE_URL = "http://127.0.0.1:8001"
$env:VALHALLA_BASE_URL = "http://127.0.0.1:8002"
$env:OVERPASS_ENDPOINT = "http://127.0.0.1:8003/api/interpreter"

Write-Host "Backend local environment"
Write-Host "  FRONTEND_MODE=$env:FRONTEND_MODE"
Write-Host "  FRONTEND_DEV_ORIGIN=$env:FRONTEND_DEV_ORIGIN"
Write-Host "  LOCAL_QUERY_BASE_URL=$env:LOCAL_QUERY_BASE_URL"
Write-Host "  VALHALLA_BASE_URL=$env:VALHALLA_BASE_URL"
Write-Host "  OVERPASS_ENDPOINT=$env:OVERPASS_ENDPOINT"

if ($CheckOnly) {
    Write-Host "[check] Would run: $PythonPath -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload"
    exit 0
}

Push-Location $RepoRoot
try {
    & $PythonPath -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
} finally {
    Pop-Location
}
