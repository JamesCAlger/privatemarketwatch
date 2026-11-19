# Scripts

Moved from AGENTS.md on 2026-11-12. Run a script with `--help` for its current flags.

| Script | Purpose | Usage |
|---|---|---|
| `scripts/rebuild_outputs.py` | Rebuild all output CSVs from cached data (no downloads). Use after running tests. | `python scripts/rebuild_outputs.py` (all), `--unified`, `--income`, `--returns` |
| `scripts/snapshot_outputs.py` | Refresh the active deterministic official baseline after approval. Archive the prior baseline first if retiring it. | `python scripts/snapshot_outputs.py --clean` |
| `scripts/diff_outputs.py` | Compare current outputs with the active official baseline, including generated SQL and optional semantic summaries. | `python scripts/diff_outputs.py --semantic` |
| `scripts/current_cache_phase6_parity.py` | One-off current-cache pre/post comparator for Phase 6-style refactor parity. Use named snapshots under `data/snapshots/`, not the official baseline. | `snapshot --clean --snapshot-dir ...`, `diff --semantic --snapshot-dir ...` |
| `scripts/learn_template.py` | Manage per-CIK HTML extraction templates. Auto-detect, validate, inspect, accept, batch revalidate. | `--auto-detect <CIK>`, `--auto-detect-all`, `--validate <CIK>`, `--validate-only <CIK>`, `--next`, `--inspect <CIK>`, `--accept <CIK> --justification "..."`, `--revalidate-all`, `--add-periods <CIK\|ALL>`, `--list` |
| `scripts/run_quarter_pass.py` | Staged quarter remediation pass: rebuild, oracle, validate, provenance re-verify, shadow rules, queue, ledger, preflight, packet selection. Writes to `data/output/quarter_pass/<pass_id>/`. | `--pass-id <id> --quarter YYYY-MM-DD [--from/--until <stage>] [--force] [--dry-run] [--list]` |
| `scripts/reattest_quarters.py` | Record and re-check attestations for signed-off quarters. Run `check` after any pipeline change that touches cohort holdings. | `attest --quarter Q --source <battery.json>`, `check [--quarter Q]` |
| `scripts/findings_ledger.py` | Findings lifecycle ledger: one state per finding across the review queue, verdicts and correction stores. Source of the `outstanding_findings` sign-off check. Read-only on production. | `python scripts/findings_ledger.py --out <csv> [--compare <prior.csv>]` |
| `scripts/shadow_validation_runner.py` | Run the shadow-rule engines (conservation, identity, cross-source, weak, Agent A) and emit the disposition ledger. Invoked by the quarter pass; runnable standalone. | `python scripts/shadow_validation_runner.py` |
| `scripts/run_codex_worker.ps1`, `scripts/dispatch_*_workers.ps1` | Sandboxed Codex worker fleets (Agent A / B / B2 / anchor / convention / investigation). Dispatch from an ADMIN PowerShell; MaxParallel ceiling is 2. See `docs/reference/codex_worker_dispatch.md`. | per-lane dispatch script |
| `scripts/backup_raw_to_r2.ps1` | Sync the raw EDGAR cache (optionally baselines) to Cloudflare R2 via rclone. Setup in `docs/reference/cloud_backup_setup.md`. | `.\scripts\backup_raw_to_r2.ps1` |
