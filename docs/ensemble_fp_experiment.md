# Weak-rule False-Positive + Ensemble B1 Experiment

**Branch:** `ensemble-fp-experiment` (all code here is additive; Agent B1 is NOT modified).
**Status as of 2026-06-29 ~08:45 local.** Current batch is **`ens2`** (cohort-scoped;
`ens1*` is superseded — see section 2a). Resume steps are in section 5.

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
- **In-scope rules:** weak/review-lane rules with **>= 30 firings** in the queue.
- **Budget:** "Standard" ~1,000 adjudications.

## 2a. Scope correction (2026-06-29) -- why ens1 is superseded by ens2

`ens1` was drawn before two bugs were understood; its pilot (`ens1_pilot`, 157 flags)
returned **70% `no_source`** and only 43 decided. Root causes (both now fixed in
`sample_units.py`):

1. **Wrong sampling frame.** The sampler read the WHOLE `review_queue.csv`, not the v1
   **wrapper cohort** (AGENTS.md scope: ~70 unlisted BDCs). Only 5/56 sampled CIKs were
   in-cohort; 17/56 were N-PORT/N-CSR interval/tender funds. The B1 evidence CLI
   (`scripts/review_agent/evidence_cli.py`) is **BDC-SOI-HTML-only** (`_ENGINE_SOURCE`
   -> "BDC", `_html_path` -> `BDC_HTML_CACHE_DIR`): it roams the WHOLE filing once it
   resolves one, but cannot open N-PORT XML / N-CSR HTML -> those funds are 100%
   `no_source` (failure `missing_cached_html`).
2. **No-accession engines.** `fund_financials` (F*), `html_extract` (html_carry) and
   `fund_strategy` bundles carry no resolvable accession, so the CLI fails at
   `no_accession_resolved` BEFORE any file open -- independent of cohort. (`row_validation`
   / `oracle` only failed on non-BDC funds, so cohort scoping rescues them.)

This was NOT a "B1 only sees a slice" problem -- B1 roams the entire filing; the gap is
*which source* it can open. See the memory note `full-filing-search-adjudication`.

**Fixes (in `sample_units.py`):**
- **Cohort filter** -- default `config.WRAPPER_COHORT_MANIFEST_FILE` (70 CIKs);
  `--all-vehicles` disables (audit only). Non-cohort and N-PORT CIKs are dropped.
- **`--exclude-engines`** -- default `fund_financials,html_extract,fund_strategy`; these
  are excluded from the adjudicated in-scope set but **still recorded in
  `all_weak_rules`** as co-firing features (the ensemble feature vector stays complete).
- Manifest records `cohort_scoped`, `cohort_cik_count`, `excluded_engines` for provenance.

**Drawn sample (`ens2`, 2026-06-29):** cohort-scoped frame = 789 units / 32 in-scope
rules (>=30 firings). Allocation `--n-d1 8 --n-d2_3 13 --n-d4_7 90 --n-d8plus 30` ->
**141 units / 934 adjudications**, all 42 CIKs in-cohort; engines row_validation 635 /
oracle 175 / weak 84 / nonaccrual 40. **Caveat:** the cohort frame is degree-skewed
(81% of units are d8plus; only 8 d1 + 13 d2_3 units exist), so per-rule FP is
well-powered but the ensemble-DEGREE contrast is structurally weak.

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
| `ens2` | 934 | **CURRENT** full sample (cohort-scoped). discover done. |
| `ens2_pilot` | 122 | strict subset of ens2 (32 units). **Dispatching now** -- gate on `no_source` before running the remainder. |
| `ens2_rest` | 812 | remainder of ens2 (109 units). Run after the pilot gate passes. |
| `ens1*` | -- | **SUPERSEDED** (wrong frame; see section 2a). `ens1`, `ens1_pilot` (157, 70% no_source), `ens1_pilot_r2` (119), `ens1_rest` (851). Kept only for audit. |

ens1's pilot also hit dispatch infra issues (section 6) on its first runs; those are
orthogonal to the scope bug and are fixed/documented separately.

## 5. RESUME after restart

A restart clears the 2 stuck codex workers and resets sandbox state, so **no `taskkill`
needed**. From a fresh **elevated** PowerShell:

`ens2` is already drawn and discovered; `ens2_pilot` is dispatching. From a fresh
**elevated** PowerShell:

```powershell
Set-Location "C:\Users\alger\Documents\000. Projects\005. evergreen funds platform xbrl"

# 0. sanity: no codex should be running
Get-Process -Name codex* -ErrorAction SilentlyContinue

# 1. (if re-drawing ens2 from scratch) cohort-scoped sample + disjoint pilot split
python -m scripts.ensemble.sample_units --batch-id ens2 --n-d1 8 --n-d2_3 13 --n-d4_7 90 --n-d8plus 30
python -m scripts.ensemble.sample_units --pilot-of ens2     # -> ens2_pilot + ens2_rest

# 2. PILOT GATE: discover the PILOT batch (each batch needs its OWN discover/worklist),
#    then dispatch. NOTE: discover the exact batch id you are about to dispatch.
python -m scripts.agent_b.run_review discover ens2_pilot --review-ids-from data/output/ensemble/ens2_pilot/review_ids.csv
.\scripts\dispatch_agent_b_workers.ps1 -BatchId ens2_pilot -MaxParallel 2
python -m scripts.ensemble.strip_verdict_bom --batch-id ens2_pilot
python -m scripts.agent_b.run_review finalize ens2_pilot
# -> check no_source in finalize_summary.json; expect LOW teens, not the old 70%.

# 3. (after the pilot gate passes) run the remaining 812
python -m scripts.agent_b.run_review discover ens2_rest --review-ids-from data/output/ensemble/ens2_rest/review_ids.csv
.\scripts\dispatch_agent_b_workers.ps1 -BatchId ens2_rest -MaxParallel 2

# 4. analyze the FULL ens2 (verdicts are shared by review_id across pilot+rest)
python -m scripts.ensemble.strip_verdict_bom --batch-id ens2
python -m scripts.ensemble.analyze_ensemble --batch-id ens2
# -> read data/output/ensemble/ens2/ensemble_summary.md
```

Notes:
- **Discover is per-batch-id.** The dispatcher reads `data/output/agent_b/batch/<id>/worklist.csv`,
  which `discover <id>` creates. Running `discover ens2` then dispatching `ens2_pilot`
  fails `PRECHECK_FAIL: missing worklist` -- discover the SAME id you dispatch. Bundles are
  keyed by review_id and shared, so a subset discover reuses existing bundles (no rework).
- `-MaxParallel 2` is the proven-clean value (section 6). Watch the first ~20 verdicts; if
  `no_source` climbs, stop and check (a fresh batch id avoids stale-marker cascades).
- ens2_pilot = 122 adjudications (~30-60 min at 2-wide); ens2_rest = 812 (long).
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
