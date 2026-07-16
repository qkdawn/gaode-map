param(
    [switch]$Restart,
    [switch]$NoOpen,
    [string]$BackendHost = "0.0.0.0",
    [int]$BackendPort = 8000,
    [string]$FrontendHost = "0.0.0.0",
    [int]$FrontendPort = 5173,
    [int]$SearxngPort = 8004,
    [int]$ArcGISBridgePort = 18081,
    [switch]$SkipSearxng,
    [switch]$SkipArcGISBridge
)

$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$FrontendRoot = Join-Path $RepoRoot "frontend"
$RuntimeDir = Join-Path $RepoRoot "runtime"
$BackendUrl = "http://127.0.0.1:$BackendPort/analysis"
$SearxngUrl = "http://127.0.0.1:$SearxngPort"
$ArcGISBridgeUrl = "http://127.0.0.1:$ArcGISBridgePort"
$LocalOverpassUrl = "http://127.0.0.1:8003/api/interpreter"
$PublicOverpassUrl = "https://overpass-api.de/api/interpreter"
$ArcGISBridgeRoot = Join-Path (Split-Path $RepoRoot -Parent) "host_bridge"
$ArcGISBridgeParent = Split-Path $ArcGISBridgeRoot -Parent

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

function Test-DockerEngine {
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        docker info > $null 2>&1
        return ($LASTEXITCODE -eq 0)
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
}

function Ensure-DockerEngine {
    if (Test-DockerEngine) {
        return
    }

    $dockerDesktopCandidates = @(
        "$env:ProgramFiles\Docker\Docker\Docker Desktop.exe",
        "$env:LOCALAPPDATA\Docker\Docker Desktop.exe"
    )
    $dockerDesktop = $dockerDesktopCandidates |
        Where-Object { $_ -and (Test-Path -LiteralPath $_) } |
        Select-Object -First 1
    if (-not $dockerDesktop) {
        throw "Docker engine is not running and Docker Desktop was not found."
    }

    Write-Host "Docker engine is not running; starting Docker Desktop..."
    Start-Process -FilePath $dockerDesktop -WindowStyle Hidden
    $deadline = (Get-Date).AddSeconds(120)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 3
        if (Test-DockerEngine) {
            Write-Host "Docker engine is ready."
            return
        }
    }
    throw "Docker Desktop was started, but the Docker engine did not become ready within 120 seconds."
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

function Wait-Overpass {
    param(
        [string]$Url,
        [int]$Seconds
    )

    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest `
                -Uri $Url `
                -Method Post `
                -Body @{ data = '[out:json][timeout:5];node(1);out;' } `
                -UseBasicParsing `
                -TimeoutSec 8
            if ($response.StatusCode -eq 200 -and $response.Content.TrimStart().StartsWith('{')) {
                return $true
            }
        } catch {
            Start-Sleep -Seconds 2
        }
    }
    return $false
}

function Test-ArcGISBridge {
    param([string]$BaseUrl)
    try {
        $payload = Invoke-RestMethod -Uri "$($BaseUrl.TrimEnd('/'))/health" -TimeoutSec 5
        return ($payload.status -eq "ok") -and
            [bool]$payload.python_exists -and
            [bool]$payload.script_exists -and
            [bool]$payload.road_syntax_script_exists -and
            [bool]$payload.token_configured
    } catch {
        return $false
    }
}

function Start-ArcGISBridge {
    if ($SkipArcGISBridge) {
        return $false
    }
    if (Test-ArcGISBridge -BaseUrl $ArcGISBridgeUrl) {
        Write-Host "Reusing existing ArcGIS bridge at $ArcGISBridgeUrl"
        return $true
    }
    if (-not (Test-Path (Join-Path $ArcGISBridgeRoot "main.py"))) {
        throw "ArcGIS bridge source is missing: $ArcGISBridgeRoot"
    }

    $owner = Get-PortOwner $ArcGISBridgePort
    if ($owner) {
        throw "Port $ArcGISBridgePort is already used by PID $($owner.ProcessId): $($owner.CommandLine)"
    }

    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pythonCommand) {
        throw "Missing command: python. ArcGIS bridge cannot start."
    }

    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $pythonCommand.Source -c "import fastapi, uvicorn" > $null 2>&1
        if ($LASTEXITCODE -ne 0) {
            throw "The default Python environment is missing fastapi/uvicorn for ArcGIS bridge."
        }
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }

    Start-Process `
        -FilePath $pythonCommand.Source `
        -ArgumentList @("-m", "uvicorn", "host_bridge.main:app", "--host", "0.0.0.0", "--port", "$ArcGISBridgePort") `
        -WorkingDirectory $ArcGISBridgeParent `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $ArcGISBridgeRoot "bridge.out.log") `
        -RedirectStandardError (Join-Path $ArcGISBridgeRoot "bridge.err.log")

    if (-not (Wait-Http -Url "$ArcGISBridgeUrl/health" -Seconds 30)) {
        throw "ArcGIS bridge did not respond at $ArcGISBridgeUrl. Check $ArcGISBridgeRoot\bridge.err.log."
    }
    if (-not (Test-ArcGISBridge -BaseUrl $ArcGISBridgeUrl)) {
        throw "ArcGIS bridge health check is incomplete. Check its Python, scripts, and token configuration."
    }
    return $true
}

