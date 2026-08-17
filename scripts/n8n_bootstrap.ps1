param(
    [switch]$SkipSmokeCheck,
    [switch]$SkipModelCheck
)

$ErrorActionPreference = "Stop"

function Get-DotEnvValue([string]$Name, [string]$DefaultValue) {
    if (-not (Test-Path ".env")) { return $DefaultValue }
    $setting = Get-Content ".env" | Where-Object { $_ -match "^$([regex]::Escape($Name))=" } | Select-Object -Last 1
    if (-not $setting) { return $DefaultValue }
    $value = ($setting -split '=', 2)[1].Trim()
    if ($value) { return $value }
    return $DefaultValue
}

function Assert-DockerDataDriveSpace([double]$MinimumFreeGb) {
    $settingsPath = Join-Path $env:APPDATA "Docker\settings-store.json"
    if (-not (Test-Path $settingsPath)) { return }

    try {
        $dockerSettings = Get-Content -LiteralPath $settingsPath -Raw | ConvertFrom-Json
        $dockerDataDirectory = [string]$dockerSettings.CustomWslDistroDir
        if (-not $dockerDataDirectory) { return }
        $driveRoot = [System.IO.Path]::GetPathRoot($dockerDataDirectory)
        $driveName = $driveRoot.TrimEnd('\').TrimEnd(':')
        $drive = Get-PSDrive -Name $driveName -PSProvider FileSystem -ErrorAction Stop
        $freeGb = [math]::Round($drive.Free / 1GB, 2)
    } catch {
        Write-Warning "Could not inspect Docker data drive free space: $($_.Exception.Message)"
        return
    }

    if ($freeGb -lt $MinimumFreeGb) {
        throw "Docker data drive $driveRoot has only $freeGb GB free. Free at least $MinimumFreeGb GB before starting n8n. Docker data directory: $dockerDataDirectory"
    }
}

$embeddingPort = if ($env:EMBEDDING_SERVICE_PORT) { $env:EMBEDDING_SERVICE_PORT } else { Get-DotEnvValue "EMBEDDING_SERVICE_PORT" "11435" }
$embeddingModel = if ($env:EMBEDDING_MODEL) { $env:EMBEDDING_MODEL } else { Get-DotEnvValue "EMBEDDING_MODEL" "jinaai/jina-embeddings-v2-base-zh" }
$embeddingDimensions = if ($env:EMBEDDING_DIMENSIONS) { $env:EMBEDDING_DIMENSIONS } else { Get-DotEnvValue "EMBEDDING_DIMENSIONS" "768" }
$minimumDockerFreeGb = [double](Get-DotEnvValue "N8N_MIN_DOCKER_FREE_GB" "8")
$embeddingLocalBaseUrl = "http://127.0.0.1:$embeddingPort"
$env:EMBEDDING_MODEL = $embeddingModel
$env:EMBEDDING_DIMENSIONS = $embeddingDimensions

$embeddingReady = $false
try {
    $health = Invoke-RestMethod "$embeddingLocalBaseUrl/health" -TimeoutSec 5
    $embeddingReady = $health.status -eq "healthy" -and $health.model -eq $embeddingModel -and [int]$health.dimensions -eq [int]$embeddingDimensions
} catch {
    $embeddingReady = $false
}

if (-not $embeddingReady) {
    $embeddingLive = $false
    try {
        $live = Invoke-RestMethod "$embeddingLocalBaseUrl/live" -TimeoutSec 2
        $embeddingLive = $live.status -eq "alive"
    } catch {
        $embeddingLive = $false
    }
    if (-not $embeddingLive) {
        $pythonCommand = Join-Path (Get-Location) ".venv\Scripts\python.exe"
        if (-not (Test-Path $pythonCommand)) {
            throw "Missing .venv Python. Run uv sync --locked before bootstrapping n8n."
        }
        $runtimeDir = Join-Path (Get-Location) "runtime"
        New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null
        $stdoutPath = Join-Path $runtimeDir "embedding-service.stdout.log"
        $stderrPath = Join-Path $runtimeDir "embedding-service.stderr.log"
        $embeddingProcess = Start-Process -FilePath $pythonCommand `
            -ArgumentList @("-m", "uvicorn", "modules.embedding_service:app", "--host", "127.0.0.1", "--port", $embeddingPort) `
            -WorkingDirectory (Get-Location) -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath
        Set-Content -Path (Join-Path $runtimeDir "embedding-service.pid") -Value $embeddingProcess.Id
        for ($attempt = 0; $attempt -lt 60; $attempt++) {
            try {
                $live = Invoke-RestMethod "$embeddingLocalBaseUrl/live" -TimeoutSec 2
                if ($live.status -eq "alive") { $embeddingLive = $true; break }
            } catch {
                Start-Sleep -Seconds 1
            }
        }
        if (-not $embeddingLive) {
            throw "Embedding service did not start. Check $stderrPath."
        }
    }
    $health = Invoke-RestMethod "$embeddingLocalBaseUrl/health" -TimeoutSec 900
    if ($health.status -ne "healthy" -or $health.model -ne $embeddingModel -or [int]$health.dimensions -ne [int]$embeddingDimensions) {
        throw "Embedding service health contract mismatch."
    }
}

Assert-DockerDataDriveSpace $minimumDockerFreeGb

$mcpPort = Get-DotEnvValue "N8N_SPATIAL_MCP_PORT" "8040"
$mcpListener = Get-NetTCPConnection -LocalPort ([int]$mcpPort) -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $mcpListener) {
    $pythonCommand = Join-Path (Get-Location) ".venv\Scripts\python.exe"
    if (-not (Test-Path $pythonCommand)) { throw "Missing .venv Python for the spatial MCP service." }
    $env:FASTMCP_HOST = "0.0.0.0"
    $env:FASTMCP_PORT = $mcpPort
    $runtimeDir = Join-Path (Get-Location) "runtime"
    New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null
    $mcpProcess = Start-Process -FilePath $pythonCommand `
        -ArgumentList @("-m", "modules.spatial_projects.mcp_server", "--transport", "streamable-http") `
        -WorkingDirectory (Get-Location) -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $runtimeDir "spatial-mcp.stdout.log") `
        -RedirectStandardError (Join-Path $runtimeDir "spatial-mcp.stderr.log")
    Set-Content -Path (Join-Path $runtimeDir "spatial-mcp.pid") -Value $mcpProcess.Id
    Start-Sleep -Seconds 2
}

docker compose up -d n8n-postgres rag-postgres redis n8n n8n-worker n8n-runners n8n-worker-runners
if ($LASTEXITCODE -ne 0) {
    throw "Failed to start n8n infrastructure."
}

docker compose exec -T rag-postgres sh -lc 'for file in /docker-entrypoint-initdb.d/*.sql; do psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f "$file"; done'
if ($LASTEXITCODE -ne 0) {
    throw "Failed to apply RAG database schema."
}

$codexBaseUrl = $env:CODEX_RELAY_BASE_URL
$codexModel = $env:CODEX_RELAY_MODEL
$codexApiKey = $env:CODEX_RELAY_API_KEY

if (-not ($codexBaseUrl -and $codexModel -and $codexApiKey)) {
    $codexConfigPath = Join-Path $env:USERPROFILE ".codex\config.toml"
    $codexAuthPath = Join-Path $env:USERPROFILE ".codex\auth.json"
    if (-not (Test-Path $codexConfigPath) -or -not (Test-Path $codexAuthPath)) {
        throw "Codex relay configuration is missing. Set CODEX_RELAY_BASE_URL, CODEX_RELAY_MODEL and CODEX_RELAY_API_KEY."
    }
    $codexConfig = Get-Content -Raw $codexConfigPath
    $baseMatch = [regex]::Match($codexConfig, '(?m)^openai_base_url\s*=\s*"([^"]+)"')
    $modelMatch = [regex]::Match($codexConfig, '(?m)^model\s*=\s*"([^"]+)"')
    if (-not $baseMatch.Success) {
        $providerMatch = [regex]::Match($codexConfig, '(?m)^model_provider\s*=\s*"([^"]+)"')
        if ($providerMatch.Success) {
            $providerName = [regex]::Escape($providerMatch.Groups[1].Value)
            $providerBlock = [regex]::Match(
                $codexConfig,
                "(?ms)^\[model_providers\.$providerName\]\s*(.*?)(?=^\[|\z)"
            )
            if ($providerBlock.Success) {
                $baseMatch = [regex]::Match($providerBlock.Groups[1].Value, '(?m)^base_url\s*=\s*"([^"]+)"')
            }
        }
    }
    $codexAuth = Get-Content -Raw $codexAuthPath | ConvertFrom-Json
    if (-not $codexBaseUrl) { $codexBaseUrl = $baseMatch.Groups[1].Value }
    if (-not $codexModel) { $codexModel = $modelMatch.Groups[1].Value }
    if (-not $codexApiKey) { $codexApiKey = $codexAuth.OPENAI_API_KEY }
}

$bootstrapPayload = @{
    codexRelayBaseUrl = $codexBaseUrl
    codexRelayModel = $codexModel
    codexRelayApiKey = $codexApiKey
} | ConvertTo-Json -Compress

$bootstrapPayload | docker compose exec -T n8n node /bootstrap/bootstrap/render-bootstrap.mjs
if ($LASTEXITCODE -ne 0) {
    throw "Failed to render temporary n8n credentials and workflows."
}

try {
    $n8nPort = Get-DotEnvValue "N8N_PORT" "5678"
    $n8nManagementKey = if ($env:N8N_MANAGEMENT_API_KEY) { $env:N8N_MANAGEMENT_API_KEY } else { Get-DotEnvValue "N8N_MANAGEMENT_API_KEY" "" }
    $legacyWorkflowIds = @(
        "ragDbSmoke000001", "kbPublishSource0001", "kbIngestProjectDoc01", "kbIngestWebhook0001",
        "ollamaEmbedding0001", "kbHybridRetrieve0001", "codexRelayResponse1", "codexRerankCandidates1",
        "analysisDecisionStep01", "analysisSpatialStrategyWebhook1", "analysisSpatialStrategyStatus01",
        "analysisStepTest001", "codexRelayTest001", "ragIntegration0001", "analysisSpatialStrategy1"
    )
    $workflowList = docker compose exec -T n8n n8n list:workflow
    if ($LASTEXITCODE -ne 0) { throw "Failed to inspect existing n8n workflows." }
    $existingWorkflowIds = @($workflowList | ForEach-Object { ($_ -split '\|', 2)[0].Trim() } | Where-Object { $_ })
    $presentLegacyIds = @($legacyWorkflowIds | Where-Object { $_ -in $existingWorkflowIds })
    if ($presentLegacyIds.Count -gt 0) {
        if (-not $n8nManagementKey) {
            throw "N8N_MANAGEMENT_API_KEY is required because obsolete workflows exist: $($presentLegacyIds -join ', ')"
        }
        $managementHeaders = @{ "X-N8N-API-KEY" = $n8nManagementKey }
        foreach ($workflowId in $presentLegacyIds) {
            try {
                Invoke-RestMethod -Method Delete -Uri "http://localhost:$n8nPort/api/v1/workflows/$workflowId" -Headers $managementHeaders -TimeoutSec 20 | Out-Null
                Write-Host "Removed obsolete n8n workflow $workflowId"
            } catch {
                throw "Failed to remove obsolete workflow ${workflowId}: $($_.Exception.Message)"
            }
        }
    }
    docker compose exec -T n8n n8n import:credentials --input=/tmp/gaode-n8n-credentials.json
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to import n8n credentials."
    }

    docker compose exec -T n8n n8n import:workflow --separate --input=/tmp/gaode-n8n-workflows --activeState=fromJson
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to import n8n workflows."
    }

    # n8n 2.x can import active workflows without rebuilding webhook_entity.
    # Reconcile the registry from the imported webhook nodes before smoke tests.
    $webhookRegistrySql = @'
WITH desired AS (
  SELECT
    w.id AS "workflowId",
    n->>'id' AS node,
    n->'parameters'->>'path' AS "webhookPath",
    upper(n->'parameters'->>'httpMethod') AS method,
    NULLIF(n->>'webhookId', '') AS "webhookId"
  FROM workflow_entity w
  CROSS JOIN LATERAL json_array_elements(w.nodes::json) n
  WHERE w.active
    AND w.id IN ('urbanRenewalDecisionSupportAgent', 'urbanRenewalPublicKnowledgeBase')
    AND n->>'type' = 'n8n-nodes-base.webhook'
)
INSERT INTO webhook_entity (
  "webhookPath", method, node, "webhookId", "pathLength", "workflowId"
)
SELECT
  "webhookPath",
  method,
  node,
  "webhookId",
  cardinality(regexp_split_to_array("webhookPath", '/')),
  "workflowId"
FROM desired
ON CONFLICT ("webhookPath", method) DO UPDATE SET
  node = EXCLUDED.node,
  "webhookId" = EXCLUDED."webhookId",
  "pathLength" = EXCLUDED."pathLength",
  "workflowId" = EXCLUDED."workflowId";
'@
    $webhookRegistrySql | docker compose exec -T n8n-postgres sh -lc 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to synchronize n8n webhook registry."
    }

    $workflowList = docker compose exec -T n8n n8n list:workflow
    if ($LASTEXITCODE -ne 0) { throw "Failed to verify imported n8n workflows." }
    $workflowIds = @($workflowList | ForEach-Object { ($_ -split '\|', 2)[0].Trim() } | Where-Object { $_ })
    foreach ($requiredId in @("urbanRenewalDecisionSupportAgent", "urbanRenewalPublicKnowledgeBase")) {
        if ($requiredId -notin $workflowIds) { throw "Required n8n workflow was not imported: $requiredId" }
    }
    $remainingLegacyIds = @($legacyWorkflowIds | Where-Object { $_ -in $workflowIds })
    if ($remainingLegacyIds.Count -gt 0) {
        throw "Obsolete project workflows still exist: $($remainingLegacyIds -join ', ')"
    }
}
finally {
    docker compose exec -T n8n node /bootstrap/bootstrap/render-bootstrap.mjs --cleanup
}

if (-not $SkipSmokeCheck) {
    docker compose exec -T rag-postgres sh -lc 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT 1 FROM kb_documents LIMIT 0; SELECT 1 FROM analysis_runs LIMIT 0;"'
    if ($LASTEXITCODE -ne 0) {
        throw "RAG database smoke check failed."
    }
    $pythonCommand = Join-Path (Get-Location) ".venv\Scripts\python.exe"
    $previousPluginSetting = $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD
    $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"
    & $pythonCommand -m pytest tests/domain/test_n8n_rag_workflows.py -q
    $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = $previousPluginSetting
    if ($LASTEXITCODE -ne 0) {
        throw "n8n workflow contract tests failed."
    }
}

if (-not $SkipModelCheck) {
    $modelCheckHeaders = @{ Authorization = "Bearer $codexApiKey"; "Content-Type" = "application/json" }
    $modelCheckBody = @{
        model = $codexModel
        input = "Reply with OK only."
        max_output_tokens = 16
        store = $false
    } | ConvertTo-Json -Compress
    try {
        $modelCheck = Invoke-RestMethod -Method Post -Uri "$($codexBaseUrl.TrimEnd('/'))/responses" -Headers $modelCheckHeaders -Body $modelCheckBody -TimeoutSec 120
    } catch {
        throw "Codex Responses model check failed: $($_.Exception.Message)"
    }
    if (-not $modelCheck.id -or -not $modelCheck.output) {
        throw "Codex Responses model check returned an invalid response."
    }
}

docker compose restart n8n n8n-worker n8n-runners n8n-worker-runners
if ($LASTEXITCODE -ne 0) {
    throw "Failed to restart n8n services after import."
}

Write-Host "n8n bootstrap complete. Editor: http://localhost:$n8nPort"
