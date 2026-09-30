# Sub-project 1: Drift Replay Q4-2025 to Q1-2026 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Score the existing contract suite plus a new `independent_totals` kind on the 2025-12-31 -> 2026-03-31 pair for all 8 pilot filers against the q1p3 adjudicated findings, report recall and false-alarm rate per kind against the spec's criterion 3 floors, and write the shadow drift queue in findings-ledger shape.

**Architecture:** Everything rides on the Stage B2 harness (`scripts/profile_pilot/`): the all-quarter census, `contracts.py` learn/evaluate, `m2_seed.py` seeded drift and `m2_backtest.py` rolling pairs. Three additions: (1) the amendment scanner is wired into the inventory freeze so the three filers missing a Q4-2025 census get one; (2) `contracts_totals.py` adds the `independent_totals` kind (published-basis FV sum vs the fund's filed total, pct-of-net-assets sum) with tolerances v4; (3) `replay_report.py` scores only the Q4-to-Q1 pair against a widened, pre-registered ledger mapping and emits the floors verdict and the shadow queue. No production code under `pipeline/` changes.

**Tech Stack:** Python 3, DuckDB (pinned parquet slices), pytest via `scripts/profile_pilot/verify.py`, write-once run roots under `<main>/data/pilot/filer_profile/`.

**Spec:** `docs/superpowers/specs/2026-09-29-filer-profile-programme-design.md` sections 3 (criterion 3), 5 (independent totals, provisional contracts), 5.1 (adoption rule), 8 (sub-project 1 row), 9 (constraints). Pilot spec v4.2 (`docs/superpowers/specs/2026-09-28-filer-profile-pilot-design.md`) remains the authority for census, envelope and contract mechanics. Ledger rulings R36, R37, R38, R39 (`.superpowers/sdd/2026-09-28-filer-profile-pilot/progress.md`) are binding.

## Global Constraints

- Code lives ONLY in the worktree `.claude/worktrees/filer-profile-pilot` on branch `filer-profile-pilot`; data lives in the MAIN checkout `data/` (`--data-root "<main>/data"`). The worktree has no `data/raw` or `data/output`.
- No writes under `data/output/` or `frontend/public/data/` from any stage. Pilot writes only under `<data_root>/pilot/filer_profile/<run_id>/` (write-once roots) and `scratch/`.
- No unrequested network. No `python -` or long `python -c`. ASCII only in code, logs and docs.
- Heavy work (census, seed, back-test) runs under the shared lease and ALONE: never concurrent with pytest, `scripts/rebuild_outputs.py` or `pipeline.programme.bootstrap` (ruling R36). `pipeline.programme.runner.heavy_lock` refuses while any such python process exists. The sub-project 0b base build (`rebuild_outputs.py`, started 2026-09-30 08:59, PID in `<main>/scratch/2026-09-30_base_build/rebuild.pid`) must have EXITED before Tasks 1, 5 and 6 run.
- Tests run through the launcher, never bare pytest: `python -m scripts.profile_pilot.verify test --data-root "<main>/data" --run-id sp1-verify-<stamp> --no-pre-backstop tests/test_profile_pilot_<x>.py`. The pre-existing backstop divergence count is 161 and must stay 161 on any run without `--no-pre-backstop`.
- Commit before any real (non-test) run. Every real run records its run id in the changelog entry.
- Tolerances change only by a NEW version (v4) that carries v3 verbatim plus `supersedes`; v2 and v3 digests are never edited. Every contract whose kind is new in v4 carries `status_basis = "provisional"` (spec section 5).
- Bands and floors are pre-registered in this plan (Task 3 and Task 6) BEFORE any real run and are not tuned to the replay result. A band that turns out wrong is reported, not adjusted.
- Every metric reported is labelled IN-SAMPLE (the q1p3 findings were adjudicated before this replay; Q2-2026 is the first out-of-sample quarter).
- Subagents use model Opus 5.5; one reviewer per task; the SDD ledger lives at `.superpowers/sdd/2026-09-30-sp1-drift-replay/progress.md` (create on Task 1).

---

## File structure

| Path (worktree) | Responsibility | Task |
|---|---|---|
| `scripts/profile_pilot/verify.py` | `freeze --quarters all --scan-amendments` takes the lease and passes the scanner | 1 |
| `scripts/profile_pilot/cohort.py` | unchanged interface; `all_quarter_inventory(paths, scanner=, lease=)` already exists | 1 |
| `scripts/profile_pilot/contracts_totals.py` (new) | pure functions: observe totals on a census doc, learn/evaluate the `independent_totals` kind | 3 |
| `scripts/profile_pilot/contracts.py` | register the kind: `KINDS`/`ALL_KINDS`, `KIND_BAND_KEYS`, `band_for`, learn loop, `_evaluate` dispatch, `evaluate_contracts(..., financials_q2=None)`, `learn_contracts(..., financials_q1=None)`, `tolerance_content_v4()` | 4 |
| `scripts/profile_pilot/contracts_run.py` | `materialise_financials_slice(paths)` pins `inputs/fund_financials_pilot8.parquet`; passes financials rows into learn/evaluate | 4 |
| `scripts/profile_pilot/m2_seed.py` | perturbation `fair_value_scale_flip` and `pct_scale_flip`; kind registered; v4 tolerance accepted | 4 |
| `scripts/profile_pilot/m2_backtest.py` | `SUITE` entry; widened `LEDGER_RULES` (pre-registered map) and `LEDGER_EXCLUDED_STATES` report; v4 accepted; financials per quarter | 2, 4 |
| `scripts/profile_pilot/replay_report.py` (new) | score the Q4-to-Q1 pair only, evaluate floors, write `replay_q4_q1.json/.md` and `drift_queue.csv` | 5 |
| `tests/test_profile_pilot_all_quarters.py` | scanner wiring tests | 1 |
| `tests/test_profile_pilot_m2_backtest.py` | ledger mapping tests | 2 |
| `tests/test_profile_pilot_totals.py` (new) | totals kind unit tests | 3, 4 |
| `tests/test_profile_pilot_replay.py` (new) | replay scoring, floors and queue shape tests | 5 |
| `docs/agent_changelog.md` | one entry per real run and the sub-project close | 6 |

Pre-registered constants (copied into code in Tasks 3 and 6, never changed afterwards):

| Constant | Value | Source |
|---|---|---|
| `fv_residual_pct` standard / low_history | 5.0 / 10.0 | `pipeline/oracle_checks.check_A04_gav_reconciliation` bdc_tolerance=0.05; the published-basis 0.5% band (`config.FV_CONSERVATION_BAND_PCT`) applies to production anchors with verified overrides, which the pilot does not pin |
| `pct_sum_min` / `pct_sum_max` | 50 / 250 | `check_A07_pct_of_net_assets_sum` defaults |
| `pct_sum_shift_pp` standard / low_history | 15 / 25 | learned Q1 sum vs Q2 sum; chosen from the A07 outlier_threshold=25 halved for standard tier |
| `min_positions` for totals | 5 | `validate_holdings.check_pct_of_net_assets_sum` minimum |
| Structural floor | recall >= 0.90, false-alarm <= the band version's stated rate (v3 structural ~0.02) | spec criterion 3 |
| Totals floor | seeded x100 / x0.01 flip detected at fraction <= 0.20 on every CIK with a pinned financials row | spec criterion 3 |
| Semantic kinds | floor per 5.1 adoption rule or label `detection_not_claimed` | spec criterion 3 |

---

### Task 1: Amendment scan for the missing Q4-2025 censuses

Three pilot filers (Ares 0001287750, TCW 0001715933, NexPoint 0001588272) have no authoritative 2025-12-31 census in `stageb2-census-20260929t094408z`; `results/excluded.json` gives `reason=unavailable, detail=selection_requires_amendment_scan` because the B2 freeze ran with `scanner=None`. The scan mechanism exists (`cohort.all_quarter_inventory(paths, scanner=, lease=)` -> `run_context_census.scan_selected_source` -> default scanner `run_context_census.scan_instance(path, cik, quarter)`), but no CLI passes a scanner. This task wires it, re-freezes the all-quarter inventory into a NEW census root, and re-runs the all-quarter census and validation there.

**Files:**
- Modify: `scripts/profile_pilot/verify.py:223-241` (`freeze_inventory_content`, `cmd_freeze`)
- Test: `tests/test_profile_pilot_all_quarters.py`

**Interfaces:**
- Consumes: `cohort.all_quarter_inventory(paths, *, scanner=None, lease=None)`; `protection.shared_heavy_lease(paths, head=)`; `run_context_census.scan_instance`.
- Produces: CLI `verify freeze --quarters all --scan-amendments`; new census root `sp1-census-<stamp>` whose `results/authoritative.json` has a `2025-12-31` row for every pilot CIK, or a residual `excluded.json` row with a reason other than `selection_requires_amendment_scan`.

- [ ] **Step 1: Create the SDD ledger** at `.superpowers/sdd/2026-09-30-sp1-drift-replay/progress.md` with the header `# SP1 drift replay ledger` and one line `2026-09-30 Task 1 started; base build PID <pid> status <running|exited>` (read `<main>/scratch/2026-09-30_base_build/rebuild.pid` and `tasklist`).

- [ ] **Step 2: Write the failing tests** (append to `tests/test_profile_pilot_all_quarters.py`):

```python
def test_freeze_all_with_scan_passes_the_default_scanner_under_a_held_lease(tmp_path, monkeypatch):
    from scripts.profile_pilot import verify, cohort
    seen = {}

    def fake_inventory(paths, *, scanner=None, lease=None):
        seen["scanner"] = scanner
        seen["lease"] = lease
        return dict(fund_quarters=[])

    class Lease:
        held = True
        lock_path = tmp_path / "heavy.lock"

    monkeypatch.setattr(cohort, "all_quarter_inventory", fake_inventory)
    paths = _paths(tmp_path)  # existing helper in this file
    verify.freeze_inventory_content(paths, "all", scan_amendments=True, lease=Lease())
    from scripts import run_context_census
    assert seen["scanner"] is run_context_census.scan_instance
    assert seen["lease"].held is True


def test_freeze_all_without_scan_keeps_scanner_none(tmp_path, monkeypatch):
    from scripts.profile_pilot import verify, cohort
    seen = {}
    monkeypatch.setattr(cohort, "all_quarter_inventory",
                        lambda paths, *, scanner=None, lease=None: seen.update(scanner=scanner) or dict(fund_quarters=[]))
    verify.freeze_inventory_content(_paths(tmp_path), "all")
    assert seen["scanner"] is None


def test_scan_flag_with_cohort_quarters_is_refused(tmp_path):
    from scripts.profile_pilot import verify
    with pytest.raises(ValueError, match="scan-amendments"):
        verify.freeze_inventory_content(_paths(tmp_path), "cohort", scan_amendments=True)
```

If `_paths` does not exist in that test file, use the same `TmpRunPaths` fixture `tests/test_profile_pilot_m2_seed.py` exports (import it) and name the variable accordingly.

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python -m scripts.profile_pilot.verify test --data-root "<main>/data" --run-id sp1-verify-t1a --no-pre-backstop tests/test_profile_pilot_all_quarters.py`
Expected: the three new tests FAIL with `TypeError: freeze_inventory_content() got an unexpected keyword argument`.

- [ ] **Step 4: Implement** in `verify.py`:

```python
def freeze_inventory_content(paths, quarters: str, *, scan_amendments: bool = False, lease=None) -> dict:
    """primary_quarter_inventory content: the Stage B cohort (default) or every cached quarter.

    scan_amendments=True (all mode only) passes run_context_census.scan_instance so that
    fund-quarters whose selection needs an amendment scan are settled instead of excluded;
    the caller must hold the shared heavy lease (cohort asserts it).
    """
    from scripts.profile_pilot import cohort
    if scan_amendments and quarters != "all":
        raise ValueError("--scan-amendments applies only to --quarters all")
    if quarters == "cohort":
        return cohort.primary_quarter_inventory(paths)
    if quarters == "all":
        if not scan_amendments:
            return cohort.all_quarter_inventory(paths)
        from scripts import run_context_census
        return cohort.all_quarter_inventory(paths, scanner=run_context_census.scan_instance, lease=lease)
    raise ValueError("quarters must be one of " + repr(QUARTERS_MODES) + ", got " + repr(quarters))
```

In `cmd_freeze`, add `scan = getattr(args, "scan_amendments", False)`; when `scan` is true, wrap the freeze in `with protection.shared_heavy_lease(paths, head=_git_head()) as lease:` (use the same helper the census runner uses at `census_run.py:483`; copy its `head` computation) and pass `lease=lease`; otherwise call as today. Add `cmd.add_argument("--scan-amendments", action="store_true")` to the `freeze` subparser. Record `scan_amendments` and the lease acquire/release timestamps in the freeze receipt dict that `cmd_freeze` already writes.

- [ ] **Step 5: Run the tests to verify they pass**

Run: same launcher command with `--run-id sp1-verify-t1b`.
Expected: whole file PASS; exit 0.

- [ ] **Step 6: Commit**

```bash
git add scripts/profile_pilot/verify.py tests/test_profile_pilot_all_quarters.py .superpowers/sdd/2026-09-30-sp1-drift-replay/progress.md
git commit -m "Wire the amendment scanner into the all-quarter inventory freeze" -m "- freeze --quarters all --scan-amendments takes the shared lease and passes run_context_census.scan_instance
- cohort.all_quarter_inventory already accepted a scanner; no CLI passed one, so Q4-2025 stayed excluded for three pilot filers
- refused for --quarters cohort; tests cover both paths"
```

- [ ] **Step 7: Confirm the base build has exited** (`tasklist | grep -i python` must show no `rebuild_outputs.py`; `<main>/scratch/2026-09-30_base_build/rebuild.log` must end with `rebuild exit=0` or the detached process must be gone). If it is still running, STOP this task and record the wait in the ledger; do not proceed to Step 8.

- [ ] **Step 8: Freeze the scanned inventory** (real run, lease held, nothing else running):

```
python -m scripts.profile_pilot.verify freeze --quarters all --scan-amendments --data-root "<main>/data" --run-id sp1-census-<YYYYMMDDtHHMMSSz>
```

Expected: exit 0; `<run_root>/inventories/primary_quarter_inventory.json` lists a `status=selected` row for `0001287750:2025-12-31`, `0001715933:2025-12-31`, `0001588272:2025-12-31`, each with `source_selection` trace entries whose earlier dispositions are `amendment_without_target_instant`. If any row stays `unavailable`, its `reason` must now be one of `ambiguous_same_quarter_candidates`, `selection_scan_failed`, `source_not_cached`; record the reason verbatim in the ledger. Also record what happened to the other four B2 `unavailable` rows (including Ares 2022-12-31, the sub-project 0 item).

- [ ] **Step 9: Census and validate the new root** (real runs, alone):

```
python -m scripts.profile_pilot.census_run run --data-root "<main>/data" --run-id sp1-census-<stamp> --scope all
python -m scripts.profile_pilot.census_validate run --data-root "<main>/data" --run-id sp1-census-<stamp>
```

(Use the exact `census_validate` CLI shape printed by `python -m scripts.profile_pilot.census_validate --help`; its Stage B invocation is recorded in `docs/agent_changelog.md` under the 2026-09-29 Task 5 entry.) Expected: `results/authoritative.json` has >= 109 fund-quarters (106 + 3); every pilot CIK has both `2025-12-31` and `2026-03-31` rows with `validation_verdict=pass`. Record run wall time and peak memory from `run_summary` in the ledger.

- [ ] **Step 10: Append a changelog entry** to `docs/agent_changelog.md` titled `2026-09-30 -- SP1 Task 1: amendment scan settles Q4-2025 for Ares, TCW, NexPoint` with the run id, the per-CIK selection trace summary, the residual exclusions with reasons, and the counts. Commit:

```bash
git add docs/agent_changelog.md .superpowers/sdd/2026-09-30-sp1-drift-replay/progress.md
git commit -m "Record the SP1 scanned all-quarter census root" -m "- run id sp1-census-<stamp>: <n> authoritative fund-quarters, Q4-2025 present for all 8 pilot filers (or residuals listed)
- census + validation ran alone under the lease after the base build exited"
```

---

### Task 2: Pre-registered ledger mapping for the totals and identity rules

`m2_backtest.ledger_positives` scores only five `rule_name` values. The q1p3 ledger carries totals-type adjudications for the 8 filers on the two replay quarters (`fv_conservation`, `cost_conservation`, `pct_of_net_assets_identity`, oracle `A07`, `A04`, `E01`) that the new kind must be scored against. This task widens the map BEFORE the kind exists, so the mapping cannot be shaped by results.

**Files:**
- Modify: `scripts/profile_pilot/m2_backtest.py:118-129` (`LEDGER_RULES`, `LEDGER_STATES`, add `LEDGER_EXCLUDED_STATES`, `LEDGER_MAP_VERSION`)
- Test: `tests/test_profile_pilot_m2_backtest.py`

**Interfaces:**
- Consumes: ledger CSV columns `review_id,state,in_queue,population_origin,verdict_status,verdict_detail,has_fix_route,cik,rule_name,report_date,lane,engine,fv_at_risk_m,fund_quarter_fv_m`.
- Produces: `LEDGER_RULES` with the six new keys below; `ledger_exclusions(rows, ciks, dates) -> list[dict(cik, date, rule_name, state, verdict_status, reason)]` listing every row for the 8 CIKs on the replay dates that is NOT scored and why; `TOTALS_FIELD = "fair_value"` and `PCT_FIELD = "pct_of_net_assets"` (the two `independent_totals` fields, defined here and imported by Task 3).

- [ ] **Step 1: Write the failing tests** (append):

```python
def test_totals_and_identity_rules_map_to_independent_totals_fields():
    from scripts.profile_pilot import m2_backtest as bt
    assert bt.LEDGER_RULES["fv_conservation"] == {"independent_totals": ["fair_value"]}
    assert bt.LEDGER_RULES["cost_conservation"] == {"independent_totals": ["fair_value"]}
    assert bt.LEDGER_RULES["A04"] == {"independent_totals": ["fair_value"]}
    assert bt.LEDGER_RULES["E01"] == {"independent_totals": ["fair_value"]}
    assert bt.LEDGER_RULES["A07"] == {"independent_totals": ["pct_of_net_assets"]}
    assert bt.LEDGER_RULES["pct_of_net_assets_identity"] == {"independent_totals": ["pct_of_net_assets"]}
    assert bt.LEDGER_MAP_VERSION == "sp1-2026-09-30"
    # the five v2/v3 rules are untouched
    assert bt.LEDGER_RULES["dl_rate_fill"] == {"fill_rate": ["interest_rate"]}


def test_ledger_exclusions_list_every_unscored_row_with_a_reason():
    from scripts.profile_pilot import m2_backtest as bt
    rows = [
        dict(review_id="r1", state="open", verdict_status="MISSING", cik="0001287750", rule_name="A07", report_date="2026-03-31"),
        dict(review_id="r2", state="needs_human", verdict_status="verdict_ESCALATE", cik="0001287750", rule_name="fv_conservation", report_date="2025-12-31"),
        dict(review_id="r3", state="real_error_unremediated", verdict_status="verdict_real_error", cik="0001287750", rule_name="A07", report_date="2026-03-31"),
        dict(review_id="r4", state="real_error_unremediated", verdict_status="verdict_real_error", cik="0001287750", rule_name="nonaccrual_x", report_date="2026-03-31"),
        dict(review_id="r5", state="real_error_unremediated", verdict_status="verdict_real_error", cik="0009999999", rule_name="A07", report_date="2026-03-31"),
    ]
    out = bt.ledger_exclusions(rows, ciks={"0001287750"}, dates={"2025-12-31", "2026-03-31"})
    by_id = {o["review_id"]: o["reason"] for o in out}
    assert by_id == {"r1": "state_not_adjudicated:open", "r2": "state_not_adjudicated:needs_human",
                     "r4": "rule_not_mapped:nonaccrual_x"}
    # r3 is scored (not excluded); r5 is outside the cohort and not listed
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m scripts.profile_pilot.verify test --data-root "<main>/data" --run-id sp1-verify-t2a --no-pre-backstop tests/test_profile_pilot_m2_backtest.py`
Expected: FAIL (`KeyError: 'fv_conservation'`, `AttributeError: ledger_exclusions`).

- [ ] **Step 3: Implement** in `m2_backtest.py` next to `LEDGER_RULES`:

```python
TOTALS_FIELD = "fair_value"
PCT_FIELD = "pct_of_net_assets"
LEDGER_MAP_VERSION = "sp1-2026-09-30"
LEDGER_RULES.update({
    # independent totals (spec 2026-09-29 section 5, D-floor): pre-registered before the kind existed
    "fv_conservation": {"independent_totals": [TOTALS_FIELD]},
    "cost_conservation": {"independent_totals": [TOTALS_FIELD]},
    "A04": {"independent_totals": [TOTALS_FIELD]},
    "E01": {"independent_totals": [TOTALS_FIELD]},
    "A07": {"independent_totals": [PCT_FIELD]},
    "pct_of_net_assets_identity": {"independent_totals": [PCT_FIELD]},
})
LEDGER_EXCLUDED_STATES = ("open", "needs_human", "evidence_backlog", "remediation_pulled", "gone_unadjudicated",
                          "resolved_upstream")


def ledger_exclusions(rows, *, ciks, dates) -> list:
    """Every ledger row for the replay cohort and dates that is NOT scored, with the reason.

    A row is scored only when its state is in LEDGER_STATES or LEDGER_NEGATIVE_STATE and its
    rule_name is in LEDGER_RULES. Everything else is reported so the recall denominator is honest.
    """
    out = []
    for r in rows:
        cik, date = str(r["cik"]).zfill(10), str(r["report_date"])[:10]
        if cik not in ciks or date not in dates:
            continue
        scored_state = r["state"] in LEDGER_STATES + (LEDGER_NEGATIVE_STATE,)
        if not scored_state:
            reason = "state_not_adjudicated:" + str(r["state"])
        elif r["rule_name"] not in LEDGER_RULES:
            reason = "rule_not_mapped:" + str(r["rule_name"])
        else:
            continue
        out.append(dict(review_id=r["review_id"], cik=cik, date=date, rule_name=r["rule_name"], state=r["state"],
                        verdict_status=r.get("verdict_status"), reason=reason))
    return sorted(out, key=lambda o: (o["cik"], o["date"], o["review_id"]))
```

Add `"independent_totals"` to `KNOWN_KINDS` only in Task 4 (the kind does not exist yet; `test_every_typed_positive_names_a_source_and_known_kinds` must keep passing now).

- [ ] **Step 4: Run to verify they pass**

Run: same launcher with `--run-id sp1-verify-t2b`. Expected: file PASS. Note: `test_findings_ledger_rows_map_to_kinds_and_false_alarms_are_negative_evidence` (line 134) must still pass; if it asserts the exact key set of `LEDGER_RULES`, update it to assert the five original keys are a subset.

- [ ] **Step 5: Commit**

```bash
git add scripts/profile_pilot/m2_backtest.py tests/test_profile_pilot_m2_backtest.py
git commit -m "Pre-register the ledger mapping for the independent-totals kind" -m "- six totals/identity rule names map to independent_totals fields before the kind exists
- ledger_exclusions lists every unscored cohort row with its reason (unadjudicated state or unmapped rule)
- map version sp1-2026-09-30; the five v2/v3 rules are unchanged"
```

---

### Task 3: `contracts_totals.py`: observe, learn and evaluate the `independent_totals` kind

Pure functions only; no I/O. Two fields: `fair_value` (published-basis FV sum of the census's current-period positions vs the fund's filed `investments_at_fair_value` from the pinned `fund_financials` slice) and `pct_of_net_assets` (sum of current-period `pct_of_net_assets` vs the A07 band and vs the learned Q1 sum). Income reconciliation is recorded as EVIDENCE ONLY in this sub-project (the S2 income vote is copied into the evidence block; no status criterion), labelled `detection_not_claimed`, because the pilot found the yield contract never learnable with one-quarter windows and the spec forbids a home-made ratio; the criterion is deferred to sub-project 2. Record this deviation from spec section 5 in the changelog.

**Files:**
- Create: `scripts/profile_pilot/contracts_totals.py`
- Test: `tests/test_profile_pilot_totals.py` (new)

**Interfaces:**
- Consumes: census document shape (`doc["positions"][n]["fields"][field]["value"]`, `doc["positions"][n]["period"]["instant"]`, `doc["document_metadata"]["document_period_end_dates"]`); `m2_backtest.TOTALS_FIELD`, `m2_backtest.PCT_FIELD`; a financials row `dict(cik, report_date, investments_at_fair_value, net_assets, total_assets)` or `None`.
- Produces:

```python
KIND = "independent_totals"
FIELDS = (TOTALS_FIELD, PCT_FIELD)
BAND_KEYS = ("fv_residual_pct", "pct_sum_min", "pct_sum_max", "pct_sum_shift_pp", "min_positions")

def observe_totals(doc: dict, *, financials: dict | None) -> dict
    # -> dict(n_positions, fv_sum, fv_filled, fv_anchor, fv_residual_pct, pct_sum, pct_filled, anchor_source)
    #    fv_anchor / fv_residual_pct are None when financials is None or investments_at_fair_value is None

def learn_totals(cik: str, tier: str, band: dict, q1_doc: dict, *, financials_q1: dict | None) -> list[dict]
    # -> two contract dicts (one per field) shaped like contracts._contract, with
    #    learn_status in {"learned", "insufficient_evidence"}, learn_cause, expectation, evidence,
    #    status_basis="provisional", partition_id="whole_filing", applies_to={"whole_filing": True}

def evaluate_totals(contract: dict, q2: dict, q2_doc: dict, *, financials_q2: dict | None, band: dict) -> dict
    # -> result dict shaped like contracts._result (status, cause, expected, observed, violating_keys=[])
```

Evaluation rules (fixed, pre-registered):
- `fair_value`: `insufficient_evidence` with cause `no_anchor` when `financials_q2` is None or its `investments_at_fair_value` is None; cause `too_few_positions` when `n_positions < min_positions`; `breach` with cause `fv_residual_outside_band` when `abs(fv_residual_pct) > fv_residual_pct` band; else `holds`. `fv_residual_pct = 100 * (fv_sum - anchor) / anchor`.
- `pct_of_net_assets`: `insufficient_evidence` cause `pct_not_filled` when fewer than `min_positions` positions carry a pct; `breach` cause `pct_sum_outside_band` when `pct_sum < pct_sum_min or pct_sum > pct_sum_max`; `breach` cause `pct_sum_shifted` when `abs(pct_sum - expectation.pct_sum_q1) > pct_sum_shift_pp`; else `holds`.
- Learning: `fair_value` learns only when Q1 has an anchor and `n_positions >= min_positions` (expectation records the Q1 residual as evidence, not as the band centre: the band is absolute); `pct_of_net_assets` learns `pct_sum_q1` when filled.
- A current-period position is one whose `period.instant` is in `document_period_end_dates`; only positions with a filled numeric `fields[field]["value"]` count toward the sum; values are parsed with `decimal.Decimal(str(value))`.

- [ ] **Step 1: Write the failing tests** in `tests/test_profile_pilot_totals.py` (import `mk_doc`, `debt`, `val`, `tolerances` from `tests.test_profile_pilot_contracts`; extend positions by setting `p["fields"]["fair_value"] = val("1000000", unit="USD")` and `p["fields"]["pct_of_net_assets"] = val("1.25")` for each current-period position):

```python
import copy
import pytest
from tests.test_profile_pilot_contracts import mk_doc, debt, val
from scripts.profile_pilot import contracts_totals as ct

BAND = dict(fv_residual_pct=5.0, pct_sum_min=50, pct_sum_max=250, pct_sum_shift_pp=15, min_positions=5)
FIN = dict(cik="0000000001", report_date="2026-03-31", investments_at_fair_value=80_000_000.0,
           net_assets=60_000_000.0, total_assets=90_000_000.0)


def book(n=80, fv="1000000", pct="1.25"):
    doc = mk_doc([debt(i) for i in range(n)])
    for p in doc["positions"]:
        p["fields"]["fair_value"] = val(fv, unit="USD")
        p["fields"]["pct_of_net_assets"] = val(pct)
    return doc


def test_observe_sums_current_period_positions_and_computes_residual():
    obs = ct.observe_totals(book(), financials=FIN)
    assert obs["n_positions"] == 80 and obs["fv_filled"] == 80
    assert obs["fv_sum"] == 80_000_000 and obs["fv_residual_pct"] == 0
    assert obs["pct_sum"] == 100 and obs["anchor_source"] == "fund_financials.investments_at_fair_value"


def test_observe_without_financials_has_no_anchor():
    obs = ct.observe_totals(book(), financials=None)
    assert obs["fv_anchor"] is None and obs["fv_residual_pct"] is None


def test_learn_then_holds_on_an_unchanged_book():
    q1 = book()
    contracts = ct.learn_totals("0000000001", "standard", BAND, q1, financials_q1=FIN)
    assert [c["field"] for c in contracts] == ["fair_value", "pct_of_net_assets"]
    assert all(c["learn_status"] == "learned" and c["status_basis"] == "provisional" for c in contracts)
    q2 = dict(report_date="2026-03-31", form_type="10-Q", status="selected", detail=None)
    res = [ct.evaluate_totals(c, q2, book(), financials_q2=FIN, band=BAND) for c in contracts]
    assert [r["status"] for r in res] == ["holds", "holds"]


def test_x100_scale_flip_on_fair_value_breaches_fv_and_pct_flip_breaches_pct():
    contracts = ct.learn_totals("0000000001", "standard", BAND, book(), financials_q1=FIN)
    q2 = dict(report_date="2026-03-31", form_type="10-Q", status="selected", detail=None)
    fv_flip = book(fv="100000000")          # x100 on every row
    r = ct.evaluate_totals(contracts[0], q2, fv_flip, financials_q2=FIN, band=BAND)
    assert r["status"] == "breach" and r["cause"] == "fv_residual_outside_band"
    pct_flip = book(pct="125")              # x100 on every row
    r = ct.evaluate_totals(contracts[1], q2, pct_flip, financials_q2=FIN, band=BAND)
    assert r["status"] == "breach" and r["cause"] == "pct_sum_outside_band"


def test_partial_flip_at_twenty_percent_of_rows_is_detected():
    contracts = ct.learn_totals("0000000001", "standard", BAND, book(), financials_q1=FIN)
    q2 = dict(report_date="2026-03-31", form_type="10-Q", status="selected", detail=None)
    doc = book()
    for p in doc["positions"][:16]:      # 20% of 80 rows x100
        p["fields"]["fair_value"] = val("100000000", unit="USD")
    r = ct.evaluate_totals(contracts[0], q2, doc, financials_q2=FIN, band=BAND)
    assert r["status"] == "breach"


def test_missing_anchor_in_q2_abstains_with_cause_no_anchor():
    contracts = ct.learn_totals("0000000001", "standard", BAND, book(), financials_q1=FIN)
    q2 = dict(report_date="2026-03-31", form_type="10-Q", status="selected", detail=None)
    r = ct.evaluate_totals(contracts[0], q2, book(), financials_q2=None, band=BAND)
    assert r["status"] == "insufficient_evidence" and r["cause"] == "no_anchor"


def test_pct_sum_shift_within_band_holds_and_beyond_band_breaches():
    contracts = ct.learn_totals("0000000001", "standard", BAND, book(), financials_q1=FIN)
    q2 = dict(report_date="2026-03-31", form_type="10-Q", status="selected", detail=None)
    assert ct.evaluate_totals(contracts[1], q2, book(pct="1.40"), financials_q2=FIN, band=BAND)["status"] == "holds"   # 112
    r = ct.evaluate_totals(contracts[1], q2, book(pct="1.50"), financials_q2=FIN, band=BAND)                          # 120
    assert r["status"] == "breach" and r["cause"] == "pct_sum_shifted"


def test_too_few_positions_never_learns():
    contracts = ct.learn_totals("0000000001", "standard", BAND, book(n=3), financials_q1=FIN)
    assert all(c["learn_status"] == "insufficient_evidence" for c in contracts)
    assert contracts[0]["learn_cause"] == "too_few_positions"
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m scripts.profile_pilot.verify test --data-root "<main>/data" --run-id sp1-verify-t3a --no-pre-backstop tests/test_profile_pilot_totals.py`
Expected: FAIL with `ModuleNotFoundError: scripts.profile_pilot.contracts_totals`.

- [ ] **Step 3: Implement `contracts_totals.py`** (about 150 lines):

```python
"""Independent-totals contract kind (spec 2026-09-29 section 5, D-floor).

Two whole-filing criteria that cannot abstain on a pure scale flip: the census's
published-basis fair-value sum against the fund's filed investments_at_fair_value,
and the pct-of-net-assets sum. Income reconciliation is EVIDENCE ONLY here
(detection_not_claimed); the criterion is deferred to sub-project 2.
Pure functions: no I/O, no tolerances access beyond the band dict passed in.
"""
from __future__ import annotations
from decimal import Decimal, InvalidOperation

KIND = "independent_totals"
TOTALS_FIELD = "fair_value"
PCT_FIELD = "pct_of_net_assets"
FIELDS = (TOTALS_FIELD, PCT_FIELD)
BAND_KEYS = ("fv_residual_pct", "pct_sum_min", "pct_sum_max", "pct_sum_shift_pp", "min_positions")
ANCHOR_SOURCE = "fund_financials.investments_at_fair_value"
PARTITION = "whole_filing"
INCOME_LABEL = "detection_not_claimed"


def _num(value):
    try:
        return Decimal(str(value)) if value not in (None, "") else None
    except InvalidOperation:
        return None


def _current(doc):
    ends = set(doc["document_metadata"]["document_period_end_dates"])
    return [p for p in doc["positions"] if p["period"].get("instant") in ends]


def _sum(positions, field):
    values = [_num((p["fields"].get(field) or {}).get("value")) for p in positions]
    filled = [v for v in values if v is not None]
    return sum(filled, Decimal(0)), len(filled)


def observe_totals(doc: dict, *, financials: dict | None) -> dict:
    positions = _current(doc)
    fv_sum, fv_filled = _sum(positions, TOTALS_FIELD)
    pct_sum, pct_filled = _sum(positions, PCT_FIELD)
    anchor = _num((financials or {}).get("investments_at_fair_value"))
    residual = None if anchor in (None, Decimal(0)) else float(100 * (fv_sum - anchor) / anchor)
    return dict(n_positions=len(positions), fv_sum=float(fv_sum), fv_filled=fv_filled,
                fv_anchor=None if anchor is None else float(anchor), fv_residual_pct=residual,
                pct_sum=float(pct_sum), pct_filled=pct_filled,
                anchor_source=ANCHOR_SOURCE if anchor is not None else None)


def _contract(cik, field, tier, band, learn_status, learn_cause, expectation, evidence):
    return dict(contract_id=cik + ":" + KIND + ":" + field + ":" + PARTITION, cik=cik, kind=KIND, field=field,
                partition_id=PARTITION, applies_to={PARTITION: True}, tier=tier, band=dict(band),
                learn_status=learn_status, learn_cause=learn_cause, expectation=expectation,
                evidence=evidence, status_basis="provisional")


def learn_totals(cik: str, tier: str, band: dict, q1_doc: dict, *, financials_q1: dict | None) -> list:
    obs = observe_totals(q1_doc, financials=financials_q1)
    few = obs["n_positions"] < band["min_positions"]
    out = []
    if few:
        out.append(_contract(cik, TOTALS_FIELD, tier, band, "insufficient_evidence", "too_few_positions", None, obs))
    elif obs["fv_anchor"] is None:
        out.append(_contract(cik, TOTALS_FIELD, tier, band, "insufficient_evidence", "no_anchor", None, obs))
    else:
        out.append(_contract(cik, TOTALS_FIELD, tier, band, "learned", None,
                             dict(anchor_source=ANCHOR_SOURCE, fv_residual_pct_q1=obs["fv_residual_pct"]),
                             dict(obs, income=INCOME_LABEL)))
    if few or obs["pct_filled"] < band["min_positions"]:
        out.append(_contract(cik, PCT_FIELD, tier, band, "insufficient_evidence",
                             "too_few_positions" if few else "pct_not_filled", None, obs))
    else:
        out.append(_contract(cik, PCT_FIELD, tier, band, "learned", None, dict(pct_sum_q1=obs["pct_sum"]), obs))
    return out


def _result(c, status, q2, *, cause=None, expected=None, observed=None):
    return dict(contract_id=c["contract_id"], cik=c["cik"], kind=c["kind"], field=c["field"],
                partition_id=c["partition_id"], applies_to=c["applies_to"], tier=c["tier"], status=status,
                cause=cause, expected=expected, observed=observed, violating_keys=[], q2=q2, band=c["band"],
                status_basis="provisional")


def evaluate_totals(contract: dict, q2: dict, q2_doc: dict, *, financials_q2: dict | None, band: dict) -> dict:
    obs = observe_totals(q2_doc, financials=financials_q2)
    exp = contract["expectation"]
    if obs["n_positions"] < band["min_positions"]:
        return _result(contract, "insufficient_evidence", q2, cause="too_few_positions", expected=exp, observed=obs)
    if contract["field"] == TOTALS_FIELD:
        if obs["fv_residual_pct"] is None:
            return _result(contract, "insufficient_evidence", q2, cause="no_anchor", expected=exp, observed=obs)
        if abs(obs["fv_residual_pct"]) > band["fv_residual_pct"]:
            return _result(contract, "breach", q2, cause="fv_residual_outside_band", expected=exp, observed=obs)
        return _result(contract, "holds", q2, expected=exp, observed=obs)
    if obs["pct_filled"] < band["min_positions"]:
        return _result(contract, "insufficient_evidence", q2, cause="pct_not_filled", expected=exp, observed=obs)
    if obs["pct_sum"] < band["pct_sum_min"] or obs["pct_sum"] > band["pct_sum_max"]:
        return _result(contract, "breach", q2, cause="pct_sum_outside_band", expected=exp, observed=obs)
    if abs(obs["pct_sum"] - exp["pct_sum_q1"]) > band["pct_sum_shift_pp"]:
        return _result(contract, "breach", q2, cause="pct_sum_shifted", expected=exp, observed=obs)
    return _result(contract, "holds", q2, expected=exp, observed=obs)
```

Adjust `_current` if `mk_doc` in the test helpers stores the instant under a different key; the seed harness reads `p["period"].get("instant")` (`m2_seed.py:236`), so match that.

- [ ] **Step 4: Run to verify they pass**

Run: same launcher, `--run-id sp1-verify-t3b`. Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/profile_pilot/contracts_totals.py tests/test_profile_pilot_totals.py
git commit -m "Add the independent-totals contract kind as pure functions" -m "- published-basis FV sum vs pinned investments_at_fair_value, and pct-of-net-assets sum; absolute bands pre-registered
- breaches on x100 flips at 20% of rows; abstains only without an anchor or with too few positions
- income reconciliation recorded as evidence only (detection_not_claimed); criterion deferred to sub-project 2"
```

---

### Task 4: Register the kind: tolerances v4, contracts wiring, pinned financials, seed and back-test

**Files:**
- Modify: `scripts/profile_pilot/contracts.py` (`KINDS`/`ALL_KINDS` at :60-86, `KIND_BAND_KEYS` :79, `band_for` :342, `learn_contracts` :426 signature and loop near :478-499, `evaluate_contracts` :709 signature, `_evaluate` :751 dispatch, add `tolerance_content_v4(v3)`)
- Modify: `scripts/profile_pilot/contracts_run.py` (`materialise_financials_slice`, pass financials into learn/evaluate, pin the slice in the manifest)
- Modify: `scripts/profile_pilot/m2_seed.py` (`PERTURB_KINDS` :71, `VARIANTS` :74, `CONTRACT_KINDS` :81, `EXPECTED_DETECTOR` :82, `_target_ids` :697, handlers, `pin_tolerances` :1265 to accept v4)
- Modify: `scripts/profile_pilot/m2_backtest.py` (`SUITE` :97, `KNOWN_KINDS`, tolerance digest check, financials per quarter in `_quarter` :1440, `_trim` :464 adds `status_basis`)
- Test: `tests/test_profile_pilot_totals.py` (wiring tests), `tests/test_profile_pilot_contracts.py` (denominator test), `tests/test_profile_pilot_m2_seed.py`

**Interfaces:**
- Consumes: Task 3 functions; `contracts_income.read_quarter_frames` pattern for DuckDB reads of pinned slices.
- Produces:
  - `contracts.tolerance_content_v4(v3: dict) -> dict`: v3 verbatim under `v3_verbatim` + `v3_content_sha256`, plus `bands.standard.independent_totals = dict(fv_residual_pct=5.0, pct_sum_min=50, pct_sum_max=250, pct_sum_shift_pp=15, min_positions=5)` and `bands.low_history.independent_totals = dict(fv_residual_pct=10.0, pct_sum_min=50, pct_sum_max=250, pct_sum_shift_pp=25, min_positions=5)`, `version=4`, `supersedes={... , "superseded_v4": "<v3 sha>"}`, `provisional_kinds=["independent_totals"]`, `calibration.quarters_seen=[]`.
  - `KIND_BAND_KEYS["independent_totals"] = ("independent_totals",)`; `band_for(tolerances, tier, "independent_totals")` returns the nested dict above (so `_check_frozen` equality holds).
  - `learn_contracts(..., financials_q1=None)` appends `contracts_totals.learn_totals(cik, tier, band, q1_doc, financials_q1=financials_q1)` after the semantic kinds; `evaluate_contracts(..., financials_q2=None)`; `_evaluate` dispatches `c["kind"] == contracts_totals.KIND` to `contracts_totals.evaluate_totals(c, q2, q2_doc, financials_q2=financials_q2, band=c["band"])` BEFORE the partition-routing branch (the kind is whole-filing and must not abstain on `ambiguous_partition_overlap`).
  - `contracts_run.materialise_financials_slice(paths) -> dict` writes `inputs/fund_financials_pilot8.parquet` with columns `cik (lpad 10), report_date, investments_at_fair_value, net_assets, total_assets` for the 8 CIKs from `<main>/data/output/fund_financials.csv`, mirroring `materialise_income_slice` (:139) including the manifest source record; `contracts_run.load_financials(paths, cik, report_date) -> dict | None`.
  - `m2_seed`: perturbations `fair_value_scale_flip` (multiply `fair_value` by 100 on the sampled fraction of current-period rows; handler mirrors `_scale_flip` but with `field="fair_value"`) and `pct_scale_flip` (same on `pct_of_net_assets`); `EXPECTED_DETECTOR[...] = "independent_totals"`; `_target_ids` returns both totals contract ids for these variants; `pin_tolerances` accepts a v4 file whose `v3_verbatim.v2_verbatim` digest equals `TOLERANCES_V2_SHA256`.
  - `m2_backtest`: `SUITE["independent_totals"] = (TOTALS_FIELD, PCT_FIELD)`; `--tolerances-version {2,3,4}` flag (default 4 when `--semantic`); `_quarter` loads `financials = contracts_run.load_financials(paths, cik, date)` and passes it to learn (`financials_q1`) and evaluate (`financials_q2`).

- [ ] **Step 1: Write the failing wiring tests** (append to `tests/test_profile_pilot_totals.py`):

```python
from tests.test_profile_pilot_contracts import learn, evaluate, pick, tolerances as tol_v2

def test_v4_tolerances_carry_v3_verbatim_and_the_totals_bands():
    from scripts.profile_pilot import contracts
    v3 = contracts.semantic_tolerances(tol_v2())
    v4 = contracts.tolerance_content_v4(v3)
    assert v4["version"] == 4 and v4["v3_verbatim"] == v3
    assert v4["bands"]["standard"]["independent_totals"] == dict(fv_residual_pct=5.0, pct_sum_min=50, pct_sum_max=250,
                                                               pct_sum_shift_pp=15, min_positions=5)
    assert v4["bands"]["low_history"]["independent_totals"]["fv_residual_pct"] == 10.0
    assert v4["provisional_kinds"] == ["independent_totals"]
    assert contracts.band_for(v4, "standard", "independent_totals") == v4["bands"]["standard"]["independent_totals"]


def test_learn_and_evaluate_route_the_totals_kind_whole_filing():
    from scripts.profile_pilot import contracts
    v4 = contracts.tolerance_content_v4(contracts.semantic_tolerances(tol_v2()))
    q1 = book()
    block = learn(q1, tol=v4, financials_q1=FIN)
    ids = {c["contract_id"] for c in block["contracts"] if c["kind"] == "independent_totals"}
    assert len(ids) == 2
    res = evaluate(block, book(fv="100000000"), tol=v4, financials_q2=FIN)
    assert pick(res, "independent_totals", "fair_value")["status"] == "breach"
    assert pick(res, "independent_totals", "pct_of_net_assets")["status"] == "holds"
    assert all(r.get("status_basis") == "provisional" for r in res if r["kind"] == "independent_totals")


def test_m2_denominator_counts_two_totals_contracts_per_cik():
    from scripts.profile_pilot import contracts
    v4 = contracts.tolerance_content_v4(contracts.semantic_tolerances(tol_v2()))
    block = learn(book(), tol=v4, financials_q1=FIN)
    assert sum(1 for c in block["contracts"] if c["kind"] == "independent_totals") == 2
```

Update the helpers `learn`/`evaluate` in `tests/test_profile_pilot_contracts.py` to accept and forward `financials_q1=None` / `financials_q2=None` (keyword-only, default None, so every existing call is unchanged).

- [ ] **Step 2: Run to verify they fail**

Run: `... --run-id sp1-verify-t4a --no-pre-backstop tests/test_profile_pilot_totals.py`
Expected: FAIL (`AttributeError: tolerance_content_v4`, then TypeError on the new kwargs).

- [ ] **Step 3: Implement the contracts.py wiring**: add `from scripts.profile_pilot import contracts_totals` at the top; `TOTALS_KIND = contracts_totals.KIND`; `ALL_KINDS = KINDS + SEMANTIC_KINDS + (TOTALS_KIND,)`; `KIND_BAND_KEYS[TOTALS_KIND] = (TOTALS_KIND,)`; in `band_for`, after the yield branch: `if kind == TOTALS_KIND: return dict(_req(bands, TOTALS_KIND, "tolerances.bands." + tier))` (bands dict from the tier); in `learn_contracts`, after semantic contracts are appended and only when `tolerances.get("version", 2) >= 4`: `contracts += contracts_totals.learn_totals(cik, tier, band_for(tolerances, tier, TOTALS_KIND), q1_doc, financials_q1=financials_q1)`; in `_evaluate`, right after the `not_learned_in_q1` check: `if c["kind"] == TOTALS_KIND: results.append(contracts_totals.evaluate_totals(c, q2, q2_doc, financials_q2=financials_q2, band=c["band"])); continue`. Thread `financials_q1`/`financials_q2` through `learn_contracts`, `evaluate_contracts` and `_evaluate` as keyword-only args defaulting to None. Add:

```python
def tolerance_content_v4(v3: dict) -> dict:
    """v4 = v3 verbatim + the independent_totals bands (spec 2026-09-29 s5, D-floor). IN-SAMPLE until Q2-2026."""
    import copy, hashlib, json
    v3_sha = hashlib.sha256(json.dumps(v3, sort_keys=True, separators=(",", ":")).encode("ascii")).hexdigest()
    out = copy.deepcopy(v3)
    out["bands"]["standard"][TOTALS_KIND] = dict(fv_residual_pct=5.0, pct_sum_min=50, pct_sum_max=250,
                                                 pct_sum_shift_pp=15, min_positions=5)
    out["bands"]["low_history"][TOTALS_KIND] = dict(fv_residual_pct=10.0, pct_sum_min=50, pct_sum_max=250,
                                                    pct_sum_shift_pp=25, min_positions=5)
    out.update(version=4, v3_verbatim=v3, v3_content_sha256=v3_sha, provisional_kinds=[TOTALS_KIND],
               supersedes=dict(v3.get("supersedes", {}), superseded_v4=v3_sha),
               calibration=dict(v3.get("calibration", {}), v4_quarters_seen=[], v4_basis=
                                "pre-registered 2026-09-30 from oracle A04 bdc_tolerance and A07 defaults; "
                                "not tuned to any replay result"),
               totals_income="evidence only, detection_not_claimed (criterion deferred to sub-project 2)")
    return out
```

`_check_frozen` already compares `c["band"] == band_for(...)`; the totals contract stores `dict(band)` so equality holds.

- [ ] **Step 4: Implement `contracts_run.materialise_financials_slice` and `load_financials`** by copying `materialise_income_slice` (:139-160) with `FINANCIALS_SLICE = "inputs/fund_financials_pilot8.parquet"`, source `<main>/data/output/fund_financials.csv`, the SELECT `lpad(cik,10,'0') AS cik, report_date, investments_at_fair_value, net_assets, total_assets WHERE lpad(cik,10,'0') IN (<PILOT_CIKS>)`; `load_financials(paths, cik, report_date)` runs `SELECT ... FROM read_parquet(?) WHERE cik = ? AND report_date = ?` through `paths.pilot_duckdb()` and returns the single row as a dict or None (raise `ContractError` on more than one row). Add the slice to the pinned inputs list in `run_stage` (:317-323). Pass `financials_q1=load_financials(paths, cik, q1_date)` into `learn_contracts` and `financials_q2=load_financials(paths, cik, q2_date)` into `evaluate_contracts` where `run_stage` calls them.

- [ ] **Step 5: Implement the seed and back-test wiring** per the Interfaces block. In `m2_seed.py`: handler

```python
def _field_scale_flip(ed, receipt, field, fraction, seed, delta):
    # x100 on a seeded fraction of current-period rows carrying the field (deterministic per seed)
    return _scale_flip(ed, receipt, field, fraction, seed, delta)
```

registered as `"fair_value_scale_flip": functools.partial(_field_scale_flip, field="fair_value")` only if `_scale_flip` takes `field` positionally as the plan reads at `:366`; otherwise copy `_scale_flip`'s body with the field bound. `_target_ids` returns `[cik + ":independent_totals:fair_value:whole_filing"]` for `fair_value_scale_flip` and the pct id for `pct_scale_flip`. `pin_tolerances`: accept `version == 4` when `content["v3_verbatim"]["v2_verbatim"]` hashes to `TOLERANCES_V2_SHA256`. In `m2_backtest.py`: `SUITE["independent_totals"] = (TOTALS_FIELD, PCT_FIELD)`; add `--tolerances-version` (choices 2, 3, 4; default 4 when `--semantic` else 2) and derive v4 in memory with `contracts.tolerance_content_v4(contracts.semantic_tolerances(v2))` where v3 is derived today; `_trim` keeps `status_basis`; `_quarter` loads financials per (cik, date) and threads them.

- [ ] **Step 6: Run the tests**

Run: `... --run-id sp1-verify-t4b --no-pre-backstop tests/test_profile_pilot_totals.py tests/test_profile_pilot_contracts.py tests/test_profile_pilot_m2_seed.py tests/test_profile_pilot_m2_backtest.py`
Expected: all PASS, including `test_every_expected_contract_is_in_the_fixed_denominator_with_exactly_one_status` (denominator +2 per CIK under v4 only; v2 runs unchanged) and `test_every_typed_positive_names_a_source_and_known_kinds`.

- [ ] **Step 7: Commit**

```bash
git add scripts/profile_pilot/contracts.py scripts/profile_pilot/contracts_run.py scripts/profile_pilot/m2_seed.py scripts/profile_pilot/m2_backtest.py tests/test_profile_pilot_totals.py tests/test_profile_pilot_contracts.py tests/test_profile_pilot_m2_seed.py tests/test_profile_pilot_m2_backtest.py
git commit -m "Register independent_totals: tolerances v4, pinned financials, seed and back-test wiring" -m "- v4 carries v3 verbatim plus pre-registered totals bands; totals contracts are provisional
- fund_financials_pilot8.parquet pinned beside the income slice; learn/evaluate take financials rows
- seed variants fair_value_scale_flip and pct_scale_flip; back-test SUITE and trim carry the kind"
```

---

### Task 5: `replay_report.py`: score the Q4-to-Q1 pair, evaluate the floors, write the shadow queue

The back-test scores every rolling pair. Sub-project 1 needs one number set per kind for the single pair `2025-12-31 -> 2026-03-31` per CIK, the floors verdict from spec criterion 3, and the drift queue in findings-ledger shape (spec section 5: "breaches and newly-abstained events, ranked by fair value at risk, with violating source rows").

**Files:**
- Create: `scripts/profile_pilot/replay_report.py`
- Test: `tests/test_profile_pilot_replay.py` (new)

**Interfaces:**
- Consumes: a back-test run root (`results/pairs.json`, `results/backtest_results.json`, `results/positives.json`, `results/scoring.json`), a seed run root (`results/sensitivity.json`), the ledger CSV rows, `m2_backtest.ledger_exclusions`, `m2_backtest.score` (signature `score(pairs, results, positives, *, mode, exclude_categories=())`).
- Produces: `python -m scripts.profile_pilot.replay_report run --data-root D --backtest-run-id B --seed-run-id S [--run-id sp1-replay-<stamp>]` writing under its own run root:
  - `results/replay_q4_q1.json`: `{pair_rule, ciks{cik: {pair_id, learn_date, eval_date, gapped}}, per_kind{kind: {pos_units, detected, abstained, missed, recall, neg_n, neg_breach, false_alarm_rate, adjudicated_false_alarm_breaches, unadjudicated_breaches, abstentions[list of (cik, field, cause)]}}, floors{kind: {floor, measured, verdict in PASS|FAIL|NOT_CLAIMED, basis}}, exclusions[...], seeded{kind: {variant, median_smallest_detected, detected_ciks, applicable_ciks}}, sample_label: "IN-SAMPLE (q1p3 adjudicated 2026-08/09; first out-of-sample quarter 2026-06-30)"}`
  - `results/replay_q4_q1.md`: one table per section above.
  - `results/drift_queue.csv` with EXACTLY the ledger header `review_id,state,in_queue,population_origin,verdict_status,verdict_detail,has_fix_route,cik,rule_name,report_date,lane,engine,fv_at_risk_m,fund_quarter_fv_m` plus trailing columns `contract_id,kind,field,cause,n_violating,violating_keys`; one row per `breach` or `newly_abstained` result on the pair; `review_id = "DRIFT_" + sha1(contract_id + eval_date)[:12]`, `state="open"`, `in_queue="shadow"`, `population_origin="live"`, `verdict_status="MISSING"`, `rule_name="drift:" + kind`, `lane="drift"`, `engine="profile_contracts"`, `fv_at_risk_m` = the fair-value sum of the violating rows / 1e6 (0 when no keys), `fund_quarter_fv_m` = the census FV sum / 1e6; sorted by `fv_at_risk_m` descending.

Floor evaluation rules (fixed):
- Structural kinds `source_concept_set`, `fill_rate`, `format_grammar`, `scale`: `PASS` when `recall >= 0.90` AND `false_alarm_rate <= 0.02`, where `false_alarm_rate = (adjudicated_false_alarm_breaches + unadjudicated_breaches) / neg_n` (the UPPER bound: unadjudicated breaches count against the kind); `FAIL` otherwise; when `pos_units == 0`, recall is `null` and the verdict is `NO_POSITIVES` (reported, not PASS).
- `independent_totals`: `PASS` when the seed run's `median_smallest_detected <= 0.20` for `fair_value_scale_flip` AND `detected_ciks == applicable_ciks` (every CIK with a pinned financials row); `FAIL` otherwise; abstentions listed.
- `value_range`, `rate_composition`, `text_agreement`, `fund_income_yield`: verdict `NOT_CLAIMED` with the measured numbers alongside (spec criterion 3, `detection_not_claimed`), unless sub-project 2 later adopts a floor.

- [ ] **Step 1: Write the failing tests** in `tests/test_profile_pilot_replay.py`:

```python
import csv, io
from scripts.profile_pilot import replay_report as rr

LEDGER_HEADER = ("review_id,state,in_queue,population_origin,verdict_status,verdict_detail,has_fix_route,cik,"
                 "rule_name,report_date,lane,engine,fv_at_risk_m,fund_quarter_fv_m")


def _pair(cik, learn, ev, gapped=False):
    return dict(pair_id="rolling:" + cik + ":" + learn + ":" + ev, cik=cik, mode="rolling", learn_date=learn,
                eval_date=ev, gapped=gapped, gap_reasons=[], status="evaluated", labels=[])


def test_select_q4_q1_pair_per_cik_and_flag_gapped_ones():
    pairs = [_pair("A", "2025-12-31", "2026-03-31"), _pair("A", "2025-09-30", "2025-12-31"),
             _pair("B", "2025-09-30", "2026-03-31", gapped=True)]
    chosen = rr.select_pairs(pairs, eval_date="2026-03-31")
    assert chosen["A"]["learn_date"] == "2025-12-31" and chosen["A"]["gapped"] is False
    assert chosen["B"]["gapped"] is True


def test_structural_floor_passes_at_recall_90_and_fp_2_and_fails_below():
    assert rr.floor_verdict("fill_rate", dict(pos_units=10, detected=9, abstained=0, missed=1, neg_n=100,
                                              adjudicated_false_alarm_breaches=1, unadjudicated_breaches=1)) == "PASS"
    assert rr.floor_verdict("fill_rate", dict(pos_units=10, detected=8, abstained=1, missed=1, neg_n=100,
                                              adjudicated_false_alarm_breaches=0, unadjudicated_breaches=0)) == "FAIL"
    assert rr.floor_verdict("fill_rate", dict(pos_units=0, detected=0, abstained=0, missed=0, neg_n=5,
                                              adjudicated_false_alarm_breaches=0, unadjudicated_breaches=0)) == "NO_POSITIVES"
    assert rr.floor_verdict("value_range", dict(pos_units=3, detected=0, abstained=0, missed=3, neg_n=5,
                                                adjudicated_false_alarm_breaches=0, unadjudicated_breaches=0)) == "NOT_CLAIMED"


def test_totals_floor_uses_the_seed_sensitivity():
    ok = dict(median_smallest_detected=0.05, detected_ciks=5, applicable_ciks=5)
    assert rr.totals_verdict(ok) == "PASS"
    assert rr.totals_verdict(dict(ok, detected_ciks=4)) == "FAIL"
    assert rr.totals_verdict(dict(ok, median_smallest_detected=0.3)) == "FAIL"


def test_drift_queue_has_the_ledger_header_and_ranks_by_fv_at_risk():
    results = {"rolling:A:2025-12-31:2026-03-31": [
        dict(contract_id="A:fill_rate:interest_rate:whole_filing", kind="fill_rate", field="interest_rate",
             partition_id="whole_filing", status="breach", cause="fill_dropped", n_violating=2,
             violating_keys=["c1", "c2"], newly_abstained=False),
        dict(contract_id="A:scale:pik_rate:whole_filing", kind="scale", field="pik_rate", partition_id="whole_filing",
             status="insufficient_evidence", cause="unresolved_unit", n_violating=0, violating_keys=[], newly_abstained=True),
        dict(contract_id="A:scale:interest_rate:whole_filing", kind="scale", field="interest_rate",
             partition_id="whole_filing", status="holds", cause=None, n_violating=0, violating_keys=[], newly_abstained=False)]}
    fv = {("A", "2026-03-31"): dict(total=80_000_000.0, by_key={"c1": 5_000_000.0, "c2": 1_000_000.0})}
    text = rr.drift_queue_csv(results, pairs={"A": _pair("A", "2025-12-31", "2026-03-31")}, fv_by_quarter=fv)
    rows = list(csv.DictReader(io.StringIO(text)))
    assert text.splitlines()[0].startswith(LEDGER_HEADER)
    assert [r["rule_name"] for r in rows] == ["drift:fill_rate", "drift:scale"]
    assert rows[0]["fv_at_risk_m"] == "6.0" and rows[0]["fund_quarter_fv_m"] == "80.0"
    assert rows[0]["state"] == "open" and rows[0]["lane"] == "drift" and rows[0]["engine"] == "profile_contracts"
    assert rows[1]["cause"] == "unresolved_unit"
```

- [ ] **Step 2: Run to verify they fail**

Run: `... --run-id sp1-verify-t5a --no-pre-backstop tests/test_profile_pilot_replay.py`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `replay_report.py`** with: `STRUCTURAL = ("source_concept_set", "fill_rate", "format_grammar", "scale")`, `NOT_CLAIMED = ("value_range", "rate_composition", "text_agreement", "fund_income_yield")`, `STRUCTURAL_RECALL_FLOOR = 0.90`, `STRUCTURAL_FP_CEILING = 0.02`, `TOTALS_FRACTION_FLOOR = 0.20`, `EVAL_DATE = "2026-03-31"`, `SAMPLE_LABEL = "IN-SAMPLE (q1p3 adjudicated before this replay; first out-of-sample quarter 2026-06-30)"`; the four functions the tests call (`select_pairs`, `floor_verdict`, `totals_verdict`, `drift_queue_csv`); `per_kind_scores(pairs, results, positives)` calling `m2_backtest.score(...)` once with only the selected pairs and reading `scoring[mode][reading][positive_set]` for `mode="rolling"`, `reading="as_evaluated"`, `positive_set="all"`, then splitting by kind using the `positive_units` list in `scoring.json` (each unit carries `kind`); `fv_by_quarter` computed from the census docs of the selected eval quarter via `contracts_totals.observe_totals(doc, financials=None)["fv_sum"]` and a per-key map `{src_context_id: fair_value}` (positions keyed by `p["identity"]["context_id"]`; confirm the key name against `m2_seed._current_indices` and the census schema before use); `run(paths, *, backtest_run_id, seed_run_id)` writing the three artifacts through `paths.write_once_json` and `manifest.build_manifest`; `main()` with the CLI above inside `protection.protected_session(paths, receipt="verification/<ts>_replay_preservation.json")`. `fv_at_risk_m` and `fund_quarter_fv_m` are formatted with `format(x / 1e6, ".1f")` so the ledger's float columns stay comparable.

- [ ] **Step 4: Run to verify they pass**

Run: `... --run-id sp1-verify-t5b --no-pre-backstop tests/test_profile_pilot_replay.py`. Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/profile_pilot/replay_report.py tests/test_profile_pilot_replay.py
git commit -m "Add the Q4-to-Q1 replay report with floors and the shadow drift queue" -m "- scores only the 2025-12-31 -> 2026-03-31 pair per CIK, per kind, against the widened ledger
- criterion 3 floors: structural recall >= 0.90 at FP <= 0.02 (upper bound), totals seeded flip at <= 0.20, others NOT_CLAIMED
- drift_queue.csv carries the findings-ledger header, ranked by fair value at risk"
```

---

### Task 6: Real runs, replay verdict, changelog and close

All runs take the lease and run ALONE (R36). Order matters: contracts (freezes v4 and pins the financials slice) -> seed -> back-test -> replay report. Confirm first that the base build has exited (Task 1 Step 7 check) and that `<main>/data/output/fund_financials.csv` is the post-base-build file (its mtime must be after the rebuild started, 2026-09-30 08:59); record its sha256 in the ledger, since the pinned slice derives from it.

**Files:**
- Modify: `docs/agent_changelog.md`, `.superpowers/sdd/2026-09-30-sp1-drift-replay/progress.md`, `docs/superpowers/specs/2026-09-29-filer-profile-programme-design.md` (section 8 row 1 status only)

- [ ] **Step 1: Focused suite through the launcher, WITH the backstop** (no `--no-pre-backstop`):

```
python -m scripts.profile_pilot.verify test --data-root "<main>/data" --run-id sp1-verify-full-<stamp> tests/test_profile_pilot_all_quarters.py tests/test_profile_pilot_contracts.py tests/test_profile_pilot_totals.py tests/test_profile_pilot_m2_seed.py tests/test_profile_pilot_m2_backtest.py tests/test_profile_pilot_replay.py
```

Expected: exit 0; backstop count 161 unchanged (record the number printed). Commit anything the run changed under `.superpowers/` only.

- [ ] **Step 2: Contracts run under v4** (real; alone):

```
python -m scripts.profile_pilot.contracts_run run --data-root "<main>/data" --census-run-id sp1-census-<stamp> --profile-run-id stageb-profile-20260929t053308z --run-id sp1-contracts-<stamp> --v2-run-id stageb-contracts-20260929t053506z
```

Expected: `inventories/contract_tolerances.json` content `version == 4`; `results/v2_subset_check.json` reports the v2 subset identical to the pinned v2 run (M1/M2 for v2 kinds byte-identical); `results/m2.json` denominator = 472 + 16 (two totals contracts per CIK); `inputs/fund_financials_pilot8.parquet` pinned with its source sha. If `contracts_run` does not yet emit v4 by default, add a `--tolerances-version 4` flag in the same shape as the back-test's and re-run.

- [ ] **Step 3: Seed run under v4** (real; alone):

```
python -m scripts.profile_pilot.m2_seed run --data-root "<main>/data" --census-run-id sp1-census-<stamp> --profile-run-id stageb-profile-20260929t053308z --contracts-run-id sp1-contracts-<stamp> --run-id sp1-seed-<stamp> --semantic
```

Expected: `results/sensitivity.json` has `fair_value_scale_flip` and `pct_scale_flip` rows; record `median_smallest_detected`, `detected_ciks`, `applicable_ciks` per variant in the ledger BEFORE looking at the back-test.

- [ ] **Step 4: Back-test run under v4** (real; alone):

```
python -m scripts.profile_pilot.m2_backtest run --data-root "<main>/data" --census-run-id sp1-census-<stamp> --contracts-run-id sp1-contracts-<stamp> --run-id sp1-backtest-<stamp> --semantic --seed-run-id sp1-seed-<stamp> --tolerances-version 4
```

Expected: every pilot CIK has an ungapped `2025-12-31 -> 2026-03-31` rolling pair (or the Task 1 residual is carried as `gapped=True` with the reason); `results/scoring.csv` includes kind `independent_totals`; `results/unadjudicated.csv` written.

- [ ] **Step 5: Replay report** (real):

```
python -m scripts.profile_pilot.replay_report run --data-root "<main>/data" --backtest-run-id sp1-backtest-<stamp> --seed-run-id sp1-seed-<stamp> --run-id sp1-replay-<stamp>
```

Expected: `results/replay_q4_q1.md` with the per-kind table, the floors table (PASS / FAIL / NOT_CLAIMED / NO_POSITIVES per kind), the exclusions list with counts by reason, and `results/drift_queue.csv`. Copy `replay_q4_q1.md` and `drift_queue.csv` to `<main>/scratch/2026-09-30_sp1_replay/`.

- [ ] **Step 6: Record and close.** Append a changelog entry `2026-09-30 -- SP1 drift replay Q4-2025 -> Q1-2026 (shadow): results and floors` with: the four run ids; per-kind recall, false-alarm upper bound, abstentions; the floors verdicts verbatim; the seeded totals sensitivity; the exclusions count by reason (the honest denominator); the deviation on income (evidence only); the sample label; and the explicit statement of what was NOT run (no production rebuild, no baseline refresh, no threshold change, drift queue read by nothing downstream). Update spec section 8 row 1 with `status: DONE <date>, run ids ...` and whether criterion 3's structural floor passed. Update the SDD ledger. Commit:

```bash
git add docs/agent_changelog.md docs/superpowers/specs/2026-09-29-filer-profile-programme-design.md .superpowers/sdd/2026-09-30-sp1-drift-replay/progress.md
git commit -m "Record the SP1 Q4-to-Q1 drift replay results" -m "- run ids: census sp1-census-<stamp>, contracts sp1-contracts-<stamp>, seed sp1-seed-<stamp>, back-test sp1-backtest-<stamp>, replay sp1-replay-<stamp>
- floors per kind recorded verbatim; all numbers IN-SAMPLE; drift queue written in shadow only
- income criterion deferred to sub-project 2 (evidence only)"
```

- [ ] **Step 7: STOP.** Sub-project 2's plan is written only after the owner has read the replay verdict; the floors are not adjusted in this sub-project whatever the result.

---

## Self-review

**Spec coverage.** Criterion 3 structural floors: Task 5. Independent totals as a required kind that cannot abstain on a scale flip: Tasks 3 and 4, seeded in 4, floor in 5. Provisional contracts: `status_basis` in Tasks 3 and 4, `provisional_kinds` in v4. Q4-to-Q1 replay reporting recall and false-alarm per kind against q1p3: Tasks 2 and 5. Drift queue in findings-ledger shape ranked by fair value at risk with violating rows: Task 5. Shadow (nothing downstream reads it): Task 6 wording. Adoption rule (5.1): not exercised here; NOT_CLAIMED kinds carried to sub-project 2. Sub-project 0 item (Ares 2022-12-31 amendment scan): Task 1 Step 8 records its outcome. Income reconciliation as a contract (spec section 5): DEVIATION, evidence only, stated in Task 3 and the changelog.

**Placeholders.** Every command is written out. Two facts must be confirmed by the implementer at run time and the plan says where: the census position context key name (Task 5 Step 3) and the `_scale_flip` handler signature (Task 4 Step 5). Both have a fallback stated.

**Type consistency.** `learn_totals` returns a list of contract dicts with the same keys `_check_frozen` requires plus `status_basis`; `evaluate_totals` returns the `_result` shape plus `status_basis`; `_trim` is extended to keep it. `band_for` returns the nested totals dict and the contract stores `dict(band)`, so the frozen-band equality holds. `TOTALS_FIELD`/`PCT_FIELD` are defined in `m2_backtest` (Task 2) and redefined identically in `contracts_totals` (Task 3) to avoid a circular import; Task 4 must assert they are equal in a test (`assert bt.TOTALS_FIELD == ct.TOTALS_FIELD`), added to `tests/test_profile_pilot_totals.py`.
