# Build funds in a fresh fund sandbox, from cached inputs only (no network), ending in a ledger.
#   bash scripts/v05_evidence/build_fund.sh <label> [--add-quarter YYYY-MM-DD] <cik> [<cik> ...]
# --add-quarter: a quarter downloaded after the last published build (the first ten funds have
# 2026-06-30 on disk). Without it the build ends at the last published quarter.
# Refuses to start while another Python process runs: one build at a time, no edits while it runs.
# Log: scratch/fund_runs/<label>.log. Last line of a complete run: CHAIN_DONE.
set -e
cd "$(dirname "$0")/../.."
L="$1"; shift
Q=""
if [ "$1" = "--add-quarter" ]; then Q="$2"; shift; shift; fi
C="$@"
if [ -z "$L" ] || [ -z "$C" ]; then echo "usage: build_fund.sh <label> [--add-quarter YYYY-MM-DD] <cik> ..."; exit 2; fi
if [ -e "scratch/fund_sandbox/$L" ]; then echo "sandbox $L exists: use a new label"; exit 2; fi
# The SDK fund loop (scripts/sdk_loop) is itself a Python process and passes its PID: only that one
# process is ignored; any other Python process still blocks the build.
if [ -n "$SDK_LOOP_DRIVER_PID" ]; then
  RUNNING=$(tasklist //FO CSV //NH | grep -i "python" | grep -v "^\"[^\"]*\",\"$SDK_LOOP_DRIVER_PID\"," || true)
else
  RUNNING=$(tasklist | grep -i "python" || true)
fi
if [ -n "$RUNNING" ]; then echo "a Python process is running: not started"; exit 3; fi
mkdir -p scratch/fund_runs
# No model call from a sandbox build: industry labels come from the page and the cache only.
export OPENAI_API_KEY=
LOG="scratch/fund_runs/$L.log"
{
  python scripts/fund_ledger_trial.py --label $L --ciks $C --until highlights
  if [ -n "$Q" ]; then
    PM_OUTPUT_DIR="scratch/fund_sandbox/$L/output" python scripts/sandbox_add_quarter.py --quarter $Q
  else
    PM_OUTPUT_DIR="scratch/fund_sandbox/$L/output" python scripts/rebuild_outputs.py --bdc-holdings --ciks $C --income --derivatives --sector-breakdown
    PM_OUTPUT_DIR="scratch/fund_sandbox/$L/output" python scripts/v05_evidence/pik_evidence.py
  fi
  python scripts/fund_ledger_trial.py --label $L --from highlights --until highlights
  PM_OUTPUT_DIR="scratch/fund_sandbox/$L/output" python scripts/refresh_ixbrl_field_status.py --ciks $C
  python scripts/fund_ledger_trial.py --label $L --from financials
  echo CHAIN_DONE
} > "$LOG" 2>&1
grep -E "exit [0-9]+|ledger for|CHAIN_DONE|Traceback" "$LOG" | cut -c1-120
