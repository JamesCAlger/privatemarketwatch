# Weak-rule False-Positive + Ensemble B1 Experiment

**Branch:** `ensemble-fp-experiment` (all code here is additive; Agent B1 is NOT modified).
**Status as of 2026-06-28 ~20:15 local.** Resume steps are in section 5.

---

## 1. Goal

Run Agent B1 (blinded per-flag adjudication) on a statistically representative sample of
the weak (review-lane) validation rules, to measure:

- **(i) per-rule false-positive (false_alarm) rate** — with Wilson 95% CIs.
- **(ii) ensemble signal** — whether multiple weak rules *co-firing* on the same
  fund-quarter unit is a better defect indicator than any single rule firing alone.

B1 adjudicates one flag per `review_id`, **blinded** to which other rules fired on the
same unit — which is exactly what we want: independent per-flag labels that we correlate
against co-firing structure afterward.

## 2. Design (decided with the user)

- **Frame:** unit-stratified. Sample fund-quarter units (cik, report_date), stratified by
  co-firing degree (d1=1 rule, d2_3, d4_7, d8plus), and adjudicate every in-scope weak
  flag on each sampled unit. Gives pooled per-rule FP rates AND the co-firing->precision
  relationship from one batch.
- **In-scope rules:** weak/review-lane rules with **>= 30 firings** in the queue (59 rules).
- **Budget:** "Standard" ~1,000 adjudications.
- **Drawn sample (`ens1`):** 260 units -> **1,008 adjudications**, 59 in-scope rules
  (53 got >=1 sampled flag; ~12 reach n>=30 for tight CIs).

## 3. Scripts (all on this branch, under `scripts/ensemble/`)

| Script | Purpose |
|---|---|
| `sample_units.py` | Unit-stratified sampler. `--profile` to inspect strata; default build writes `data/output/ensemble/<batch>/review_ids.csv` + `cofire_manifest.json`. `--pilot-of <batch>` splits a batch into a disjoint `<batch>_pilot` + `<batch>_rest`. |
| `analyze_ensemble.py` | Post-finalize analysis: `per_rule_fp.csv`, `ensemble_by_degree.csv`, `rule_lift.csv`, `ensemble_summary.md`. Reads the FULL batch's review_ids + shared verdicts. BOM-tolerant. |
| `strip_verdict_bom.py` | Removes UTF-8 BOM from a batch's verdict files (B1 finalize uses strict utf-8 and crashes on BOM). Run before `run_review finalize`. |
| `prep_retry.py` | After a partial/failed run: keeps decided + source_checked-ambiguous verdicts, deletes failed-run verdicts, emits the not-yet-decided rids as a new retry batch. |

B1 is driven through its existing seam only: `run_review discover --review-ids-from <csv>`.

## 4. Batches and where they stand

Ensemble artifacts live in `data/output/ensemble/<batch>/`; B1 batch dirs in
`data/output/agent_b/batch/<batch>/`; verdicts are shared in
`data/output/review_queue/verdicts/<review_id>.json`.

| Batch | rids | State |
|---|---|---|
| `ens1` | 1,008 | full sample (universe). discover+preflight done. Analysis target. |
| `ens1_pilot` | 157 | pilot (disjoint subset of ens1). **Partially adjudicated:** 34 decided + 4 ambiguous kept; 119 still need adjudication. |
| `ens1_pilot_r2` | 119 | **retry batch** for the pilot's undecided rids. discover+preflight done; ready to dispatch. |
| `ens1_rest` | 851 | remainder of ens1 (not yet dispatched). Run after the pilot is complete. |

The pilot's first runs failed/degraded due to dispatch infra issues (section 6), not the
experiment design. `prep_retry` already salvaged the 34 decided verdicts.

## 5. RESUME after restart

A restart clears the 2 stuck codex workers and resets sandbox state, so **no `taskkill`
needed**. From a fresh **elevated** PowerShell:

