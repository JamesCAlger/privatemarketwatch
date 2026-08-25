# B3 Fact Recheck (Phases 1-2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the B3 gate a mechanical per-row, per-field check that holdings values match the filer's tagged XBRL facts, with mismatches routed to an agent worklist instead of auto-refusal.

**Architecture:** A new pure comparison module (`pipeline/fact_recheck.py`) joins the EXISTING source-fact frame (`pipeline.source_reconciliation.extract_bdc_source_facts_from_xbrl`, which already extracts rate concepts via `pipeline.bdc_filings.CONCEPT_MAP`) to unified holdings rows by normalized identifier, compares rate fields under per-field power-of-10 scales, and emits match/mismatch/not_covered rows. A second layer wires two predicates into `run_remediation gate` and appends mismatches to an agent handback worklist.

**Tech Stack:** Python 3.13 (conda at `C:\Users\alger\miniconda3\python.exe`), pandas + DuckDB (project convention: DuckDB for big joins, pandas for small frames), pytest.

**Spec:** `docs/adjudication_architecture/B3_fact_recheck_spec.md` (read it first — the caveats there are binding design decisions, especially "mismatch never auto-refuses").

## Global Constraints

- **No SEC downloads. Cached data only** (`data/raw/filings/bdc_xbrl/<cik-no-leading-zeros>/<accession-nodashes>.xml`). (AGENTS.md contract)
- **No pandas `.apply()`/`.iterrows()` on >10K-row frames** — use DuckDB SQL or vectorized ops. (AGENTS.md contract)
- **ASCII-only log/print output** (Windows cp1252). (AGENTS.md contract)
- Tests must not write under `data/output/` or `frontend/public/data/` — the conftest guard blocks it; use `tmp_path`. Production artifact writes happen only in CLI paths, never at import or in tests.
- Do not modify Agent B1, verdict files, or validation thresholds. Do not edit `AGENTS.md`; append results to `docs/agent_changelog.md` when done.
- Commit only files this plan creates/modifies — the worktree has concurrent uncommitted work from other sessions. Commit messages: short subject + 2-4 bullet body.
- New artifacts live under `data/output/fact_recheck/` (reports) and `data/output/agent_b2/fact_mismatch_worklist.csv` (handback).

## Reference: existing interfaces this plan consumes (verified 2026-08-22)

- `pipeline.source_reconciliation.extract_bdc_source_facts_from_xbrl(filings_index_df=None, filings_index_path=None) -> pd.DataFrame` — one row per investment context, columns include `cik, accession_number, report_date, period, context_id, investment_identifier, dimensions_raw, concept_names` plus every `_VALUE_COLUMNS` entry: `interest_rate, pik_rate, basis_spread, interest_rate_floor, reference_rate_type, fair_value, cost, principal_amount, pct_of_net_assets, maturity_date, ...`. Rate facts are RAW XBRL decimals (e.g. 0.075 for 7.5%).
- `pipeline.source_reconciliation._norm_identifier_sql(expr: str) -> str` — SQL snippet producing the normalized identifier used by the existing reconciliation match.
- Unified holdings frame columns (per-CIK slice or full CSV/parquet): `cik` (10-digit padded), `row_id` (ROW-<16hex>), `report_date`, `bdc_investment_identifier`, `issuer_name`, `interest_rate` (percent scale, e.g. 7.5), `pik_rate` (percent), `basis_spread` (bps scale, e.g. 750.0), `fair_value`, ...
- `data/overrides/rate_convention/<cik10>.json` — keys include `cik`, `convention` (e.g. `"cash_leg"`), free-text `column_semantics`. Absence of the file = unknown convention.
- `scripts.agent_b2.run_remediation` gate CLI: `gate --cik --target-quarter --baseline-holdings --trial-holdings [--correction ...] [--batch-id ...]`; `gate_conservation_packet(...)` returns a result whose dict is printed as the gate JSON.
- `pipeline.config.OUTPUT_DIR` = `data/output`; `config.PROJECT_ROOT` = repo root.

---

### Task 1: Comparison core — `compare_fields` (pure, no I/O)

**Files:**
- Create: `pipeline/fact_recheck.py`
- Test: `tests/test_fact_recheck.py`

