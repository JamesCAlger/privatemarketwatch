# Match-Quality Phase 0 (Measurement) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the measurement layer for position-match and borrower-entity quality: permanent deterministic metrics (`pipeline/match_quality.py` -> `match_quality_metrics.csv`) plus an agent-adjudication gold-set harness (~600 packets, verdict schema, scorer with per-tier precision).

**Architecture:** Pure DuckDB metric functions over `private_markets_holdings.csv` + `position_id_edges.csv`, wired into `scripts/rebuild_outputs.py`. Gold harness follows the existing B1/B2 conventions: stratified deterministic sampling -> blinded packet JSONs + per-accession mini-bundles readable by `scripts/review_agent/evidence_cli.py` -> worker verdict JSONs validated by a new `pipeline/match_verdict_leaf.py` -> scorer producing `gold_set.csv`, `precision_by_tier.csv`, and a 10% audit slice.

**Tech Stack:** Python, DuckDB (all large transforms), pandas (small frames only), pytest, existing evidence CLI / Codex fleet dispatch pattern.

**Spec:** `docs/superpowers/specs/2026-09-03-position-borrower-tracking-design.md`

## Global Constraints

- No SEC EDGAR or any network calls; everything reads cached data on disk.
- No pandas `.apply()`/`.iterrows()`/row loops on >10K-row data; use DuckDB SQL. Pandas only for small summaries.
- All log messages ASCII-only (Windows cp1252).
- Tests must never write under `data/output/` or `frontend/public/data/` (conftest guard enforces this); metric/sampler functions must accept DataFrames or explicit paths so tests use tmp_path.
- Worker-authored JSON is read with `encoding="utf-8-sig"` (sandbox workers emit BOMs).
- Deterministic artifacts: no timestamps, no `random` without the frozen seed `20260903`, stable sort order before every CSV write.
- Adjudication scope is BDC-source rows in the wrapper cohort (`pipeline.cohort_guard.load_cohort_ciks()`); cohort is a parameter, never hardcoded in logic.
- Commit messages: short subject + 2-4 bullet body.
- Do not run the full pytest suite as inner loop; run the targeted test file per task. Full suite once at the end (Task 10).

## File Structure

| Path | Responsibility |
|---|---|
| `pipeline/match_quality.py` (new) | Deterministic metrics + candidate DataFrames (drift-break, anomalies) reused by the sampler |
| `pipeline/match_verdict_leaf.py` (new) | Schema validation for gold-set verdict JSONs |
| `scripts/match_gold/build_packets.py` (new) | Stratified sampling, packet/prompt/mini-bundle/worklist writing |
| `scripts/match_gold/score_gold.py` (new) | Verdict ingest, validation, per-tier precision, gold_set.csv, audit slice |
| `scripts/rebuild_outputs.py` (modify) | `--match-quality` flag |
| `scripts/review_agent/evidence_cli.py` (modify) | register `match_gold` engine (one line) |
| `pipeline/config.py` (modify) | new path constants |
| `docs/reference/match_gold_dispatch.md` (new) | operator runbook |
| Tests | `tests/test_match_quality.py`, `tests/test_match_verdict_leaf.py`, `tests/test_match_gold_packets.py`, `tests/test_match_gold_score.py` |

Artifact layout (produced at run time, not by tests):

```
data/output/match_quality_metrics.csv
data/output/match_quality/gold/<batch_id>/
    worklist.csv                     # packet_id, packet_type, stratum, cik(s), prompt/packet paths
    packets/<packet_id>.json         # blinded packet (no match_method / match_score)
    packets_meta/<packet_id>.json    # sidecar: tier per edge_index, stratum internals (scorer-only)
    filings/<packet_id>/<accession>.json   # mini-bundles for evidence_cli
    prompts/<packet_id>.md
    verdicts/<packet_id>.json        # worker output
    gold_set.csv, precision_by_tier.csv, audit_slice.csv, summary.md   # scorer output
```

---

### Task 1: Config constants + chain-continuity and singleton metrics

**Files:**
- Modify: `pipeline/config.py` (after line 276, `POSITION_ID_EDGES_FILE`)
- Create: `pipeline/match_quality.py`
- Test: `tests/test_match_quality.py`

**Interfaces:**
- Produces: `pipeline.config.MATCH_QUALITY_METRICS_FILE`, `pipeline.config.MATCH_GOLD_DIR`;
  `match_quality.chain_continuity(holdings_df) -> pd.DataFrame` (columns `metric, scope_type, scope, numerator, denominator, value`);
  `match_quality.singleton_decomposition(holdings_df) -> pd.DataFrame` (same columns);
  `match_quality.METRIC_COLUMNS` list.
- Consumes: `private_markets_holdings.csv` columns `source, cik, report_date, issuer_name, fair_value, position_id, row_id, index_classification`.

- [ ] **Step 1: Add config constants**

In `pipeline/config.py` directly below `POSITION_ID_EDGES_FILE`:

```python
MATCH_QUALITY_METRICS_FILE = OUTPUT_DIR / "match_quality_metrics.csv"
MATCH_GOLD_DIR = OUTPUT_DIR / "match_quality" / "gold"
```

- [ ] **Step 2: Write failing tests**

Create `tests/test_match_quality.py`:

```python
"""Tests for pipeline/match_quality.py deterministic metrics."""
import pandas as pd
import pytest

from pipeline import match_quality as mq

HOLDING_COLS = [
    "source", "cik", "report_date", "issuer_name", "fair_value",
    "position_id", "row_id", "index_classification", "interest_rate",
    "maturity_date", "entity_id",
]


def _holdings(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    for c in HOLDING_COLS:
        if c not in df.columns:
            df[c] = None
    return df[HOLDING_COLS]


def _row(cik, date, issuer, fv, pid, rid, **kw):
    base = {
        "source": "bdc", "cik": cik, "report_date": date, "issuer_name": issuer,
        "fair_value": fv, "position_id": pid, "row_id": rid,
        "index_classification": "DIRECT_LENDING",
    }
    base.update(kw)
    return base


class TestChainContinuity:
    def test_continued_and_dropped_rows(self):
        # CIK A: q1 has 2 rows; one continues into q2 (same position_id), one does not.
        df = _holdings([
            _row("0000000001", "2025-03-31", "Acme Corp", 100.0, "POS-1", "ROW-a"),
            _row("0000000001", "2025-03-31", "Beta LLC", 50.0, "POS-2", "ROW-b"),
            _row("0000000001", "2025-06-30", "Acme Corp", 101.0, "POS-1", "ROW-c"),
        ])
        out = mq.chain_continuity(df)
        all_row = out[(out["scope_type"] == "ALL")].iloc[0]
        # q2 rows are terminal (no later quarter) -> only the 2 q1 rows are eligible
        assert all_row["denominator"] == 2
        assert all_row["numerator"] == 1
        assert all_row["value"] == pytest.approx(0.5)

    def test_zero_fv_rows_excluded(self):
        df = _holdings([
            _row("0000000001", "2025-03-31", "Acme Corp", 0.0, "POS-1", "ROW-a"),
            _row("0000000001", "2025-06-30", "Acme Corp", 10.0, "POS-1", "ROW-b"),
        ])
        out = mq.chain_continuity(df)
        assert out[(out["scope_type"] == "ALL")].iloc[0]["denominator"] == 0

    def test_nport_rows_excluded(self):
        df = _holdings([
            _row("0000000001", "2025-03-31", "Acme Corp", 10.0, "POS-1", "ROW-a",
                 source="nport"),
            _row("0000000001", "2025-06-30", "Acme Corp", 10.0, "POS-1", "ROW-b",
                 source="nport"),
        ])
        out = mq.chain_continuity(df)
        assert out[(out["scope_type"] == "ALL")].iloc[0]["denominator"] == 0


class TestSingletonDecomposition:
    def test_classes(self):
        df = _holdings([
            # interior suspicious singleton: has quarters before and after, positive FV
            _row("0000000001", "2025-03-31", "Acme Corp", 10.0, "POS-1", "ROW-a"),
            _row("0000000001", "2025-06-30", "Lone Star", 20.0, "POS-9", "ROW-b"),
            _row("0000000001", "2025-09-30", "Acme Corp", 11.0, "POS-1", "ROW-c"),
            # terminal-quarter singleton
            _row("0000000001", "2025-09-30", "Newco Inc", 5.0, "POS-8", "ROW-d"),
            # zero-FV singleton
            _row("0000000001", "2025-06-30", "Zero Co", 0.0, "POS-7", "ROW-e"),
            # negative-FV singleton
            _row("0000000001", "2025-06-30", "Neg Co", -3.0, "POS-6", "ROW-f"),
        ])
        out = mq.singleton_decomposition(df)
        by_scope = out.set_index("scope")
        assert by_scope.loc["interior_suspicious", "numerator"] == 1
        assert by_scope.loc["terminal_quarter", "numerator"] == 1
        assert by_scope.loc["zero_or_null_fv", "numerator"] == 1
        assert by_scope.loc["negative_fv", "numerator"] == 1
        # denominator = total singletons everywhere
        assert (out["denominator"] == 4).all()
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_match_quality.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pipeline.match_quality'` (after config edit imports cleanly).

- [ ] **Step 4: Implement `pipeline/match_quality.py`**

