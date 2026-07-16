param(
    [string]$CodexHome = $env:CODEX_HOME
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$source = Join-Path $repoRoot "skills\spatial-business-analyst"
if (-not (Test-Path -LiteralPath (Join-Path $source "SKILL.md") -PathType Leaf)) {
    throw "Spatial Business Analyst Skill source is missing: $source"
}

if ([string]::IsNullOrWhiteSpace($CodexHome)) {
    $CodexHome = Join-Path $HOME ".codex"
}
$skillsRoot = Join-Path $CodexHome "skills"
$target = Join-Path $skillsRoot "spatial-business-analyst"
New-Item -ItemType Directory -Path $skillsRoot -Force | Out-Null

if (Test-Path -LiteralPath $target) {
    $existing = Get-Item -LiteralPath $target -Force
    if (($existing.Attributes -band [IO.FileAttributes]::ReparsePoint) -eq 0) {
        throw "Refusing to replace non-link Skill directory: $target"
    }
    $resolved = [IO.Path]::GetFullPath((Get-Item -LiteralPath $target).Target)
    if ($resolved -ne [IO.Path]::GetFullPath($source)) {
        throw "Existing Skill link points elsewhere: $target -> $resolved"
    }
    Write-Output $target
    exit 0
}

New-Item -ItemType Junction -Path $target -Target $source | Out-Null
Write-Output $target
