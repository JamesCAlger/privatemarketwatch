# pct_of_net_assets Sense-Check Re-Lane -- Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the `pct_of_net_assets` recompute-vs-declared comparison from the provenance blocker lane (`filing_mismatch`, tight-fail) to a warn-lane sense check (`pct_sense_check`) with a rounding-aware tolerance, keeping the comparison alive as a cross-check while retiring ~81 of 87 filing_mismatch blocker packets that are comparison artifacts, not data errors.

**Architecture:** Three code changes riding existing machinery: (1) `pipeline/provenance_reverify.py` gets a pct-only rounding-aware tolerance (+-0.005 percentage points, the half-ULP of the filer's 2-decimal disclosure) in BOTH tiers, and a new full_status `pct_recompute_divergence` that `classify_reason` maps to a new reason code `pct_sense_check`; (2) `scripts/shadow_adapter.py` routes `pct_sense_check` to weak/warn (PROV_TIGHT_FAIL is NOT touched -- the ledger-error-verdict parity test must stay green); (3) a per-(cik, report_date) divergence summary artifact supports the future context-pairing investigation. Then a live rebuild propagates the re-lane through shadow ledger -> review queue -> provenance worklist.

**Tech Stack:** Python 3.x, DuckDB (cheap tier SQL), pandas (small aggregates), lxml (full-tier fixtures), pytest.

**Spec:** The 2026-08-25 canary findings + owner decision, recorded in `docs/agent_changelog.md` (entries "ledger-error-classifier CANARY", "canary hardening", "hardened batch + 77ad re-adjudication + pool profile") and quantified in `scratch/2026-08-25_lec_canary/tolerance_profile.py` output. Key facts the plan argues from:
- 44,907 of 45,011 filing_mismatch ledger rows (99.8%) are `pct_of_net_assets`, spanning 20 CIKs / 81 of 87 filing_mismatch packets, all with `fv_at_risk_m = 0`.
- Published pct is a recomputed FV/NAV figure; `declared_raw` is the filer's 2-decimal rounded fraction. Exact comparison (1e-6 relative) can never pass.
- Rounding-aware +-0.005 pp clears 25,727 rows (sub-pattern A: rounding noise). The ~19,180 residual rows (sub-pattern B) are context-to-position misattributions -- a REAL defect signal that must stay visible, in the warn lane.
- Owner decision (conversation 2026-08-25): keep the comparison as a sense check ("it makes sense to compare a recomputed number to their own number"), re-lane it, do NOT widen tolerance to +-5% relative or +-1 pp (measured: they clear 1 and 51 packets respectively but blind the check; the rounding-aware form is the principled one).

## Global Constraints

- ASCII only in all log messages, comments, and generated text (Windows cp1252).
- No pandas `.apply()`/`.iterrows()` on large data. The cheap tier stays DuckDB SQL; new summary aggregation uses vectorized groupby (pct_sense_check rows ~19K -- small).
- `PROV_TIGHT_FAIL` in `scripts/shadow_adapter.py:454` is UNCHANGED. `tests/test_ledger_error_verdict.py::test_tight_codes_match_shadow_adapter` asserts parity with `pipeline/ledger_error_verdict._PROV_TIGHT_FAIL_LOCAL`; both stay as-is. Only `PROV_WEAK_WARN` gains a member.
- Do NOT touch B3-dirty files: `pipeline/verdict_leaf.py`, `pipeline/review_bundles.py`, `pipeline/agent_b2_appliers.py`, `pipeline/correction_leaf.py`, `scripts/agent_b2/*` and their tests.
- Tolerance constant: `PCT_SENSE_TOL_PP = 0.005` (percentage points, absolute). Applied ONLY to `pct_of_net_assets`; monetary fields, `pik_rate`, and other rate fields keep the strict 1e-6 relative comparison.
- New enum values (exact strings, used across all tasks): full_status `"pct_recompute_divergence"`, reason_code `"pct_sense_check"`.
- Pytest write-guard blocks writes to `data/output/`; all tests use in-memory frames / tmp_path.
- Commit style: short subject + 2-4 bullets. Stage only named files.
- The live rebuild (Task 4) regenerates `provenance_ledger.csv` (676MB) and downstream queue artifacts -- check for concurrent pytest/rebuild processes before starting, per AGENTS.md.
- Enforcement context: the provenance_reverify engine rows are `enforcement='advisory'` in the shadow ledger (shadow_adapter.py:531), so quarter-acceptance thresholds v2 are NOT directly gated on these counts. Still document the count changes in the changelog.

## File Structure

| File | Change | Task |
|---|---|---|
| `pipeline/provenance_reverify.py` | pct tolerance both tiers, new status/reason, summary artifact | 1, 3 |
| `tests/test_provenance_reverify.py` | new `TestPctSenseCheck` + summary tests | 1, 3 |
| `scripts/shadow_adapter.py` | `PROV_WEAK_WARN` += `pct_sense_check` | 2 |
| `tests/test_shadow_adapter.py` | lane-membership test | 2 |
| `docs/reference/schemas.md`, `docs/agent_changelog.md` | reason enum + re-lane record | 4 |

---

### Task 1: Rounding-aware pct tolerance + `pct_recompute_divergence` (`pipeline/provenance_reverify.py`)

**Files:**
- Modify: `pipeline/provenance_reverify.py` (module constant near line 30; `_field_sql` CASE around lines 142-166; `full_tier` pub_ok block lines 387-400; `_FULL_REASON` dict line 433; docstring enums lines 298-299 and 445-448)
- Test: `tests/test_provenance_reverify.py` (append new test class; reuse `_row` helper at :18 and the `_cheap`/`_loader` patterns at :224-241)

**Interfaces:**
- Consumes: existing `cheap_tier(holdings_df=...)`, `full_tier(cheap_df, xml_loader=...)`, `classify_reason(cheap_status, full_status)`.
- Produces: module constant `PCT_SENSE_TOL_PP = 0.005`; full_status value `"pct_recompute_divergence"`; reason_code value `"pct_sense_check"` (Tasks 2-4 depend on these exact strings).

- [ ] **Step 1: Write the failing tests** (append to `tests/test_provenance_reverify.py`)

```python
_PCT_FIXTURE_XML = (
    '<xbrl xmlns:us-gaap="http://fasb.org/us-gaap/2024">'
    '<us-gaap:InvestmentOwnedPercentOfNetAssets contextRef="ctxp">0.0043'
    '</us-gaap:InvestmentOwnedPercentOfNetAssets>'
    '</xbrl>'
)


def _pct_loader(cik, accession):
    from lxml import etree
    return etree.ElementTree(etree.fromstring(_PCT_FIXTURE_XML.encode()))


class TestPctSenseCheck:
    """Canary 2026-08-25: pct_of_net_assets published is recomputed FV/NAV while
    declared is the filer's 2-decimal rounded fraction. Rounding-consistent rows
    (within +-0.005 pp) must PASS; divergent rows must route to the new
    pct_recompute_divergence -> pct_sense_check (warn lane), NOT filing_mismatch."""

    # --- cheap tier ---------------------------------------------------------

    def _pct_holding(self, published, raw):
        return _row(
            row_id="ROW-p", pct_of_net_assets=published,
            pct_of_net_assets_source="xbrl_field",
            src_facts=json.dumps({"pct_of_net_assets": {"r": raw}}),
            src_transforms="pct_of_net_assets:rate_x100",
        )

    def test_cheap_rounding_consistent_passes(self):
        # declared 0.0043 -> expected 0.43; published 0.4311 (recomputed): diff 0.0011 pp
        df = pd.DataFrame([self._pct_holding(published=0.4311, raw=0.0043)])
        out = cheap_tier(holdings_df=df)
        row = out[out["field"] == "pct_of_net_assets"].iloc[0]
        assert row["cheap_status"] == "pass"

    def test_cheap_divergent_still_fails(self):
        # declared 0.0159 -> expected 1.59; published 0.004425: diff 1.586 pp
        df = pd.DataFrame([self._pct_holding(published=0.004425, raw=0.0159)])
        out = cheap_tier(holdings_df=df)
        row = out[out["field"] == "pct_of_net_assets"].iloc[0]
        assert row["cheap_status"] == "fail"

    def test_cheap_other_rate_fields_keep_strict_tolerance(self):
        # interest_rate 0.0011-pp slack must NOT pass: strict 1e-6 relative only
        df = pd.DataFrame([_row(
            row_id="ROW-i", interest_rate=10.5011,
            interest_rate_source="xbrl_field",
            src_facts=json.dumps({"interest_rate": {"r": 0.105}}),
            src_transforms="interest_rate:rate_x100")])
        out = cheap_tier(holdings_df=df)
        row = out[out["field"] == "interest_rate"].iloc[0]
        assert row["cheap_status"] == "fail"

    # --- full tier ----------------------------------------------------------

    def _pct_cheap(self, **kw):
        base = {
            "row_id": "ROW-p", "cik": "0001803498",
            "accession_number": "0001803498-25-000081",
            "report_date": "2025-09-30", "src_context_id": "ctxp",
            "field": "pct_of_net_assets", "pathway": "xbrl_field",
            "declared_raw": 0.0043,
            "declared_events": "pct_of_net_assets:rate_x100",
            "published": 0.4311, "expected": 0.43, "cheap_status": "pass",
            "src_facts": json.dumps({"pct_of_net_assets": {
                "c": "investmentownedpercentofnetassets", "r": 0.0043}}),
        }
        return pd.DataFrame([{**base, **kw}])

    def test_full_rounding_consistent_is_raw_match(self):
        out = full_tier(self._pct_cheap(), xml_loader=_pct_loader)
        assert out.iloc[0]["full_status"] == "raw_match"

    def test_full_divergent_is_pct_recompute_divergence(self):
        # instance 0.0043 * 100 = 0.43 vs published 2.0 -> divergent, pct-specific status
        out = full_tier(self._pct_cheap(published=2.0, cheap_status="fail"),
                        xml_loader=_pct_loader)
        assert out.iloc[0]["full_status"] == "pct_recompute_divergence"

    def test_full_monetary_mismatch_still_published_mismatch(self):
        # interest_rate row from the existing fixture keeps the old status
        cheap = pd.DataFrame([{
            "row_id": "ROW-a", "cik": "0001287750",
            "accession_number": "0001287750-26-000001",
            "report_date": "2025-12-31", "src_context_id": "ctx1",
            "field": "interest_rate", "pathway": "xbrl_field",
            "declared_raw": 0.105,
            "declared_events": "interest_rate:rate_x100",
            "published": 99.0, "expected": 10.5, "cheap_status": "fail",
            "src_facts": json.dumps({"interest_rate": {"r": 0.105}}),
        }])
        out = full_tier(cheap, xml_loader=_loader)
        assert out.iloc[0]["full_status"] == "published_mismatch"

    # --- reason triage ------------------------------------------------------

    def test_classify_reason_pct_sense_check(self):
        assert classify_reason("fail", "pct_recompute_divergence") == "pct_sense_check"
        assert classify_reason("pass", "pct_recompute_divergence") == "pct_sense_check"

    def test_classify_reason_filing_mismatch_unchanged(self):
        assert classify_reason("pass", "published_mismatch") == "filing_mismatch"
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_provenance_reverify.py::TestPctSenseCheck -q`
Expected: FAIL -- `test_cheap_rounding_consistent_passes` gets `fail` (strict tolerance), `test_full_divergent_is_pct_recompute_divergence` gets `published_mismatch`, `test_classify_reason_pct_sense_check` gets `filing_mismatch`. The two "unchanged" guards should already PASS.

- [ ] **Step 3: Implement**

(a) Module constant, near the other module-level constants (after the logger, ~line 30):

```python
# Rounding-aware tolerance for the pct_of_net_assets sense check, in percentage
# points. Filers disclose pct to 2 decimals; published is a recomputed FV/NAV
# figure, so agreement within half-ULP of the disclosure (+-0.005 pp) is
# confirmation, not error. Canary 2026-08-25.
PCT_SENSE_TOL_PP = 0.005
```

(b) Cheap tier -- in `_field_sql`, add a pct-only pass branch. Immediately before the final strict-comparison WHEN clause (`WHEN ABS({expected} - {published}) <= 1e-6 * GREATEST(...)`), insert a conditional fragment defined next to `rate_absent_trivial` (~line 124):

```python
    # pct_of_net_assets: published is recomputed FV/NAV, declared is the filer's
    # 2-decimal rounded fraction -- exact equality is unreachable. Within the
    # disclosure's rounding tolerance -> pass (sense check confirmed).
    pct_round_pass = (
        f"WHEN ABS({expected} - {published}) <= {PCT_SENSE_TOL_PP} THEN 'pass'"
        if field == "pct_of_net_assets" else ""
    )
```

and place `{pct_round_pass}` in the CASE template on its own line directly above the strict-comparison WHEN.

(c) Full tier -- replace lines 392-400 (`if neg_null: ... continue`) with:

```python
                if neg_null:
                    pub_ok = pd.isna(published) and instance_raw < 0
                else:
                    pub_ok = (not pd.isna(published)
                              and _numbers_close(instance_raw * mult, float(published)))
                    if (not pub_ok and field == "pct_of_net_assets"
                            and not pd.isna(published)):
                        # Rounding-aware sense-check tolerance (see PCT_SENSE_TOL_PP)
                        pub_ok = abs(instance_raw * mult
                                     - float(published)) <= PCT_SENSE_TOL_PP

                if not pub_ok:
                    out.at[i, "full_status"] = (
                        "pct_recompute_divergence"
                        if field == "pct_of_net_assets"
                        else "published_mismatch")
                    continue
```

(d) Reason triage -- add to `_FULL_REASON` (line 433, after the `published_mismatch` entry):

```python
    "pct_recompute_divergence": "pct_sense_check",
```

(e) Update the two docstring enums: `full_tier` (:298-299) gains `pct_recompute_divergence`; `classify_reason` (:445-448) gains `pct_sense_check`.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_provenance_reverify.py -q`
Expected: all pass (new class + all pre-existing tests -- the strict-tolerance and monetary paths are unchanged).

- [ ] **Step 5: Commit**

```bash
git add pipeline/provenance_reverify.py tests/test_provenance_reverify.py
git commit -m "provenance-reverify: pct sense-check tolerance + pct_recompute_divergence

- pct_of_net_assets gets +-0.005pp rounding-aware tolerance in both tiers
  (published is recomputed FV/NAV vs filer's 2-decimal disclosure)
- residual divergence routes to new pct_recompute_divergence -> pct_sense_check
  reason; monetary/rate fields keep strict 1e-6 relative comparison"
```

---

### Task 2: Route `pct_sense_check` to the warn lane (`scripts/shadow_adapter.py`)

**Files:**
- Modify: `scripts/shadow_adapter.py:456-457` (`PROV_WEAK_WARN`)
- Test: `tests/test_shadow_adapter.py` (append one test)

**Interfaces:**
- Consumes: reason string `"pct_sense_check"` from Task 1.
- Produces: shadow-ledger rows with `tier='weak'`, `status='warn'` for `pct_sense_check` groups; blocker-lane membership unchanged. (Note: unknown codes already default to warn per the `ELSE 'warn'` at :538 -- the explicit membership makes the routing declared, not accidental, and documents intent.)

- [ ] **Step 1: Write the failing test** (append to `tests/test_shadow_adapter.py`, mirroring that file's existing import of the module; if it imports via `sys.path` injection of `scripts/`, reuse that pattern):

```python
def test_pct_sense_check_is_warn_lane_not_tight():
    """Canary re-lane 2026-08-25: pct_sense_check must be weak/warn and must
    NOT join the tight-fail (blocker) set -- PROV_TIGHT_FAIL is frozen by the
    ledger_error_verdict parity test."""
    assert "pct_sense_check" in PROV_WEAK_WARN
    assert "pct_sense_check" not in PROV_TIGHT_FAIL
    assert "filing_mismatch" in PROV_TIGHT_FAIL  # monetary mismatches stay blockers
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_shadow_adapter.py -q -k pct_sense_check`
Expected: FAIL -- `"pct_sense_check" in PROV_WEAK_WARN` is False.

- [ ] **Step 3: Implement** -- edit `scripts/shadow_adapter.py:456`:

```python
PROV_WEAK_WARN = {"anchor_stale", "no_provenance", "text_pathway",
                  "merged_context_excluded", "pct_sense_check"}
```

and extend the comment block above (:450-453) with one line: `# pct_sense_check: recompute-vs-disclosure divergence on the derived pct field -- sense-check signal, not a pointer-verification failure (re-laned 2026-08-25).`

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_shadow_adapter.py -q && python -m pytest "tests/test_ledger_error_verdict.py::test_tight_codes_match_shadow_adapter" -q`
Expected: both green. The parity test MUST pass untouched -- if it fails, PROV_TIGHT_FAIL was modified by mistake; revert that.

- [ ] **Step 5: Commit**

```bash
git add scripts/shadow_adapter.py tests/test_shadow_adapter.py
git commit -m "shadow-adapter: pct_sense_check routes weak/warn

- new provenance reason joins PROV_WEAK_WARN; PROV_TIGHT_FAIL untouched
  (ledger_error_verdict parity test stays green)"
```

---

### Task 3: Divergence summary artifact for the pairing investigation

**Files:**
- Modify: `pipeline/provenance_reverify.py` (new function after `classify_reason`; one call inside `build_ledger` after `ledger["reason_code"]` is assigned, before the return)
- Test: `tests/test_provenance_reverify.py` (append `TestPctSenseSummary`)

**Interfaces:**
- Consumes: the in-memory `ledger` frame inside `build_ledger` (columns incl. `cik`, `report_date`, `row_id`, `reason_code`, `expected`, `published`).
- Produces: `pct_sense_check_summary(ledger: pd.DataFrame) -> pd.DataFrame` with columns `["cik", "report_date", "n_rows", "median_expected_pp", "median_published_pp", "median_abs_diff_pp"]`; CSV artifact `data/output/provenance_pct_sense_check_summary.csv`. `build_ledger`'s return signature stays `tuple[Path, Path]` (callers unchanged).

- [ ] **Step 1: Write the failing tests**

```python
class TestPctSenseSummary:
    def _ledger(self):
        return pd.DataFrame([
            {"cik": "0001803498", "report_date": "2025-09-30", "row_id": "ROW-1",
             "reason_code": "pct_sense_check", "expected": 1.59, "published": 0.0044},
            {"cik": "0001803498", "report_date": "2025-09-30", "row_id": "ROW-2",
             "reason_code": "pct_sense_check", "expected": 2.22, "published": 0.0062},
            {"cik": "0001287750", "report_date": "2025-12-31", "row_id": "ROW-3",
             "reason_code": "verified", "expected": 10.5, "published": 10.5},
        ])

    def test_groups_and_medians(self):
        from pipeline.provenance_reverify import pct_sense_check_summary
        out = pct_sense_check_summary(self._ledger())
        assert list(out.columns) == ["cik", "report_date", "n_rows",
                                     "median_expected_pp", "median_published_pp",
                                     "median_abs_diff_pp"]
        assert len(out) == 1  # only the pct_sense_check group
        row = out.iloc[0]
        assert row["n_rows"] == 2
        assert row["median_abs_diff_pp"] == pytest.approx((1.5856 + 2.2138) / 2)

    def test_empty_ledger_gives_empty_frame(self):
        from pipeline.provenance_reverify import pct_sense_check_summary
        out = pct_sense_check_summary(self._ledger().iloc[2:3])
        assert out.empty

    def test_build_ledger_writes_summary_artifact(self, tmp_path):
        tier = pd.DataFrame([{
            "row_id": "ROW-1", "cik": "0001803498", "accession_number": "a",
            "report_date": "2025-09-30", "src_context_id": "c-1", "src_facts": "",
            "field": "pct_of_net_assets", "pathway": "xbrl_field",
            "declared_raw": 0.0159, "declared_events": "",
            "published": 0.0044, "expected": 1.59,
            "cheap_status": "fail", "full_status": "pct_recompute_divergence",
            "instance_raw": 0.0159,
        }])
        build_ledger(tier, out_dir=tmp_path)
        art = tmp_path / "provenance_pct_sense_check_summary.csv"
        assert art.exists()
        got = pd.read_csv(art, dtype={"cik": str})
        assert got.iloc[0]["n_rows"] == 1
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_provenance_reverify.py::TestPctSenseSummary -q`
Expected: FAIL with ImportError (`pct_sense_check_summary` not defined).

- [ ] **Step 3: Implement**

Function (after `classify_reason`):

```python
def pct_sense_check_summary(ledger: pd.DataFrame) -> pd.DataFrame:
    """Per (cik, report_date) profile of pct_sense_check divergences.

    Supports the context-to-position pairing investigation: a quarter where
    every position diverges by a similar factor points at a denominator or
    pairing defect; scattered large diffs point at per-position misattribution.
    Vectorized; the pct_sense_check population is ~19K rows.
    """
    cols = ["cik", "report_date", "n_rows", "median_expected_pp",
            "median_published_pp", "median_abs_diff_pp"]
    rows = ledger[ledger["reason_code"] == "pct_sense_check"].copy()
    if rows.empty:
        return pd.DataFrame(columns=cols)
    rows["expected_pp"] = pd.to_numeric(rows["expected"], errors="coerce")
    rows["published_pp"] = pd.to_numeric(rows["published"], errors="coerce")
    rows["abs_diff_pp"] = (rows["expected_pp"] - rows["published_pp"]).abs()
    out = (rows.groupby(["cik", "report_date"], dropna=False)
           .agg(n_rows=("row_id", "nunique"),
                median_expected_pp=("expected_pp", "median"),
                median_published_pp=("published_pp", "median"),
                median_abs_diff_pp=("abs_diff_pp", "median"))
           .reset_index())
    return out[cols]
```

Call site in `build_ledger`, immediately before `summary_path = out_dir / "provenance_ledger_summary.csv"` (line 548):

```python
    pct_summary = pct_sense_check_summary(ledger)
    pct_summary_path = out_dir / "provenance_pct_sense_check_summary.csv"
    pct_summary.to_csv(pct_summary_path, index=False)
    logger.info("pct sense-check summary: %d cik-quarters -> %s",
                len(pct_summary), pct_summary_path)
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_provenance_reverify.py -q`
Expected: all green (build_ledger's return signature unchanged, existing build_ledger tests unaffected -- they will now also write the extra CSV into their tmp dirs, which is harmless).

- [ ] **Step 5: Commit**

```bash
git add pipeline/provenance_reverify.py tests/test_provenance_reverify.py
git commit -m "provenance-reverify: pct_sense_check divergence summary artifact

- per (cik, report_date) medians of expected/published/abs-diff for the
  warn-lane pct divergences; input for the context-pairing investigation"
```

---

### Task 4: Live rebuild, queue regeneration, verification, docs

No new code -- operator steps propagating the re-lane through the artifact chain. Check for concurrent pytest/rebuild/codex processes first (`Get-Process -Name codex,pytest,python -ErrorAction SilentlyContinue`); do not overlap with another agent's rebuild.

- [ ] **Step 1: Regenerate the provenance ledger** (cached filings only, no network):

```powershell
python -m pipeline.provenance_reverify --cohort
```

Expected log tail: ledger + summary + the NEW `provenance_pct_sense_check_summary.csv` paths.

- [ ] **Step 2: Rebuild the shadow ledger and review queue:**

```powershell
python scripts\shadow_validation_runner.py
python -m pipeline.review_queue --emit-provenance-worklist
```

- [ ] **Step 3: Verify the re-lane landed** (read-only checks; record actual numbers):

```powershell
# (a) ledger reason profile -- expect filing_mismatch ~100 rows (monetary+pik only)
#     and pct_sense_check ~19,000 rows
python scratch\2026-08-25_lec_canary\ledger_mismatch_profile.py

# (b) provenance worklist -- expect ~26 packets (6-7 filing_mismatch + 20 anchor_missing),
#     down from 107; zero pct-only packets in the blocker lane
Import-Csv data\output\review_queue\provenance_worklist.csv |
  Group-Object reason_code | Select-Object Name, Count
```

Acceptance: `filing_mismatch` blocker packets <= 10 (was 87); `pct_sense_check` appears ONLY in the review lane of `review_queue.csv` (`Import-Csv ... | Where-Object { $_.rule_name -eq 'pct_sense_check' } | Group-Object lane` shows `review` only); `python scripts/diff_outputs.py --semantic` run and its provenance-related deltas documented (the ledger reason redistribution is the intended change).

- [ ] **Step 4: Rebuild the classifier batch from the new worklist** (the old batches cite pct packets that no longer exist in the blocker lane):

```powershell
python -m scripts.ledger_error_classifier.build_dispatch --batch-id lec_postrelane_<date> --top-n 10
```

Note in the changelog: prior pct-citing verdicts (e.g. `RVQ_BLK_77ad57cdee2c` in `lec_hard_20260825`) are now REFUSED by the intake gate's tight-code check -- by design, their packets dissolved with the re-lane.

- [ ] **Step 5: Docs.** `docs/reference/schemas.md`: add `pct_sense_check` to the provenance reason enum wherever `filing_mismatch`/`anchor_missing` are listed, with one line: "recompute-vs-disclosure divergence on the derived pct field; warn lane, never packetized as a blocker". `docs/agent_changelog.md`: APPEND dated entry with before/after counts from Step 3 (rows by reason, packets by reason, worklist size 107 -> actual), the artifact name, and the standing scope note: **the context-to-position pairing defect (sub-pattern B, ~19K rows) is NOT fixed by this change -- it is now measured by `provenance_pct_sense_check_summary.csv` and awaits its own investigation; do not suppress the warn lane to make it disappear.**

- [ ] **Step 6: Commit docs** (`git add docs/reference/schemas.md docs/agent_changelog.md`), message: `"docs: pct_sense_check re-lane record (blocker 87 -> N packets)"` + bullets with the measured counts.

---

## Explicitly Out of Scope

- **Fixing the context-to-position pairing** (sub-pattern B root cause). That investigation starts from the Task 3 artifact; it may implicate `src_context_id` assignment in the extractor and needs its own plan with source-filing evidence.
- **Widening any tolerance beyond +-0.005 pp.** Measured (2026-08-25): +-5% relative clears 1/87 packets; +-1 pp clears 51 but waves through ~15K misattributed rows. Both rejected.
- **Changing PROV_TIGHT_FAIL** or the ledger-error-verdict gate.
- **Retiring the comparison.** Owner decision: it stays, as a warn-lane sense check.

## Self-Review Notes

- Spec coverage: re-lane (Tasks 1-2), rounding tolerance both tiers (Task 1), pairing-fix scoping via measurement artifact + out-of-scope note (Task 3, Out of Scope), live propagation + counts (Task 4). Owner's "keep the comparison" honored: rounding-consistent rows become verified confirmations; divergent rows stay visible in the warn lane.
- Type consistency: `PCT_SENSE_TOL_PP`, `"pct_recompute_divergence"`, `"pct_sense_check"`, `pct_sense_check_summary`, `provenance_pct_sense_check_summary.csv` used identically across tasks.
- The cheap-tier `transform_drift` interaction is covered: with the Task 1 cheap-tier tolerance, rounding-consistent pct rows are cheap `pass` + full `raw_match` -> `verified` (not `transform_drift`), because both tiers apply the same tolerance. Divergent rows are cheap `fail` + full `pct_recompute_divergence` -> `pct_sense_check` (the `_FULL_REASON` lookup precedes the `raw_match`/`transform_drift` branch in `classify_reason`).