function Test-SearxngSearch {
    param([string]$BaseUrl)
    try {
        $url = "$($BaseUrl.TrimEnd('/'))/search?q=test&format=json"
        $response = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 5
        if ($response.StatusCode -lt 200 -or $response.StatusCode -ge 500) {
            return $false
        }
        $payload = $response.Content | ConvertFrom-Json -ErrorAction Stop
        return $null -ne $payload
    } catch {
        return $false
    }
}

function Stop-RepoDevProcesses {
    Get-CimInstance Win32_Process |
        Where-Object {
            $_.CommandLine -and (
                (
                    $_.CommandLine -like "*$RepoRoot*" -and (
                        ($_.CommandLine -match "uvicorn" -and $_.CommandLine -match "main:app") -or
                        ($_.CommandLine -match "searx.webapp") -or
                        ($_.CommandLine -match [regex]::Escape("runtime\start_one_click_searxng.ps1")) -or
                        ($_.CommandLine -match "vite" -and $_.CommandLine -like "*$FrontendRoot*") -or
                        ($_.CommandLine -match [regex]::Escape("runtime\start_one_click_backend.ps1")) -or
                        ($_.CommandLine -match [regex]::Escape("runtime\start_one_click_frontend.ps1"))
                    )
                ) -or
                ($_.CommandLine -match "uvicorn" -and $_.CommandLine -match "host_bridge\.main:app|host_bridge.main:app")
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
if (-not (Test-CommandAvailable "docker")) {
    throw "Missing command: docker. Start Docker Desktop before running this script."
}
if (-not $SkipSearxng -and -not (Test-CommandAvailable "git")) {
    throw "Missing command: git. Install git or use -SkipSearxng before running this script."
}

Ensure-DockerEngine

if ($Restart) {
    Stop-RepoDevProcesses
    Start-Sleep -Seconds 2
}

Write-Host "Starting Docker infrastructure on ports 8001-8003..."
& (Join-Path $PSScriptRoot "dev_infra.ps1")

$localOverpassAvailable = Wait-Overpass -Url $LocalOverpassUrl -Seconds 60
$backendOverpassEndpoint = if ($localOverpassAvailable) { $LocalOverpassUrl } else { $PublicOverpassUrl }
if ($localOverpassAvailable) {
    Write-Host "Local Overpass is ready at $LocalOverpassUrl"
} else {
    Write-Warning "Local Overpass did not become ready within 60 seconds; road queries will use $PublicOverpassUrl."
}

$arcgisBridgeAvailable = Start-ArcGISBridge

$backendOwner = Get-PortOwner $BackendPort
if ($backendOwner) {
    throw "Port $BackendPort is already used by PID $($backendOwner.ProcessId): $($backendOwner.CommandLine)"
}

$frontendOwner = Get-PortOwner $FrontendPort
if ($frontendOwner) {
    throw "Port $FrontendPort is already used by PID $($frontendOwner.ProcessId): $($frontendOwner.CommandLine)"
}

$searxngAvailable = $false
$searxngOwner = if ($SkipSearxng) { $null } else { Get-PortOwner $SearxngPort }
if (-not $SkipSearxng -and $searxngOwner) {
    if (Test-SearxngSearch -BaseUrl $SearxngUrl) {
        $searxngAvailable = $true
        Write-Host "Reusing existing SearXNG at $SearxngUrl"
    } else {
        throw "Port $SearxngPort is already used by PID $($searxngOwner.ProcessId): $($searxngOwner.CommandLine). Use -SearxngPort to choose another port."
    }
}

$backendScript = Join-Path $RuntimeDir "start_one_click_backend.ps1"
$frontendScript = Join-Path $RuntimeDir "start_one_click_frontend.ps1"
$searxngScript = Join-Path $RuntimeDir "start_one_click_searxng.ps1"

if (-not $SkipSearxng -and -not $searxngAvailable) {
    $searxngRoot = Join-Path $RuntimeDir "searxng"
    $searxngSource = Join-Path $searxngRoot "source"
    $searxngSettings = Join-Path $searxngRoot "settings.yml"
    $searxngVenv = Join-Path $searxngRoot ".venv"
    Ensure-Directory $searxngRoot

@"
`$ErrorActionPreference = "Stop"
Set-Location -LiteralPath "$searxngRoot"
if (-not (Test-Path -LiteralPath "$searxngSource")) {
    Write-Host "Cloning SearXNG into $searxngSource"
    git clone --depth 1 https://github.com/searxng/searxng.git "$searxngSource"
    if (`$LASTEXITCODE -ne 0) {
        throw "git clone SearXNG failed"
    }
}
if (-not (Test-Path -LiteralPath "$searxngVenv")) {
    Write-Host "Creating SearXNG virtual environment"
    uv venv "$searxngVenv"
    if (`$LASTEXITCODE -ne 0) {
        throw "uv venv for SearXNG failed"
    }
}
Set-Location -LiteralPath "$searxngSource"
`$searxngPython = "$searxngVenv\Scripts\python.exe"
`$previousErrorActionPreference = `$ErrorActionPreference
`$ErrorActionPreference = "Continue"
& `$searxngPython -c "import searx" > `$null 2>&1
`$searxngReady = (`$LASTEXITCODE -eq 0)
`$ErrorActionPreference = `$previousErrorActionPreference
if (-not `$searxngReady) {
    Write-Host "Installing SearXNG dependencies"
    uv pip install --python `$searxngPython -e .
    if (`$LASTEXITCODE -ne 0) {
        throw "SearXNG dependency install failed"
    }
}
@'
use_default_settings: true

server:
  bind_address: "127.0.0.1"
  port: $SearxngPort
  secret_key: "gaode-map-dev-searxng"
  limiter: false
  public_instance: false
  image_proxy: false

search:
  safe_search: 1
  formats:
    - html
    - json

ui:
  static_use_hash: true

outgoing:
  request_timeout: 5.0
'@ | Set-Content -Path "$searxngSettings" -Encoding UTF8
`$env:SEARXNG_SETTINGS_PATH = "$searxngSettings"
Write-Host "SearXNG: $SearxngUrl"
& "$searxngVenv\Scripts\python.exe" "$searxngSource\searx\webapp.py"
"@ | Set-Content -Path $searxngScript -Encoding UTF8
}

@"
`$ErrorActionPreference = "Stop"
Set-Location -LiteralPath "$RepoRoot"
`$env:FRONTEND_MODE = "dev"
`$env:FRONTEND_DEV_ORIGIN = "http://127.0.0.1:$FrontendPort"
`$env:LOCAL_QUERY_BASE_URL = "http://127.0.0.1:8001"
`$env:VALHALLA_BASE_URL = "http://127.0.0.1:8002"
`$env:OVERPASS_ENDPOINT = "$backendOverpassEndpoint"
`$env:OVERPASS_FALLBACK_ENDPOINTS = "https://overpass-api.de/api/interpreter,https://overpass.kumi.systems/api/interpreter"
`$env:ARCGIS_BRIDGE_BASE_URL = "$ArcGISBridgeUrl"
`$env:SEARXNG_BASE_URL = "$SearxngUrl"
`$env:SEARXNG_TIMEOUT_MS = "8000"
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

if (-not $SkipSearxng -and -not $searxngAvailable) {
    Start-Process `
        -FilePath "powershell.exe" `
        -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-NoExit", "-File", $searxngScript) `
        -WorkingDirectory $RuntimeDir `
        -WindowStyle Normal

    if (Wait-Http -Url "$SearxngUrl/search?q=test&format=json" -Seconds 90) {
        if (Test-SearxngSearch -BaseUrl $SearxngUrl) {
            $searxngAvailable = $true
        }
    }
    if (-not $searxngAvailable) {
        Write-Warning "SearXNG was started, but $SearxngUrl did not return JSON within 90 seconds. AI 搜索地区资料 may be unavailable."
    }
}

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
Write-Host "  POI DB:   http://127.0.0.1:8001"
Write-Host "  Valhalla: http://127.0.0.1:8002"
Write-Host "  Overpass: http://127.0.0.1:8003"
if ($SkipSearxng) {
    Write-Host "  SearXNG:  skipped"
} else {
    Write-Host "  SearXNG:  $SearxngUrl"
}
if ($SkipArcGISBridge) {
    Write-Host "  ArcGIS:   skipped"
} elseif ($arcgisBridgeAvailable) {
    Write-Host "  ArcGIS:   $ArcGISBridgeUrl"
}
Write-Host ""
Write-Host "LAN access uses this machine's IP with ports $BackendPort and $FrontendPort."
Write-Host "Use -Restart to stop matching repo dev processes and start fresh."
