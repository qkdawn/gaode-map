param(
    [switch]$CheckOnly
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$ComposeBase = @("-f", "docker-compose.yml")
$ComposeDev = @("-f", "docker-compose.yml", "-f", "docker-compose.dev.yml")
$InfraServices = @("search", "valhalla", "overpass")
$LocalServices = @("app", "frontend")

function Invoke-RepoCommand {
    param([string[]]$Arguments)
    Push-Location $RepoRoot
    try {
        & $Arguments[0] $Arguments[1..($Arguments.Length - 1)]
        if ($LASTEXITCODE -ne 0) {
            throw "Command failed: $($Arguments -join ' ')"
        }
    } finally {
        Pop-Location
    }
}

function Get-ContainerState {
    param([string]$Name)
    $line = docker ps -a --filter "name=^/$Name$" --format "{{.Names}}|{{.Status}}|{{.Ports}}" 2>$null
    if (-not $line) {
        return [pscustomobject]@{ Name = $Name; Status = "missing"; Ports = "" }
    }
    $parts = $line -split "\|", 3
    return [pscustomobject]@{ Name = $parts[0]; Status = $parts[1]; Ports = $parts[2] }
}

function Get-PortOwner {
    param([int]$Port)
    $listeners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    $owners = @()
    if (-not $listeners) {
        $listeners = @()
    }
    foreach ($listener in @($listeners)) {
        $process = Get-Process -Id $listener.OwningProcess -ErrorAction SilentlyContinue
        $processName = if ($process) { $process.ProcessName } else { "unknown" }
        $owners += "$($listener.OwningProcess):$processName"
    }

    $dockerRows = docker ps --format "{{.Names}}|{{.Ports}}" 2>$null
    foreach ($row in @($dockerRows)) {
        $parts = $row -split "\|", 2
        if ($parts.Length -eq 2 -and $parts[1].Contains(":$Port->")) {
            $owners += "docker:$($parts[0])"
        }
    }

    if (-not $owners) {
        return "free"
    }
    return ($owners | Sort-Object -Unique) -join ", "
}

Write-Host "Hybrid dev layout"
Write-Host "  Docker : search, valhalla, overpass"
Write-Host "  Local  : app(FastAPI), frontend(Vite)"
Write-Host ""

if ($CheckOnly) {
    Write-Host "[check] Would stop Docker app/frontend and start Docker infra services."
} else {
    Write-Host "Stopping Docker app/frontend so local ports are free..."
    Invoke-RepoCommand (@("docker", "compose") + $ComposeDev + @("stop") + $LocalServices)
    Write-Host "Starting Docker infra services without --build..."
    Invoke-RepoCommand (@("docker", "compose") + $ComposeBase + @("up", "-d") + $InfraServices)
}

Write-Host ""
Write-Host "Docker containers"
foreach ($name in @("gaode-map-search", "gaode-map-valhalla", "gaode-map-overpass", "gaode-map-app", "gaode-map-frontend-1")) {
    $state = Get-ContainerState $name
    Write-Host ("  {0,-24} {1}" -f $state.Name, $state.Status)
}

Write-Host ""
Write-Host "Port ownership"
foreach ($port in @(8000, 5173, 8001, 8002, 8003)) {
    Write-Host ("  {0,-5} {1}" -f $port, (Get-PortOwner $port))
}

Write-Host ""
Write-Host "Next terminals:"
Write-Host "  powershell -NoProfile -ExecutionPolicy Bypass -File scripts/dev_backend.ps1"
Write-Host "  powershell -NoProfile -ExecutionPolicy Bypass -File scripts/dev_frontend.ps1"
