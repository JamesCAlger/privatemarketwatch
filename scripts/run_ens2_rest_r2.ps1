# run_ens2_rest_r2.ps1
# Resumes the ens2_rest run after a partial first attempt left 9 decided verdicts on disk
# (B1 preflight aborts with PRECHECK_FAIL on any pre-existing verdict). prep_retry keeps
# the decided verdicts, emits the still-undecided rids as a FRESH batch (ens2_rest_r2),
# then we discover + dispatch only those. The full-ens2 analysis reads all verdicts by
# review_id, so the kept decisions still count.
#
# REQUIREMENTS: elevated PowerShell; only Codex fleet on the machine; MaxParallel <= 2.
# A FRESH batch id (ens2_rest_r2) means fresh worker_home dirs -> no stale setup markers.

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

# --- 1. prep_retry: keep decided verdicts, emit undecided rids as ens2_rest_r2 ----------
# Read-only on the queue except deleting genuinely-failed verdicts (none expected here).
Write-Host "[1/5] prep_retry ens2_rest -> ens2_rest_r2..." -ForegroundColor Cyan
python -m scripts.ensemble.prep_retry --src ens2_rest --retry ens2_rest_r2
Assert-LastExit "prep_retry ens2_rest"

# --- 2. discover the retry batch (its own worklist; reuses shared bundles by review_id) --
Write-Host "[2/5] discover ens2_rest_r2..." -ForegroundColor Cyan
python -m scripts.agent_b.run_review discover ens2_rest_r2 --review-ids-from data/output/ensemble/ens2_rest_r2/review_ids.csv
Assert-LastExit "discover ens2_rest_r2"

# --- 3. dispatch (long step). Dispatcher signals failure by THROWING, not exit code ------
Write-Host "[3/5] dispatch ens2_rest_r2 (MaxParallel 2)... long step. Watch the first ~20 verdicts for no_source." -ForegroundColor Cyan
try {
    .\scripts\dispatch_agent_b_workers.ps1 -BatchId ens2_rest_r2 -MaxParallel 2
} catch {
    Write-Host "FAILED: dispatch ens2_rest_r2 threw." -ForegroundColor Red
    Write-Host "  $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "  PRECHECK_FAIL again -> a worker wrote more verdicts; re-run this script (prep_retry will re-split)." -ForegroundColor Yellow
    Write-Host "  Stale worker-home markers / 1326 -> bump to a fresh id (ens2_rest_r3)." -ForegroundColor Yellow
    exit 1
}

# --- 4. strip BOM from the FULL ens2 verdicts (finalize/analyze need clean utf-8) --------
Write-Host "[4/5] strip verdict BOM for full ens2..." -ForegroundColor Cyan
python -m scripts.ensemble.strip_verdict_bom --batch-id ens2
Assert-LastExit "strip_verdict_bom ens2"

# --- 5. analyze the FULL ens2 (pilot + rest + the 9 kept, shared by review_id) -----------
Write-Host "[5/5] analyze full ens2..." -ForegroundColor Cyan
python -m scripts.ensemble.analyze_ensemble --batch-id ens2
Assert-LastExit "analyze_ensemble ens2"

Write-Host ""
Write-Host "DONE. Read:" -ForegroundColor Green
Write-Host "  data\output\ensemble\ens2\ensemble_summary.md"
Write-Host "  data\output\ensemble\ens2\per_rule_fp.csv"
Write-Host "  data\output\ensemble\ens2\ensemble_by_degree.csv"
Write-Host "  data\output\ensemble\ens2\rule_lift.csv"
