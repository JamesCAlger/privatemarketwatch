param(
  [string] $BatchId = "trial10",          # keep SHORT (feeds worker-home paths; MAX_PATH)
  [int] $N = 10,
  [string] $ExcludeCik = "1715933,1603480,1743415",
  [string] $ExcludeBatch = "canary_b1_to_b2_20260626T125839Z",
  [int] $TimeoutMinutes = 45,
  [int] $MaxParallel = 2,
  [switch] $SkipBuild,                     # reuse an existing worklist
  [switch] $SkipB1,                        # verdicts already exist -> skip B1 dispatch
  [switch] $SkipChain
)

# Run the full B1 -> B2 -> anchor -> B2 chain on N fresh cohort CIKs:
#   1. build a B1 batch worklist from EXISTING fv_conservation bundles (no review-queue rebuild)
#   2. dispatch B1 (adjudicate real_error / mechanism)
#   3. run the full remediation chain (B2 fix -> anchor adjudicator -> B2 re-fix)
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

# --- 1. Build the B1 batch worklist from existing bundles (idempotent) ---
if (-not $SkipBuild) {
  Write-Host "================ BUILD B1 BATCH ($BatchId) ================"
  $build = & python -m scripts.build_b1_batch_from_bundles --batch-id $BatchId --n $N `
    --exclude-cik $ExcludeCik --exclude-batch $ExcludeBatch
  if ($LASTEXITCODE -ne 0) { throw "build failed: $($build -join [Environment]::NewLine)" }
  Write-Host ($build | Out-String).Trim()
}
$wl = Join-Path $root "data/output/agent_b/batch/$BatchId/worklist.csv"
if (-not (Test-Path -LiteralPath $wl -PathType Leaf)) { throw "B1 worklist missing: $wl" }

# --- 2. Dispatch B1 (adjudicate). Skip when verdicts already exist (-SkipB1). ---
if (-not $SkipB1) {
  Write-Host "================ B1 ADJUDICATION ================"
  & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "dispatch_agent_b_workers.ps1") `
    -BatchId $BatchId -MaxParallel $MaxParallel -TimeoutMinutes $TimeoutMinutes
  if ($LASTEXITCODE -ne 0) { Write-Host "[warn] B1 dispatch returned $LASTEXITCODE (verdicts may already exist; use -SkipB1)" }
} else { Write-Host "[skip] B1 dispatch (verdicts already exist for batch $BatchId)" }

# --- 3. Full remediation chain (B2 -> anchor -> B2) ---
if (-not $SkipChain) {
  Write-Host "================ REMEDIATION CHAIN ================"
  & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "run_full_remediation_canary.ps1") `
    -B1BatchId $BatchId -TimeoutMinutes $TimeoutMinutes
  if ($LASTEXITCODE -ne 0) { Write-Host "[warn] chain returned $LASTEXITCODE" }
} else { Write-Host "[skip] chain" }

Write-Host "================ DONE ($BatchId) ================"
Write-Host "B1 worklist:       data/output/agent_b/batch/$BatchId/worklist.csv"
Write-Host "B2 stage-3 gates:  data/output/agent_investigate/batch/investigate_$BatchId/b3_gate_summary_stage3.csv"
Write-Host "Stage-1 B2 gates:  data/output/agent_investigate/batch/investigate_$BatchId/b3_gate_summary.csv"
Write-Host "Anchor overrides:  data/overrides/agent_anchor/<cik>/<quarter>.json"
