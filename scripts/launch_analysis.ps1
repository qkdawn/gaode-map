param(
    [switch]$Restart,
    [switch]$NoOpen,
    [switch]$UpdateEnvOnly,
    [string]$PublicDbHost
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$RuntimeDir = Join-Path $RepoRoot "runtime"
$FrontendRoot = Join-Path $RepoRoot "frontend"
$BackendPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$EnvPath = Join-Path $RepoRoot ".env"
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

function Set-PublicDbHost {
    param([string]$HostValue)

    $hostClean = ""
    if ($null -ne $HostValue) {
        $hostClean = $HostValue.Trim()
    }
    if (-not ($hostClean -match '^(?:\d{1,3}\.){3}\d{1,3}$')) {
        throw "Invalid public DB host: $HostValue"
    }
    $octets = $hostClean.Split(".") | ForEach-Object { [int]$_ }
    if (($octets | Where-Object { $_ -lt 0 -or $_ -gt 255 }).Count -gt 0) {
        throw "Invalid public DB host: $HostValue"
    }
    if (-not (Test-Path $EnvPath)) {
        throw "Missing env file: $EnvPath"
    }

    $lines = Get-Content -LiteralPath $EnvPath
    $hasDbHost = $false
    $hasDbUrl = $false
    $updated = foreach ($line in $lines) {
        if ($line -match '^DB_HOST=') {
            $hasDbHost = $true
            "DB_HOST=$hostClean"
        } elseif ($line -match '^DB_URL=') {
            $hasDbUrl = $true
            $dbUrl = $line.Substring(7).Trim()
            try {
                $builder = [System.UriBuilder]::new($dbUrl)
                $builder.Host = $hostClean
                "DB_URL=$($builder.Uri.AbsoluteUri)"
            } catch {
                throw "Failed to rewrite DB_URL host. Please check .env DB_URL format."
            }
        } else {
            $line
        }
    }

    if (-not $hasDbHost) {
        $updated += "DB_HOST=$hostClean"
    }
    if (-not $hasDbUrl) {
        Write-Warning ".env does not contain DB_URL; only DB_HOST was updated."
    }

    Set-Content -LiteralPath $EnvPath -Value $updated -Encoding UTF8
    Write-Host "Updated .env public DB host: $hostClean"
}

function Get-EnvValue {
    param([string]$Name)

    if (-not (Test-Path $EnvPath)) {
        return ""
    }
    $pattern = "^$([regex]::Escape($Name))=(.*)$"
    $line = Get-Content -LiteralPath $EnvPath |
        Where-Object { $_ -match $pattern } |
        Select-Object -First 1
    if (-not $line) {
        return ""
    }
    return ($line -replace $pattern, '$1').Trim()
}

function Test-DatabaseConfig {
    $dbUrl = Get-EnvValue -Name "DB_URL"
    if ($dbUrl) {
        return $true
    }
    $dbHost = Get-EnvValue -Name "DB_HOST"
    $dbPassword = Get-EnvValue -Name "DB_PASSWORD"
    return [bool]($dbHost -and $dbPassword)
}

function Assert-DatabaseConfig {
    if (Test-DatabaseConfig) {
        return
    }
    throw "Missing database config: .env must contain DB_URL, or DB_HOST together with DB_PASSWORD. Current .env has DB_HOST but no DB_URL/DB_PASSWORD, so the backend cannot start."
}

function Test-BackendImports {
    if (-not (Test-Path $BackendPython)) {
        return $false
    }
    Push-Location $RepoRoot
    try {
        $previousErrorActionPreference = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        try {
            & $BackendPython -c "from pydantic_core import __version__; import fastapi; import main" > $null 2>&1
            return ($LASTEXITCODE -eq 0)
        } finally {
            $ErrorActionPreference = $previousErrorActionPreference
        }
    } finally {
        Pop-Location
    }
}

function Repair-BackendVenv {
    Write-Host "Backend Python environment looks incomplete; repairing with uv sync..."
    Push-Location $RepoRoot
    try {
        $attempts = 0
        while ($true) {
            $attempts += 1
            uv sync
            if ($LASTEXITCODE -eq 0) {
                return
            }
            if ($attempts -ge 2) {
                throw "uv sync failed"
            }
            Write-Warning "uv sync failed, stopping repo-local Python processes and retrying once..."
            Get-CimInstance Win32_Process |
                Where-Object {
                    $_.Name -eq "python.exe" -and (
                        ($_.CommandLine -like "*$RepoRoot*") -or
                        ($_.ExecutablePath -like "*$RepoRoot*") -or
                        ($_.CommandLine -like "*uvicorn*main:app*")
                    )
                } |
                ForEach-Object {
                    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
                }
            Start-Sleep -Seconds 2
        }
    } finally {
        Pop-Location
    }
}

Ensure-RuntimeDir

if ($PublicDbHost) {
    Set-PublicDbHost -HostValue $PublicDbHost
    if ($UpdateEnvOnly) {
        Write-Host "Only .env was updated; services were not restarted."
        exit 0
    }
    $Restart = $true
}

if (-not (Test-Path $BackendPython)) {
    Repair-BackendVenv
}

Assert-DatabaseConfig

if (-not (Test-BackendImports)) {
    Repair-BackendVenv
    if (-not (Test-BackendImports)) {
        throw "Backend Python environment is still not importable after repair. Check .venv and runtime\launch_backend.err.log."
    }
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
    throw "Services were started, but $AnalysisUrl did not respond within 45 seconds. Check runtime\launch_backend.err.log."
}

if (-not $NoOpen) {
    Start-Process $AnalysisUrl
}

Write-Host "Gaode Map analysis is ready:"
Write-Host "  $AnalysisUrl"
