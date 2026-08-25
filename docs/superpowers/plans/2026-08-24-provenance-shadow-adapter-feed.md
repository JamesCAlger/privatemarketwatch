# Provenance Feed into the Shadow Ledger -- Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route the provenance re-verifier's verdicts into the existing shadow ledger so unverified/mismatched rows reach the B1/B2 agent queues through the same machinery as every other check -- with the scoping doc's mandatory dedup against the source-reconciliation packets already in the ledger, so no row is remediated twice.

**Architecture:** One new adapter feed (`_provenance_select()` in `scripts/shadow_adapter.py`) aggregates `data/output/provenance_ledger.csv` -- (row_id, field)-grained, ~2.1M rows -- to the ledger's `(cik, report_date, rule_name)` grain, where `rule_name = reason_code`. Actionable reason codes enter as `tight/fail` (blocker lane); informational codes as `weak/warn` (review lane); verified/derived/corrected/unchecked as `pass` rows for coverage measurement. Before aggregation, a row-level anti-join excludes provenance rows whose fact anchor (`src:<accession>:<src_context_id>`) already appears in a blocking source-reconciliation packet for the same cik-quarter -- the 8.1 dedup -- with the excluded count emitted as an audit row (no silent truncation). The raw provenance ledger becomes the drill-down evidence artifact for review bundles, and the quarter-pass battery gains a provenance stage so the feed is never stale within a pass.

