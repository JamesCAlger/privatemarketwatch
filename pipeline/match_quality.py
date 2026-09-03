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
        ),
        candidates AS (
            SELECT d.cik,
                   d.row_id AS dropped_row_id, d.issuer_name AS dropped_issuer,
                   d.report_date AS dropped_date,
                   s.row_id AS start_row_id, s.issuer_name AS start_issuer,
                   s.report_date AS start_date,
                   s.fv / d.fv AS fv_ratio,
                   ROW_NUMBER() OVER (PARTITION BY d.row_id
                                      ORDER BY ABS(s.fv / d.fv - 1.0), s.row_id) AS rn
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
        )
        SELECT cik, dropped_row_id, dropped_issuer, dropped_date,
               start_row_id, start_issuer, start_date, fv_ratio
        FROM candidates
        WHERE rn = 1
        ORDER BY cik, dropped_row_id, start_row_id
    """).df()


def drift_break_metric(holdings_df: pd.DataFrame) -> pd.DataFrame:
    cands = drift_break_candidates(holdings_df)
    n_pairs = len(cands)
    total = pd.DataFrame([{
        "scope": "ALL", "scope_type": "ALL",
        "numerator": n_pairs, "denominator": 1,
    }])
    out = _finish(total, "drift_break_candidate_pairs")
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


def build_match_quality_metrics(
    holdings_path=None, edges_path=None, output_path=None, cohort_ciks=None,
) -> pd.DataFrame:
    """Load unified holdings + position edges, filter to cohort, compute all metrics,
    write to output_path (default MATCH_QUALITY_METRICS_FILE), and return the frame."""
    from pipeline.config import (
        MATCH_QUALITY_METRICS_FILE, POSITION_ID_EDGES_FILE, UNIFIED_HOLDINGS_FILE,
    )
    import pathlib
    holdings_path = holdings_path or UNIFIED_HOLDINGS_FILE
    edges_path = edges_path or POSITION_ID_EDGES_FILE
    output_path = output_path or MATCH_QUALITY_METRICS_FILE
    output_path = pathlib.Path(output_path)

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

    if "row_id" not in holdings.columns:
        raise ValueError(
            "holdings artifact lacks row_id; run "
            "`python scripts/rebuild_outputs.py --unified` then `--returns` first"
        )

    out = compute_all(holdings, edges)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(output_path, index=False)
    logger.info("Match-quality metrics: %d rows -> %s", len(out), output_path)
    return out
