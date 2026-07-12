param(
  [int] $N = 1,
  [string] $BatchId = "",                  # default: fresh<N>
  [string] $ExcludeCik = "1715933,1603480,1743415,1920453,2052153,1633336,1742313,1792509,1851322,1860424,1899017,1905824,1930679,1965934,1837532,1377936",
  [int] $TimeoutMinutes = 45,
  [int] $MaxParallel = 2,
  [switch] $IncludeNullAnchor,              # (b) include companyfacts-less quarters (anchor from filing)
  [switch] $SkipB1,
  [switch] $SkipChain
)

# Run the full B1 -> B2 -> anchor -> B2 chain on N FRESH cohort CIKs (no existing bundle):
#   1. prepare: select N fresh CIKs from the review queue, GENERATE their bundles, build the B1
#      worklist (anchorable-only; null-anchor quarters deferred + logged)
#   2. B1 adjudicate (fresh CIKs have no verdict yet)
#   3. full remediation chain (B2 fix -> anchor adjudicator -> B2 re-fix)
# Run from an operator shell OUTSIDE a Codex session (conda-activated, `codex login` done).

$ErrorActionPreference = "Stop"
function Assert-OutsideCodexSession {
  $sig = @("CODEX_THREAD_ID", "CODEX_MANAGED_BY_NPM", "CODEX_MANAGED_PACKAGE_ROOT") |
    Where-Object { -not [string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($_)) }
  if ($sig.Count -gt 0) { throw "Refusing to dispatch Codex workers from inside a Codex session: $($sig -join ', ')" }
}
Assert-OutsideCodexSession

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
if ([string]::IsNullOrWhiteSpace($BatchId)) { $BatchId = "fresh$N" }   # keep SHORT (MAX_PATH)

# --- 1. Prepare: select fresh CIKs, generate bundles, build the B1 worklist ---
Write-Host "================ PREPARE FRESH BATCH ($BatchId, N=$N) ================"
$prepArgs = @("-m", "scripts.prepare_fresh_batch", "--batch-id", $BatchId, "--n", [string]$N, "--exclude-cik", $ExcludeCik)
if ($IncludeNullAnchor) { $prepArgs += "--include-null-anchor" }
$prep = & python @prepArgs
if ($LASTEXITCODE -ne 0) { throw "prepare failed: $($prep -join [Environment]::NewLine)" }
$prepText = ($prep | Out-String).Trim()
Write-Host $prepText
$prepObj = $prepText | ConvertFrom-Json
if ($prepObj.status -ne "ok") { throw "prepare status: $($prepObj.status)" }
$wl = Join-Path $root "data/output/agent_b/batch/$BatchId/worklist.csv"
if (-not (Test-Path -LiteralPath $wl -PathType Leaf)) { throw "B1 worklist missing: $wl" }

# --- 2. B1 adjudicate (fresh CIKs have no verdict) ---
if (-not $SkipB1) {
  Write-Host "================ B1 ADJUDICATION ================"
  & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "dispatch_agent_b_workers.ps1") `
    -BatchId $BatchId -MaxParallel $MaxParallel -TimeoutMinutes $TimeoutMinutes
  if ($LASTEXITCODE -ne 0) { Write-Host "[warn] B1 dispatch returned $LASTEXITCODE" }
} else { Write-Host "[skip] B1 dispatch" }

# --- 3. Full remediation chain (B2 -> anchor -> B2) ---
if (-not $SkipChain) {
  Write-Host "================ REMEDIATION CHAIN ================"
  & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "run_full_remediation_canary.ps1") `
    -B1BatchId $BatchId -TimeoutMinutes $TimeoutMinutes
  if ($LASTEXITCODE -ne 0) { Write-Host "[warn] chain returned $LASTEXITCODE" }
} else { Write-Host "[skip] chain" }

Write-Host "================ DONE ($BatchId) ================"
Write-Host "B1 worklist:       data/output/agent_b/batch/$BatchId/worklist.csv"
Write-Host "Stage-1 B2 gates:  data/output/agent_investigate/batch/investigate_$BatchId/b3_gate_summary.csv"
Write-Host "Stage-3 gates:     data/output/agent_investigate/batch/investigate_$BatchId/b3_gate_summary_stage3.csv"
Write-Host "Anchor overrides:  data/overrides/agent_anchor/<cik>/<quarter>.json"