**Interfaces:**
- Produces: `FIELD_SCALES: dict[str, float]`, `compare_fields(joined_df: pd.DataFrame, *, fields: tuple[str, ...], rel_tol: float = 1e-4) -> pd.DataFrame` where `joined_df` has columns `row_id, report_date, <field>` (holdings, output scale) and `fact_<field>` (raw XBRL decimal) per field, and the result has one row per (row_id, field) with columns `row_id, report_date, field, holdings_value, fact_value, expected_value, status, scale_hint`.
- `status` in `{"match", "mismatch_scale", "mismatch_value", "not_covered"}`.

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for the B3 fact-recheck comparison layer (spec:
docs/adjudication_architecture/B3_fact_recheck_spec.md)."""

from __future__ import annotations

import pandas as pd

from pipeline import fact_recheck as fr


def _joined(**over):
    base = {
        "row_id": ["ROW-aaaaaaaaaaaaaaaa"],
        "report_date": ["2025-12-31"],
        "interest_rate": [7.5],        # holdings, percent scale
        "fact_interest_rate": [0.075], # raw XBRL decimal
    }
    base.update(over)
    return pd.DataFrame(base)


def test_match_at_configured_scale():
    out = fr.compare_fields(_joined(), fields=("interest_rate",))
    assert list(out["status"]) == ["match"]
    assert out.iloc[0]["expected_value"] == 7.5


def test_mismatch_scale_flags_wrong_power_of_ten():
    # Holdings 0.75 but fact says 7.5 at configured scale -> off by 10^1.
    out = fr.compare_fields(_joined(interest_rate=[0.75]), fields=("interest_rate",))
    assert list(out["status"]) == ["mismatch_scale"]
    assert out.iloc[0]["scale_hint"] == 0.1


def test_mismatch_value_when_no_power_of_ten_fits():
    out = fr.compare_fields(_joined(interest_rate=[9.1]), fields=("interest_rate",))
    assert list(out["status"]) == ["mismatch_value"]


def test_not_covered_when_fact_is_null():
    out = fr.compare_fields(
        _joined(fact_interest_rate=[None]), fields=("interest_rate",))
    assert list(out["status"]) == ["not_covered"]


def test_not_covered_when_holdings_is_null_but_fact_exists_is_mismatch():
    # A tagged fact with NO extracted value is a real defect signal (e.g. the
    # AAM blank interest_rate), not a coverage gap.
    out = fr.compare_fields(
        _joined(interest_rate=[None]), fields=("interest_rate",))
    assert list(out["status"]) == ["mismatch_value"]


def test_basis_spread_uses_bps_scale():
    out = fr.compare_fields(
        _joined(basis_spread=[750.0], fact_basis_spread=[0.075]),
        fields=("basis_spread",))
    assert list(out["status"]) == ["match"]


def test_zero_fact_zero_holdings_is_match():
    out = fr.compare_fields(
        _joined(interest_rate=[0.0], fact_interest_rate=[0.0]),
        fields=("interest_rate",))
    assert list(out["status"]) == ["match"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_fact_recheck.py -q`
Expected: FAIL / error with `No module named 'pipeline.fact_recheck'` (or AttributeError).

- [ ] **Step 3: Write the minimal implementation**

```python
"""B3 fact recheck: compare holdings rate fields against the filer's tagged
XBRL facts. Spec: docs/adjudication_architecture/B3_fact_recheck_spec.md.

