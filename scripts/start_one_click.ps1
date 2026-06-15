param(
    [switch]$Restart,
    [switch]$NoOpen,
    [string]$BackendHost = "0.0.0.0",
    [int]$BackendPort = 8000,
    [string]$FrontendHost = "0.0.0.0",
    [int]$FrontendPort = 5173
)

$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$FrontendRoot = Join-Path $RepoRoot "frontend"
$RuntimeDir = Join-Path $RepoRoot "runtime"
$BackendUrl = "http://127.0.0.1:$BackendPort/analysis"

function Ensure-Directory {
    param([string]$Path)
    if (-not (Test-Path $Path)) {
        New-Item -ItemType Directory -Path $Path | Out-Null
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

function Test-CommandAvailable {
    param([string]$Name)
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
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

function Stop-RepoDevProcesses {
    Get-CimInstance Win32_Process |
        Where-Object {
            $_.CommandLine -and
            $_.CommandLine -like "*$RepoRoot*" -and
            (
                ($_.CommandLine -match "uvicorn" -and $_.CommandLine -match "main:app") -or
                ($_.CommandLine -match "vite" -and $_.CommandLine -like "*$FrontendRoot*") -or
                ($_.CommandLine -match [regex]::Escape("runtime\start_one_click_backend.ps1")) -or
                ($_.CommandLine -match [regex]::Escape("runtime\start_one_click_frontend.ps1"))
            )
        } |
        ForEach-Object {
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        }
}

Ensure-Directory $RuntimeDir

if (-not (Test-Path (Join-Path $RepoRoot "main.py"))) {
    throw "Missing backend entry: $RepoRoot\main.py"
}
if (-not (Test-Path (Join-Path $FrontendRoot "package.json"))) {
    throw "Missing frontend package: $FrontendRoot\package.json"
}
if (-not (Test-CommandAvailable "uv")) {
    throw "Missing command: uv. Install uv or add it to PATH before running this script."
}
if (-not (Test-CommandAvailable "npm")) {
    throw "Missing command: npm. Install Node.js/npm or add it to PATH before running this script."
}

if ($Restart) {
    Stop-RepoDevProcesses
    Start-Sleep -Seconds 2
}

$backendOwner = Get-PortOwner $BackendPort
if ($backendOwner) {
    throw "Port $BackendPort is already used by PID $($backendOwner.ProcessId): $($backendOwner.CommandLine)"
}

$frontendOwner = Get-PortOwner $FrontendPort
if ($frontendOwner) {
    throw "Port $FrontendPort is already used by PID $($frontendOwner.ProcessId): $($frontendOwner.CommandLine)"
}

$backendScript = Join-Path $RuntimeDir "start_one_click_backend.ps1"
$frontendScript = Join-Path $RuntimeDir "start_one_click_frontend.ps1"

@"
`$ErrorActionPreference = "Stop"
Set-Location -LiteralPath "$RepoRoot"
`$env:FRONTEND_MODE = "dev"
`$env:FRONTEND_DEV_ORIGIN = "http://127.0.0.1:$FrontendPort"
`$env:LOCAL_QUERY_BASE_URL = "http://127.0.0.1:8001"
`$env:VALHALLA_BASE_URL = "http://127.0.0.1:8002"
`$env:OVERPASS_ENDPOINT = "http://127.0.0.1:8003/api/interpreter"
Write-Host "Backend: uv run uvicorn main:app --host $BackendHost --port $BackendPort --reload"
uv run uvicorn main:app --host $BackendHost --port $BackendPort --reload
"@ | Set-Content -Path $backendScript -Encoding UTF8

@"
`$ErrorActionPreference = "Stop"
Set-Location -LiteralPath "$FrontendRoot"
`$env:VITE_BACKEND_ORIGIN = "http://127.0.0.1:$BackendPort"
if (-not (Test-Path "node_modules")) {
    Write-Host "Frontend dependencies missing; running npm install first."
    npm install
    if (`$LASTEXITCODE -ne 0) {
        throw "npm install failed"
    }
}
Write-Host "Frontend: npm run dev -- --host $FrontendHost --port $FrontendPort"
npm run dev -- --host $FrontendHost --port $FrontendPort
"@ | Set-Content -Path $frontendScript -Encoding UTF8

Start-Process `
    -FilePath "powershell.exe" `
    -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-NoExit", "-File", $backendScript) `
    -WorkingDirectory $RepoRoot `
    -WindowStyle Normal

Start-Process `
    -FilePath "powershell.exe" `
    -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-NoExit", "-File", $frontendScript) `
    -WorkingDirectory $FrontendRoot `
    -WindowStyle Normal

if (-not (Wait-Http -Url $BackendUrl -Seconds 45)) {
    Write-Warning "Services were started, but $BackendUrl did not respond within 45 seconds."
}

if (-not $NoOpen) {
    Start-Process $BackendUrl
}

Write-Host ""
Write-Host "Gaode Map demo started."
Write-Host "  Backend:  http://127.0.0.1:$BackendPort"
Write-Host "  Analysis: $BackendUrl"
Write-Host "  Frontend: http://127.0.0.1:$FrontendPort"
Write-Host ""
Write-Host "LAN access uses this machine's IP with ports $BackendPort and $FrontendPort."
Write-Host "Use -Restart to stop matching repo dev processes and start fresh."
