# v0.5 evidence scripts

Read-only checks cited as re-run commands by `docs/investigations/v05_decision_log.md` and by the
standing dispositions in `data/overrides/finding_dispositions/`. Each reads a fund sandbox built by
`scripts/fund_ledger_trial.py --label <label> --ciks <ciks>` (under `scratch/fund_sandbox/`, not
tracked) or the cached filings. None writes to published data.

`make_dispositions.py <label> --write` regenerates the dispositions file from a sandbox ledger.
