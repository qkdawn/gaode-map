param(
    [switch]$Restart,
    [switch]$NoOpen
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$RuntimeDir = Join-Path $RepoRoot "runtime"
$FrontendRoot = Join-Path $RepoRoot "frontend"
$BackendPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$AnalysisUrl = "http://127.0.0.1:8000/analysis"

function Ensure-RuntimeDir {
    if (-not (Test-Path $RuntimeDir)) {
        New-Item -ItemType Directory -Path $RuntimeDir | Out-Null
    }
}

function Get-PortOwner {
    param([int]$Port)
    $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $listener) {
        return $null
    }
    return Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)" -ErrorAction SilentlyContinue
}

function Test-RepoBackend {
    $owner = Get-PortOwner 8000
    return $owner -and ($owner.CommandLine -match "uvicorn") -and ($owner.CommandLine -match "main:app") -and ($owner.CommandLine -like "*$RepoRoot*")
}

function Test-RepoFrontend {
    $owner = Get-PortOwner 5173
    return $owner -and ($owner.CommandLine -like "*$FrontendRoot*") -and ($owner.CommandLine -match "vite")
}

function Wait-Http {
    param(
        [string]$Url,
        [int]$Seconds
    )
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
                return $true
            }
        } catch {
            Start-Sleep -Seconds 1
        }
    }
    return $false
}

Ensure-RuntimeDir

if (-not (Test-Path $BackendPython)) {
    throw "Missing Python venv: $BackendPython"
}

if ($Restart) {
    Get-CimInstance Win32_Process |
        Where-Object {
            ($_.CommandLine -match "uvicorn" -and $_.CommandLine -match "main:app") -or
            ($_.CommandLine -match [regex]::Escape((Join-Path $PSScriptRoot "dev_frontend.ps1"))) -or
            ($_.CommandLine -like "*$FrontendRoot*" -and $_.CommandLine -match "vite")
        } |
        ForEach-Object {
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        }
    Start-Sleep -Seconds 2
}

$backendOwner = Get-PortOwner 8000
if ($backendOwner -and -not (Test-RepoBackend)) {
    throw "Port 8000 is already used by PID $($backendOwner.ProcessId): $($backendOwner.CommandLine)"
}

$frontendOwner = Get-PortOwner 5173
if ($frontendOwner -and -not (Test-RepoFrontend)) {
    throw "Port 5173 is already used by PID $($frontendOwner.ProcessId): $($frontendOwner.CommandLine)"
}

if (-not (Test-RepoFrontend)) {
    $env:VITE_BACKEND_ORIGIN = "http://127.0.0.1:8000"
    Start-Process `
        -FilePath "npm.cmd" `
        -ArgumentList @("run", "dev", "--", "--host", "127.0.0.1", "--port", "5173") `
        -WorkingDirectory $FrontendRoot `
        -WindowStyle Minimized `
        -RedirectStandardOutput (Join-Path $RuntimeDir "launch_frontend.out.log") `
        -RedirectStandardError (Join-Path $RuntimeDir "launch_frontend.err.log")
}

if (-not (Test-RepoBackend)) {
    $env:FRONTEND_MODE = "dev"
    $env:FRONTEND_DEV_ORIGIN = "http://127.0.0.1:5173"
    $env:LOCAL_QUERY_BASE_URL = "http://127.0.0.1:8001"
    $env:VALHALLA_BASE_URL = "http://127.0.0.1:8002"
    $env:OVERPASS_ENDPOINT = "http://127.0.0.1:8003/api/interpreter"
    Start-Process `
        -FilePath $BackendPython `
        -ArgumentList @("-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8000", "--reload") `
        -WorkingDirectory $RepoRoot `
        -WindowStyle Minimized `
        -RedirectStandardOutput (Join-Path $RuntimeDir "launch_backend.out.log") `
        -RedirectStandardError (Join-Path $RuntimeDir "launch_backend.err.log")
}

if (-not (Wait-Http -Url $AnalysisUrl -Seconds 45)) {
    Write-Warning "Services were started, but $AnalysisUrl did not respond within 45 seconds."
}

if (-not $NoOpen) {
    Start-Process $AnalysisUrl
}

Write-Host "Gaode Map analysis is ready:"
Write-Host "  $AnalysisUrl"