MISMATCH IS TRIAGE, NOT REFUSAL: our BDC rows originate from these same tags,
so a mismatch can mean OUR transform is wrong OR the filer's tag is wrong
(0001588272 CCS: tag itself is 0.016). Mismatches route to an agent worklist;
they never auto-fail a leaf. ASCII-only output.
"""

from __future__ import annotations

import math

import pandas as pd

# holdings-unit / fact-unit factor per field. Facts are raw XBRL decimals
# (0.075 = 7.5%); holdings store percent for rates and bps for spread.
# CALIBRATED in the Task 4 measurement step -- adjust there if measurement
# disagrees, never silently here.
FIELD_SCALES: dict[str, float] = {
    "interest_rate": 100.0,
    "pik_rate": 100.0,
    "pct_of_net_assets": 100.0,
    "basis_spread": 10000.0,
}
# Powers of 10 (relative to the configured scale) tried when the configured
# scale does not match; a hit becomes mismatch_scale with that hint recorded.
_SCALE_HINTS = (0.001, 0.01, 0.1, 10.0, 100.0, 1000.0)
_STATUS_ORDER = ("match", "mismatch_scale", "mismatch_value", "not_covered")


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not (isinstance(v, float) and math.isnan(v))


def _close(a: float, b: float, rel_tol: float) -> bool:
    if a == b:
        return True
    scale = max(abs(a), abs(b))
    return scale > 0 and abs(a - b) / scale <= rel_tol


def compare_fields(
    joined_df: pd.DataFrame,
    *,
    fields: tuple[str, ...] = ("interest_rate", "pik_rate", "basis_spread"),
    rel_tol: float = 1e-4,
) -> pd.DataFrame:
    """One output row per (row_id, field). Pure; no I/O. joined_df carries the
    holdings column ``<field>`` and the fact column ``fact_<field>``."""
    out_rows: list[dict] = []
    for rec in joined_df.to_dict("records"):
        for field in fields:
            hv, fv = rec.get(field), rec.get(f"fact_{field}")
            hv = hv if _is_num(hv) else None
            fv = fv if _is_num(fv) else None
            row = {
                "row_id": rec.get("row_id"), "report_date": rec.get("report_date"),
                "field": field, "holdings_value": hv, "fact_value": fv,
                "expected_value": None, "status": "not_covered", "scale_hint": None,
            }
            if fv is None:
                out_rows.append(row)          # nothing tagged -> not covered
                continue
            expected = fv * FIELD_SCALES[field]
            row["expected_value"] = expected
            if hv is None:
                row["status"] = "mismatch_value"   # tagged fact, blank extraction
            elif _close(hv, expected, rel_tol):
                row["status"] = "match"
            else:
                row["status"] = "mismatch_value"
                for hint in _SCALE_HINTS:
                    if _close(hv, expected * hint, rel_tol):
                        row["status"], row["scale_hint"] = "mismatch_scale", hint
                        break
            out_rows.append(row)
    return pd.DataFrame(out_rows, columns=[
        "row_id", "report_date", "field", "holdings_value", "fact_value",
        "expected_value", "status", "scale_hint"])
```

NOTE: the per-record Python loop is acceptable here because `joined_df` is one
CIK-quarter (hundreds to low-thousands of rows), not the 800K-row unified frame.
The join that feeds it (Task 2) is DuckDB.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_fact_recheck.py -q`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add pipeline/fact_recheck.py tests/test_fact_recheck.py
git commit -m "fact_recheck: comparison core for B3 fact recheck

- per-(row,field) match/mismatch_scale/mismatch_value/not_covered vs raw XBRL facts
- configured per-field scales (percent rates, bps spread), power-of-10 hints
- spec: docs/adjudication_architecture/B3_fact_recheck_spec.md"
```

---

### Task 2: Fact-to-row join + convention masking — `recheck_cik_quarter`

**Files:**
- Modify: `pipeline/fact_recheck.py` (append)
- Test: `tests/test_fact_recheck.py` (append)

**Interfaces:**
- Consumes: `compare_fields` (Task 1); `pipeline.source_reconciliation._norm_identifier_sql`.
- Produces: `recheck_cik_quarter(holdings_df, source_facts_df, *, cik: str, quarters: list[str], fields=..., rate_convention: dict | None = None) -> pd.DataFrame` — result adds columns `cik, accession_number, context_id, join_status` to the Task-1 output. `join_status` in `{"joined", "ambiguous", "no_fact_row", "no_holdings_row"}`; ambiguous/unjoined rows come back as `status="not_covered"` with the reason in `join_status`. If `rate_convention` has `{"interest_rate_semantics": "mixed"}`, every `interest_rate` comparison is forced to `not_covered` with `join_status="mixed_semantics"`.
- Also produces: `load_rate_convention(cik: str) -> dict` reading `data/overrides/rate_convention/<cik10>.json` (empty dict when absent) — kwarg `convention_dir` for tests.

- [ ] **Step 1: Write the failing tests (append to tests/test_fact_recheck.py)**

```python
def _holdings(**over):
    base = {
        "cik": ["0001588272"],
        "row_id": ["ROW-aaaaaaaaaaaaaaaa"],
        "report_date": ["2025-12-31"],
        "bdc_investment_identifier": ["CCS Medical, Inc (First Lien Term Loan)"],
        "interest_rate": [1.6],
        "pik_rate": [None],
        "basis_spread": [None],
    }
    base.update(over)
    return pd.DataFrame(base)


def _facts(**over):
    base = {
        "cik": ["0001588272"],
        "accession_number": ["0001193125-26-134282"],
        "report_date": ["2025-12-31"],
        "context_id": ["ctx_1"],
        "investment_identifier": ["CCS Medical, Inc (First Lien Term Loan)"],
        "interest_rate": [0.016],
        "pik_rate": [None],
        "basis_spread": [None],
    }
    base.update(over)
    return pd.DataFrame(base)


def test_recheck_joins_on_normalized_identifier_and_matches():
    out = fr.recheck_cik_quarter(
        _holdings(), _facts(), cik="0001588272", quarters=["2025-12-31"])
    ir = out[out["field"] == "interest_rate"].iloc[0]
    assert ir["join_status"] == "joined"
    assert ir["status"] == "match"          # 0.016 * 100 == 1.6 (circularity!)
    assert ir["accession_number"] == "0001193125-26-134282"


def test_recheck_flags_scale_mismatch_after_correction():
    # After a (correct) fix to 16.0 the tag still says 0.016 -> mismatch_scale.
    # Spec: this is TRIAGE (agent handback), never auto-refusal.
    out = fr.recheck_cik_quarter(
        _holdings(interest_rate=[16.0]), _facts(),
        cik="0001588272", quarters=["2025-12-31"])
    ir = out[out["field"] == "interest_rate"].iloc[0]
    assert ir["status"] == "mismatch_scale"


def test_ambiguous_join_is_not_covered():
    facts = pd.concat([_facts(), _facts(context_id=["ctx_2"])], ignore_index=True)
    out = fr.recheck_cik_quarter(
        _holdings(), facts, cik="0001588272", quarters=["2025-12-31"])
    assert set(out["join_status"]) == {"ambiguous"}
    assert set(out["status"]) == {"not_covered"}


def test_unjoined_holdings_row_is_not_covered():
    out = fr.recheck_cik_quarter(
        _holdings(bdc_investment_identifier=["Some Other Loan"]), _facts(),
        cik="0001588272", quarters=["2025-12-31"])
    assert set(out["join_status"]) == {"no_fact_row"}
    assert set(out["status"]) == {"not_covered"}


def test_mixed_semantics_convention_masks_interest_rate_only():
    out = fr.recheck_cik_quarter(
        _holdings(pik_rate=[12.0]), _facts(pik_rate=[0.12]),
        cik="0001588272", quarters=["2025-12-31"],
        rate_convention={"interest_rate_semantics": "mixed"})
    ir = out[out["field"] == "interest_rate"].iloc[0]
    pik = out[out["field"] == "pik_rate"].iloc[0]
    assert ir["status"] == "not_covered" and ir["join_status"] == "mixed_semantics"
    assert pik["status"] == "match"


def test_quarter_filter_excludes_other_quarters():
    out = fr.recheck_cik_quarter(
        _holdings(report_date=["2025-09-30"]), _facts(),
        cik="0001588272", quarters=["2025-12-31"])
    assert out.empty


def test_load_rate_convention_missing_file_is_empty(tmp_path):
    assert fr.load_rate_convention("0009999999", convention_dir=tmp_path) == {}
```

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `python -m pytest tests/test_fact_recheck.py -q`
Expected: Task-1 tests pass; new tests fail with AttributeError (`recheck_cik_quarter`).

- [ ] **Step 3: Write the implementation (append to pipeline/fact_recheck.py)**

```python
import json
from pathlib import Path

import duckdb

from pipeline import config
from pipeline.source_reconciliation import _norm_identifier_sql

RATE_CONVENTION_DIR = config.PROJECT_ROOT / "data" / "overrides" / "rate_convention"
_JOIN_META_COLS = ("accession_number", "context_id")


def load_rate_convention(cik: str, *, convention_dir: Path | None = None) -> dict:
    """Per-CIK rate-semantics registry entry; {} when the filer has none."""
    root = convention_dir or RATE_CONVENTION_DIR
    path = Path(root) / f"{str(cik).zfill(10)}.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}


def recheck_cik_quarter(
    holdings_df: pd.DataFrame,
    source_facts_df: pd.DataFrame,
    *,
    cik: str,
    quarters: list[str],
    fields: tuple[str, ...] = ("interest_rate", "pik_rate", "basis_spread"),
    rate_convention: dict | None = None,
    rel_tol: float = 1e-4,
) -> pd.DataFrame:
    """Join tagged facts to holdings rows for one CIK's target quarters and
    compare the rate fields. Ambiguous or missing joins -> not_covered (the
    join is 1:1 by normalized identifier within a report_date, or nothing)."""
    empty = pd.DataFrame(columns=[
        "cik", "row_id", "report_date", "field", "holdings_value", "fact_value",
        "expected_value", "status", "scale_hint", "accession_number",
        "context_id", "join_status"])
    hold = holdings_df.loc[
        holdings_df["report_date"].astype(str).isin([str(q) for q in quarters])
    ].copy()
    if hold.empty:
        return empty
    facts = source_facts_df.loc[
        source_facts_df["report_date"].astype(str).isin([str(q) for q in quarters])
    ].copy() if len(source_facts_df) else source_facts_df

    con = duckdb.connect()
    con.register("hold", hold)
    con.register("facts", facts if len(facts) else pd.DataFrame(
        columns=["report_date", "investment_identifier", *_JOIN_META_COLS, *fields]))
    fact_cols = ", ".join(
        f"f.{c} AS fact_{c}" for c in fields) or "NULL AS fact_none"
    joined = con.execute(f"""
        WITH h AS (
            SELECT *, {_norm_identifier_sql('bdc_investment_identifier')} AS norm_id
            FROM hold
        ),
        f0 AS (
            SELECT *, {_norm_identifier_sql('investment_identifier')} AS norm_id
            FROM facts
        ),
        f AS (
            SELECT *, COUNT(*) OVER (PARTITION BY report_date, norm_id) AS n_dup
            FROM f0
        ),
        hh AS (
            SELECT *, COUNT(*) OVER (PARTITION BY report_date, norm_id) AS h_dup
            FROM h
        )
        SELECT hh.* EXCLUDE (norm_id, h_dup),
               {fact_cols},
               f.accession_number AS fact_accession, f.context_id AS fact_context,
               CASE
                 WHEN f.norm_id IS NULL THEN 'no_fact_row'
                 WHEN f.n_dup > 1 OR hh.h_dup > 1 THEN 'ambiguous'
                 ELSE 'joined'
               END AS join_status
        FROM hh LEFT JOIN f
          ON hh.report_date = f.report_date AND hh.norm_id = f.norm_id
    """).fetchdf()

    # Ambiguity: null the fact values so the comparator emits not_covered.
    amb = joined["join_status"] != "joined"
    for c in fields:
        joined.loc[amb, f"fact_{c}"] = None

    out = compare_fields(joined, fields=fields, rel_tol=rel_tol)
    meta = joined[["row_id", "fact_accession", "fact_context", "join_status"]]
    out = out.merge(meta, on="row_id", how="left")
    out.loc[out["join_status"] != "joined", "status"] = "not_covered"
    # De-duplicate ambiguous fan-out: one output row per (row_id, field).
    out = out.drop_duplicates(subset=["row_id", "field"], keep="first")

    conv = rate_convention if rate_convention is not None else load_rate_convention(cik)
    if str(conv.get("interest_rate_semantics") or "") == "mixed":
        m = out["field"] == "interest_rate"
        out.loc[m, ["status", "join_status"]] = ["not_covered", "mixed_semantics"]

    out.insert(0, "cik", str(cik).zfill(10))
    return out.rename(columns={
        "fact_accession": "accession_number", "fact_context": "context_id"})
```

- [ ] **Step 4: Run the full test file**

Run: `python -m pytest tests/test_fact_recheck.py -q`
Expected: 14 passed. If the DuckDB `EXCLUDE` syntax errors on the installed version, replace `hh.* EXCLUDE (norm_id, h_dup)` with an explicit column list built in Python from `hold.columns`.

- [ ] **Step 5: Commit**

```bash
git add pipeline/fact_recheck.py tests/test_fact_recheck.py
git commit -m "fact_recheck: fact-to-row join + convention masking

- DuckDB join on normalized identifier (reuses source_reconciliation normalizer)
- ambiguous/missing joins -> not_covered with join_status reason
- mixed interest_rate semantics masked per rate_convention registry"
```

---

### Task 3: CLI + report artifact — `python -m pipeline.fact_recheck`

**Files:**
- Modify: `pipeline/fact_recheck.py` (append `main()` + `__main__` guard)
- Test: `tests/test_fact_recheck.py` (append; use `tmp_path` for all writes)

**Interfaces:**
- Consumes: `recheck_cik_quarter` (Task 2); `extract_bdc_source_facts_from_xbrl` (existing).
- Produces: `run_recheck(cik: str, quarters: list[str], *, holdings_path: Path, filings_index_path: Path | None = None, out_dir: Path | None = None) -> dict` returning `{"csv_path", "n_match", "n_mismatch", "n_not_covered", "coverage_pct"}` and writing `<out_dir>/fact_recheck.<cik>.<quarter>.csv`. Default `out_dir` = `data/output/fact_recheck/` (CLI only — tests always pass `tmp_path`).
- CLI: `python -m pipeline.fact_recheck --cik 0001588272 --quarter 2025-12-31 [--holdings <csv/parquet>] [--out-dir <dir>]`.

- [ ] **Step 1: Write the failing test (append)**

```python
def test_run_recheck_writes_report_and_counts(tmp_path):
    holdings_path = tmp_path / "holdings.csv"
    _holdings().to_csv(holdings_path, index=False)

    def fake_facts(**kwargs):
        return _facts()

    res = fr.run_recheck(
        "0001588272", ["2025-12-31"], holdings_path=holdings_path,
        out_dir=tmp_path, facts_loader=fake_facts)
    assert res["n_match"] == 1                       # interest_rate matches the tag
    assert res["n_not_covered"] == 2                 # pik + spread untagged
    written = pd.read_csv(res["csv_path"])
    assert set(written["status"]) == {"match", "not_covered"}
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_fact_recheck.py::test_run_recheck_writes_report_and_counts -q`
Expected: FAIL (AttributeError: `run_recheck`).

- [ ] **Step 3: Implement (append to pipeline/fact_recheck.py)**

```python
def _load_holdings_cik(holdings_path: Path, cik: str) -> pd.DataFrame:
    con = duckdb.connect()
    src = str(holdings_path).replace("'", "''")
    reader = "read_parquet" if str(holdings_path).endswith(".parquet") else "read_csv_auto"
    return con.execute(
        f"SELECT * FROM {reader}('{src}') WHERE ltrim(regexp_replace("
        f"CAST(cik AS VARCHAR), '[^0-9]', '', 'g'), '0') = '{str(cik).lstrip('0')}'"
    ).fetchdf()


def run_recheck(
    cik: str,
    quarters: list[str],
    *,
    holdings_path: Path,
    filings_index_path: Path | None = None,
    out_dir: Path | None = None,
    facts_loader=None,
) -> dict:
    """Operator entry point: recheck one CIK's quarters and write the report CSV.
    ``facts_loader`` is injectable for tests; production default extracts from
    the cached XBRL via the existing source-reconciliation path (cache-only)."""
    from pipeline.source_reconciliation import extract_bdc_source_facts_from_xbrl
    loader = facts_loader or extract_bdc_source_facts_from_xbrl
    facts = loader(filings_index_path=filings_index_path) if facts_loader is None \
        else facts_loader(filings_index_path=filings_index_path)
    facts = facts.loc[facts["cik"].astype(str).str.lstrip("0")
                      == str(cik).lstrip("0")] if len(facts) else facts
    holdings = _load_holdings_cik(Path(holdings_path), cik)
    out = recheck_cik_quarter(holdings, facts, cik=cik, quarters=quarters)

    dest_dir = Path(out_dir) if out_dir is not None \
        else config.OUTPUT_DIR / "fact_recheck"
    dest_dir.mkdir(parents=True, exist_ok=True)
    csv_path = dest_dir / f"fact_recheck.{str(cik).zfill(10)}.{quarters[0]}.csv"
    out.to_csv(csv_path, index=False)
    n = len(out)
    n_match = int((out["status"] == "match").sum())
    n_mis = int(out["status"].str.startswith("mismatch").sum())
    n_nc = int((out["status"] == "not_covered").sum())
    return {"csv_path": csv_path, "n_match": n_match, "n_mismatch": n_mis,
            "n_not_covered": n_nc,
            "coverage_pct": round(100.0 * (n_match + n_mis) / n, 1) if n else 0.0}


def main(argv=None) -> int:
    import argparse
    p = argparse.ArgumentParser(description="B3 fact recheck (cache-only).")
    p.add_argument("--cik", required=True)
    p.add_argument("--quarter", required=True, action="append",
                   help="Repeatable YYYY-MM-DD.")
    p.add_argument("--holdings", type=Path,
                   default=config.OUTPUT_DIR / "private_markets_holdings.csv")
    p.add_argument("--out-dir", type=Path, default=None)
    args = p.parse_args(argv)
    res = run_recheck(args.cik, args.quarter, holdings_path=args.holdings,
                      out_dir=args.out_dir)
    print(f"fact_recheck {args.cik}: match={res['n_match']} "
          f"mismatch={res['n_mismatch']} not_covered={res['n_not_covered']} "
          f"coverage={res['coverage_pct']}% -> {res['csv_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the full test file**

Run: `python -m pytest tests/test_fact_recheck.py -q`
Expected: 15 passed.

- [ ] **Step 5: Commit**

```bash
git add pipeline/fact_recheck.py tests/test_fact_recheck.py
git commit -m "fact_recheck: operator CLI + per-CIK report artifact

- python -m pipeline.fact_recheck --cik --quarter; cache-only fact extraction
- report CSV under data/output/fact_recheck/, injectable loaders for tests"
```

---

### Task 4: Calibration measurement on real filers (no code — measurement gate)

**Files:**
- Create: `scratch/<today>_fact_recheck_calibration/notes.md` (session scratch, git-ignored)
- Possibly modify: `pipeline/fact_recheck.py` `FIELD_SCALES` (only with measured evidence)

This task decides whether the configured `FIELD_SCALES` survive contact with real
filings. Do NOT skip it and do NOT tune tolerances to force green — a surprising
result is a finding to document, not an error to suppress (AGENTS.md).

- [ ] **Step 1: Run the recheck on the two session-known filers**

```powershell
& python -m pipeline.fact_recheck --cik 0001812554 --quarter 2025-12-31
& python -m pipeline.fact_recheck --cik 0001588272 --quarter 2025-12-31
```

- [ ] **Step 2: Verify the known ground truths against the report CSVs**

Expected observations (record actuals in the scratch notes; deviations are findings):
- 0001588272 CCS row `ROW-5fc443b59f9a09ce`: `interest_rate` **match** (holdings 1.6 == tag 0.016 x 100) — demonstrates the circularity boundary from the spec: the tag-recheck cannot catch filer tag errors. This is EXPECTED, not a failure.
- 0001812554 AAM row `ROW-a7f8a13bfb1589de`: whatever the filer tagged (`PaidInCash` vs `PaidInKind` concepts — this filer tags no bare `InvestmentInterestRate`), the row should surface as `mismatch_value` on at least one of `interest_rate`/`pik_rate` given the known cash/PIK displacement (holdings: pik 12.0, cash blank). If it comes back `match` on both, the displacement originated in the filer's own tags — write that finding down; it recalibrates what B2's column_remap class can claim.
- Join coverage (`joined` share) per CIK: record it. Below ~70% joined, Task 5's gate predicates will be too blind to be useful for that filer — note per-filer.

- [ ] **Step 3: Adjust FIELD_SCALES only if measurement demands it**

If `basis_spread` shows systematic `mismatch_scale` with hint 0.01 (i.e. filers tag
7.5 not 0.075), change `FIELD_SCALES["basis_spread"]` to the measured factor, update
`test_basis_spread_uses_bps_scale` to the corrected pair, and re-run the test file.

- [ ] **Step 4: Append a dated calibration entry to docs/agent_changelog.md**

Counts per CIK (match/mismatch/not_covered/joined%), the AAM and CCS observations,
any FIELD_SCALES change with its evidence.

- [ ] **Step 5: Commit (only if code/tests changed in step 3)**

```bash
git add pipeline/fact_recheck.py tests/test_fact_recheck.py docs/agent_changelog.md
git commit -m "fact_recheck: calibrate field scales against real filers

- measured 0001812554 + 0001588272 2025-12-31; scales confirmed/adjusted per report
- changelog entry with per-CIK coverage and the circularity-boundary demonstration"
```

---

### Task 5: B3 gate wiring — `fact_recheck` block + predicates

**Files:**
- Modify: `scripts/agent_b2/run_remediation.py` (gate CLI branch, `args.mode == "gate"`, currently ~line 938; add `--fact-recheck` flag to the gate subparser)
- Modify: `pipeline/fact_recheck.py` (append `gate_fact_recheck`)
- Test: `tests/test_fact_recheck.py` (append)

**Interfaces:**
- Consumes: `recheck_cik_quarter` (Task 2); the gate CLI's already-loaded `base_df` (baseline holdings, CIK-filtered) and `trial_df` (trial holdings), the correction leaf dict when `--correction` is given, and `_selector_mask` from `pipeline.agent_b2_appliers` (signature: `_selector_mask(df, row_selector) -> tuple[pd.Series, str]`).
- Produces: `gate_fact_recheck(cik, target_quarter, baseline_df, trial_df, source_facts_df, *, correction: dict | None = None, rate_convention: dict | None = None) -> dict` with shape:
  `{"checks": {"fact_mismatch_non_increasing": bool, "corrected_rows_fact_effect": bool | None}, "baseline_mismatches": int, "trial_mismatches": int, "coverage_pct": float, "effect_not_assessable": int, "mismatch_rows": [ {row_id, field, holdings_value, expected_value, accession_number, context_id}, ... ] }`.
  `corrected_rows_fact_effect` is `None` (not asserted) when there is no correction, the selector matches nothing, or every selected row is `not_covered`.
- Gate JSON gains a top-level `"fact_recheck"` key with that dict. **Neither predicate changes the gate verdict in this phase** — the block is evidence + handback feed; flipping predicates into the verdict AND is an owner decision after calibration (spec: mismatch never auto-refuses).

- [ ] **Step 1: Write the failing tests (append)**

```python
def test_gate_fact_recheck_no_op_leaf_leaves_mismatch_uncleared():
    # Baseline: tagged cash 12% (fact 0.12), holdings blank -> mismatch.
    # A no-op "correction" leaves trial == baseline -> effect predicate False.
    base = _holdings(
        cik=["0001812554"], row_id=["ROW-bbbbbbbbbbbbbbbb"],
        bdc_investment_identifier=["AAM Series 1.1 Feeder, LLC"],
        interest_rate=[None])
    facts = _facts(
        cik=["0001812554"], investment_identifier=["AAM Series 1.1 Feeder, LLC"],
        interest_rate=[0.12])
    correction = {"template": {"row_selector": {"row_id": "ROW-bbbbbbbbbbbbbbbb"}}}
    res = fr.gate_fact_recheck(
        "0001812554", "2025-12-31", base, base.copy(), facts, correction=correction)
    assert res["checks"]["corrected_rows_fact_effect"] is False
    assert res["checks"]["fact_mismatch_non_increasing"] is True
    assert res["trial_mismatches"] == 1


def test_gate_fact_recheck_effective_leaf_clears():
    base = _holdings(
        cik=["0001812554"], row_id=["ROW-bbbbbbbbbbbbbbbb"],
        bdc_investment_identifier=["AAM Series 1.1 Feeder, LLC"],
        interest_rate=[None])
    trial = base.copy(); trial["interest_rate"] = [12.0]
    facts = _facts(
        cik=["0001812554"], investment_identifier=["AAM Series 1.1 Feeder, LLC"],
        interest_rate=[0.12])
    correction = {"template": {"row_selector": {"row_id": "ROW-bbbbbbbbbbbbbbbb"}}}
    res = fr.gate_fact_recheck(
        "0001812554", "2025-12-31", base, trial, facts, correction=correction)
    assert res["checks"]["corrected_rows_fact_effect"] is True
    assert res["trial_mismatches"] == 0
    assert res["mismatch_rows"] == []


def test_gate_fact_recheck_not_covered_rows_are_not_assessable():
    base = _holdings()          # facts below carry no rate tags at all
    facts = _facts(interest_rate=[None])
    correction = {"template": {"row_selector": {"row_id": "ROW-aaaaaaaaaaaaaaaa"}}}
    res = fr.gate_fact_recheck(
        "0001588272", "2025-12-31", base, base.copy(), facts, correction=correction)
    assert res["checks"]["corrected_rows_fact_effect"] is None
    assert res["effect_not_assessable"] >= 1
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_fact_recheck.py -q`
Expected: prior tests pass; 3 new fail (AttributeError: `gate_fact_recheck`).

- [ ] **Step 3: Implement `gate_fact_recheck` (append to pipeline/fact_recheck.py)**

```python
def gate_fact_recheck(
    cik: str,
    target_quarter: str,
    baseline_df: pd.DataFrame,
    trial_df: pd.DataFrame,
    source_facts_df: pd.DataFrame,
    *,
    correction: dict | None = None,
    rate_convention: dict | None = None,
) -> dict:
    """B3 evidence block. NEVER flips the gate verdict in this phase (spec:
    mismatch is triage). Effect predicate: rows the correction selected that
    were fact-mismatched in baseline must match in trial (when covered)."""
    kw = dict(cik=cik, quarters=[target_quarter], rate_convention=rate_convention)
    base = recheck_cik_quarter(baseline_df, source_facts_df, **kw)
    trial = recheck_cik_quarter(trial_df, source_facts_df, **kw)
    base_mis = base.loc[base["status"].str.startswith("mismatch")]
    trial_mis = trial.loc[trial["status"].str.startswith("mismatch")]

    effect: bool | None = None
    not_assessable = 0
    if correction is not None:
        from pipeline.agent_b2_appliers import _selector_mask
        selector = (correction.get("template") or {}).get("row_selector")
        if selector:
            mask, err = _selector_mask(trial_df, selector)
            sel_ids = set(trial_df.loc[mask, "row_id"].astype(str)) if not err else set()
            target = base_mis.loc[base_mis["row_id"].astype(str).isin(sel_ids)]
            if len(target):
                after = trial.merge(
                    target[["row_id", "field"]], on=["row_id", "field"], how="inner")
                covered = after.loc[after["status"] != "not_covered"]
                not_assessable = int(len(after) - len(covered))
                effect = bool(len(covered)) and bool(
                    (covered["status"] == "match").all()) or (
                    None if not len(covered) else
                    bool((covered["status"] == "match").all()))
    n = len(trial)
    covered_n = int((trial["status"] != "not_covered").sum())
    return {
        "checks": {
            "fact_mismatch_non_increasing": len(trial_mis) <= len(base_mis),
            "corrected_rows_fact_effect": effect,
        },
        "baseline_mismatches": int(len(base_mis)),
        "trial_mismatches": int(len(trial_mis)),
        "coverage_pct": round(100.0 * covered_n / n, 1) if n else 0.0,
        "effect_not_assessable": not_assessable,
        "mismatch_rows": trial_mis[[
            "row_id", "field", "holdings_value", "expected_value",
            "accession_number", "context_id"]].to_dict("records"),
    }
```

Simplify the `effect` expression while implementing — the intent, exactly: `None` if no correction / no selector hit / zero covered target rows; else `True` iff every covered target row is `match` in trial. Write it as plain if/else, keep the tests as the contract.

- [ ] **Step 4: Wire into the gate CLI (scripts/agent_b2/run_remediation.py)**

In the gate subparser add:

```python
    g.add_argument("--fact-recheck", action="store_true",
                   help="Attach the fact_recheck evidence block (cache-only "
                        "XBRL fact comparison; never changes the verdict).")
```

In the `args.mode == "gate"` branch, after `out` is built and before it is printed,
add:

```python
        if args.fact_recheck:
            from pipeline.fact_recheck import gate_fact_recheck
            from pipeline.source_reconciliation import (
                extract_bdc_source_facts_from_xbrl)
            facts = extract_bdc_source_facts_from_xbrl()
            facts = facts.loc[facts["cik"].astype(str).str.lstrip("0")
                              == str(args.cik).lstrip("0")] if len(facts) else facts
            out["fact_recheck"] = gate_fact_recheck(
                args.cik, args.target_quarter, base_df, trial_df, facts,
                correction=correction if args.correction is not None else None)
```

NOTE: `correction` is only defined inside the existing `if args.correction is not None:`
block — hoist the `json.loads(...)` read above both uses so each consumes the same
parsed dict (read it once, `correction = None` default).

- [ ] **Step 5: Run the full test file + a smoke gate**

Run: `python -m pytest tests/test_fact_recheck.py tests/test_agent_b2_run_remediation.py -q`
Expected: all pass.

Smoke (reuses the 0001287750 trial artifacts if still present from the 2026-08-21
session, else re-run apply first):

```powershell
& python -m scripts.agent_b2.run_remediation gate --cik 0001287750 --target-quarter 2025-12-31 `
  --baseline-holdings "data\output\private_markets_holdings.csv" `
  --trial-holdings "data\output\bdc_xbrl_wrapper_trial\0001287750\unified_trial\private_markets_holdings.0001287750.corrected.csv" `
  --correction "data\output\agent_b2\corrections\0001287750\all_pik_normalization.json" `
  --fact-recheck
```

Expected: gate JSON now carries a `fact_recheck` block; verdict unchanged from the
2026-08-21 PASS.

- [ ] **Step 6: Commit**

```bash
git add pipeline/fact_recheck.py scripts/agent_b2/run_remediation.py tests/test_fact_recheck.py
git commit -m "B3 gate: attach fact_recheck evidence block (--fact-recheck)

- fact_mismatch_non_increasing + corrected_rows_fact_effect predicates
- evidence-only in this phase: never changes the gate verdict (spec decision)
- no-op leaves now visibly fail the effect predicate for fact-covered rows"
```

---

### Task 6: Agent handback — `fact_mismatch_worklist.csv`

**Files:**
- Modify: `pipeline/fact_recheck.py` (append `append_mismatch_worklist`)
- Modify: `scripts/agent_b2/run_remediation.py` (gate branch: call it when `--fact-recheck` and a batch id are given)
- Test: `tests/test_fact_recheck.py` (append; `tmp_path` only)

**Interfaces:**
- Consumes: the `mismatch_rows` list from `gate_fact_recheck` (Task 5).
- Produces: `append_mismatch_worklist(rows: list[dict], *, cik: str, target_quarter: str, batch_id: str, worklist_path: Path) -> int` (returns rows appended). CSV columns: `cik, target_quarter, row_id, field, holdings_value, expected_value, accession_number, context_id, batch_id, recorded_utc`. Append-only (`mode="a"`, header only when the file does not exist), mirroring `READJUDICATION_WORKLIST` conventions. Production path: `data/output/agent_b2/fact_mismatch_worklist.csv`. Timestamps via `datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")`.

- [ ] **Step 1: Write the failing test (append)**

```python
def test_append_mismatch_worklist_appends_without_clobbering(tmp_path):
    wl = tmp_path / "fact_mismatch_worklist.csv"
    rows = [{"row_id": "ROW-aaaaaaaaaaaaaaaa", "field": "interest_rate",
             "holdings_value": 1.6, "expected_value": 16.0,
             "accession_number": "0001193125-26-134282", "context_id": "ctx_1"}]
    n1 = fr.append_mismatch_worklist(
        rows, cik="0001588272", target_quarter="2025-12-31",
        batch_id="b1", worklist_path=wl)
    n2 = fr.append_mismatch_worklist(
        rows, cik="0001588272", target_quarter="2025-12-31",
        batch_id="b2", worklist_path=wl)
    assert (n1, n2) == (1, 1)
    df = pd.read_csv(wl)
    assert len(df) == 2 and set(df["batch_id"]) == {"b1", "b2"}
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_fact_recheck.py::test_append_mismatch_worklist_appends_without_clobbering -q`
Expected: FAIL (AttributeError).

- [ ] **Step 3: Implement**

```python
import csv
from datetime import datetime, timezone

FACT_MISMATCH_WORKLIST = config.OUTPUT_DIR / "agent_b2" / "fact_mismatch_worklist.csv"
_WORKLIST_COLUMNS = ["cik", "target_quarter", "row_id", "field", "holdings_value",
                     "expected_value", "accession_number", "context_id",
                     "batch_id", "recorded_utc"]


def append_mismatch_worklist(
    rows: list[dict], *, cik: str, target_quarter: str, batch_id: str,
    worklist_path: Path | None = None,
) -> int:
    """Append fact-mismatch handback packets (append-only, like the
    re-adjudication worklist; agents adjudicate tag-vs-text, nothing is
    auto-applied)."""
    path = Path(worklist_path) if worklist_path is not None else FACT_MISMATCH_WORKLIST
    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.exists()
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=_WORKLIST_COLUMNS)
        if new_file:
            w.writeheader()
        for r in rows:
            w.writerow({"cik": str(cik).zfill(10), "target_quarter": target_quarter,
                        "row_id": r.get("row_id"), "field": r.get("field"),
                        "holdings_value": r.get("holdings_value"),
                        "expected_value": r.get("expected_value"),
                        "accession_number": r.get("accession_number"),
                        "context_id": r.get("context_id"),
                        "batch_id": batch_id, "recorded_utc": stamp})
    return len(rows)
```

In `run_remediation.py`, inside the `if args.fact_recheck:` block added in Task 5,
after computing `out["fact_recheck"]`:

```python
            if args.batch_id and out["fact_recheck"]["mismatch_rows"]:
                from pipeline.fact_recheck import append_mismatch_worklist
                append_mismatch_worklist(
                    out["fact_recheck"]["mismatch_rows"], cik=args.cik,
                    target_quarter=args.target_quarter, batch_id=args.batch_id)
```

- [ ] **Step 4: Run the full test file**

Run: `python -m pytest tests/test_fact_recheck.py -q`
Expected: all pass (19).

- [ ] **Step 5: Commit**

```bash
git add pipeline/fact_recheck.py scripts/agent_b2/run_remediation.py tests/test_fact_recheck.py
git commit -m "fact_recheck: append-only mismatch worklist for agent handback

- gate --fact-recheck with --batch-id appends handback packets
- packet carries fact citation (accession, context) + holdings row + expected value"
```

---

### Task 7: Wrap-up — changelog, focused suites, semantic-diff backstop

**Files:**
- Modify: `docs/agent_changelog.md` (append only)

- [ ] **Step 1: Run the focused suites**

Run: `python -m pytest tests/test_fact_recheck.py tests/test_agent_b2_run_remediation.py tests/test_correction_leaf.py -q`
Expected: all pass. Do NOT run the full suite unless shared contracts changed (proportional verification; check for other running pytest processes first if you do).

- [ ] **Step 2: Semantic-diff backstop**

Run: `python scripts/diff_outputs.py --semantic`
Expected: no NEW divergences beyond the pre-existing drift documented in the 2026-08-22 changelog entry (production holdings mtime must be unchanged by this work — this plan writes only `data/output/fact_recheck/` and the worklist CSV, neither of which is baseline-tracked; if the baseline script flags them as untracked extras, note it in the changelog rather than deleting).

- [ ] **Step 3: Append the changelog entry**

Dated entry: module added, gate flag, worklist artifact, calibration results (from Task 4), test count delta, explicit statement that the predicates are evidence-only pending the owner's decision to enforce, and the Phase 3 pointer (spec section "Phase 3").

- [ ] **Step 4: Commit**

```bash
git add docs/agent_changelog.md
git commit -m "docs: changelog for B3 fact-recheck phases 1-2"
```

---

## Self-Review (done at planning time)

- **Spec coverage:** outcomes table -> Task 1; join/convention -> Task 2; per-CIK report -> Task 3; calibration + circularity demonstration -> Task 4; both gate predicates + evidence-only rule -> Task 5; handback worklist -> Task 6. Phase 3 explicitly deferred to its own plan (spec section retained).
- **Known simplification (accepted):** Task 5's `effect` expression sketch is convoluted; the step text pins the exact truth table and the tests are the contract.
- **Type consistency check:** `recheck_cik_quarter` output columns match what `gate_fact_recheck` selects; `mismatch_rows` keys match `_WORKLIST_COLUMNS` inputs; `_selector_mask` consumed with its real `(df, selector) -> (mask, err)` signature.
- **Open risk flagged to executor:** the DuckDB `EXCLUDE` clause and `read_csv_auto` dtype inference (all-NULL columns infer INT32 — CAST to VARCHAR if the join keys degrade; known project pitfall). If `_norm_identifier_sql` proves too strict/loose on a filer, record join% in Task 4 notes — do not invent a new normalizer in this plan.
