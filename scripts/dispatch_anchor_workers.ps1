param(
  [Parameter(Mandatory = $true)] [string] $Cik,
  [Parameter(Mandatory = $true)] [string] $TargetQuarter,
  [string] $BundlePath = "",
  [int] $TimeoutMinutes = 20,
  [int] $MaxAttempts = 2,
  [switch] $PrepOnly
)

# Anchor-adjudicator dispatcher -- runs ONE Codex worker that finds this filer's GRAND total of
# investments at fair value (the independent pre-pass), writes an anchor leaf, then the driver
# VERIFIES it against the balance sheet and promotes it to the per-cik override the B2 fixer reads.
# Mirrors dispatch_investigation.ps1 (shared sandbox harness). Run OUTSIDE a Codex session.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Assert-OutsideCodexSession {
  $sig = @("CODEX_THREAD_ID", "CODEX_MANAGED_BY_NPM", "CODEX_MANAGED_PACKAGE_ROOT") |
    Where-Object { -not [string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($_)) }
  if ($sig.Count -gt 0) { throw "Refusing to dispatch a Codex worker from inside a Codex session: $($sig -join ', ')" }
}
Assert-OutsideCodexSession

function Get-SourceCodexHome {
  if (-not [string]::IsNullOrWhiteSpace($env:CODEX_HOME)) { return $env:CODEX_HOME }
  return Join-Path $HOME ".codex"
}
$sourceAuth = Join-Path (Get-SourceCodexHome) "auth.json"
$hasFileAuth = Test-Path -LiteralPath $sourceAuth -PathType Leaf
$hasApiKey = -not [string]::IsNullOrWhiteSpace($env:CODEX_API_KEY)
if (-not ($hasFileAuth -or $hasApiKey)) {
  throw "No Codex auth found. Run 'codex login' (creates $sourceAuth) or set CODEX_API_KEY."
}

$cikNorm = $Cik.TrimStart('0')
$base = Join-Path $root "data/output/agent_anchor/$cikNorm"
$leafPath = Join-Path $base "leaf/anchor.$TargetQuarter.json"
$promptPath = Join-Path $base "prompt.$TargetQuarter.md"
$workerHome = Join-Path $base "worker_home"
$workerRunroot = $base
$setup = Join-Path $PSScriptRoot "setup_codex_worker_harness.ps1"
$runner = Join-Path $PSScriptRoot "run_codex_worker.ps1"

# Read grants: repo root + the worker interpreter's site-packages (B1's canonical resolver).
$pyDirs = @(& python -c "from scripts.agent_b.dispatch_preflight import _worker_read_dirs as w`nfor d in w(): print(d)")
$readGrants = @($root)
foreach ($d in $pyDirs) { $s = [string]$d; if ($s.Trim() -and -not ($readGrants -contains $s)) { $readGrants += $s } }
$logDir = Join-Path $base "logs"
New-Item -ItemType Directory -Force $logDir | Out-Null
Write-Host "[auth] using $(if ($hasFileAuth) { 'auth.json' } else { 'CODEX_API_KEY' })"

for ($i = 1; $i -le $MaxAttempts; $i++) {
  Write-Host "[attempt $i] prep"
  python -m scripts.agent_anchor.run_anchor prep --cik $Cik --target-quarter $TargetQuarter
  if (-not (Test-Path $promptPath)) { throw "prep did not produce a prompt at $promptPath" }
  if ($PrepOnly) { Write-Host "[prep-only] prompt at $promptPath ; leaf -> $leafPath"; return }

  & $setup -WorkerHome $workerHome -WorkerRunroot $workerRunroot -WriteDirs @($base) `
    -ReadDirs $readGrants -EnvInherit all -AllowUserSite
  if ($hasFileAuth) {
    Copy-Item -LiteralPath $sourceAuth -Destination (Join-Path $workerHome "auth.json") -Force
  }

  $log = Join-Path $logDir "attempt$i.trace.jsonl"
  Write-Host "[attempt $i] running Codex (trace -> $log)"
  & $runner -PromptPath $promptPath -WorkerHome $workerHome -WorkerRunroot $workerRunroot -NoSetup *> $log
  $workerExit = $LASTEXITCODE
  Get-Content $log -Tail 6
  if ($null -ne $workerExit -and $workerExit -ne 0) { throw "Codex worker exited $workerExit; see $log" }

  Write-Host "[attempt $i] verify (schema + balance-sheet closure)"
  $verifyJson = python -m scripts.agent_anchor.run_anchor verify --cik $Cik --target-quarter $TargetQuarter
  Write-Host $verifyJson
  $verify = $verifyJson | ConvertFrom-Json
  if ($verify.ok) {
    Write-Host "[promote] anchor verified (tier=$($verify.tier)) -> writing per-cik override"
    python -m scripts.agent_anchor.run_anchor promote --cik $Cik --target-quarter $TargetQuarter
    break
  }
  Write-Host "[attempt $i] anchor NOT verified (tier=$($verify.tier)); retry if attempts remain"
}
Write-Host "[done] see $base (leaf/, manifest, logs); override (if promoted) in data/overrides/agent_anchor/$cikNorm"