```python
"""Deterministic match-quality metrics over unified holdings + position edges.

Signals, not truth: these metrics baseline chain behavior so later changes
(Tier E repair, agent corrections) can be gated on regression. The gold set
built by scripts/match_gold/ is the truth layer.

All heavy transforms are DuckDB SQL; functions accept DataFrames so tests
never touch production paths.
"""
from __future__ import annotations

import logging

import duckdb
import pandas as pd

logger = logging.getLogger(__name__)

METRIC_COLUMNS = ["metric", "scope_type", "scope", "numerator", "denominator", "value"]

_BDC_POSITIVE = """
    SELECT cik, report_date, issuer_name, row_id, position_id,
           TRY_CAST(fair_value AS DOUBLE) AS fv,
           index_classification,
           TRY_CAST(interest_rate AS DOUBLE) AS rate,
           maturity_date
    FROM h
    WHERE source = 'bdc'
      AND TRY_CAST(fair_value AS DOUBLE) > 0
      AND position_id IS NOT NULL
"""


def _con(holdings_df: pd.DataFrame) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.register("h", holdings_df)
    return con


def _finish(df: pd.DataFrame, metric: str) -> pd.DataFrame:
    df = df.copy()
    df["metric"] = metric
    df["value"] = df.apply(
        lambda r: (r["numerator"] / r["denominator"]) if r["denominator"] else 0.0,
        axis=1,
    )  # small frame only (one row per scope)
    return df[METRIC_COLUMNS].sort_values(["metric", "scope_type", "scope"]).reset_index(drop=True)


def chain_continuity(holdings_df: pd.DataFrame) -> pd.DataFrame:
    """Share of positive-FV BDC rows in non-terminal quarters whose position_id
    reappears in a later quarter of the same CIK."""
    con = _con(holdings_df)
    per_cik = con.execute(f"""
        WITH rows_q AS ({_BDC_POSITIVE}),
        maxq AS (SELECT cik, MAX(report_date) AS max_date FROM rows_q GROUP BY cik),
        eligible AS (
            SELECT r.* FROM rows_q r JOIN maxq m
              ON r.cik = m.cik AND r.report_date < m.max_date
        ),
        continued AS (
            SELECT DISTINCT e.row_id FROM eligible e
            JOIN rows_q later
              ON later.cik = e.cik AND later.position_id = e.position_id
             AND later.report_date > e.report_date
        )
        SELECT e.cik AS scope,
               COUNT(c.row_id) AS numerator,
               COUNT(*) AS denominator
        FROM eligible e LEFT JOIN continued c ON e.row_id = c.row_id
        GROUP BY e.cik ORDER BY e.cik
    """).df()
    per_cik["scope_type"] = "cik"
    total = pd.DataFrame([{
        "scope": "ALL", "scope_type": "ALL",
        "numerator": int(per_cik["numerator"].sum()),
        "denominator": int(per_cik["denominator"].sum()),
    }])
    return _finish(pd.concat([total, per_cik], ignore_index=True), "chain_continuity_rate")


def singleton_decomposition(holdings_df: pd.DataFrame) -> pd.DataFrame:
    """Classify singleton position_ids (appear exactly once, BDC source):
    terminal_quarter / first_quarter / zero_or_null_fv / negative_fv /
    interior_suspicious. Priority order as listed: a zero-FV terminal row
    counts as terminal_quarter? No -- data-quality classes win: zero/negative
    FV first, then boundary quarters, then interior_suspicious."""
    con = _con(holdings_df)
    classes = con.execute("""
        WITH bdc AS (
            SELECT cik, report_date, position_id, row_id,
                   TRY_CAST(fair_value AS DOUBLE) AS fv
            FROM h WHERE source = 'bdc' AND position_id IS NOT NULL
        ),
        pid_counts AS (
            SELECT position_id FROM bdc GROUP BY position_id HAVING COUNT(*) = 1
        ),
        bounds AS (
            SELECT cik, MIN(report_date) AS min_date, MAX(report_date) AS max_date
            FROM bdc GROUP BY cik
        ),
        singles AS (
            SELECT b.*, bd.min_date, bd.max_date
            FROM bdc b
            JOIN pid_counts p ON b.position_id = p.position_id
            JOIN bounds bd ON b.cik = bd.cik
        )
        SELECT CASE
                 WHEN fv IS NULL OR fv = 0 THEN 'zero_or_null_fv'
                 WHEN fv < 0 THEN 'negative_fv'
                 WHEN report_date = max_date THEN 'terminal_quarter'
                 WHEN report_date = min_date THEN 'first_quarter'
                 ELSE 'interior_suspicious'
               END AS scope,
               COUNT(*) AS numerator
        FROM singles GROUP BY 1 ORDER BY 1
    """).df()
    classes["scope_type"] = "singleton_class"
    classes["denominator"] = int(classes["numerator"].sum())
    return _finish(classes, "singleton_decomposition")
```

Note: the docstring self-corrects the priority order deliberately -- implement the CASE order exactly as written (zero/null, negative, terminal, first, interior).

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_match_quality.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add pipeline/config.py pipeline/match_quality.py tests/test_match_quality.py
git commit -m "feat: match-quality metrics module (continuity, singletons)

- pipeline/match_quality.py: chain_continuity + singleton_decomposition (DuckDB)
- config: MATCH_QUALITY_METRICS_FILE, MATCH_GOLD_DIR
- tests: 5 cases incl. zero-FV and nport exclusion"
```

---

### Task 2: Anomaly metrics, drift-break candidates, entity stats

**Files:**
- Modify: `pipeline/match_quality.py`
- Test: `tests/test_match_quality.py` (append)

**Interfaces:**
- Produces:
  `edge_anomalies(edges_df) -> pd.DataFrame` (METRIC_COLUMNS, scope_type="tier", scope=match_method);
  `drift_break_candidates(holdings_df) -> pd.DataFrame` (row-level candidate pairs: `cik, dropped_row_id, dropped_issuer, dropped_date, start_row_id, start_issuer, start_date, fv_ratio`);
  `drift_break_metric(holdings_df) -> pd.DataFrame` (METRIC_COLUMNS);
  `entity_stats(holdings_df) -> pd.DataFrame` (METRIC_COLUMNS);
  `compute_all(holdings_df, edges_df) -> pd.DataFrame` (concat of every metric, sorted).
- Consumes: `position_id_edges.csv` columns `match_method, begin_fair_value, end_fair_value, position_id, cik, begin_report_date, end_report_date` (schema in `pipeline/output_schemas.py:432-449`).

- [ ] **Step 1: Write failing tests (append to `tests/test_match_quality.py`)**

```python
EDGE_COLS = ["edge_type", "position_id", "cik", "source", "begin_report_date",
             "begin_quarter", "begin_issuer_name", "begin_fair_value",
             "end_report_date", "end_quarter", "end_issuer_name",
             "end_fair_value", "match_method", "match_key", "match_score",
             "span_months"]


