# run_ens2_rest.ps1
# Runs the remaining 812 adjudications of the ensemble FP experiment (batch ens2_rest),
# then analyzes the FULL ens2 batch (pilot + rest share verdicts by review_id).
#
# REQUIREMENTS:
#   - Run from an ELEVATED PowerShell (codex workers run elevated; a non-elevated
#     shell cannot manage/kill them).
#   - This must be the ONLY Codex fleet on the machine.
#   - MaxParallel stays at 2 (the shared-account password race breaks at >2).
#
# Kill: Ctrl-C in THIS terminal stops the dispatch loop. In-flight elevated workers
# may need `taskkill /F /PID ...` from an elevated shell, or a machine restart.

$ErrorActionPreference = 'Stop'
Set-Location "C:\Users\alger\Documents\000. Projects\005. evergreen funds platform xbrl"

function Assert-LastExit($label) {
    if ($LASTEXITCODE -ne 0) {
        Write-Host "FAILED: $label (exit $LASTEXITCODE)" -ForegroundColor Red
        exit $LASTEXITCODE
    }
}

# --- 0. Sanity: elevation + no codex already running -------------------------
$isAdmin = ([Security.Principal.WindowsPrincipal] `
    [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltinRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "ERROR: not elevated. Re-launch PowerShell as Administrator." -ForegroundColor Red
    exit 1
}

$running = Get-Process -Name codex* -ErrorAction SilentlyContinue
if ($running) {
    Write-Host "ERROR: codex already running (PIDs: $($running.Id -join ', ')). Only one fleet at a time." -ForegroundColor Red
    exit 1
}
Write-Host "[0/4] Elevated, no codex running. OK." -ForegroundColor Green

# --- 1. Discover the ens2_rest batch (builds its own worklist) ---------------
# Discover is per-batch-id: dispatch reads batch/<id>/worklist.csv. Discover the
# SAME id you dispatch. Bundles are keyed by review_id, so this reuses existing ones.
Write-Host "[1/4] discover ens2_rest..." -ForegroundColor Cyan
python -m scripts.agent_b.run_review discover ens2_rest --review-ids-from data/output/ensemble/ens2_rest/review_ids.csv
Assert-LastExit "discover ens2_rest"

# --- 2. Dispatch the 812 (long-running; watch the first ~20 verdicts) --------
# The dispatcher does NOT signal failure via exit code: it aggregates per-worker
# failures (non-zero exit / timeout / verdict-validation fail) and THROWS a terminating
# error, writing dispatch_failures.txt. The try/catch below converts that throw into a
# clean stop. NOTE: a no_source CASCADE is not a dispatcher failure (no_source verdicts
# are schema-valid), so it will NOT be caught here -- watch the first ~20 verdicts and
# Ctrl-C if no_source climbs before burning the whole batch.
Write-Host "[2/4] dispatch ens2_rest (MaxParallel 2)... this is the long step." -ForegroundColor Cyan
try {
    .\scripts\dispatch_agent_b_workers.ps1 -BatchId ens2_rest -MaxParallel 2
} catch {
    Write-Host "FAILED: dispatch ens2_rest threw." -ForegroundColor Red
    Write-Host "  $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "  See data\output\agent_b\batch\ens2_rest\dispatch_failures.txt" -ForegroundColor Red
    Write-Host "  Stale worker-home markers? Re-run as a FRESH batch id (e.g. ens2_rest_r2)." -ForegroundColor Yellow
    exit 1
}

# --- 3. Strip BOM from the FULL ens2 verdicts (finalize/analyze need clean utf-8)
Write-Host "[3/4] strip verdict BOM for full ens2..." -ForegroundColor Cyan
python -m scripts.ensemble.strip_verdict_bom --batch-id ens2
Assert-LastExit "strip_verdict_bom ens2"

# --- 4. Analyze the FULL ens2 (pilot + rest, shared verdicts by review_id) ----
Write-Host "[4/4] analyze full ens2..." -ForegroundColor Cyan
python -m scripts.ensemble.analyze_ensemble --batch-id ens2
Assert-LastExit "analyze_ensemble ens2"

Write-Host ""
Write-Host "DONE. Read:" -ForegroundColor Green
Write-Host "  data\output\ensemble\ens2\ensemble_summary.md"
Write-Host "  data\output\ensemble\ens2\per_rule_fp.csv"
Write-Host "  data\output\ensemble\ens2\ensemble_by_degree.csv"
Write-Host "  data\output\ensemble\ens2\rule_lift.csv"
