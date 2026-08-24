param(
  [Parameter(Mandatory = $true)] [string] $Cik,
  [Parameter(Mandatory = $true)] [string] $TargetQuarter,
  [string] $BundlePath = "",
  [int] $TimeoutMinutes = 30,
  [switch] $PrepOnly,
  [switch] $AllowUnreviewedRawResidual,
  [switch] $B1Reviewed
)

# Agentic investigation dispatcher -- runs ONE Codex worker that investigates a conservation
# FV discrepancy for $Cik using the read-only data-query + evidence tools, and authors auditable
# rules. BYPASSES the deterministic B2 battery entirely. After the worker, the driver applies the
# authored rules to a trial and runs the B3 conservation gate. Run from an operator shell OUTSIDE
# a Codex session (conda-activated). Shares run_codex_worker.ps1 + setup_codex_worker_harness.ps1.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# Guard: this worker authors fixes. It is the INTENDED B2 path when the target came from B1
# (-B1Reviewed, as the investigation canary passes). Raw, un-adjudicated use stays gated behind
# -AllowUnreviewedRawResidual (diagnostics only).
if (-not ($AllowUnreviewedRawResidual -or $B1Reviewed)) {
  throw @"
dispatch_investigation.ps1 needs a B1-reviewed target. Run it via scripts/run_investigation_canary.ps1
(which discovers targets from a B1 batch and passes -B1Reviewed), or for diagnostics only rerun with
-AllowUnreviewedRawResidual.
"@
}

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
# Auth: the sandboxed worker gets a FRESH CODEX_HOME, so copy the operator's logged-in
# auth.json into it (or rely on CODEX_API_KEY). Without this the worker hits 401 Unauthorized.
$sourceAuth = Join-Path (Get-SourceCodexHome) "auth.json"
$hasFileAuth = Test-Path -LiteralPath $sourceAuth -PathType Leaf
$hasApiKey = -not [string]::IsNullOrWhiteSpace($env:CODEX_API_KEY)
if (-not ($hasFileAuth -or $hasApiKey)) {
  throw "No Codex auth found. Run 'codex login' (creates $sourceAuth) or set CODEX_API_KEY."
}

$cikNorm = $Cik.TrimStart('0')

$base = Join-Path $root "data/output/agent_investigate/$cikNorm"
$rulesDir = Join-Path $base "rules"
$promptPath = Join-Path $base "prompt.md"
$workerHome = Join-Path $base "worker_home"
# The worker's project dir (codex -C / apply_patch boundary) = the cik dir, so the rules/
# subdir is INSIDE the boundary and the agent can write its rule there.
$workerRunroot = $base
$setup = Join-Path $PSScriptRoot "setup_codex_worker_harness.ps1"
$runner = Join-Path $PSScriptRoot "run_codex_worker.ps1"
$MaxIter = 5

# Read grants: the repo root (CLIs + cached data, read-only) PLUS the worker interpreter's
# install + ALL site-packages roots (incl. the USER site, where pandas may live) -- or the
# worker can't import its deps and python exits 1. Use B1's canonical resolver, not an inline
# one-liner (which PowerShell quoting mangled to a partial list).
# Emit one path per line (not JSON) -- PowerShell captures that as a flat string[] with no
# array nesting; a JSON array via ConvertFrom-Json + `+` collapsed into one bogus element.
$pyDirs = @(& python -c "from scripts.agent_b.dispatch_preflight import _worker_read_dirs as w`nfor d in w(): print(d)")
$readGrants = @($root)
foreach ($d in $pyDirs) { $s = [string]$d; if ($s.Trim() -and -not ($readGrants -contains $s)) { $readGrants += $s } }
$logDir = Join-Path $base "logs"
New-Item -ItemType Directory -Force $logDir | Out-Null
Write-Host "[auth] using $(if ($hasFileAuth) { 'auth.json' } else { 'CODEX_API_KEY' })"
Write-Host "[grants] read ($($readGrants.Count)): $($readGrants -join ' ; ')"

# The investigate -> author -> apply -> gate loop. Each iteration re-prompts the agent with the
# residual + the last gate failure; stop when FV is within 1% or after $MaxIter iterations.
for ($i = 1; $i -le $MaxIter; $i++) {
  Write-Host "[iter $i] prep (residual fed back to the agent)"
  python -m scripts.agent_investigate.run_investigation prep --cik $Cik --target-quarter $TargetQuarter --iteration $i
  if (-not (Test-Path $promptPath)) { throw "prep did not produce a prompt at $promptPath" }
  if ($PrepOnly) { Write-Host "[prep-only] prompt at $promptPath ; rules dir $rulesDir"; return }

  # Sandbox: read the repo + interpreter; write ONLY this cik's scratch dir ($base) -- which
  # holds BOTH codex's runroot/session state AND the rules/ subdir (so the patch tool's project
  # boundary = $base includes rules, and codex can write its own runroot). Scoped per-cik.
  & $setup -WorkerHome $workerHome -WorkerRunroot $workerRunroot -WriteDirs @($base) `
    -ReadDirs $readGrants -EnvInherit all -AllowUserSite
  # Copy the operator's auth into the fresh worker home so the worker can authenticate.
  if ($hasFileAuth) {
    Copy-Item -LiteralPath $sourceAuth -Destination (Join-Path $workerHome "auth.json") -Force
  }

  # Capture the worker's JSON trace to a file (so the console stays clean and the trace is
  # readable after the fact); show only the tail.
  $log = Join-Path $logDir "iter$i.trace.jsonl"
  Write-Host "[iter $i] running Codex (trace -> $log)"
  & $runner -PromptPath $promptPath -WorkerHome $workerHome -WorkerRunroot $workerRunroot -NoSetup `
    -TraceDir $logDir -TracePrefix "iter${i}__" *> $log
  $workerExit = $LASTEXITCODE
  Write-Host "---- iter $i trace tail ----"
  Get-Content $log -Tail 8
  if ($null -ne $workerExit -and $workerExit -ne 0) {
    throw "Codex worker exited $workerExit; see $log"
  }

  Write-Host "[iter $i] apply + status (stop at <=1% FV match + gate PASS)"
  $statusJson = python -m scripts.agent_investigate.run_investigation status --cik $Cik --target-quarter $TargetQuarter --iteration $i
  Write-Host $statusJson
  $status = $statusJson | ConvertFrom-Json
  if ($status.decision.stop) {
    Write-Host "[stop] $($status.decision.reason)  (success=$($status.decision.success))"
    break
  }
}
Write-Host "[done] see $base (rules/, corrected_holdings, manifest.json)"
