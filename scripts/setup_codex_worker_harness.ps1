param(
  [string] $WorkerHome = (Join-Path $env:TEMP 'codex-worker-home'),
  [string] $WorkerRunroot = (Join-Path $env:TEMP 'codex-worker-runroot'),
  # The dirs the worker may WRITE to. Empty -> Agent A default (the proposals dir).
  # Agent B passes the verdicts dir. RepoRoot is always granted READ, so read-only
  # inputs (bundles, contract, evidence cache) need no explicit grant.
  [string[]] $WriteDirs = @(),
  # Extra dirs to grant READ beyond the repo root. Agent B passes the Python interpreter
  # dir (e.g. a conda/venv root outside the repo) so the worker can EXECUTE the exact
  # interpreter the prompt names -- a bare sandbox `python` lacks the project deps.
  [string[]] $ReadDirs = @(),
  # Codex shell env inheritance. "core" (A default) is a minimal env; "all" carries the
  # operator PATH (incl. the conda/venv dirs) so the named interpreter's DLLs resolve.
  [string] $EnvInherit = "core",
  # Keep the user site-packages (%APPDATA%\Python) on sys.path. Off by default (A hardens
  # with PYTHONNOUSERSITE=1). Agent B sets it when the project deps live in the user site.
  [switch] $AllowUserSite
)

$ErrorActionPreference = 'Stop'

function ConvertTo-TomlLiteralKey {
  param([Parameter(Mandatory = $true)][string] $Value)
  return "'" + ($Value -replace "'", "''") + "'"
}

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path

if ($WriteDirs.Count -eq 0) {
  # Agent A backward-compatible default: require the override input dirs to exist and
  # grant write only to the proposals dir. Behavior identical to the pre-generalization
  # script when no -WriteDirs is supplied.
  $AnchorsDir = Join-Path $RepoRoot 'data\overrides\identifier_anchors'
  $GrammarsDir = Join-Path $RepoRoot 'data\overrides\identifier_rate_grammars'
  foreach ($Path in @($AnchorsDir, $GrammarsDir)) {
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
      throw "Required override directory does not exist: $Path"
    }
  }
  $WriteDirs = @(Join-Path $RepoRoot 'data\output\agent_a\proposals')
}

New-Item -ItemType Directory -Force -Path (@($WorkerHome, $WorkerRunroot) + $WriteDirs) | Out-Null

$ConfigPath = Join-Path $WorkerHome 'config.toml'

# Compose the filesystem grant lines as one block so optional read/write grants never
# leave a stray blank line. Resolve extra dirs; skip nonexistent ones. TOML rejects
# duplicate keys, so de-dupe exact paths and let write grants override read grants.
$ResolvedReadDirs = @($ReadDirs | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
  ForEach-Object { (Resolve-Path -LiteralPath $_ -ErrorAction SilentlyContinue).Path } |
  Where-Object { $_ } | Select-Object -Unique)
$ResolvedWriteDirs = @($WriteDirs | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
  ForEach-Object { (Resolve-Path -LiteralPath $_ -ErrorAction SilentlyContinue).Path } |
  Where-Object { $_ } | Select-Object -Unique)
$WriteSet = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
foreach ($Path in $ResolvedWriteDirs) { [void]$WriteSet.Add($Path) }
$SeenReads = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
$ReadGrantPaths = @($WorkerRunroot, $RepoRoot) + $ResolvedReadDirs
$ReadOnlyDirs = @()
foreach ($Path in $ReadGrantPaths) {
  if ([string]::IsNullOrWhiteSpace($Path)) { continue }
  $Resolved = (Resolve-Path -LiteralPath $Path -ErrorAction SilentlyContinue).Path
  if (-not $Resolved) { continue }
  if ($WriteSet.Contains($Resolved)) { continue }
  if ($SeenReads.Add($Resolved)) { $ReadOnlyDirs += $Resolved }
}
$FsLines = @(
  '":minimal" = "read"'
)
$FsLines += ($ReadOnlyDirs | ForEach-Object { "$(ConvertTo-TomlLiteralKey $_) = ""read""" })
$FsLines += ($ResolvedWriteDirs | ForEach-Object { "$(ConvertTo-TomlLiteralKey $_) = ""write""" })
$FsLines += @('":tmpdir" = "deny"', '":slash_tmp" = "deny"')
$FsBlock = $FsLines -join "`n"

# Worker env: never write .pyc; disable the user site UNLESS the caller needs it (Agent B,
# when the project deps are pip-installed into the user site rather than the env).
$EnvSet = if ($AllowUserSite) {
  '{ PYTHONDONTWRITEBYTECODE = "1" }'
} else {
  '{ PYTHONDONTWRITEBYTECODE = "1", PYTHONNOUSERSITE = "1" }'
}

$Config = @"
approval_policy = "never"
default_permissions = "pm_worker"
web_search = "disabled"
project_root_markers = []
# Emit model-written reasoning summaries into the persisted rollout trace (live-verified
# 2026-08-20, worker_home3 in the canary batch). Raw chain-of-thought stays encrypted;
# summaries are headline-to-paragraph digests per reasoning burst. TOML: this key MUST
# stay above the first [table] header or it lands inside that table and --strict-config
# rejects the file.
model_reasoning_summary = "detailed"

[windows]
sandbox = "elevated"

[shell_environment_policy]
inherit = "$EnvInherit"
set = $EnvSet

[permissions.pm_worker.filesystem]
$FsBlock
"@

Set-Content -LiteralPath $ConfigPath -Value $Config -Encoding ASCII

[pscustomobject]@{
  WorkerHome = $WorkerHome
  WorkerRunroot = $WorkerRunroot
  WriteDirs = $WriteDirs
  ConfigPath = $ConfigPath
}
