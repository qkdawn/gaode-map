param(
  [ValidateSet('index', 'query')]
  [string]$Mode = 'index',
  [string]$Query = '',
  [ValidateSet('global', 'local', 'drift', 'basic')]
  [string]$SearchMethod = 'global'
)

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$workspace = Join-Path $repo 'runtime/graphrag-public-knowledge'
$python = Join-Path $repo 'runtime/graphrag-venv/Scripts/python.exe'
$graphrag = Join-Path $repo 'runtime/graphrag-venv/Scripts/graphrag.exe'
$sourceDir = Join-Path $repo 'runtime/public-knowledge-sources-20260815'
$embeddingApiBase = if ($env:GRAPHRAG_EMBEDDING_API_BASE) { $env:GRAPHRAG_EMBEDDING_API_BASE.TrimEnd('/') } else { 'http://127.0.0.1:11435/v1' }
$projectEnvPath = Join-Path $repo '.env'

function Get-ProjectEnvValue {
  param([Parameter(Mandatory = $true)][string]$Name)

  $processValue = [Environment]::GetEnvironmentVariable($Name)
  if (-not [string]::IsNullOrWhiteSpace($processValue)) { return $processValue }
  if (-not (Test-Path $projectEnvPath)) { return '' }

  $pattern = '^\s*' + [regex]::Escape($Name) + '\s*=\s*(.*)\s*$'
  foreach ($line in Get-Content -Path $projectEnvPath) {
    if ($line -notmatch $pattern) { continue }
    $value = $Matches[1].Trim()
    if ($value.Length -ge 2 -and (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'")))) {
      $value = $value.Substring(1, $value.Length - 2)
    }
    return $value
  }
  return ''
}

$projectApiBase = Get-ProjectEnvValue 'AI_BASE_URL'
$projectModel = Get-ProjectEnvValue 'AI_MODEL'
$projectApiKey = Get-ProjectEnvValue 'AI_API_KEY'
$chatModel = if ($env:GRAPHRAG_CHAT_MODEL) { $env:GRAPHRAG_CHAT_MODEL } elseif ($projectModel) { $projectModel } else { 'DeepSeek-V4-Flash' }
$embeddingModel = if ($env:GRAPHRAG_EMBEDDING_MODEL) { $env:GRAPHRAG_EMBEDDING_MODEL } else { 'jinaai/jina-embeddings-v2-base-zh' }
$completionUserAgent = if ($env:GRAPHRAG_USER_AGENT) { $env:GRAPHRAG_USER_AGENT } else { 'gaode-map-graphrag/1.0' }

if (-not (Test-Path $python)) {
  throw "GraphRAG environment is missing. Create runtime/graphrag-venv with Python 3.11/3.12 and install requirements-graphrag.txt."
}
if (-not (Test-Path $workspace)) { New-Item -ItemType Directory -Path $workspace | Out-Null }

& $python (Join-Path $repo 'scripts/prepare_graphrag_public_knowledge.py') --source-dir $sourceDir --workspace $workspace
if ($LASTEXITCODE -ne 0) { throw 'GraphRAG corpus preparation failed.' }

if (-not (Test-Path (Join-Path $workspace 'settings.yaml'))) {
  & $graphrag init --root $workspace --force --model $chatModel --embedding $embeddingModel
  if ($LASTEXITCODE -ne 0) { throw 'GraphRAG initialization failed.' }
}

# GraphRAG's MarkItDown input adapter reads the original PDFs directly.
$settingsPath = Join-Path $workspace 'settings.yaml'
$settings = Get-Content -Raw $settingsPath
$settings = [regex]::Replace(
  $settings,
  '(?ms)(^input:\s*\r?\n\s*type:)\s*\S+',
  '$1 markitdown'
)
$settings = [regex]::Replace($settings, '(?m)^(\s+file_pattern:\s*)"\.\*\\\\\.pdf\$"\s*$', '$1".*\\.pdf"')
if ($settings -notmatch '(?ms)^input:\s*\r?\n\s+file_pattern:') {
  $settings = [regex]::Replace(
    $settings,
    '(?m)^(input:\s*\r?\n)',
    '$1  file_pattern: ".*\\.pdf"' + [Environment]::NewLine,
    1
  )
}
$completionBase = if ($env:GRAPHRAG_API_BASE) { $env:GRAPHRAG_API_BASE.TrimEnd('/') } elseif ($projectApiBase) { $projectApiBase.TrimEnd('/') } else { 'https://api.chat.csu.edu.cn/v1' }
$modelMatches = [regex]::Matches($settings, '(?m)^(\s{4}model:\s*[^\r\n]+)\r?\n(?:\s{4}api_base:\s*[^\r\n]+\r?\n)?')
for ($index = $modelMatches.Count - 1; $index -ge 0; $index--) {
  $match = $modelMatches[$index]
  $base = if ($index -eq 0) { $completionBase } else { $embeddingApiBase }
  $model = if ($index -eq 0) { $chatModel } else { $embeddingModel }
  $replacement = if ([string]::IsNullOrWhiteSpace($base)) {
    "    model: $model`r`n"
  } else {
    "    model: $model`r`n    api_base: `"$base`"`r`n"
  }
  $settings = $settings.Remove($match.Index, $match.Length).Insert($match.Index, $replacement)
}
$completionHeaderPattern = '(?ms)(^completion_models:\s*\r?\n\s+default_completion_model:.*?^\s{4}api_base:\s*[^\r\n]+\r?\n)(?:\s{4}call_args:\s*\r?\n\s{6}extra_headers:\s*\r?\n\s{8}User-Agent:\s*[^\r\n]+\r?\n)?'
$completionHeaderRegex = [regex]::new($completionHeaderPattern)
$settings = $completionHeaderRegex.Replace(
  $settings,
  {
    param($match)
    $match.Groups[1].Value +
      "    call_args:`r`n" +
      "      extra_headers:`r`n" +
      "        User-Agent: `"$completionUserAgent`"`r`n"
  },
  1
)
$embeddingBatchSize = if ($env:GRAPHRAG_EMBED_BATCH_SIZE) { $env:GRAPHRAG_EMBED_BATCH_SIZE } else { '64' }
if ($settings -match '(?m)^\s+batch_size:') {
  $settings = [regex]::Replace($settings, '(?m)^(\s+batch_size:)\s*\d+', ('$1 ' + $embeddingBatchSize))
} elseif ($settings -match '(?m)^embed_text:\s*\r?\n') {
  $settings = $settings -replace '(?m)^(embed_text:\s*\r?\n)', ('$1  batch_size: ' + $embeddingBatchSize + [Environment]::NewLine)
}
$communityClusterSize = if ($env:GRAPHRAG_MAX_CLUSTER_SIZE) { $env:GRAPHRAG_MAX_CLUSTER_SIZE } else { '50' }
if ($settings -match '(?m)^cluster_graph:\s*\r?\n') {
  if ($settings -match '(?m)^\s+max_cluster_size:') {
    $settings = [regex]::Replace($settings, '(?m)^(\s+max_cluster_size:)\s*\d+', ('$1 ' + $communityClusterSize))
  } else {
    $settings = $settings -replace '(?m)^(cluster_graph:\s*\r?\n)', ('$1  max_cluster_size: ' + $communityClusterSize + [Environment]::NewLine)
  }
}
Set-Content -Path $settingsPath -Value $settings -Encoding UTF8

if ([string]::IsNullOrWhiteSpace($env:GRAPHRAG_API_KEY)) {
  $env:GRAPHRAG_API_KEY = $projectApiKey
}
if ([string]::IsNullOrWhiteSpace($env:GRAPHRAG_API_KEY)) {
  throw 'GRAPHRAG_API_KEY or AI_API_KEY must be available in the process environment or repository .env; the key is never written into the repository.'
}

if ($Mode -eq 'index') {
  & $graphrag index --root $workspace
  $exitCode = $LASTEXITCODE
  if ($exitCode -eq 0) {
    & $python (Join-Path $repo 'scripts/verify_graphrag_index.py') --workspace $workspace
    $exitCode = $LASTEXITCODE
  }
} else {
  if ([string]::IsNullOrWhiteSpace($Query)) { throw 'Query is required when Mode=query.' }
  & $graphrag query $Query --root $workspace --method $SearchMethod
  $exitCode = $LASTEXITCODE
}
exit $exitCode