**Tech Stack:** Python 3.x, DuckDB SQL (the adapter's native idiom), pytest. No new dependencies.

**Spec:** `docs/provenance_columns_scoping.md` sections 8.1-8.2 (field-level ledger keying, MANDATORY dedup against existing queues, deterministic triage feeding lanes). Factual basis: the 2026-08-24 shadow-architecture scout (summarized in Global Constraints below -- the plan is self-contained). Reason-code semantics: `docs/reference/schemas.md` (provenance ledger section).

## Global Constraints

(scout-verified facts every task builds on -- treat as binding)
- Ledger contract: 13 columns exactly -- `engine, rule_name, tier, enforcement, cik, period_kind, period, status, metric, metric_name, n_units, mechanism, src_confidence`; `metric`/`n_units` numeric, rest VARCHAR; hard-asserted by `_assert_ledger_contract()` in `scripts/shadow_validation_runner.py` (~:105-125) before the UNION ALL.
- Feed pattern: a private `_<name>_select() -> str | None` in `scripts/shadow_adapter.py` returning a DuckDB SELECT fragment (or None when the source file is absent), registered in `adapter_selects()` (~:448-455). Model feed: `_source_recon_select()` (~:95-154).
- Tier semantics: `tight` -> blocker lane, gate-eligible; `weak` -> review lane, status pass|warn only (a weak row must never carry status 'fail'). All adapter feeds use `enforcement='advisory'`.
- Queue derivation: `pipeline/review_queue.py` reads `data/output/shadow/validation_results_ledger.csv`, keeps status in {fail, warn}, lanes by tier, writes `data/output/review_queue/review_queue.csv`; evidence bundles come from `pipeline/review_bundles.py` EVIDENCE_SPECS.
- Dedup join: provenance ledger rows carry `row_id, cik, report_date, accession_number, src_context_id, field, reason_code, published, cheap_status, full_status`. Source-recon's source-only detail (`data/output/source_reconciliation_source_only_detail.csv`) carries `source_row_id = 'src:'<accession>':'<context_id>` (possibly `#k`-suffixed), `cik, report_date, mechanism, is_blocking`; residual classification carries `(cik, report_date, mechanism, blocking_issue)`.
- Reason-code -> tier/status mapping (THE design decision, fixed here):
  - `tight` + `fail`: `filing_mismatch, anchor_missing, provenance_wrong, source_unavailable, transform_drift`
  - `weak` + `warn`: `anchor_stale` (maintenance: re-stamp, not a data error), `no_provenance, text_pathway, merged_context_excluded`
  - `weak` + `pass`: `verified, corrected, derived, unchecked_trivial` (coverage measurement only; never queued)
- AGENTS.md contracts: ASCII-only; no inline `python -`; DuckDB for the 2.1M-row work (no pandas row loops); pytest write-guard (tests use tmp_path + monkeypatched config paths); stage only named files, never `git add -A`/`-u`; the B3 workstream's dirty files (`pipeline/agent_b2_appliers.py`, `pipeline/correction_leaf.py`, `pipeline/review_bundles.py` -- NOTE: review_bundles.py IS dirty -- `pipeline/verdict_leaf.py`, `scripts/agent_b2/*`, their tests) must not be swept into commits: check `git diff HEAD -- <file>` before staging; if Task 2's edit lands in dirty `pipeline/review_bundles.py`, use the selective-staging procedure (filtered patch + `git apply --cached`, commit WITHOUT pathspec) documented in `.superpowers/sdd/2026-08-23-provenance-steps2-4-srcfacts-reverifier/task-5-report.md`, and verify the committed tree in a temp worktree.
- The shadow runner is read-only over its inputs and stale-tolerant by design ("ledger row reflects whatever the last pipeline run wrote"); freshness inside a quarter pass comes from battery ordering (Task 3).
- No gate behavior changes: everything this plan adds is `enforcement='advisory'`. Quarter-acceptance thresholds are untouched.

## File Structure

| File | Change | Task |
|---|---|---|
| `scripts/shadow_adapter.py` | `_provenance_select()` + registration + reason-code tier/status maps | 1 |
| `tests/test_shadow_adapter.py` (or the file housing existing adapter tests -- locate with `rg -l "adapter_selects\|_source_recon_select" tests/`; create `tests/test_shadow_adapter.py` if none exists) | feed tests | 1 |
| `pipeline/review_bundles.py` | EVIDENCE_SPECS entry for provenance drill-down (DIRTY FILE -- selective staging) | 2 |
| `scripts/run_quarter_pass.py` | provenance stage before the shadow stage | 3 |
| `docs/reference/schemas.md`, `docs/agent_changelog.md` | feed mapping + run record | 3 |

---

### Task 1: The adapter feed with 8.1 dedup

**Files:**
- Modify: `scripts/shadow_adapter.py` (new `_provenance_select()`; register in `adapter_selects()`; module-level maps)
- Test: `tests/test_shadow_adapter.py` (locate or create per File Structure)

**Interfaces:**
- Consumes: `config.PROVENANCE_LEDGER_FILE` (exists, `data/output/provenance_ledger.csv`), `SOURCE_RECONCILIATION_SOURCE_ONLY_DETAIL_FILE` (already imported by the module).
- Produces: `_provenance_select() -> str | None` emitting, per `(cik, report_date, reason_code)` group present in the provenance ledger:
  - `engine='provenance_reverify'`, `rule_name=reason_code`, tier/status per the Global Constraints map, `enforcement='advisory'`, `period_kind='quarter'`, `period=report_date`, `metric=ROUND(SUM(fv_at_risk)/1e6, 2)` where fv_at_risk sums `published` over the group's fair_value-field rows only (0.0 for groups with no fair_value rows), `metric_name='affected_fv_m'`, `n_units=COUNT(DISTINCT row_id)`, `mechanism=reason_code`, `src_confidence=NULL`.
  - PLUS one audit row per cik-quarter where dedup excluded anything: `rule_name='provenance_already_queued'`, `tier='weak'`, `status='pass'`, `n_units=<excluded distinct row_ids>`, `metric=excluded fv $M`, `metric_name='affected_fv_m'`, `mechanism='dedup_source_recon'`.
  - Dedup rule (applies ONLY to the tight/fail codes; informational codes are not queue items so they are not deduped): exclude ledger rows whose `'src:' || accession_number || ':' || src_context_id` matches a `source_row_id` (with any `#k` suffix stripped via `regexp_replace(source_row_id, '#[0-9]+$', '')`) among BLOCKING source-only-detail rows of the same `(cik, report_date)`.
  - Returns None when the provenance ledger file does not exist.

- [ ] **Step 1: Write the failing tests**

In the adapter test file (module-level helpers; follow the existing file's fixture style if one exists, else this standalone pattern -- the feed is testable by executing its fragment in DuckDB against fixture CSVs):

```python
import duckdb
import pandas as pd


def _prov_rows(rows):
    base = {
        "row_id": "ROW-0000000000000001", "cik": "0001287750",
        "accession_number": "0001287750-26-000001", "report_date": "2025-12-31",
        "src_context_id": "ctx1", "field": "fair_value",
        "reason_code": "verified", "published": 1000000.0,
        "cheap_status": "pass", "full_status": "raw_match",
    }
    return pd.DataFrame([{**base, **r} for r in rows])


def _run_fragment(monkeypatch, tmp_path, prov_df, so_detail_df=None):
    import scripts.shadow_adapter as adp
    prov = tmp_path / "provenance_ledger.csv"
    prov_df.to_csv(prov, index=False)
    monkeypatch.setattr(adp, "PROVENANCE_LEDGER_FILE", prov, raising=False)
    so = tmp_path / "source_only_detail.csv"
    if so_detail_df is None:
        so_detail_df = pd.DataFrame(columns=[
            "cik", "report_date", "accession_number", "source_row_id",
            "mechanism", "is_blocking"])
    so_detail_df.to_csv(so, index=False)
    monkeypatch.setattr(adp, "SOURCE_RECONCILIATION_SOURCE_ONLY_DETAIL_FILE",
                        so, raising=False)
    frag = adp._provenance_select()
    assert frag is not None
    return duckdb.connect().execute(frag).fetchdf()


class TestProvenanceFeed:
    def test_tier_status_mapping(self, monkeypatch, tmp_path):
        df = _prov_rows([
            {"row_id": "ROW-a", "reason_code": "filing_mismatch"},
            {"row_id": "ROW-b", "reason_code": "no_provenance"},
            {"row_id": "ROW-c", "reason_code": "verified"},
        ])
        out = _run_fragment(monkeypatch, tmp_path, df).set_index("rule_name")
        assert out.loc["filing_mismatch", "tier"] == "tight"
        assert out.loc["filing_mismatch", "status"] == "fail"
        assert out.loc["no_provenance", "tier"] == "weak"
        assert out.loc["no_provenance", "status"] == "warn"
        assert out.loc["verified", "tier"] == "weak"
        assert out.loc["verified", "status"] == "pass"
        assert (out["engine"] == "provenance_reverify").all()
        assert (out["enforcement"] == "advisory").all()

    def test_aggregation_and_fv_metric(self, monkeypatch, tmp_path):
        df = _prov_rows([
            {"row_id": "ROW-a", "field": "fair_value",
             "reason_code": "filing_mismatch", "published": 2000000.0},
            {"row_id": "ROW-a", "field": "interest_rate",
             "reason_code": "filing_mismatch", "published": 10.5},
            {"row_id": "ROW-b", "field": "cost",
             "reason_code": "filing_mismatch", "published": 999.0},
        ])
        out = _run_fragment(monkeypatch, tmp_path, df)
        row = out[out["rule_name"] == "filing_mismatch"].iloc[0]
        assert row["n_units"] == 2            # distinct row_ids
        assert row["metric"] == 2.0           # only the fair_value row, $M
        assert row["metric_name"] == "affected_fv_m"

    def test_dedup_excludes_already_queued_and_audits(self, monkeypatch, tmp_path):
        prov = _prov_rows([
            {"row_id": "ROW-a", "src_context_id": "ctxQ",
             "reason_code": "filing_mismatch", "published": 3000000.0},
            {"row_id": "ROW-b", "src_context_id": "ctxF",
             "reason_code": "filing_mismatch", "published": 1000000.0},
        ])
        so = pd.DataFrame([{
            "cik": "0001287750", "report_date": "2025-12-31",
            "accession_number": "0001287750-26-000001",
            "source_row_id": "src:0001287750-26-000001:ctxQ#2",
            "mechanism": "blocking_source_pct_leaf_parser_mismatch",
            "is_blocking": True,
        }])
        out = _run_fragment(monkeypatch, tmp_path, prov, so)
        fm = out[out["rule_name"] == "filing_mismatch"].iloc[0]
        assert fm["n_units"] == 1             # ROW-a excluded (ctxQ queued)
        assert fm["metric"] == 1.0
        audit = out[out["rule_name"] == "provenance_already_queued"].iloc[0]
        assert audit["status"] == "pass" and audit["n_units"] == 1
        assert audit["mechanism"] == "dedup_source_recon"

    def test_informational_codes_not_deduped(self, monkeypatch, tmp_path):
        prov = _prov_rows([
            {"row_id": "ROW-a", "src_context_id": "ctxQ",
             "reason_code": "no_provenance"}])
        so = pd.DataFrame([{
            "cik": "0001287750", "report_date": "2025-12-31",
            "accession_number": "0001287750-26-000001",
            "source_row_id": "src:0001287750-26-000001:ctxQ",
            "mechanism": "m", "is_blocking": True}])
        out = _run_fragment(monkeypatch, tmp_path, prov, so)
        assert out[out["rule_name"] == "no_provenance"].iloc[0]["n_units"] == 1

    def test_absent_file_returns_none(self, monkeypatch, tmp_path):
        import scripts.shadow_adapter as adp
        monkeypatch.setattr(adp, "PROVENANCE_LEDGER_FILE",
                            tmp_path / "missing.csv", raising=False)
        assert adp._provenance_select() is None

    def test_fragment_satisfies_ledger_contract(self, monkeypatch, tmp_path):
        # 13 columns, exact names/order per LEDGER_COLUMNS in the runner
        out = _run_fragment(monkeypatch, tmp_path, _prov_rows([{}]))
        assert list(out.columns) == [
            "engine", "rule_name", "tier", "enforcement", "cik",
            "period_kind", "period", "status", "metric", "metric_name",
            "n_units", "mechanism", "src_confidence"]
```

(Adapt the monkeypatch targets to how the module actually holds the paths -- if it imports the constants at module top, patch the module attributes as shown; if `PROVENANCE_LEDGER_FILE` is not yet imported there, the implementation adds the import. If an existing adapter test file has its own fixture helpers for fragment execution, reuse them instead of `_run_fragment`.)

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_shadow_adapter.py -k Provenance -v`
Expected: FAIL -- `_provenance_select` does not exist.

- [ ] **Step 3: Implement**

In `scripts/shadow_adapter.py`, add near the tier maps:

```python
# Provenance re-verifier reason codes (pipeline/provenance_reverify.py).
# tight/fail = pointer-verification failures that belong in the blocker lane;
# weak/warn = informational states (incl. anchor_stale: re-stamp maintenance,
# not a data error); weak/pass = healthy states kept for coverage measurement.
PROV_TIGHT_FAIL = {"filing_mismatch", "anchor_missing", "provenance_wrong",
                   "source_unavailable", "transform_drift"}
PROV_WEAK_WARN = {"anchor_stale", "no_provenance", "text_pathway",
                  "merged_context_excluded"}
# everything else (verified, corrected, derived, unchecked_trivial) -> weak/pass
```

Then `_provenance_select()` following the module's established shape (file-exists guard returning None; a single SELECT fragment). The fragment (DuckDB; adapt quoting to the module's `_p()` path helper if one exists):

```python
def _provenance_select() -> str | None:
    """Provenance re-verifier verdicts, aggregated to (cik, quarter, reason_code).

    8.1 dedup: tight-lane rows whose fact anchor (src:<accession>:<context>)
    already sits in a BLOCKING source-only packet for the same cik-quarter are
    excluded from the queue-facing groups and counted in a per-cik-quarter
    'provenance_already_queued' audit row instead (no silent truncation).
    """
    if not PROVENANCE_LEDGER_FILE.exists():
        return None
    prov = str(PROVENANCE_LEDGER_FILE).replace("\\", "/")
    so = str(SOURCE_RECONCILIATION_SOURCE_ONLY_DETAIL_FILE).replace("\\", "/")
    so_exists = SOURCE_RECONCILIATION_SOURCE_ONLY_DETAIL_FILE.exists()
    tight = ", ".join(f"'{c}'" for c in sorted(PROV_TIGHT_FAIL))
    warn = ", ".join(f"'{c}'" for c in sorted(PROV_WEAK_WARN))
    queued_cte = (f"""
        queued AS (
            SELECT DISTINCT cik, report_date,
                   regexp_replace(source_row_id, '#[0-9]+$', '') AS anchor
            FROM read_csv_auto('{so}', header=true, all_varchar=true)
            WHERE lower(COALESCE(is_blocking, '')) IN ('true', '1')
        ),""" if so_exists else """
        queued AS (
            SELECT NULL AS cik, NULL AS report_date, NULL AS anchor WHERE 1=0
        ),""")
    return f"""
    WITH {queued_cte}
    prov AS (
        SELECT p.*,
               'src:' || COALESCE(p.accession_number, '') || ':'
                      || COALESCE(p.src_context_id, '') AS anchor,
               (q.anchor IS NOT NULL
                AND p.reason_code IN ({tight})) AS already_queued
        FROM read_csv_auto('{prov}', header=true, all_varchar=true) p
        LEFT JOIN queued q
          ON q.cik = p.cik AND q.report_date = p.report_date
         AND q.anchor = 'src:' || COALESCE(p.accession_number, '') || ':'
                              || COALESCE(p.src_context_id, '')
    ),
    grouped AS (
        SELECT cik, report_date, reason_code,
               COUNT(DISTINCT row_id) AS n_rows,
               ROUND(COALESCE(SUM(CASE WHEN field = 'fair_value'
                     THEN TRY_CAST(published AS DOUBLE) END), 0) / 1e6, 2)
                   AS fv_m
        FROM prov WHERE NOT already_queued
        GROUP BY 1, 2, 3
    ),
    excluded AS (
        SELECT cik, report_date,
               COUNT(DISTINCT row_id) AS n_rows,
               ROUND(COALESCE(SUM(CASE WHEN field = 'fair_value'
                     THEN TRY_CAST(published AS DOUBLE) END), 0) / 1e6, 2)
                   AS fv_m
        FROM prov WHERE already_queued
        GROUP BY 1, 2
    )
    SELECT 'provenance_reverify' AS engine,
           reason_code AS rule_name,
           CASE WHEN reason_code IN ({tight}) THEN 'tight' ELSE 'weak' END AS tier,
           'advisory' AS enforcement,
           cik,
           'quarter' AS period_kind,
           report_date AS period,
           CASE WHEN reason_code IN ({tight}) THEN 'fail'
                WHEN reason_code IN ({warn}) THEN 'warn'
                ELSE 'pass' END AS status,
           CAST(fv_m AS DOUBLE) AS metric,
           'affected_fv_m' AS metric_name,
           CAST(n_rows AS BIGINT) AS n_units,
           reason_code AS mechanism,
           CAST(NULL AS VARCHAR) AS src_confidence
    FROM grouped
    UNION ALL
    SELECT 'provenance_reverify', 'provenance_already_queued', 'weak',
           'advisory', cik, 'quarter', report_date, 'pass',
           CAST(fv_m AS DOUBLE), 'affected_fv_m', CAST(n_rows AS BIGINT),
           'dedup_source_recon', CAST(NULL AS VARCHAR)
    FROM excluded
    """
```

Add `PROVENANCE_LEDGER_FILE` to the module's config import block, and `_provenance_select()` to the `adapter_selects()` tuple. Match the module's existing conventions exactly (path quoting, docstring style, all_varchar reads).

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_shadow_adapter.py -q` (whole file -- existing feed tests stay green).
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/shadow_adapter.py tests/test_shadow_adapter.py
git commit -m "shadow ledger: provenance re-verifier feed with 8.1 dedup

- reason codes aggregated to (cik, quarter): tight/fail for pointer
  failures, weak/warn for informational, weak/pass for healthy coverage
- tight rows already in blocking source-recon packets are excluded and
  counted in a provenance_already_queued audit row (no silent truncation)"
```

---

### Task 2: Evidence bundle drill-down (DIRTY-FILE selective staging)

**Files:**
- Modify: `pipeline/review_bundles.py` (EVIDENCE_SPECS entry) -- CARRIES OTHER-WORKSTREAM UNCOMMITTED HUNKS; selective staging per Global Constraints
- Test: the review-bundles test file (`rg -l "EVIDENCE_SPECS|review_bundles" tests/`)

**Interfaces:**
- Consumes: EVIDENCE_SPECS' established entry shape (read the dict at ~review_bundles.py:90 -- each spec names an artifact path, an `art_key` lambda over artifact rows, an `item_key` lambda over queue items, and a row cap).
- Produces: queue items with `engine='provenance_reverify'` get an evidence slice from `config.PROVENANCE_LEDGER_FILE`: rows matching `(cik, report_date, reason_code=rule_name)`, capped at 50 rows, selected via DuckDB filtered read (the file is ~676MB -- a pandas full read is forbidden; check how existing large-artifact specs read and follow that pattern; if all existing specs use pandas full reads, add a DuckDB filtered reader for this spec and say so in the report).

- [ ] **Step 1: Write the failing test**

In the located test file, following its existing bundle-fixture style: build a tmp provenance ledger CSV with 3 matching + 2 non-matching rows, a queue item dict with `engine='provenance_reverify'`, `rule_name='filing_mismatch'`, cik/report_date matching, and assert the built bundle's evidence contains exactly the 3 matching rows with their `row_id`, `field`, `declared_raw`, `instance_raw`, `published` columns present. (Copy the arrange/act of the nearest existing EVIDENCE_SPECS test verbatim; only the spec key and fixture differ.)

- [ ] **Step 2: Run to verify failure** -- the spec key is missing, bundle has no provenance evidence.

- [ ] **Step 3: Implement** the EVIDENCE_SPECS entry per the dict's established shape, keys `(cik, report_date, reason_code)` vs `(cik, report_date, rule_name)`, cap 50 rows, DuckDB filtered read.

- [ ] **Step 4: Run tests** -- the located test file fully green.

- [ ] **Step 5: Commit (selective staging).** Verify `git diff HEAD -- pipeline/review_bundles.py` -- if it contains hunks you did not author, build a filtered patch of only your hunks, `git apply --cached`, verify the cached diff, commit WITHOUT pathspec, and confirm the committed tree imports cleanly (`python -c` is banned: use `python -m pytest <located test file> -q --collect-only` in a temp worktree of HEAD if in doubt). Message: "shadow ledger: provenance evidence slice for review bundles" + 2 bullets.

---

### Task 3: Battery stage, run, docs

**Files:**
- Modify: `scripts/run_quarter_pass.py` (stage list ~:100)
- Docs: `docs/reference/schemas.md`, `docs/agent_changelog.md`

- [ ] **Step 1: Battery stage**

In the stage list, immediately BEFORE `Stage(f"shadow{suffix}", ...)`, insert:

```python
        Stage(f"provenance{suffix}", [py, "-m", "pipeline.provenance_reverify",
                                      "--cohort"]),
```

(Mirror the surrounding Stage constructor signature exactly -- if stages carry extra args like log paths or continue-on-error flags, copy the shadow stage's shape.) Run whatever fast test covers the stage list if one exists (`rg -l "run_quarter_pass" tests/`); otherwise `python scripts/run_quarter_pass.py --help` must still work.

- [ ] **Step 2: Operator verification run (no gates change)**

```powershell
python -m pipeline.provenance_reverify --cohort
python scripts\shadow_validation_runner.py
python -m pipeline.review_queue --emit-bdc-worklist
```

Then verify with a named scratch script (`scratch/2026-08-24_prov_feed/verify_feed.py`, read-only DuckDB):
- `validation_results_ledger.csv` contains `engine='provenance_reverify'` rows; per-rule counts match an independent aggregation of `provenance_ledger.csv`;
- dedup sanity: `provenance_already_queued` audit totals equal the anti-join count computed independently;
- `review_queue.csv`: tight provenance rows appear in the blocker lane, warn rows in the review lane, NO pass rows queued;
- quarter-acceptance artifacts unchanged (the feed is advisory): re-run `python -m pipeline.quarter_acceptance` only if the battery normally does; otherwise diff `data/output/quarter_acceptance*` mtimes untouched.
Record all counts in the report.

- [ ] **Step 3: Docs + commit**

- `docs/reference/schemas.md`: the feed's reason-code -> tier/status table, the audit-row semantics, the evidence-slice contract.
- `docs/agent_changelog.md`: APPEND dated entry -- feed shipped, first-run ledger/queue counts (per reason code), dedup exclusion count, explicit line "enforcement=advisory; no gate or acceptance-threshold changes".

```bash
git add scripts/run_quarter_pass.py docs/reference/schemas.md docs/agent_changelog.md
git commit -m "shadow ledger: provenance stage in quarter-pass battery + feed record

- provenance re-verifier runs before the shadow stage so the feed is
  fresh within a pass; first-run queue counts recorded
- advisory-only: no gate changes"
```

---

## Self-Review Notes

- Spec coverage: 8.1 field-level evidence (drill-down slice keeps (row_id, field) grain in bundles) + MANDATORY dedup vs existing queues (Task 1 anti-join + audit row) + 8.2 triage-to-lanes (tier/status map) all implemented; the doc's "no provenance is its own state" honored (weak/warn, never conflated with unverified-with-anchor).
- Deliberate choices: dedup applies only to tight codes (informational codes are not queue items, so double-queueing cannot occur -- test pins this); `anchor_stale` is weak/warn not tight/fail (re-stamp maintenance, scoping 8.2); pass rows ARE emitted (coverage measurement in the ledger, filtered out by the queue's fail/warn filter).
- Known risks: `review_bundles.py` is dirty (selective-staging procedure named, with the prior session's mangled-blob lesson: verify the committed tree); the 676MB evidence source mandates a filtered read; the runner's ledger contract is hard-asserted so a wrong fragment fails loudly at runner time -- the contract test (13 exact columns) catches it earlier.
- Type consistency: `PROV_TIGHT_FAIL`/`PROV_WEAK_WARN` names used in both the maps and the fragment; `provenance_already_queued` rule_name identical in fragment, tests, and docs.
