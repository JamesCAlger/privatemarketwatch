# run_ens2_rest_r3.ps1
# Resumes the ens2_rest run after the r2 attempt aborted on a Codex USAGE LIMIT.
# The r2 dispatch decided ~6 verdicts before the account quota was exhausted; the
# rest are still undecided. prep_retry keeps the decided verdicts (shared globally
# by review_id, so the r2 decisions still count) and emits the still-undecided rids
# as a FRESH batch (ens2_rest_r3), which we discover + dispatch at MaxParallel 1.
#
# Why a fresh batch id (r3, not re-running r2):
#   - r2's worker_home dirs already exist -> stale codex setup markers if reused.
#   - A new id gives every worker a clean worker_home (no marker race).
# Why MaxParallel 1: single-worker dispatch avoids the auth/password copy race.
#
# PREREQ FOR SUCCESS: the Codex quota that tripped the r2 circuit breaker must have
# reset (or credits added). Check the reset time in any r2 worker stdout under
#   data\output\agent_b\batch\ens2_rest_r2\logs\*.stdout.jsonl
# If the quota is still capped, the dispatcher's circuit breaker will abort again
# after the FIRST worker -- fast and cheap, but no progress.
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

# --- 1. prep_retry: keep decided verdicts, emit undecided rids as ens2_rest_r3 ----------
Write-Host "[1/5] prep_retry ens2_rest_r2 -> ens2_rest_r3..." -ForegroundColor Cyan
python -m scripts.ensemble.prep_retry --src ens2_rest_r2 --retry ens2_rest_r3
Assert-LastExit "prep_retry ens2_rest_r2"

# --- 2. discover the retry batch (its own worklist; reuses shared bundles by review_id) --
Write-Host "[2/5] discover ens2_rest_r3..." -ForegroundColor Cyan
python -m scripts.agent_b.run_review discover ens2_rest_r3 --review-ids-from data/output/ensemble/ens2_rest_r3/review_ids.csv
Assert-LastExit "discover ens2_rest_r3"

# --- 3. dispatch (long step). MaxParallel 1. Circuit breaker aborts fast on usage limit -
Write-Host "[3/5] dispatch ens2_rest_r3 (MaxParallel 1)... long step. Watch the first ~20 verdicts." -ForegroundColor Cyan
try {
    .\scripts\dispatch_agent_b_workers.ps1 -BatchId ens2_rest_r3 -MaxParallel 1
} catch {
    Write-Host "FAILED: dispatch ens2_rest_r3 threw." -ForegroundColor Red
    Write-Host "  $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "  If the message says USAGE LIMIT: the Codex quota is still capped. Wait for reset" -ForegroundColor Yellow
    Write-Host "  or add credits, then re-run THIS script (prep_retry will re-split into r4)." -ForegroundColor Yellow
    Write-Host "  If it says PRECHECK_FAIL: a worker wrote more verdicts; re-run this script." -ForegroundColor Yellow
    Write-Host "  If it mentions stale worker-home markers: bump to a fresh id (ens2_rest_r4)." -ForegroundColor Yellow
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