```powershell
Set-Location "C:\Users\alger\Documents\000. Projects\005. evergreen funds platform xbrl"

# 0. sanity: no codex should be running
Get-Process -Name codex* -ErrorAction SilentlyContinue

# 1. finish the pilot: retry the 119 undecided rids (fresh batch id => no stale markers)
python -m scripts.ensemble.prep_retry --src ens1_pilot --retry ens1_pilot_r2
python -m scripts.agent_b.run_review discover ens1_pilot_r2 --review-ids-from data/output/ensemble/ens1_pilot_r2/review_ids.csv
.\scripts\dispatch_agent_b_workers.ps1 -BatchId ens1_pilot_r2 -MaxParallel 1

# 2. analyze the FULL pilot (verdicts are shared by review_id)
python -m scripts.ensemble.strip_verdict_bom --batch-id ens1_pilot
python -m scripts.ensemble.analyze_ensemble --batch-id ens1_pilot
# -> read data/output/ensemble/ens1_pilot/ensemble_summary.md

# 3. (after the pilot looks right) run the remaining 851
python -m scripts.agent_b.run_review discover ens1_rest --review-ids-from data/output/ensemble/ens1_rest/review_ids.csv
.\scripts\dispatch_agent_b_workers.ps1 -BatchId ens1_rest -MaxParallel 2
python -m scripts.ensemble.strip_verdict_bom --batch-id ens1
python -m scripts.ensemble.analyze_ensemble --batch-id ens1
```

Notes:
- `-MaxParallel 1` for the retry = guaranteed (no race). Fresh post-restart state may make
  `-MaxParallel 2` clean (it matches the working `restall` batch); if trying 2, watch the
  first ~20 verdicts and drop to 1 if `no_source` climbs.
- 119 workers at 1-wide ~= 1-3 hrs; 851 at 2-wide is long (consider a second machine).
- Run only ONE Codex fleet at a time on this machine.

## 6. Dispatch infra gotchas (hard-won)

Codex's elevated Windows sandbox (`[windows] sandbox = "elevated"`, set by
`setup_codex_worker_harness.ps1`) runs each command as shared local accounts
`CodexSandboxOnline/Offline` via `CreateProcessWithLogonW`.

- **MaxParallel <= 2.** Each worker setup resets the shared account password; >2 concurrent
  workers clobber it -> `CreateProcessWithLogonW failed: 1326` for all but one. Working
  batches use 2 (`run_fresh_cik_trial.ps1` default).
- **Stale setup markers are the dominant re-run failure.** Codex writes a per-worker-home
  `.sandbox/setup_marker.json` and never deletes it; the dispatcher reuses per-rid
  `worker_home/<rid>` dirs across runs, so re-running the SAME batch id hits marker
  FILE_EXISTS (error 80) -> setup aborts -> cascades to 1326. **Always retry as a NEW
  batch id** (fresh worker homes). This is why `ens1_pilot_r2` exists rather than re-running
  `ens1_pilot`.
- **One Codex fleet per machine** (two independent fleets also race the shared accounts).
- **BOM:** workers sometimes write verdicts with a UTF-8 BOM; B1 finalize uses strict utf-8.
  Run `strip_verdict_bom.py` before `run_review finalize`.
- **Killing a run:** the dispatcher loop runs in the operator's interactive terminal
  (Ctrl-C or close it). In-flight codex workers run elevated -> a non-elevated shell gets
  "Access is denied"; use elevated `taskkill /F /PID ...`, or just restart the machine.
- **finalize is contained:** writes `routing.csv` (advisory labels) + `finalize_summary.json`
  to the batch dir only; no production-queue pollution. The ensemble analysis does not even
  require finalize — `analyze_ensemble.py` computes the per-rule FP itself.

## 7. NOT a problem

- Account lockout: ruled out (`net accounts` threshold = Never; accounts not locked).
- B1 code: unchanged and correct; discover/preflight build all bundles+prompts cleanly.
- The deterministic prep (sampling, discover, preflight) has always worked; only the Codex
  worker sandbox execution was flaky, for the reasons in section 6.