def _edges(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    for c in EDGE_COLS:
        if c not in df.columns:
            df[c] = None
    return df[EDGE_COLS]


def _edge(pid, method, bfv, efv, cik="0000000001"):
    return {"edge_type": "match_pair", "position_id": pid, "cik": cik,
            "source": "bdc", "begin_fair_value": bfv, "end_fair_value": efv,
            "match_method": method, "begin_report_date": "2025-03-31",
            "end_report_date": "2025-06-30"}


class TestEdgeAnomalies:
    def test_fv_jump_flagged_per_tier(self):
        edges = _edges([
            _edge("POS-1", "B2_exact_name", 100.0, 110.0),   # normal
            _edge("POS-2", "B2_exact_name", 100.0, 900.0),   # 9x jump -> anomaly
            _edge("POS-3", "D_fuzzy", 50.0, 55.0),           # normal
        ])
        out = mq.edge_anomalies(edges)
        b2 = out[out["scope"] == "B2_exact_name"].iloc[0]
        assert b2["numerator"] == 1 and b2["denominator"] == 2
        d = out[out["scope"] == "D_fuzzy"].iloc[0]
        assert d["numerator"] == 0 and d["denominator"] == 1


class TestDriftBreakCandidates:
    def test_detects_rename_pair(self):
        df = _holdings([
            # chain POS-1 stops at q1 under name "Acme Corp" ...
            _row("0000000001", "2025-03-31", "Acme Corp", 100.0, "POS-1", "ROW-a",
                 interest_rate=10.0, maturity_date="2029-01-15"),
            # ... and a brand-new chain starts q2 as "Acme Holdings" with same terms
            _row("0000000001", "2025-06-30", "Acme Holdings", 102.0, "POS-2", "ROW-b",
                 interest_rate=10.0, maturity_date="2029-01-15"),
            # unrelated stable chain so q2 is not terminal-only noise
            _row("0000000001", "2025-03-31", "Beta LLC", 50.0, "POS-3", "ROW-c"),
            _row("0000000001", "2025-06-30", "Beta LLC", 51.0, "POS-3", "ROW-d"),
        ])
        cands = mq.drift_break_candidates(df)
        assert len(cands) == 1
        assert cands.iloc[0]["dropped_row_id"] == "ROW-a"
        assert cands.iloc[0]["start_row_id"] == "ROW-b"

    def test_different_terms_not_candidate(self):
        df = _holdings([
            _row("0000000001", "2025-03-31", "Acme Corp", 100.0, "POS-1", "ROW-a",
                 interest_rate=10.0, maturity_date="2029-01-15"),
            _row("0000000001", "2025-06-30", "Gamma Inc", 300.0, "POS-2", "ROW-b",
                 interest_rate=6.0, maturity_date="2027-06-01"),
        ])
        assert len(mq.drift_break_candidates(df)) == 0


class TestEntityStats:
    def test_coverage_and_cross_fund(self):
        df = _holdings([
            _row("0000000001", "2025-03-31", "Acme Corp", 10.0, "POS-1", "ROW-a",
                 entity_id="ENT-1"),
            _row("0000000002", "2025-03-31", "Acme Corporation", 20.0, "POS-2", "ROW-b",
                 entity_id="ENT-1"),
            _row("0000000002", "2025-03-31", "Solo Co", 20.0, "POS-3", "ROW-c"),
        ])
        out = mq.entity_stats(df)
        cov = out[out["metric"] == "entity_coverage_rate"].iloc[0]
        assert cov["numerator"] == 2 and cov["denominator"] == 3
        xf = out[out["metric"] == "entity_cross_fund_count"].iloc[0]
        assert xf["numerator"] == 1
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_match_quality.py -v -k "Anomal or Drift or Entity"`
Expected: FAIL with `AttributeError` (functions missing).

- [ ] **Step 3: Implement**

Append to `pipeline/match_quality.py`:

```python
FV_JUMP_RATIO = 4.0
DRIFT_FV_LO, DRIFT_FV_HI = 0.5, 2.0
DRIFT_RATE_TOL = 0.5          # percentage points
DRIFT_MAX_GAP_DAYS = 100      # adjacent quarters only


def edge_anomalies(edges_df: pd.DataFrame) -> pd.DataFrame:
    """Per-tier share of chain edges with an FV jump beyond FV_JUMP_RATIO."""
    con = duckdb.connect()
    con.register("e", edges_df)
    out = con.execute(f"""
        WITH pairs AS (
            SELECT match_method,
                   TRY_CAST(begin_fair_value AS DOUBLE) AS bfv,
                   TRY_CAST(end_fair_value AS DOUBLE) AS efv
            FROM e
            WHERE TRY_CAST(begin_fair_value AS DOUBLE) > 0
              AND TRY_CAST(end_fair_value AS DOUBLE) > 0
        )
        SELECT match_method AS scope,
               SUM(CASE WHEN GREATEST(bfv, efv) / LEAST(bfv, efv)
                        > {FV_JUMP_RATIO} THEN 1 ELSE 0 END) AS numerator,
               COUNT(*) AS denominator
        FROM pairs GROUP BY 1 ORDER BY 1
    """).df()
    out["scope_type"] = "tier"
    return _finish(out, "edge_fv_jump_rate")


def drift_break_candidates(holdings_df: pd.DataFrame) -> pd.DataFrame:
    """Unchained row pairs that look like the same instrument under a renamed
    issuer: chain ends at q, new chain starts at the next quarter, same CIK and
    classification, FV ratio in [0.5, 2.0], and same maturity or rate within
    0.5pp -- but names differ and no position_id link."""
    con = _con(holdings_df)
    return con.execute(f"""
        WITH rows_q AS ({_BDC_POSITIVE}),
        ends AS (   -- last appearance of each position_id, not CIK-terminal
            SELECT r.* FROM rows_q r
            JOIN (SELECT position_id, MAX(report_date) AS last_d
                  FROM rows_q GROUP BY position_id) l
              ON r.position_id = l.position_id AND r.report_date = l.last_d
            JOIN (SELECT cik, MAX(report_date) AS max_d FROM rows_q GROUP BY cik) m
              ON r.cik = m.cik AND r.report_date < m.max_d
        ),
        starts AS (  -- first appearance of each position_id, not CIK-initial
            SELECT r.* FROM rows_q r
            JOIN (SELECT position_id, MIN(report_date) AS first_d
                  FROM rows_q GROUP BY position_id) f
              ON r.position_id = f.position_id AND r.report_date = f.first_d
            JOIN (SELECT cik, MIN(report_date) AS min_d FROM rows_q GROUP BY cik) m
              ON r.cik = m.cik AND r.report_date > m.min_d
        )
        SELECT d.cik,
               d.row_id AS dropped_row_id, d.issuer_name AS dropped_issuer,
               d.report_date AS dropped_date,
               s.row_id AS start_row_id, s.issuer_name AS start_issuer,
               s.report_date AS start_date,
               s.fv / d.fv AS fv_ratio
        FROM ends d
        JOIN starts s
          ON s.cik = d.cik
         AND s.position_id <> d.position_id
         AND DATEDIFF('day', TRY_CAST(d.report_date AS DATE),
                      TRY_CAST(s.report_date AS DATE))
             BETWEEN 1 AND {DRIFT_MAX_GAP_DAYS}
         AND s.index_classification = d.index_classification
         AND s.fv / d.fv BETWEEN {DRIFT_FV_LO} AND {DRIFT_FV_HI}
         AND LOWER(TRIM(s.issuer_name)) <> LOWER(TRIM(d.issuer_name))
         AND ( (s.maturity_date IS NOT NULL AND s.maturity_date = d.maturity_date)
               OR (s.rate IS NOT NULL AND d.rate IS NOT NULL
                   AND ABS(s.rate - d.rate) <= {DRIFT_RATE_TOL}) )
        ORDER BY d.cik, d.row_id, s.row_id
    """).df()


def drift_break_metric(holdings_df: pd.DataFrame) -> pd.DataFrame:
    cands = drift_break_candidates(holdings_df)
    n_pairs = len(cands)
    total = pd.DataFrame([{
        "scope": "ALL", "scope_type": "ALL",
        "numerator": n_pairs, "denominator": max(n_pairs, 1),
    }])
    out = _finish(total, "drift_break_candidate_pairs")
    out.loc[out["metric"] == "drift_break_candidate_pairs", "value"] = float(n_pairs)
    return out


def entity_stats(holdings_df: pd.DataFrame) -> pd.DataFrame:
    con = _con(holdings_df)
    cov = con.execute("""
        SELECT SUM(CASE WHEN entity_id IS NOT NULL AND entity_id <> ''
                        THEN 1 ELSE 0 END) AS numerator,
               COUNT(*) AS denominator
        FROM h WHERE source = 'bdc'
    """).df()
    cov["scope"] = "ALL"
    cov["scope_type"] = "ALL"
    cov = _finish(cov, "entity_coverage_rate")
    xf = con.execute("""
        SELECT COUNT(*) AS numerator FROM (
            SELECT entity_id FROM h
            WHERE entity_id IS NOT NULL AND entity_id <> ''
            GROUP BY entity_id HAVING COUNT(DISTINCT cik) > 1
        )
    """).df()
    xf["denominator"] = 1
    xf["scope"] = "ALL"
    xf["scope_type"] = "ALL"
    xf = _finish(xf, "entity_cross_fund_count")
    xf["value"] = xf["numerator"].astype(float)
    return pd.concat([cov, xf], ignore_index=True)


def compute_all(holdings_df: pd.DataFrame, edges_df: pd.DataFrame) -> pd.DataFrame:
    parts = [
        chain_continuity(holdings_df),
        singleton_decomposition(holdings_df),
        edge_anomalies(edges_df),
        drift_break_metric(holdings_df),
        entity_stats(holdings_df),
    ]
    out = pd.concat(parts, ignore_index=True)
    return out.sort_values(["metric", "scope_type", "scope"]).reset_index(drop=True)
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_match_quality.py -v`
Expected: all PASS (including Task 1 tests).

- [ ] **Step 5: Commit**

```bash
git add pipeline/match_quality.py tests/test_match_quality.py
git commit -m "feat: anomaly, drift-break, entity metrics + compute_all

- edge_fv_jump_rate per tier from position_id_edges
- drift_break_candidates: renamed-issuer pair detector (feeds gold sampler)
- entity coverage/cross-fund stats; compute_all() concat"
```

---

### Task 3: Rebuild wiring for `--match-quality`

**Files:**
- Modify: `pipeline/match_quality.py` (top-level loader/writer)
- Modify: `scripts/rebuild_outputs.py` (argparse pattern at lines 464-598)
- Test: `tests/test_match_quality.py` (append)

**Interfaces:**
- Produces: `match_quality.build_match_quality_metrics(holdings_path=None, edges_path=None, output_path=None, cohort_only=True) -> pd.DataFrame` -- loads CSVs via DuckDB `read_csv_auto`, filters to cohort when `cohort_only`, writes `MATCH_QUALITY_METRICS_FILE`, returns the frame.
- Consumes: `pipeline.cohort_guard.load_cohort_ciks()` (returns 10-digit padded CIK set).

- [ ] **Step 1: Write failing test (append)**

```python
class TestBuildMetrics:
    def test_writes_csv_to_given_path(self, tmp_path):
        holdings = _holdings([
            _row("0000000001", "2025-03-31", "Acme Corp", 10.0, "POS-1", "ROW-a"),
            _row("0000000001", "2025-06-30", "Acme Corp", 11.0, "POS-1", "ROW-b"),
            _row("0000000009", "2025-03-31", "OffCohort", 10.0, "POS-5", "ROW-x"),
        ])
        edges = _edges([_edge("POS-1", "B2_exact_name", 10.0, 11.0)])
        hp = tmp_path / "holdings.csv"
        ep = tmp_path / "edges.csv"
        op = tmp_path / "metrics.csv"
        holdings.to_csv(hp, index=False)
        edges.to_csv(ep, index=False)
        out = mq.build_match_quality_metrics(
            holdings_path=hp, edges_path=ep, output_path=op,
            cohort_ciks={"0000000001"})
        assert op.exists()
        assert list(out.columns) == mq.METRIC_COLUMNS
        # off-cohort CIK filtered out of every scope
        assert "0000000009" not in set(out["scope"])
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_match_quality.py::TestBuildMetrics -v`
Expected: FAIL (`AttributeError: build_match_quality_metrics`).

- [ ] **Step 3: Implement loader/writer (append to match_quality.py)**

```python
def build_match_quality_metrics(
    holdings_path=None, edges_path=None, output_path=None, cohort_ciks=None,
) -> pd.DataFrame:
    from pipeline.config import (
        MATCH_QUALITY_METRICS_FILE, POSITION_ID_EDGES_FILE, UNIFIED_HOLDINGS_FILE,
    )
    holdings_path = holdings_path or UNIFIED_HOLDINGS_FILE
    edges_path = edges_path or POSITION_ID_EDGES_FILE
    output_path = output_path or MATCH_QUALITY_METRICS_FILE
    if cohort_ciks is None:
        from pipeline.cohort_guard import load_cohort_ciks
        cohort_ciks = load_cohort_ciks()

    con = duckdb.connect()
    hp = str(holdings_path).replace("'", "''")
    ep = str(edges_path).replace("'", "''")
    holdings = con.execute(
        f"SELECT * FROM read_csv_auto('{hp}', all_varchar=true)").df()
    edges = con.execute(
        f"SELECT * FROM read_csv_auto('{ep}', all_varchar=true)").df()
    holdings = holdings[holdings["cik"].isin(cohort_ciks)].reset_index(drop=True)
    edges = edges[edges["cik"].astype(str).str.zfill(10).isin(cohort_ciks)].reset_index(drop=True)

    out = compute_all(holdings, edges)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(output_path, index=False)
    logger.info("Match-quality metrics: %d rows -> %s", len(out), output_path)
    return out
```

Note: edges CSV stores CIK unpadded (written from match rows); the `zfill(10)` normalizes. Holdings CIKs are already 10-digit padded.

- [ ] **Step 4: Run test, verify pass**

Run: `python -m pytest tests/test_match_quality.py -v`
Expected: all PASS.

- [ ] **Step 5: Wire into rebuild_outputs.py**

Add a rebuild function next to the others:

```python
def rebuild_match_quality():
    """Rebuild match-quality metrics (cohort scope) from existing outputs."""
    import time
    from pipeline.match_quality import build_match_quality_metrics
    logger.info("=== Rebuilding match-quality metrics ===")
    t0 = time.time()
    df = build_match_quality_metrics()
    logger.info("Match-quality metrics: %d rows in %.1f s", len(df), time.time() - t0)
```

Add `parser.add_argument("--match-quality", action="store_true", help="Rebuild match-quality metrics from position matches + unified holdings")`, add `args.match_quality` to the `rebuild_all = not (...)` expression, and append:

```python
    if rebuild_all or args.match_quality:
        rebuild_match_quality()
```

Place the call AFTER the returns/matches block so metrics always see fresh edges on full rebuilds.

- [ ] **Step 6: Smoke-run the flag on real data**

Run: `python scripts/rebuild_outputs.py --match-quality`
Expected: completes in well under a minute, ASCII-only log lines, writes `data/output/match_quality_metrics.csv`. Inspect: `python -c` is banned; use `duckdb -c "SELECT metric, COUNT(*) FROM read_csv_auto('data/output/match_quality_metrics.csv') GROUP BY 1"` if the DuckDB CLI is available, otherwise open the CSV head in the editor. Confirm every metric name appears.

- [ ] **Step 7: Commit**

```bash
git add pipeline/match_quality.py scripts/rebuild_outputs.py tests/test_match_quality.py
git commit -m "feat: wire match-quality metrics into rebuild_outputs

- build_match_quality_metrics(): cohort-filtered loader/writer
- rebuild_outputs.py --match-quality flag; runs after returns block
- artifact: data/output/match_quality_metrics.csv"
```

---

### Task 4: Verdict schema validator (`pipeline/match_verdict_leaf.py`)

**Files:**
- Create: `pipeline/match_verdict_leaf.py`
- Test: `tests/test_match_verdict_leaf.py`

**Interfaces:**
- Produces: `validate_match_verdict(doc: dict) -> list[str]` (empty list = valid; strings are error messages);
  constants `PACKET_VERDICTS = {"CONFIRMED", "WRONG_MERGE", "MISSED_LINK", "MIXED", "INSUFFICIENT_EVIDENCE"}`, `EDGE_VERDICTS = {"CONFIRMED", "WRONG", "UNCERTAIN"}`.
- Consumed by: Task 8 scorer.

Verdict JSON contract (workers write one per packet):

```json
{
  "packet_id": "MGP-...",
  "packet_type": "chain",
  "verdict": "CONFIRMED | WRONG_MERGE | MISSED_LINK | MIXED | INSUFFICIENT_EVIDENCE",
  "confidence": 0.9,
  "edge_verdicts": [
    {"edge_index": 0, "verdict": "CONFIRMED | WRONG | UNCERTAIN",
     "evidence": [{"accession": "0001...", "table_index": 3, "row_index": 41,
                   "quoted_text": "Acme Corp, First Lien Term Loan"}]}
  ],
  "proposed_links": [
    {"row_id_a": "ROW-...", "row_id_b": "ROW-...",
     "evidence": [{"accession": "...", "quoted_text": "..."}]}
  ],
  "rationale": "...",
  "escalate": false
}
```

Grounding invariants (mirror `pipeline/verdict_leaf.py`):
- chain packets: `edge_verdicts` must cover every edge_index listed in the packet exactly once; any edge verdict of `WRONG` needs at least one evidence citation with `quoted_text` or (`table_index` and `row_index`).
- `MISSED_LINK` (either packet type) requires non-empty `proposed_links`, each with at least one citation.
- `INSUFFICIENT_EVIDENCE` requires a non-empty `rationale`; no citation demanded (honest escalation is valid).
- entity packets: `edge_verdicts` empty; packet-level verdict + citations judge the cluster (`WRONG_MERGE` needs at least 1 citation).

- [ ] **Step 1: Write failing tests**

Create `tests/test_match_verdict_leaf.py`:

```python
import pytest

from pipeline.match_verdict_leaf import validate_match_verdict


def _base(**kw):
    d = {
        "packet_id": "MGP-abc123", "packet_type": "chain",
        "verdict": "CONFIRMED", "confidence": 0.9,
        "edge_verdicts": [{"edge_index": 0, "verdict": "CONFIRMED", "evidence": []}],
        "proposed_links": [], "rationale": "matches across filings", "escalate": False,
    }
    d.update(kw)
    return d


def test_valid_confirmed_chain():
    assert validate_match_verdict(_base(), expected_edges=[0]) == []


def test_missing_required_key():
    d = _base()
    del d["confidence"]
    errs = validate_match_verdict(d, expected_edges=[0])
    assert any("confidence" in e for e in errs)


def test_wrong_edge_requires_citation():
    d = _base(verdict="WRONG_MERGE",
              edge_verdicts=[{"edge_index": 0, "verdict": "WRONG", "evidence": []}])
    errs = validate_match_verdict(d, expected_edges=[0])
    assert any("citation" in e for e in errs)


def test_edge_coverage_must_be_exact():
    errs = validate_match_verdict(_base(), expected_edges=[0, 1])
    assert any("edge" in e for e in errs)


def test_missed_link_requires_proposed_links():
    d = _base(verdict="MISSED_LINK", proposed_links=[])
    errs = validate_match_verdict(d, expected_edges=[0])
    assert any("proposed_links" in e for e in errs)


def test_insufficient_evidence_needs_rationale_only():
    d = _base(verdict="INSUFFICIENT_EVIDENCE", rationale="filing table truncated",
              edge_verdicts=[{"edge_index": 0, "verdict": "UNCERTAIN", "evidence": []}])
    assert validate_match_verdict(d, expected_edges=[0]) == []


def test_entity_packet_wrong_merge_needs_citation():
    d = _base(packet_type="entity", verdict="WRONG_MERGE", edge_verdicts=[])
    errs = validate_match_verdict(d, expected_edges=[])
    assert any("citation" in e for e in errs)
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_match_verdict_leaf.py -v`
Expected: FAIL with ModuleNotFoundError.

- [ ] **Step 3: Implement**

```python
"""Schema validation for match-gold verdict leaves.

Mirrors pipeline/verdict_leaf.py conventions: validator returns a list of
error strings (empty = valid); grounding invariants are hard errors.
"""
from __future__ import annotations

PACKET_VERDICTS = {"CONFIRMED", "WRONG_MERGE", "MISSED_LINK", "MIXED",
                   "INSUFFICIENT_EVIDENCE"}
EDGE_VERDICTS = {"CONFIRMED", "WRONG", "UNCERTAIN"}
_REQUIRED = ["packet_id", "packet_type", "verdict", "confidence", "rationale"]


def _valid_citation(c: dict) -> bool:
    if not isinstance(c, dict):
        return False
    if c.get("quoted_text"):
        return True
    return c.get("table_index") is not None and c.get("row_index") is not None


def validate_match_verdict(doc: dict, *, expected_edges: list[int]) -> list[str]:
    errs: list[str] = []
    for k in _REQUIRED:
        if k not in doc or doc[k] in (None, ""):
            errs.append(f"missing required key: {k}")
    if errs:
        return errs
    if doc["verdict"] not in PACKET_VERDICTS:
        errs.append(f"unknown verdict: {doc['verdict']}")
    try:
        conf = float(doc["confidence"])
        if not 0.0 <= conf <= 1.0:
            errs.append("confidence out of [0,1]")
    except (TypeError, ValueError):
        errs.append("confidence not a number")

    edge_verdicts = doc.get("edge_verdicts") or []
    if doc["packet_type"] == "chain":
        seen = [e.get("edge_index") for e in edge_verdicts]
        if sorted(seen) != sorted(expected_edges):
            errs.append(
                f"edge coverage mismatch: expected {sorted(expected_edges)}, got {sorted(seen)}")
        for e in edge_verdicts:
            if e.get("verdict") not in EDGE_VERDICTS:
                errs.append(f"unknown edge verdict: {e.get('verdict')}")
            if e.get("verdict") == "WRONG":
                if not any(_valid_citation(c) for c in e.get("evidence") or []):
                    errs.append(
                        f"edge {e.get('edge_index')}: WRONG requires a citation")
    elif doc["packet_type"] == "entity":
        if doc["verdict"] == "WRONG_MERGE":
            cites = doc.get("evidence") or []
            if not any(_valid_citation(c) for c in cites):
                errs.append("entity WRONG_MERGE requires a citation")
    else:
        errs.append(f"unknown packet_type: {doc['packet_type']}")

    if doc["verdict"] == "MISSED_LINK":
        links = doc.get("proposed_links") or []
        if not links:
            errs.append("MISSED_LINK requires non-empty proposed_links")
        for ln in links:
            if not any(_valid_citation(c) for c in ln.get("evidence") or []):
                errs.append("proposed link missing citation")
    return errs
```

- [ ] **Step 4: Run tests, verify pass**

Run: `python -m pytest tests/test_match_verdict_leaf.py -v`
Expected: all PASS. Note the entity WRONG_MERGE test reads `doc["evidence"]` -- packet-level citations live under key `evidence` for entity packets.

- [ ] **Step 5: Commit**

```bash
git add pipeline/match_verdict_leaf.py tests/test_match_verdict_leaf.py
git commit -m "feat: match-gold verdict leaf validator

- packet/edge verdict enums, grounding invariants (WRONG needs citation,
  MISSED_LINK needs proposed_links, INSUFFICIENT_EVIDENCE is valid escalation)
- mirrors verdict_leaf.py error-list convention"
```

---

### Task 5: Chain packet sampler

**Files:**
- Create: `scripts/match_gold/__init__.py` (empty), `scripts/match_gold/build_packets.py`
- Test: `tests/test_match_gold_packets.py`

**Interfaces:**
- Produces: `sample_chains(holdings_df, edges_df, *, seed=20260903, per_tier=40, n_fv_jump=40, n_interior_singleton=40, n_drift_break=40) -> pd.DataFrame` with columns `packet_id, packet_type, stratum, position_id, cik` (one row per sampled packet; singleton/drift packets carry `position_id` of the anchor row's pid).
- Consumes: `match_quality.drift_break_candidates`, edges schema from Task 2.
- Deterministic: same inputs -> same sample (ordering via `md5(position_id)`, no RNG state).

- [ ] **Step 1: Write failing tests**

Create `tests/test_match_gold_packets.py`:

```python
import pandas as pd

from tests.test_match_quality import _edge, _edges, _holdings, _row  # reuse builders
from scripts.match_gold import build_packets as bp


def _chain_fixture():
    holdings = _holdings([
        _row("0000000001", "2025-03-31", "Acme Corp", 100.0, "POS-1", "ROW-a"),
        _row("0000000001", "2025-06-30", "Acme Corp", 101.0, "POS-1", "ROW-b"),
        _row("0000000001", "2025-03-31", "Beta LLC", 50.0, "POS-2", "ROW-c"),
        _row("0000000001", "2025-06-30", "Beta LLC", 900.0, "POS-2", "ROW-d"),
    ])
    edges = _edges([
        _edge("POS-1", "B2_exact_name", 100.0, 101.0),
        _edge("POS-2", "D_fuzzy", 50.0, 900.0),   # fv-jump anomaly
    ])
    return holdings, edges


def test_sample_chains_strata_and_determinism():
    holdings, edges = _chain_fixture()
    s1 = bp.sample_chains(holdings, edges, per_tier=5, n_fv_jump=5,
                          n_interior_singleton=5, n_drift_break=5)
    s2 = bp.sample_chains(holdings, edges, per_tier=5, n_fv_jump=5,
                          n_interior_singleton=5, n_drift_break=5)
    pd.testing.assert_frame_equal(s1, s2)          # deterministic
    assert set(s1["stratum"]) >= {"tier_random", "fv_jump"}
    # POS-2 must appear in the fv_jump stratum
    assert "POS-2" in set(s1[s1["stratum"] == "fv_jump"]["position_id"])


def test_no_duplicate_packet_for_same_pid_and_stratum():
    holdings, edges = _chain_fixture()
    s = bp.sample_chains(holdings, edges, per_tier=5, n_fv_jump=5,
                         n_interior_singleton=5, n_drift_break=5)
    assert not s.duplicated(["stratum", "position_id"]).any()
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_match_gold_packets.py -v`
Expected: FAIL with ModuleNotFoundError.

- [ ] **Step 3: Implement sampler**

`scripts/match_gold/build_packets.py` (module header + sampler; packet writing arrives in Task 7):

```python
"""Build blinded match-gold adjudication packets (chains + entity clusters).

Deterministic stratified sampling (frozen seed via md5 ordering, no RNG).
Chain strata: tier_random (per match tier), fv_jump (anomalous edges),
interior_singleton (missed-link hunting), drift_break (renamed-issuer pairs).
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import duckdb
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from pipeline.match_quality import drift_break_candidates  # noqa: E402

SEED = "20260903"
SAMPLE_COLUMNS = ["packet_id", "packet_type", "stratum", "position_id", "cik"]


def _packet_id(*parts: str) -> str:
    digest = hashlib.md5(("|".join(parts) + SEED).encode("utf-8")).hexdigest()[:12]
    return f"MGP-{digest}"


def sample_chains(holdings_df, edges_df, *, per_tier=40, n_fv_jump=40,
                  n_interior_singleton=40, n_drift_break=40) -> pd.DataFrame:
    con = duckdb.connect()
    con.register("h", holdings_df)
    con.register("e", edges_df)
    rows: list[dict] = []

    tier_sample = con.execute(f"""
        WITH ranked AS (
            SELECT position_id, cik, match_method,
                   ROW_NUMBER() OVER (
                       PARTITION BY match_method
                       ORDER BY md5(position_id || '{SEED}')) AS rn
            FROM (SELECT DISTINCT position_id, cik, match_method FROM e)
        )
        SELECT DISTINCT position_id, cik, match_method
        FROM ranked WHERE rn <= {per_tier}
        ORDER BY match_method, position_id
    """).df()
    for r in tier_sample.itertuples(index=False):   # sample-sized frame only
        rows.append({"packet_id": _packet_id("chain", "tier_random", r.position_id),
                     "packet_type": "chain", "stratum": "tier_random",
                     "position_id": r.position_id, "cik": str(r.cik)})

    jump = con.execute(f"""
        SELECT DISTINCT position_id, cik FROM e
        WHERE TRY_CAST(begin_fair_value AS DOUBLE) > 0
          AND TRY_CAST(end_fair_value AS DOUBLE) > 0
          AND GREATEST(TRY_CAST(begin_fair_value AS DOUBLE),
                       TRY_CAST(end_fair_value AS DOUBLE))
              / LEAST(TRY_CAST(begin_fair_value AS DOUBLE),
                      TRY_CAST(end_fair_value AS DOUBLE)) > 4.0
        ORDER BY md5(position_id || '{SEED}') LIMIT {n_fv_jump}
    """).df()
    for r in jump.itertuples(index=False):
        rows.append({"packet_id": _packet_id("chain", "fv_jump", r.position_id),
                     "packet_type": "chain", "stratum": "fv_jump",
                     "position_id": r.position_id, "cik": str(r.cik)})

    singles = con.execute(f"""
        WITH bdc AS (
            SELECT cik, report_date, position_id,
                   TRY_CAST(fair_value AS DOUBLE) AS fv
            FROM h WHERE source = 'bdc' AND position_id IS NOT NULL),
        pid1 AS (SELECT position_id FROM bdc GROUP BY position_id HAVING COUNT(*) = 1),
        bounds AS (SELECT cik, MIN(report_date) mn, MAX(report_date) mx
                   FROM bdc GROUP BY cik)
        SELECT b.position_id, b.cik FROM bdc b
        JOIN pid1 p ON b.position_id = p.position_id
        JOIN bounds bd ON b.cik = bd.cik
        WHERE b.fv > 0 AND b.report_date > bd.mn AND b.report_date < bd.mx
        ORDER BY md5(b.position_id || '{SEED}') LIMIT {n_interior_singleton}
    """).df()
    for r in singles.itertuples(index=False):
        rows.append({"packet_id": _packet_id("chain", "interior_singleton", r.position_id),
                     "packet_type": "chain", "stratum": "interior_singleton",
                     "position_id": r.position_id, "cik": str(r.cik)})

    drift = drift_break_candidates(holdings_df)
    if len(drift):
        drift = drift.assign(
            _o=[hashlib.md5((x + SEED).encode()).hexdigest()
                for x in drift["dropped_row_id"]]
        ).sort_values("_o").head(n_drift_break)
        pid_of = holdings_df.set_index("row_id")["position_id"]
        for r in drift.itertuples(index=False):
            rows.append({
                "packet_id": _packet_id("chain", "drift_break", r.dropped_row_id),
                "packet_type": "chain", "stratum": "drift_break",
                "position_id": pid_of.get(r.dropped_row_id, ""),
                "cik": str(r.cik)})

    out = pd.DataFrame(rows, columns=SAMPLE_COLUMNS)
    out = out.drop_duplicates(["stratum", "position_id"])
    return out.sort_values(["stratum", "packet_id"]).reset_index(drop=True)
```

- [ ] **Step 4: Run tests, verify pass**

Run: `python -m pytest tests/test_match_gold_packets.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/match_gold/__init__.py scripts/match_gold/build_packets.py tests/test_match_gold_packets.py
git commit -m "feat: chain packet sampler for match-gold

- 4 strata: tier_random / fv_jump / interior_singleton / drift_break
- deterministic md5-ordered sampling, frozen seed 20260903
- packet ids MGP-<digest>"
```

---

### Task 6: Entity packet sampler

**Files:**
- Modify: `scripts/match_gold/build_packets.py`
- Test: `tests/test_match_gold_packets.py` (append)

**Interfaces:**
- Produces: `sample_entities(holdings_df, *, n_merge_verify=60, n_cross_fund_near_miss=100, n_within_fund=40) -> pd.DataFrame` with columns `packet_id, packet_type, stratum, cluster_key, ciks` where `cluster_key` is `entity_id` for merge_verify or `nameA||nameB` for near-miss pairs, `ciks` is a `;`-joined sorted CIK list.
- Uses DuckDB `jaro_winkler_similarity` with 4-char prefix blocking (existing convention: `entity_resolution.py` fuzzy pass).

- [ ] **Step 1: Write failing tests (append)**

```python
def test_sample_entities_near_miss_pair():
    holdings = _holdings([
        _row("0000000001", "2025-06-30", "Acme Corporation", 10.0, "POS-1", "ROW-a"),
        _row("0000000002", "2025-06-30", "Acme Corportion", 20.0, "POS-2", "ROW-b"),  # typo variant, different fund
        _row("0000000001", "2025-06-30", "Zebra Partners", 10.0, "POS-3", "ROW-c"),
    ])
    s = bp.sample_entities(holdings)
    near = s[s["stratum"] == "cross_fund_near_miss"]
    assert len(near) == 1
    assert near.iloc[0]["ciks"] == "0000000001;0000000002"


def test_sample_entities_merge_verify_cross_fund_cluster():
    holdings = _holdings([
        _row("0000000001", "2025-06-30", "Acme Corp", 10.0, "POS-1", "ROW-a",
             entity_id="ENT-1"),
        _row("0000000002", "2025-06-30", "Acme Corporation", 20.0, "POS-2", "ROW-b",
             entity_id="ENT-1"),
    ])
    s = bp.sample_entities(holdings)
    mv = s[s["stratum"] == "entity_merge_verify"]
    assert list(mv["cluster_key"]) == ["ENT-1"]


def test_sample_entities_deterministic():
    holdings = _holdings([
        _row("0000000001", "2025-06-30", "Acme Corporation", 10.0, "POS-1", "ROW-a"),
        _row("0000000002", "2025-06-30", "Acme Corportion", 20.0, "POS-2", "ROW-b"),
    ])
    pd.testing.assert_frame_equal(bp.sample_entities(holdings),
                                  bp.sample_entities(holdings))
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_match_gold_packets.py -v -k entities`
Expected: FAIL (`AttributeError: sample_entities`).

- [ ] **Step 3: Implement (append to build_packets.py)**

```python
JW_LO, JW_HI = 0.86, 0.97


def sample_entities(holdings_df, *, n_merge_verify=60,
                    n_cross_fund_near_miss=100, n_within_fund=40) -> pd.DataFrame:
    con = duckdb.connect()
    con.register("h", holdings_df)
    rows: list[dict] = []

    merge_verify = con.execute(f"""
        WITH clusters AS (
            SELECT entity_id,
                   COUNT(DISTINCT cik) AS n_ciks,
                   COUNT(DISTINCT issuer_name) AS n_names,
                   STRING_AGG(DISTINCT cik, ';' ORDER BY cik) AS ciks
            FROM h
            WHERE entity_id IS NOT NULL AND entity_id <> ''
            GROUP BY entity_id
            HAVING COUNT(DISTINCT cik) > 1 OR COUNT(DISTINCT issuer_name) > 1
        )
        SELECT entity_id, ciks,
               ROW_NUMBER() OVER (ORDER BY n_ciks DESC,
                                  md5(entity_id || '{SEED}')) AS rn
        FROM clusters QUALIFY rn <= {n_merge_verify}
        ORDER BY entity_id
    """).df()
    for r in merge_verify.itertuples(index=False):
        rows.append({"packet_id": _packet_id("entity", "entity_merge_verify", r.entity_id),
                     "packet_type": "entity", "stratum": "entity_merge_verify",
                     "cluster_key": r.entity_id, "ciks": r.ciks})

    near = con.execute(f"""
        WITH names AS (
            SELECT DISTINCT cik, LOWER(TRIM(issuer_name)) AS nm,
                   COALESCE(entity_id, '') AS eid
            FROM h WHERE source = 'bdc' AND issuer_name IS NOT NULL
        )
        SELECT a.nm AS name_a, b.nm AS name_b,
               a.cik AS cik_a, b.cik AS cik_b
        FROM names a JOIN names b
          ON a.cik < b.cik
         AND LEFT(a.nm, 4) = LEFT(b.nm, 4)
         AND a.nm <> b.nm
         AND (a.eid = '' OR b.eid = '' OR a.eid <> b.eid)
         AND jaro_winkler_similarity(a.nm, b.nm) BETWEEN {JW_LO} AND {JW_HI}
        ORDER BY md5(a.nm || b.nm || '{SEED}')
        LIMIT {n_cross_fund_near_miss}
    """).df()
    for r in near.itertuples(index=False):
        key = f"{r.name_a}||{r.name_b}"
        ciks = ";".join(sorted([str(r.cik_a), str(r.cik_b)]))
        rows.append({"packet_id": _packet_id("entity", "cross_fund_near_miss", key),
                     "packet_type": "entity", "stratum": "cross_fund_near_miss",
                     "cluster_key": key, "ciks": ciks})

    within = con.execute(f"""
        WITH names AS (
            SELECT DISTINCT cik, LOWER(TRIM(issuer_name)) AS nm
            FROM h WHERE source = 'bdc' AND issuer_name IS NOT NULL
        )
        SELECT a.nm AS name_a, b.nm AS name_b, a.cik
        FROM names a JOIN names b
          ON a.cik = b.cik AND a.nm < b.nm
         AND LEFT(a.nm, 4) = LEFT(b.nm, 4)
         AND jaro_winkler_similarity(a.nm, b.nm) BETWEEN {JW_LO} AND {JW_HI}
        ORDER BY md5(a.nm || b.nm || '{SEED}')
        LIMIT {n_within_fund}
    """).df()
    for r in within.itertuples(index=False):
        key = f"{r.name_a}||{r.name_b}"
        rows.append({"packet_id": _packet_id("entity", "within_fund_name_cluster", key),
                     "packet_type": "entity", "stratum": "within_fund_name_cluster",
                     "cluster_key": key, "ciks": str(r.cik)})

    out = pd.DataFrame(rows, columns=["packet_id", "packet_type", "stratum",
                                      "cluster_key", "ciks"])
    out = out.drop_duplicates(["stratum", "cluster_key"])
    return out.sort_values(["stratum", "packet_id"]).reset_index(drop=True)
```

Note: `QUALIFY` is valid DuckDB; if the installed version rejects it, wrap the ranked CTE in a subquery with `WHERE rn <= ...` -- adjust and keep the test green.

Note on test fixtures: Jaro-Winkler values are hard to eyeball. If a fixture name pair lands outside the [0.86, 0.97] band and the near-miss test fails, verify with `duckdb -c "SELECT jaro_winkler_similarity('acme corporation','acme corportion')"` and adjust the FIXTURE NAMES until the pair scores inside the band -- do not widen the band constants to make the test pass.

- [ ] **Step 4: Run tests, verify pass**

Run: `python -m pytest tests/test_match_gold_packets.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/match_gold/build_packets.py tests/test_match_gold_packets.py
git commit -m "feat: entity packet sampler (merge-verify + JW near-miss strata)

- cross-fund near-miss band [0.86, 0.97] with 4-char blocking
- entity_merge_verify prioritizes multi-CIK clusters
- deterministic md5 ordering, no RNG"
```

---

### Task 7: Packet writer (JSON, prompts, mini-bundles, worklist) + evidence CLI registration

**Files:**
- Modify: `scripts/match_gold/build_packets.py` (writer + `main()`)
- Modify: `scripts/review_agent/evidence_cli.py:37-42` (`_ENGINE_SOURCE` add `"match_gold": "BDC"`)
- Test: `tests/test_match_gold_packets.py` (append)

**Interfaces:**
- Produces: `write_batch(holdings_df, edges_df, chain_sample, entity_sample, batch_dir: Path) -> dict` returning `{"n_packets": int, "n_missing_filing": int, "worklist_path": str}`. CLI: `python scripts/match_gold/build_packets.py --batch-id mg1 [--out-dir <dir>]` (out-dir defaults to `config.MATCH_GOLD_DIR / batch_id`; tests pass tmp_path).
- Packet JSON (blinded -- NO match_method/match_score anywhere):

```json
{
  "schema_version": "match-gold-packet.v1",
  "packet_id": "MGP-...", "packet_type": "chain", "cik": "0001234567",
  "rows": [{"row_id": "...", "report_date": "...", "issuer_name": "...",
            "instrument_description": "...", "bdc_investment_identifier": "...",
            "fair_value": "...", "principal_amount": "...", "interest_rate": "...",
            "basis_spread": "...", "maturity_date": "...",
            "accession_number": "..."}],
  "edges": [{"edge_index": 0, "begin_row_id": "...", "end_row_id": "..."}],
  "candidate_rows": [],
  "accessions": ["0001..."],
  "filing_bundles": {"0001...": "filings/MGP-.../0001....json"}
}
```

- Sidecar `packets_meta/<packet_id>.json`: `{"packet_id": ..., "stratum": ..., "edges": [{"edge_index": 0, "match_method": "B2_exact_name", "match_score": "1.0"}]}`.
- Mini-bundle per accession (readable by `evidence_cli._load`): `{"schema_version": "review-bundle.v1", "engine": "match_gold", "cik": <cik>, "report_date": <date>, "evidence_items": [{"evidence_id": "rows", "description": "packet rows for this filing", "data": [{"accession_number": <acc>}]}]}`.
- Chain packets: rows = all unified rows for the position_id (capped at the 12 most recent report_dates; cap recorded as `"truncated": true`). Edges resolved to row_ids by joining edges to rows on `(position_id, begin_report_date -> row of that date, end_report_date -> row of that date)`; where a chain has multiple rows on one date, pick by exact `begin_fair_value`/`end_fair_value` string match first, else lowest row_id (deterministic).
- `interior_singleton` packets: rows = the singleton row; `candidate_rows` = up to 8 same-CIK rows from the immediately previous and next report_date ordered by `ABS(fv - singleton_fv)` (missed-link candidates); `edges` empty.
- `drift_break` packets: rows = dropped row + start row; `edges` empty; verdict of interest is MISSED_LINK vs CONFIRMED(-ly different).
- Entity packets: rows = up to 8 rows per issuer-name variant (most recent first), across all CIKs in the cluster.
- Worklist CSV columns: `packet_id, packet_type, stratum, cik, n_rows, n_edges, prompt_path, packet_path, verdict_path, has_cached_filing`.
- Prompt template (module constant `PROMPT_TEMPLATE`), written per packet with paths filled in; content requirements: task statement per packet_type/stratum, evidence CLI usage lines (`python scripts/review_agent/evidence_cli.py --bundle <filings/...> roam --query "..."`), the verdict JSON contract from Task 4 verbatim, output path, "write UTF-8 without BOM via file-edit tool, not Out-File", and the escalation framing: "INSUFFICIENT_EVIDENCE with a clear rationale is a correct, non-penalized outcome. Never invent citations."

- [ ] **Step 1: Write failing tests (append)**

```python
import json


def test_write_batch_layout(tmp_path):
    holdings, edges = _chain_fixture()
    holdings["accession_number"] = "0000000001-25-000001"
    holdings["instrument_description"] = "First Lien Term Loan"
    holdings["bdc_investment_identifier"] = holdings["issuer_name"]
    holdings["principal_amount"] = 100.0
    holdings["basis_spread"] = 5.0
    chain_sample = bp.sample_chains(holdings, edges, per_tier=5, n_fv_jump=5,
                                    n_interior_singleton=5, n_drift_break=5)
    entity_sample = bp.sample_entities(holdings)
    stats = bp.write_batch(holdings, edges, chain_sample, entity_sample, tmp_path)
    assert stats["n_packets"] == len(chain_sample) + len(entity_sample)
    wl = pd.read_csv(tmp_path / "worklist.csv")
    assert set(wl.columns) >= {"packet_id", "packet_type", "stratum",
                               "prompt_path", "packet_path", "verdict_path"}
    pid = wl.iloc[0]["packet_id"]
    packet = json.loads((tmp_path / "packets" / f"{pid}.json").read_text("utf-8"))
    assert packet["schema_version"] == "match-gold-packet.v1"
    # blinding: tier never appears in packet or prompt
    raw = (tmp_path / "packets" / f"{pid}.json").read_text("utf-8")
    prompt = (tmp_path / "prompts" / f"{pid}.md").read_text("utf-8")
    for banned in ("match_method", "B2_exact_name", "D_fuzzy", "match_score"):
        assert banned not in raw and banned not in prompt
    # sidecar has the tier for the scorer
    meta = json.loads((tmp_path / "packets_meta" / f"{pid}.json").read_text("utf-8"))
    assert "stratum" in meta


def test_chain_packet_edges_resolve_to_row_ids(tmp_path):
    holdings, edges = _chain_fixture()
    holdings["accession_number"] = "0000000001-25-000001"
    holdings["instrument_description"] = ""
    holdings["bdc_investment_identifier"] = holdings["issuer_name"]
    holdings["principal_amount"] = None
    holdings["basis_spread"] = None
    chain_sample = bp.sample_chains(holdings, edges, per_tier=5, n_fv_jump=5,
                                    n_interior_singleton=5, n_drift_break=5)
    bp.write_batch(holdings, edges, chain_sample, entity_sample=pd.DataFrame(
        columns=["packet_id", "packet_type", "stratum", "cluster_key", "ciks"]),
        batch_dir=tmp_path)
    pos1 = chain_sample[chain_sample["position_id"] == "POS-1"].iloc[0]["packet_id"]
    packet = json.loads((tmp_path / "packets" / f"{pos1}.json").read_text("utf-8"))
    edge = packet["edges"][0]
    assert edge["begin_row_id"] == "ROW-a" and edge["end_row_id"] == "ROW-b"
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_match_gold_packets.py -v -k write`
Expected: FAIL (`AttributeError: write_batch`).

- [ ] **Step 3: Implement writer**

Append to `build_packets.py`. Core skeleton (implement fully -- row selection SQL per packet type as specified in Interfaces above):

```python
import json

PACKET_ROW_FIELDS = ["row_id", "report_date", "issuer_name",
                     "instrument_description", "bdc_investment_identifier",
                     "fair_value", "principal_amount", "interest_rate",
                     "basis_spread", "maturity_date", "accession_number"]

PROMPT_TEMPLATE = """# Match-Gold Adjudication: {packet_id}

You are a blinded adjudicator. Decide whether the rows in this packet are the
SAME instrument tracked over time (chain packets) or the SAME borrower
(entity packets). You know nothing about how the pipeline linked them, and you
must judge only from the packet rows and the cached SEC filings.

## Your packet
{packet_path}

## How to inspect source filings (cache-only, no network)
For each accession listed in the packet, a bundle file exists under
{filings_dir}. Roam the filing:

    python scripts/review_agent/evidence_cli.py --bundle {filings_dir}/<accession>.json overview
    python scripts/review_agent/evidence_cli.py --bundle {filings_dir}/<accession>.json roam --query "<issuer terms>"
    python scripts/review_agent/evidence_cli.py --bundle {filings_dir}/<accession>.json grid --table N

## Task
{task_text}

## Verdict contract
Write EXACTLY one JSON file to: {verdict_path}
Schema (all keys required unless noted):
{verdict_schema}

Rules:
- Every edge listed in the packet must receive an edge verdict (chain packets).
- A WRONG edge verdict and a WRONG_MERGE packet verdict require at least one
  evidence citation (quoted_text from the filing, or table_index+row_index).
- MISSED_LINK requires proposed_links naming row_ids from the packet.
- INSUFFICIENT_EVIDENCE with a clear rationale is a correct, non-penalized
  outcome. Never invent citations. Never guess.
- Write the file as UTF-8 WITHOUT BOM using your file-edit tool. Do NOT use
  PowerShell Out-File or Set-Content.
"""

_TASK_TEXT = {
    "chain": ("For every edge (begin_row_id -> end_row_id), verify in the two "
              "filings that both rows describe the same instrument: same "
              "borrower, same tranche/lien/type, coherent principal and terms. "
              "Verdict CONFIRMED / WRONG per edge."),
    "interior_singleton": ("The single row in `rows` appears in only one "
                           "quarter. Check `candidate_rows` (adjacent quarters, "
                           "same fund) and the filings: does this instrument "
                           "actually continue under a different name? If yes: "
                           "MISSED_LINK with proposed_links. If it truly "
                           "appears once: CONFIRMED."),
    "drift_break": ("Row 1 leaves the portfolio and row 2 appears the next "
                    "quarter with similar terms. Same instrument renamed "
                    "(MISSED_LINK) or genuinely different (CONFIRMED)?"),
    "entity": ("Are all issuer-name variants in `rows` the same borrower "
               "(legal-entity level)? CONFIRMED if yes, WRONG_MERGE if the "
               "cluster mixes distinct companies, MISSED_LINK if variants "
               "shown as separate are actually one borrower."),
}
```

`write_batch` responsibilities (implement in order):
1. `batch_dir.mkdir(parents=True, exist_ok=True)`; subdirs `packets`, `packets_meta`, `filings/<packet_id>`, `prompts`, `verdicts` (empty dir for workers).
2. For each chain-sample row: pull chain rows from `holdings_df` via DuckDB (`WHERE position_id = ?` ordered by report_date DESC, cap 12 dates, then re-sort ASC), resolve edges to row_ids (join rule in Interfaces), build candidate_rows for `interior_singleton` / row-pair for `drift_break` strata.
3. For each entity-sample row: pull up to 8 rows per name variant.
4. Write packet JSON with `json.dumps(..., indent=2, sort_keys=True)`, `encoding="utf-8"`; sidecar meta with tiers; per-accession mini-bundles; prompt from template (`task_text=_TASK_TEXT[stratum if stratum in _TASK_TEXT else packet_type]`, `verdict_schema` = the JSON block from Task 4 docstring as a string constant).
5. `has_cached_filing`: check `pipeline.html_soi_evidence._html_path("BDC", cik, accession).exists()` per accession; worklist row False if any missing (packet still written; dispatch skips it).
6. Write `worklist.csv` sorted by `packet_id`.
7. Return stats dict.

Add `main()` with argparse (`--batch-id` required, `--out-dir` optional, `--max-chains`/`--max-entities` optional caps) that loads production CSVs via DuckDB `read_csv_auto(..., all_varchar=true)`, filters holdings to cohort CIKs (`load_cohort_ciks()`), runs both samplers, calls `write_batch`, prints stats. Guard with `if __name__ == "__main__": main()`.

- [ ] **Step 4: Register engine in evidence_cli**

In `scripts/review_agent/evidence_cli.py` `_ENGINE_SOURCE` dict (line 37-42) add:

```python
    "match_gold": "BDC",  # match-quality gold-set adjudication packets
```

- [ ] **Step 5: Run tests, verify pass**

Run: `python -m pytest tests/test_match_gold_packets.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/match_gold/build_packets.py scripts/review_agent/evidence_cli.py tests/test_match_gold_packets.py
git commit -m "feat: match-gold packet writer + prompts + evidence CLI hookup

- blinded packet JSON (no tier/score), sidecar meta for scorer
- per-accession mini-bundles readable by evidence_cli (engine=match_gold)
- worklist with has_cached_filing preflight; CLI main() cohort-scoped"
```

---

### Task 8: Scorer (`scripts/match_gold/score_gold.py`)

**Files:**
- Create: `scripts/match_gold/score_gold.py`
- Test: `tests/test_match_gold_score.py`

**Interfaces:**
- Produces:
  `wilson_interval(k: int, n: int, z: float = 1.96) -> tuple[float, float]`;
  `score_batch(batch_dir: Path) -> dict` -- reads `worklist.csv`, `packets_meta/*.json`, `verdicts/*.json` (with `encoding="utf-8-sig"`), validates each verdict via `validate_match_verdict`, writes to batch_dir: `gold_set.csv` (one row per adjudicated unit: `packet_id, packet_type, stratum, unit ("edge"|"packet"), edge_index, tier, verdict, confidence, valid, audit_flag`), `precision_by_tier.csv` (`tier, n_confirmed, n_wrong, n_uncertain, precision, wilson_lo, wilson_hi`), `audit_slice.csv`, `summary.md`; returns stats dict `{"n_verdicts": ..., "n_invalid": ..., "n_missing": ...}`.
- Audit slice: deterministic ~10% -- for each (packet_type, verdict) stratum pick every packet where `int(md5(packet_id).hexdigest()[:8], 16) % 10 == 0`; guarantee at least 1 per non-empty stratum (add the md5-lowest packet if the modulus picked none).
- Invalid or missing verdicts are counted and listed in summary.md, never silently dropped.

- [ ] **Step 1: Write failing tests**

Create `tests/test_match_gold_score.py`:

```python
import json
import pandas as pd
import pytest

from scripts.match_gold import score_gold as sg


def _mk_batch(tmp_path, verdict_docs):
    (tmp_path / "packets_meta").mkdir(parents=True)
    (tmp_path / "verdicts").mkdir()
    wl_rows = []
    for pid, meta, verdict in verdict_docs:
        (tmp_path / "packets_meta" / f"{pid}.json").write_text(
            json.dumps(meta), encoding="utf-8")
        if verdict is not None:
            (tmp_path / "verdicts" / f"{pid}.json").write_text(
                json.dumps(verdict), encoding="utf-8-sig")  # BOM like real workers
        wl_rows.append({"packet_id": pid, "packet_type": meta["packet_type"],
                        "stratum": meta["stratum"], "cik": "0000000001",
                        "n_rows": 2, "n_edges": len(meta.get("edges", [])),
                        "prompt_path": "", "packet_path": "",
                        "verdict_path": f"verdicts/{pid}.json",
                        "has_cached_filing": True})
    pd.DataFrame(wl_rows).to_csv(tmp_path / "worklist.csv", index=False)


def test_wilson_interval_bounds():
    lo, hi = sg.wilson_interval(9, 10)
    assert 0.55 < lo < 0.9 < hi <= 1.0
    assert sg.wilson_interval(0, 0) == (0.0, 1.0)


def test_score_batch_per_tier_precision(tmp_path):
    meta1 = {"packet_id": "MGP-1", "packet_type": "chain", "stratum": "tier_random",
             "edges": [{"edge_index": 0, "match_method": "B2_exact_name"}]}
    v1 = {"packet_id": "MGP-1", "packet_type": "chain", "verdict": "CONFIRMED",
          "confidence": 0.95, "rationale": "same loan",
          "edge_verdicts": [{"edge_index": 0, "verdict": "CONFIRMED", "evidence": []}],
          "proposed_links": [], "escalate": False}
    meta2 = {"packet_id": "MGP-2", "packet_type": "chain", "stratum": "tier_random",
             "edges": [{"edge_index": 0, "match_method": "B2_exact_name"}]}
    v2 = {"packet_id": "MGP-2", "packet_type": "chain", "verdict": "WRONG_MERGE",
          "confidence": 0.8, "rationale": "different tranches",
          "edge_verdicts": [{"edge_index": 0, "verdict": "WRONG",
                             "evidence": [{"quoted_text": "Second Lien"}]}],
          "proposed_links": [], "escalate": False}
    _mk_batch(tmp_path, [("MGP-1", meta1, v1), ("MGP-2", meta2, v2)])
    stats = sg.score_batch(tmp_path)
    assert stats["n_verdicts"] == 2 and stats["n_invalid"] == 0
    prec = pd.read_csv(tmp_path / "precision_by_tier.csv")
    b2 = prec[prec["tier"] == "B2_exact_name"].iloc[0]
    assert b2["n_confirmed"] == 1 and b2["n_wrong"] == 1
    assert b2["precision"] == pytest.approx(0.5)


def test_score_batch_flags_invalid_and_missing(tmp_path):
    meta = {"packet_id": "MGP-3", "packet_type": "chain", "stratum": "tier_random",
            "edges": [{"edge_index": 0, "match_method": "D_fuzzy"}]}
    bad = {"packet_id": "MGP-3", "packet_type": "chain", "verdict": "WRONG_MERGE",
           "confidence": 0.9, "rationale": "x",
           "edge_verdicts": [{"edge_index": 0, "verdict": "WRONG", "evidence": []}],
           "proposed_links": [], "escalate": False}   # WRONG without citation
    meta4 = {"packet_id": "MGP-4", "packet_type": "chain", "stratum": "tier_random",
             "edges": [{"edge_index": 0, "match_method": "D_fuzzy"}]}
    _mk_batch(tmp_path, [("MGP-3", meta, bad), ("MGP-4", meta4, None)])
    stats = sg.score_batch(tmp_path)
    assert stats["n_invalid"] == 1 and stats["n_missing"] == 1
    gold = pd.read_csv(tmp_path / "gold_set.csv")
    assert not gold[gold["packet_id"] == "MGP-3"]["valid"].iloc[0]


def test_audit_slice_nonempty_per_stratum(tmp_path):
    docs = []
    for i in range(20):
        pid = f"MGP-a{i}"
        meta = {"packet_id": pid, "packet_type": "chain", "stratum": "tier_random",
                "edges": [{"edge_index": 0, "match_method": "A_within_filing"}]}
        v = {"packet_id": pid, "packet_type": "chain", "verdict": "CONFIRMED",
             "confidence": 0.9, "rationale": "ok",
             "edge_verdicts": [{"edge_index": 0, "verdict": "CONFIRMED",
                                "evidence": []}],
             "proposed_links": [], "escalate": False}
        docs.append((pid, meta, v))
    _mk_batch(tmp_path, docs)
    sg.score_batch(tmp_path)
    audit = pd.read_csv(tmp_path / "audit_slice.csv")
    assert len(audit) >= 1
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_match_gold_score.py -v`
Expected: FAIL with ModuleNotFoundError.

- [ ] **Step 3: Implement `score_gold.py`**

```python
"""Score match-gold verdicts into gold_set.csv + per-tier precision.

Reads worker verdict JSONs (utf-8-sig tolerant), validates against
pipeline.match_verdict_leaf, joins edge verdicts to blinded tiers from
packets_meta sidecars. Invalid/missing verdicts are surfaced, never dropped.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from pipeline.match_verdict_leaf import validate_match_verdict  # noqa: E402


def wilson_interval(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def _audit_pick(packet_id: str) -> bool:
    return int(hashlib.md5(packet_id.encode()).hexdigest()[:8], 16) % 10 == 0


def score_batch(batch_dir: Path) -> dict:
    batch_dir = Path(batch_dir)
    worklist = pd.read_csv(batch_dir / "worklist.csv")
    gold_rows, invalid, missing = [], [], []

    for wl in worklist.itertuples(index=False):   # <=600 rows, loop is fine
        pid = wl.packet_id
        meta = json.loads((batch_dir / "packets_meta" / f"{pid}.json")
                          .read_text(encoding="utf-8"))
        vpath = batch_dir / "verdicts" / f"{pid}.json"
        if not vpath.exists():
            missing.append(pid)
            continue
        doc = json.loads(vpath.read_text(encoding="utf-8-sig"))
        expected = [e["edge_index"] for e in meta.get("edges", [])]
        errs = validate_match_verdict(doc, expected_edges=expected)
        valid = not errs
        if errs:
            invalid.append({"packet_id": pid, "errors": errs})
        tier_of = {e["edge_index"]: e.get("match_method", "")
                   for e in meta.get("edges", [])}
        base = {"packet_id": pid, "packet_type": meta["packet_type"],
                "stratum": meta["stratum"], "valid": valid,
                "audit_flag": _audit_pick(pid)}
        for ev in (doc.get("edge_verdicts") or []):
            gold_rows.append({**base, "unit": "edge",
                              "edge_index": ev.get("edge_index"),
                              "tier": tier_of.get(ev.get("edge_index"), ""),
                              "verdict": ev.get("verdict"),
                              "confidence": doc.get("confidence")})
        gold_rows.append({**base, "unit": "packet", "edge_index": None,
                          "tier": "", "verdict": doc.get("verdict"),
                          "confidence": doc.get("confidence")})

    gold = pd.DataFrame(gold_rows).sort_values(
        ["packet_id", "unit", "edge_index"], na_position="last")
    gold.to_csv(batch_dir / "gold_set.csv", index=False)

    edges = gold[(gold["unit"] == "edge") & gold["valid"]]
    prec_rows = []
    for tier, grp in edges.groupby("tier"):
        k = int((grp["verdict"] == "CONFIRMED").sum())
        w = int((grp["verdict"] == "WRONG").sum())
        u = int((grp["verdict"] == "UNCERTAIN").sum())
        n = k + w
        p = k / n if n else 0.0
        lo, hi = wilson_interval(k, n)
        prec_rows.append({"tier": tier, "n_confirmed": k, "n_wrong": w,
                          "n_uncertain": u, "precision": p,
                          "wilson_lo": lo, "wilson_hi": hi})
    pd.DataFrame(prec_rows).sort_values("tier").to_csv(
        batch_dir / "precision_by_tier.csv", index=False)

    audit = gold[gold["audit_flag"] & (gold["unit"] == "packet")]
    for (ptype, verdict), grp in gold[gold["unit"] == "packet"].groupby(
            ["packet_type", "verdict"]):
        if not grp["audit_flag"].any():
            fallback = grp.assign(_o=grp["packet_id"].map(
                lambda x: hashlib.md5(x.encode()).hexdigest()))
            fallback = fallback.sort_values("_o").head(1).drop(columns="_o")
            audit = pd.concat([audit, fallback])
    audit.sort_values("packet_id").to_csv(batch_dir / "audit_slice.csv", index=False)

    stats = {"n_verdicts": int(worklist.shape[0] - len(missing)),
             "n_invalid": len(invalid), "n_missing": len(missing)}
    lines = ["# Match-gold scoring summary", "",
             f"- verdicts: {stats['n_verdicts']}",
             f"- invalid: {stats['n_invalid']}",
             f"- missing: {stats['n_missing']}", ""]
    for item in invalid:
        lines.append(f"- INVALID {item['packet_id']}: {'; '.join(item['errors'])}")
    for pid in missing:
        lines.append(f"- MISSING {pid}")
    (batch_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    return stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch-dir", required=True)
    args = ap.parse_args()
    print(score_batch(Path(args.batch_dir)))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests, verify pass**

Run: `python -m pytest tests/test_match_gold_score.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/match_gold/score_gold.py tests/test_match_gold_score.py
git commit -m "feat: match-gold scorer with per-tier Wilson precision

- gold_set.csv per edge/packet unit; invalid+missing surfaced in summary.md
- precision_by_tier.csv with Wilson 95pct intervals
- deterministic ~10pct audit slice, min 1 per verdict stratum"
```

---

### Task 9: Operator runbook

**Files:**
- Create: `docs/reference/match_gold_dispatch.md`

No tests (docs). Content must include, in this order:

1. **Prereqs**: fresh `python scripts/rebuild_outputs.py --match-quality`; check no other fleet running (AGENTS.md concurrency rule); admin PowerShell for dispatch (per `docs/reference/codex_worker_dispatch.md`).
2. **Build batch**: `python scripts/match_gold/build_packets.py --batch-id mg1` -> reports packet counts and `has_cached_filing` misses. Packets with missing cached HTML are NOT dispatched; list them in the run notes.
3. **Dispatch**: follow `docs/reference/codex_worker_dispatch.md` fleet pattern; one worker per packet, prompt file = `prompts/<packet_id>.md`; workers only need repo read access + write access to `verdicts/`. Reference the four sandbox traps doc section.
4. **Score**: `python scripts/match_gold/score_gold.py --batch-dir data/output/match_quality/gold/mg1`; re-dispatch or hand-review INVALID/MISSING packets listed in `summary.md`.
5. **Human audit**: open `audit_slice.csv`, review each flagged packet's verdict against the filings, record agree/disagree in a new column `owner_verdict`; disagreement rate goes in the investigation write-up.
6. **Record results**: append investigation to `docs/investigations/` per its INDEX topic conventions, then `python scripts/split_investigations.py --reindex`; append `docs/agent_changelog.md` entry (date, packet counts, per-tier precision, caveats).
7. **Caveats to state in every report**: precision estimates are per-tier on the cohort only; UNCERTAIN edges excluded from the precision denominator; gold set is versioned by batch-id and later agent runs must not be scored on packets they authored.

- [ ] **Step 1: Write the runbook with the content above**
- [ ] **Step 2: Commit**

```bash
git add docs/reference/match_gold_dispatch.md
git commit -m "docs: match-gold dispatch runbook

- build/dispatch/score/audit sequence with fleet conventions
- invalid-verdict handling and reporting caveats"
```

---

### Task 10: Real-data run + verification + handoff

**Files:**
- Modify (append): `docs/agent_changelog.md`

- [ ] **Step 1: Full targeted test pass**

Run: `python -m pytest tests/test_match_quality.py tests/test_match_verdict_leaf.py tests/test_match_gold_packets.py tests/test_match_gold_score.py -v`
Expected: all PASS.

- [ ] **Step 2: Backstop semantic diff (conftest guard sanity)**

Run: `python scripts/diff_outputs.py --semantic`
Expected: no unexplained artifact drift (the new `match_quality_metrics.csv` is a new file, not in baseline -- note it, do not add to baseline yet).

- [ ] **Step 3: Rebuild metrics on real data**

Run: `python scripts/rebuild_outputs.py --match-quality`
Record: total rows; ALL-scope chain_continuity_rate; singleton class counts; drift_break_candidate_pairs; entity_coverage_rate. These are the Phase 0 baseline numbers.

- [ ] **Step 4: Build a real packet batch (no dispatch)**

Run: `python scripts/match_gold/build_packets.py --batch-id mg1`
Verify: total packets in the 500-650 range (tune stratum caps via `--max-chains`/`--max-entities` if far off); spot-open 2 packets + prompts, confirm blinding (no tier names); count `has_cached_filing=False` rows and note them. Do NOT dispatch the fleet -- that is an operator action gated by the runbook (check for concurrent fleets first, per AGENTS.md).

- [ ] **Step 5: Full pytest suite (pre-handoff, check for concurrent runs first)**

Run: `python -m pytest --durations=50 --durations-min=0.5 -q` (only if no other agent is mid-suite; otherwise report skipped and why)
Expected: no regressions vs current green count.

- [ ] **Step 6: Changelog + commit**

Append to `docs/agent_changelog.md`: date, "Match-quality Phase 0 shipped", new modules/artifacts, baseline metric values from Step 3, packet counts from Step 4, what was NOT run (fleet dispatch).

```bash
git add docs/agent_changelog.md
git commit -m "docs: changelog for match-quality phase 0

- metrics + gold harness shipped, baseline numbers recorded
- mg1 packet batch built, fleet dispatch pending operator window"
```

---

## Out of scope for this plan

- Fleet dispatch itself (operator-gated; runbook Task 9 covers it).
- The post-adjudication investigation write-up (depends on verdict data).
- Anything in Phase 1/2 of the spec (registry promotion, borrower_resolution.py, Tier E, correction fix-classes).
