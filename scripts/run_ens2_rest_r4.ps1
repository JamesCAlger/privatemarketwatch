# run_ens2_rest_r4.ps1
# Resumes ens2_rest after the r3 dispatch left ONE unit undecided.
# r3 decided 630/631 review units. The last worker (RVQ_REV_6c111fabc639,
# CIK 0001742313 2024-12-31 X07) died on a Windows sandbox stale worker-home
# marker (setup_marker.json already existed -> create failed with error 80).
# That is NOT a usage-limit or precheck failure -- the fix per the dispatcher's
# own error text is to bump to a FRESH batch id so the unit gets a clean
# worker_home (no marker race).
#
# prep_retry keeps the 630 decided verdicts (shared globally by review_id) and
# emits only the still-undecided rid(s) as a fresh batch (ens2_rest_r4), which we
# discover + dispatch at MaxParallel 1. Expect r4 to dispatch a single worker.
#
# REQUIREMENTS: elevated PowerShell; only Codex fleet on the machine.

$ErrorActionPreference = 'Stop'
Set-Location "C:\Users\alger\Documents\000. Projects\005. evergreen funds platform xbrl"

function Assert-LastExit($label) {
    if ($LASTEXITCODE -ne 0) {
        Write-Host "FAILED: $label (exit $LASTEXITCODE)" -ForegroundColor Red
        exit $LASTEXITCODE
    }
}

# --- 0. Sanity: elevation + no codex running (prep_retry mutates shared verdicts dir) ---
$isAdmin = ([Security.Principal.WindowsPrincipal] `
    [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltinRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "ERROR: not elevated. Re-launch PowerShell as Administrator." -ForegroundColor Red
    exit 1
}
$running = Get-Process -Name codex* -ErrorAction SilentlyContinue
if ($running) {
    Write-Host "ERROR: codex still running (PIDs: $($running.Id -join ', ')). Stop the fleet before prep_retry." -ForegroundColor Red
    exit 1
}
Write-Host "[0/5] Elevated, no codex running. OK." -ForegroundColor Green

# --- 1. prep_retry: keep decided verdicts, emit undecided rids as ens2_rest_r4 ----------
Write-Host "[1/5] prep_retry ens2_rest_r3 -> ens2_rest_r4..." -ForegroundColor Cyan
python -m scripts.ensemble.prep_retry --src ens2_rest_r3 --retry ens2_rest_r4
Assert-LastExit "prep_retry ens2_rest_r3"

# --- 2. discover the retry batch (its own worklist; reuses shared bundles by review_id) --
Write-Host "[2/5] discover ens2_rest_r4..." -ForegroundColor Cyan
python -m scripts.agent_b.run_review discover ens2_rest_r4 --review-ids-from data/output/ensemble/ens2_rest_r4/review_ids.csv
Assert-LastExit "discover ens2_rest_r4"

# --- 3. dispatch (short; expect 1 worker). MaxParallel 1. --------------------------------
Write-Host "[3/5] dispatch ens2_rest_r4 (MaxParallel 1)... expect a single worker." -ForegroundColor Cyan
try {
    .\scripts\dispatch_agent_b_workers.ps1 -BatchId ens2_rest_r4 -MaxParallel 1
} catch {
    Write-Host "FAILED: dispatch ens2_rest_r4 threw." -ForegroundColor Red
    Write-Host "  $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "  If the message says USAGE LIMIT: the Codex quota is capped. Wait for reset" -ForegroundColor Yellow
    Write-Host "  or add credits, then re-run THIS script (prep_retry re-splits into the same r4)." -ForegroundColor Yellow
    Write-Host "  If it says PRECHECK_FAIL: a worker wrote more verdicts; re-run this script." -ForegroundColor Yellow
    Write-Host "  If it mentions stale worker-home markers AGAIN: bump to a fresh id (ens2_rest_r5)." -ForegroundColor Yellow
    exit 1
}

# --- 4. strip BOM from the FULL ens2 verdicts (finalize/analyze need clean utf-8) --------
Write-Host "[4/5] strip verdict BOM for full ens2..." -ForegroundColor Cyan
python -m scripts.ensemble.strip_verdict_bom --batch-id ens2
Assert-LastExit "strip_verdict_bom ens2"

# --- 5. analyze the FULL ens2 (pilot + rest + all kept decisions, shared by review_id) ---
Write-Host "[5/5] analyze full ens2..." -ForegroundColor Cyan
python -m scripts.ensemble.analyze_ensemble --batch-id ens2
Assert-LastExit "analyze_ensemble ens2"

Write-Host ""
Write-Host "DONE. Read:" -ForegroundColor Green
Write-Host "  data\output\ensemble\ens2\ensemble_summary.md"
Write-Host "  data\output\ensemble\ens2\per_rule_fp.csv"
Write-Host "  data\output\ensemble\ens2\ensemble_by_degree.csv"
Write-Host "  data\output\ensemble\ens2\rule_lift.csv"
