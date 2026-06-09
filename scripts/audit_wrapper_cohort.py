"""Deep per-CIK audit for the v1 39-wrapper BDC cohort.

Goes beyond the binary pass/fail quality gate to measure wrapper disposition
quality, source reconciliation, global rule impacts, provenance chain
completeness, and data quality metrics across 10 audit dimensions.

Outputs:
  - wrapper_v1_audit_detail.csv   (one row per CIK, wide format)
  - wrapper_v1_audit_quarterly.csv (one row per CIK-quarter)
  - wrapper_v1_audit_report.md    (human-readable markdown)
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import duckdb
import pandas as pd

from pipeline.config import OUTPUT_DIR
from scripts.wrapper_v1_quality_gate import (
    CohortEntry,
    _norm_cik,
    _read_csv,
    _to_float,
    load_manifest,
)


def _safe_int(value: Any) -> int:
    """Convert to int, treating NaN/None/non-numeric as 0."""
    try:
        v = float(value)
        if v != v:  # NaN check
            return 0
        return int(v)
    except (TypeError, ValueError):
        return 0


def _safe_float(value: Any) -> float:
    """Convert to float, treating NaN/None/non-numeric as 0.0."""
    try:
        v = float(value)
        if v != v:  # NaN check
            return 0.0
        return v
    except (TypeError, ValueError):
        return 0.0

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_MANIFEST = (
    PROJECT_ROOT
    / "data"
    / "overrides"
    / "wrapper_cohorts"
    / "v1_39_wrapper_manifest.json"
)
WRAPPER_DIR = PROJECT_ROOT / "data" / "overrides" / "bdc_xbrl_wrappers"
HOLDINGS_FILE = OUTPUT_DIR / "private_markets_holdings.csv"
FUND_FINANCIALS_FILE = OUTPUT_DIR / "fund_financials.csv"
SOURCE_RECON_METRICS_FILE = OUTPUT_DIR / "source_reconciliation_metrics.csv"
SOURCE_RECON_RESIDUAL_FILE = (
    OUTPUT_DIR / "source_reconciliation_residual_classification.csv"
)
ROW_CORRECTIONS_FILE = (
    PROJECT_ROOT / "data" / "overrides" / "row_corrections.csv"
)
FUND_STRATEGY_CORRECTIONS_FILE = (
    OUTPUT_DIR / "fund_strategy_correction_candidates.csv"
)
PROVENANCE_DIR = OUTPUT_DIR / "provenance"
WRAPPER_PROVENANCE_FILE = PROVENANCE_DIR / "holdings_wrapper_provenance.csv"
POSITION_PROVENANCE_FILE = PROVENANCE_DIR / "position_provenance_index.csv"
QUALITY_GATE_FILE = OUTPUT_DIR / "wrapper_v1_quality_gate.csv"

DEFAULT_DETAIL_OUT = OUTPUT_DIR / "wrapper_v1_audit_detail.csv"
DEFAULT_QUARTERLY_OUT = OUTPUT_DIR / "wrapper_v1_audit_quarterly.csv"
DEFAULT_REPORT_OUT = OUTPUT_DIR / "wrapper_v1_audit_report.md"


def _safe(path: Path) -> str:
    """Return a DuckDB-safe path string (forward slashes, escaped quotes)."""
    return str(path).replace("\\", "/").replace("'", "''")


# ---------------------------------------------------------------------------
# DuckDB setup
# ---------------------------------------------------------------------------
def _setup_duckdb(
    cohort_ciks: list[str],
    holdings_path: Path = HOLDINGS_FILE,
    fund_financials_path: Path = FUND_FINANCIALS_FILE,
    source_recon_metrics_path: Path = SOURCE_RECON_METRICS_FILE,
    source_recon_residual_path: Path = SOURCE_RECON_RESIDUAL_FILE,
) -> duckdb.DuckDBPyConnection:
    """Create an in-memory DuckDB connection with cohort-filtered tables."""
    con = duckdb.connect()

    # Register cohort CIK list
    cik_df = pd.DataFrame({"cik": cohort_ciks})
    con.register("cohort_ciks_view", cik_df)
    con.execute("CREATE TABLE cohort_ciks AS SELECT * FROM cohort_ciks_view")

    # Holdings - filtered to cohort at read time
    if holdings_path.exists():
        con.execute(f"""
            CREATE TABLE holdings AS
            SELECT * FROM read_csv_auto('{_safe(holdings_path)}',
                          header=true, all_varchar=true)
            WHERE LPAD(CAST(cik AS VARCHAR), 10, '0') IN (SELECT cik FROM cohort_ciks)
        """)
    else:
        con.execute("CREATE TABLE holdings (cik VARCHAR)")

    # Fund financials - filtered to cohort
    if fund_financials_path.exists():
        con.execute(f"""
            CREATE TABLE fund_financials AS
            SELECT * FROM read_csv_auto('{_safe(fund_financials_path)}',
                          header=true, all_varchar=true)
            WHERE LPAD(CAST(cik AS VARCHAR), 10, '0') IN (SELECT cik FROM cohort_ciks)
        """)
    else:
        con.execute("CREATE TABLE fund_financials (cik VARCHAR)")

    # Source reconciliation metrics - filtered to cohort
    if source_recon_metrics_path.exists():
        con.execute(f"""
            CREATE TABLE source_recon_metrics AS
            SELECT * FROM read_csv_auto('{_safe(source_recon_metrics_path)}',
                          header=true, all_varchar=true)
            WHERE LPAD(CAST(cik AS VARCHAR), 10, '0') IN (SELECT cik FROM cohort_ciks)
        """)
    else:
        con.execute("CREATE TABLE source_recon_metrics (cik VARCHAR)")

    # Source reconciliation residual - filtered to cohort
    if source_recon_residual_path.exists():
        try:
            con.execute(f"""
                CREATE TABLE source_recon_residual AS
                SELECT * FROM read_csv_auto('{_safe(source_recon_residual_path)}',
                              header=true, all_varchar=true)
                WHERE LPAD(CAST(cik AS VARCHAR), 10, '0') IN (SELECT cik FROM cohort_ciks)
            """)
        except duckdb.BinderException:
            # Empty CSV with no cik column
            con.execute("CREATE TABLE source_recon_residual (cik VARCHAR)")
    else:
        con.execute("CREATE TABLE source_recon_residual (cik VARCHAR)")

    return con


# ---------------------------------------------------------------------------
# Audit dimension functions
# ---------------------------------------------------------------------------

def audit_source_reconciliation(
    con: duckdb.DuckDBPyConnection,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Source reconciliation summary per CIK and per CIK-quarter.

    Uses calibrated_reconciled_source_row_rate (which accounts for documented
    exclusions like comparative periods, aggregates, money-market) instead of
    the raw reconciled_source_row_rate.

    Blocking issues come from the residual classification table (only rows
    with blocking_issue=True), not from the metrics-level blocking_issue_count
    which includes rows later cleared by the residual classifier.

    Returns (per_cik, per_quarter).
    """
    metrics_cols = con.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name='source_recon_metrics'"
    ).fetchdf()["column_name"].tolist()

    residual_cols = con.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name='source_recon_residual'"
    ).fetchdf()["column_name"].tolist()

    if "cik" not in metrics_cols or "reconciled_source_row_rate" not in metrics_cols:
        empty_cik = pd.DataFrame(columns=[
            "cik", "recon_quarter_count", "avg_reconciled_rate",
            "avg_raw_reconciled_rate",
            "total_blocking_issues", "total_blocking_issues_metrics",
            "total_diagnostic_issues",
        ])
        empty_q = pd.DataFrame(columns=[
            "cik", "report_date", "calibrated_reconciled_rate",
            "raw_reconciled_rate",
            "residual_blocking_issues", "metrics_blocking_issues",
            "diagnostic_issue_count",
        ])
        return empty_cik, empty_q

    # Prefer calibrated rate; fall back to raw if column missing
    rate_col = (
        "calibrated_reconciled_source_row_rate"
        if "calibrated_reconciled_source_row_rate" in metrics_cols
        else "reconciled_source_row_rate"
    )

    per_quarter = con.execute(f"""
        SELECT
            LPAD(CAST(cik AS VARCHAR), 10, '0') AS cik,
            report_date,
            TRY_CAST({rate_col} AS DOUBLE) AS calibrated_reconciled_rate,
            TRY_CAST(reconciled_source_row_rate AS DOUBLE) AS raw_reconciled_rate,
            TRY_CAST(blocking_issue_count AS DOUBLE) AS metrics_blocking_issues,
            TRY_CAST(diagnostic_issue_count AS DOUBLE) AS diagnostic_issue_count
        FROM source_recon_metrics
        ORDER BY cik, report_date
    """).fetchdf()

    # Build residual-based blocking counts per CIK from the residual table
    has_residual_blocking = (
        "blocking_issue" in residual_cols
        and "issue_count" in residual_cols
        and "cik" in residual_cols
    )

    if has_residual_blocking:
        residual_blocking = con.execute("""
            SELECT
                LPAD(CAST(cik AS VARCHAR), 10, '0') AS cik,
                SUM(TRY_CAST(issue_count AS DOUBLE)) AS total_blocking_issues
            FROM source_recon_residual
            WHERE LOWER(CAST(blocking_issue AS VARCHAR)) IN ('true', '1', 'yes')
            GROUP BY LPAD(CAST(cik AS VARCHAR), 10, '0')
        """).fetchdf()

        # Per-quarter residual blocking
        residual_blocking_q = con.execute("""
            SELECT
                LPAD(CAST(cik AS VARCHAR), 10, '0') AS cik,
                report_date,
                SUM(TRY_CAST(issue_count AS DOUBLE)) AS residual_blocking_issues
            FROM source_recon_residual
            WHERE LOWER(CAST(blocking_issue AS VARCHAR)) IN ('true', '1', 'yes')
            GROUP BY LPAD(CAST(cik AS VARCHAR), 10, '0'), report_date
        """).fetchdf()
    else:
        residual_blocking = pd.DataFrame(columns=["cik", "total_blocking_issues"])
        residual_blocking_q = pd.DataFrame(
            columns=["cik", "report_date", "residual_blocking_issues"]
        )

    # Merge residual blocking into per-quarter
    if not residual_blocking_q.empty:
        per_quarter = per_quarter.merge(
            residual_blocking_q, on=["cik", "report_date"], how="left",
        )
    else:
        per_quarter["residual_blocking_issues"] = 0.0
    per_quarter["residual_blocking_issues"] = (
        per_quarter["residual_blocking_issues"].fillna(0)
    )

    # Build per-CIK summary using calibrated rate and residual blocking
    per_cik = con.execute(f"""
        SELECT
            LPAD(CAST(cik AS VARCHAR), 10, '0') AS cik,
            COUNT(*) AS recon_quarter_count,
            AVG(TRY_CAST({rate_col} AS DOUBLE)) AS avg_reconciled_rate,
            AVG(TRY_CAST(reconciled_source_row_rate AS DOUBLE)) AS avg_raw_reconciled_rate,
            SUM(TRY_CAST(blocking_issue_count AS DOUBLE)) AS total_blocking_issues_metrics,
            SUM(TRY_CAST(diagnostic_issue_count AS DOUBLE)) AS total_diagnostic_issues
        FROM source_recon_metrics
        GROUP BY LPAD(CAST(cik AS VARCHAR), 10, '0')
    """).fetchdf()

    # Replace blocking count with residual-based count
    if not residual_blocking.empty:
        per_cik = per_cik.merge(residual_blocking, on="cik", how="left")
    else:
        per_cik["total_blocking_issues"] = 0.0
    per_cik["total_blocking_issues"] = (
        per_cik["total_blocking_issues"].fillna(0)
    )

    return per_cik, per_quarter


def audit_fv_coverage(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """FV sum vs total_assets per CIK for the latest quarter."""
    holdings_cols = con.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name='holdings'"
    ).fetchdf()["column_name"].tolist()
    fin_cols = con.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name='fund_financials'"
    ).fetchdf()["column_name"].tolist()

    if "fair_value" not in holdings_cols or "total_assets" not in fin_cols:
        return pd.DataFrame(columns=[
            "cik", "latest_holdings_quarter", "holdings_fv_sum",
            "total_assets", "fv_coverage_ratio",
        ])

    return con.execute("""
        WITH latest_h AS (
            SELECT
                LPAD(CAST(cik AS VARCHAR), 10, '0') AS cik,
                MAX(report_date) AS latest_quarter
            FROM holdings
            WHERE report_date IS NOT NULL AND report_date != ''
            GROUP BY LPAD(CAST(cik AS VARCHAR), 10, '0')
        ),
        h_sum AS (
            SELECT
                LPAD(CAST(h.cik AS VARCHAR), 10, '0') AS cik,
                lh.latest_quarter,
                SUM(TRY_CAST(h.fair_value AS DOUBLE)) AS holdings_fv_sum
            FROM holdings h
            JOIN latest_h lh
              ON LPAD(CAST(h.cik AS VARCHAR), 10, '0') = lh.cik
              AND h.report_date = lh.latest_quarter
            GROUP BY LPAD(CAST(h.cik AS VARCHAR), 10, '0'), lh.latest_quarter
        ),
        latest_f AS (
            SELECT
                LPAD(CAST(cik AS VARCHAR), 10, '0') AS cik,
                MAX(report_date) AS latest_quarter
            FROM fund_financials
            WHERE total_assets IS NOT NULL AND total_assets != ''
              AND TRY_CAST(total_assets AS DOUBLE) > 0
            GROUP BY LPAD(CAST(cik AS VARCHAR), 10, '0')
        ),
        f_ta AS (
            SELECT
                LPAD(CAST(f.cik AS VARCHAR), 10, '0') AS cik,
                TRY_CAST(f.total_assets AS DOUBLE) AS total_assets
            FROM fund_financials f
            JOIN latest_f lf
              ON LPAD(CAST(f.cik AS VARCHAR), 10, '0') = lf.cik
              AND f.report_date = lf.latest_quarter
        )
        SELECT
            hs.cik,
            hs.latest_quarter AS latest_holdings_quarter,
            hs.holdings_fv_sum,
            ft.total_assets,
            CASE
                WHEN ft.total_assets IS NOT NULL AND ft.total_assets > 0
                THEN hs.holdings_fv_sum / ft.total_assets
                ELSE NULL
            END AS fv_coverage_ratio
        FROM h_sum hs
        LEFT JOIN f_ta ft ON hs.cik = ft.cik
    """).fetchdf()


def audit_position_counts(
    con: duckdb.DuckDBPyConnection,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Position count per CIK-quarter + volatility flags.

    Returns (per_cik summary, per_quarter detail).
    """
    holdings_cols = con.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name='holdings'"
    ).fetchdf()["column_name"].tolist()

    if "cik" not in holdings_cols or "report_date" not in holdings_cols:
        empty_cik = pd.DataFrame(columns=[
            "cik", "total_quarters", "avg_position_count",
            "volatile_quarters",
        ])
        empty_q = pd.DataFrame(columns=[
            "cik", "report_date", "position_count", "qoq_ratio",
            "volatile",
        ])
        return empty_cik, empty_q

    per_quarter = con.execute("""
        WITH counts AS (
            SELECT
                LPAD(CAST(cik AS VARCHAR), 10, '0') AS cik,
                report_date,
                COUNT(*) AS position_count
            FROM holdings
            WHERE report_date IS NOT NULL AND report_date != ''
            GROUP BY LPAD(CAST(cik AS VARCHAR), 10, '0'), report_date
        ),
        with_lag AS (
            SELECT
                cik, report_date, position_count,
                LAG(position_count) OVER (PARTITION BY cik ORDER BY report_date) AS prev_count
            FROM counts
        )
        SELECT
            cik, report_date, position_count,
            CASE
                WHEN prev_count IS NOT NULL AND prev_count > 0
                THEN CAST(position_count AS DOUBLE) / prev_count
                ELSE NULL
            END AS qoq_ratio,
            CASE
                WHEN prev_count IS NOT NULL AND prev_count > 0
                     AND (CAST(position_count AS DOUBLE) / prev_count > 2.5
                          OR CAST(position_count AS DOUBLE) / prev_count < 0.4)
                THEN true
                ELSE false
            END AS volatile
        FROM with_lag
        ORDER BY cik, report_date
    """).fetchdf()

    if per_quarter.empty:
        per_cik = pd.DataFrame(columns=[
            "cik", "total_quarters", "avg_position_count",
            "volatile_quarters",
        ])
    else:
        per_cik = per_quarter.groupby("cik", as_index=False).agg(
            total_quarters=("report_date", "count"),
            avg_position_count=("position_count", "mean"),
            volatile_quarters=("volatile", "sum"),
        )

    return per_cik, per_quarter


def audit_classification_dist(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Index classification breakdown per CIK."""
    holdings_cols = con.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name='holdings'"
    ).fetchdf()["column_name"].tolist()

    if "index_classification" not in holdings_cols:
        return pd.DataFrame(columns=[
            "cik", "total_positions", "unclassified_count",
            "unclassified_pct", "classification_breakdown",
        ])

    raw = con.execute("""
        SELECT
            LPAD(CAST(cik AS VARCHAR), 10, '0') AS cik,
            COALESCE(NULLIF(index_classification, ''), 'UNCLASSIFIED') AS classification,
            COUNT(*) AS cnt
        FROM holdings
        GROUP BY LPAD(CAST(cik AS VARCHAR), 10, '0'), classification
        ORDER BY cik, cnt DESC
    """).fetchdf()

    if raw.empty:
        return pd.DataFrame(columns=[
            "cik", "total_positions", "unclassified_count",
            "unclassified_pct", "classification_breakdown",
        ])

    results = []
    for cik, grp in raw.groupby("cik"):
        total = int(grp["cnt"].sum())
        unc = int(grp.loc[grp["classification"] == "UNCLASSIFIED", "cnt"].sum())
        breakdown = "; ".join(
            f"{r['classification']}={r['cnt']}"
            for _, r in grp.iterrows()
        )
        results.append({
            "cik": cik,
            "total_positions": total,
            "unclassified_count": unc,
            "unclassified_pct": unc / total if total > 0 else 0.0,
            "classification_breakdown": breakdown,
        })
    return pd.DataFrame(results)


def audit_wrapper_vs_global(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Detect wrapper_family vs asset_class disagreements.

    Uses holdings asset_class + provenance wrapper_family if available.
    Falls back to a simpler proxy when provenance files are missing.
    """
    holdings_cols = con.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name='holdings'"
    ).fetchdf()["column_name"].tolist()

    if "asset_class" not in holdings_cols:
        return pd.DataFrame(columns=[
            "cik", "total_classified", "disagreement_count",
            "disagreement_pct",
        ])

    # Check for provenance table
    tables = con.execute(
        "SELECT table_name FROM information_schema.tables"
    ).fetchdf()["table_name"].tolist()

    if "wrapper_provenance" in tables:
        # Join provenance wrapper_family against holdings asset_class
        return con.execute("""
            WITH joined AS (
                SELECT
                    LPAD(CAST(h.cik AS VARCHAR), 10, '0') AS cik,
                    h.asset_class,
                    wp.wrapper_family
                FROM holdings h
                JOIN wrapper_provenance wp
                  ON LPAD(CAST(h.cik AS VARCHAR), 10, '0')
                     = LPAD(CAST(wp.cik AS VARCHAR), 10, '0')
                  AND h.report_date = wp.report_date
                  AND h.bdc_investment_identifier = wp.bdc_investment_identifier
                WHERE h.asset_class IS NOT NULL AND h.asset_class != ''
                  AND wp.wrapper_family IS NOT NULL AND wp.wrapper_family != ''
            )
            SELECT
                cik,
                COUNT(*) AS total_classified,
                SUM(CASE
                    WHEN UPPER(wrapper_family) LIKE '%DEBT%'
                         AND UPPER(asset_class) NOT LIKE '%CREDIT%'
                         AND UPPER(asset_class) NOT LIKE '%DEBT%'
                    THEN 1
                    WHEN UPPER(wrapper_family) LIKE '%EQUITY%'
                         AND UPPER(asset_class) NOT LIKE '%EQUITY%'
                    THEN 1
                    ELSE 0
                END) AS disagreement_count,
                CASE WHEN COUNT(*) > 0
                    THEN SUM(CASE
                        WHEN UPPER(wrapper_family) LIKE '%DEBT%'
                             AND UPPER(asset_class) NOT LIKE '%CREDIT%'
                             AND UPPER(asset_class) NOT LIKE '%DEBT%'
                        THEN 1
                        WHEN UPPER(wrapper_family) LIKE '%EQUITY%'
                             AND UPPER(asset_class) NOT LIKE '%EQUITY%'
                        THEN 1
                        ELSE 0
                    END) * 1.0 / COUNT(*)
                    ELSE 0
                END AS disagreement_pct
            FROM joined
            GROUP BY cik
        """).fetchdf()

    # Fallback: no provenance. Use asset_category vs asset_class as proxy.
    if "asset_category" not in holdings_cols:
        return pd.DataFrame(columns=[
            "cik", "total_classified", "disagreement_count",
            "disagreement_pct",
        ])

    return con.execute("""
        WITH classified AS (
            SELECT
                LPAD(CAST(cik AS VARCHAR), 10, '0') AS cik,
                asset_category,
                asset_class
            FROM holdings
            WHERE asset_class IS NOT NULL AND asset_class != ''
              AND asset_category IS NOT NULL AND asset_category != ''
        )
        SELECT
            cik,
            COUNT(*) AS total_classified,
            SUM(CASE
                WHEN UPPER(asset_category) = 'LOAN'
                     AND UPPER(asset_class) NOT LIKE '%CREDIT%'
                     AND UPPER(asset_class) NOT LIKE '%DEBT%'
                THEN 1
                WHEN UPPER(asset_category) IN ('EQUITY', 'PREFERRED')
                     AND UPPER(asset_class) NOT LIKE '%EQUITY%'
                THEN 1
                ELSE 0
            END) AS disagreement_count,
            CASE WHEN COUNT(*) > 0
                THEN SUM(CASE
                    WHEN UPPER(asset_category) = 'LOAN'
                         AND UPPER(asset_class) NOT LIKE '%CREDIT%'
                         AND UPPER(asset_class) NOT LIKE '%DEBT%'
                    THEN 1
                    WHEN UPPER(asset_category) IN ('EQUITY', 'PREFERRED')
                         AND UPPER(asset_class) NOT LIKE '%EQUITY%'
                    THEN 1
                    ELSE 0
                END) * 1.0 / COUNT(*)
                ELSE 0
            END AS disagreement_pct
        FROM classified
        GROUP BY cik
    """).fetchdf()


def audit_corrections(
    cohort_ciks: list[str],
    row_corrections_path: Path = ROW_CORRECTIONS_FILE,
    strategy_corrections_path: Path = FUND_STRATEGY_CORRECTIONS_FILE,
) -> pd.DataFrame:
    """Count row and strategy corrections per CIK."""
    results = []

    row_corr = _read_csv(row_corrections_path)
    strat_corr = _read_csv(strategy_corrections_path)

    for cik in cohort_ciks:
        row_count = 0
        strat_count = 0

        if not row_corr.empty and "cik" in row_corr.columns:
            rc = row_corr.copy()
            rc["cik"] = rc["cik"].map(_norm_cik)
            row_count = int((rc["cik"] == cik).sum())

        if not strat_corr.empty and "cik" in strat_corr.columns:
            sc = strat_corr.copy()
            sc["cik"] = sc["cik"].map(_norm_cik)
            # Only count applied corrections
            if "correction_status" in sc.columns:
                sc = sc[sc["correction_status"].str.upper() == "APPLY"]
            strat_count = int((sc["cik"] == cik).sum())

        results.append({
            "cik": cik,
            "row_correction_count": row_count,
            "strategy_correction_count": strat_count,
        })

    return pd.DataFrame(results)


def audit_provenance_completeness(
    con: duckdb.DuckDBPyConnection,
    provenance_path: Path = POSITION_PROVENANCE_FILE,
) -> pd.DataFrame:
    """Full-chain provenance % per CIK. Degrades gracefully if missing."""
    if not provenance_path.exists():
        # Return not_available indicator
        tables = con.execute(
            "SELECT table_name FROM information_schema.tables"
        ).fetchdf()["table_name"].tolist()
        ciks = con.execute("SELECT cik FROM cohort_ciks").fetchdf()["cik"].tolist()
        return pd.DataFrame({
            "cik": ciks,
            "provenance_status": "not_available",
            "full_chain_pct": 0.0,
            "total_provenance_rows": 0,
        })

    # If file exists, register and query
    con.execute(f"""
        CREATE TABLE IF NOT EXISTS position_provenance AS
        SELECT * FROM read_csv_auto('{_safe(provenance_path)}',
                      header=true, all_varchar=true)
        WHERE LPAD(CAST(cik AS VARCHAR), 10, '0') IN (SELECT cik FROM cohort_ciks)
    """)

    prov_cols = con.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name='position_provenance'"
    ).fetchdf()["column_name"].tolist()

    has_rule = "wrapper_rule_id" in prov_cols or "extraction_rule" in prov_cols
    has_acc = "accession_number" in prov_cols

    if not has_rule and not has_acc:
        ciks = con.execute("SELECT cik FROM cohort_ciks").fetchdf()["cik"].tolist()
        return pd.DataFrame({
            "cik": ciks,
            "provenance_status": "available_no_chain_fields",
            "full_chain_pct": 0.0,
            "total_provenance_rows": 0,
        })

    rule_col = "wrapper_rule_id" if "wrapper_rule_id" in prov_cols else "extraction_rule"

    return con.execute(f"""
        SELECT
            LPAD(CAST(cik AS VARCHAR), 10, '0') AS cik,
            'available' AS provenance_status,
            CASE WHEN COUNT(*) > 0
                THEN SUM(CASE
                    WHEN {rule_col} IS NOT NULL AND {rule_col} != ''
                         AND accession_number IS NOT NULL AND accession_number != ''
                    THEN 1 ELSE 0
                END) * 100.0 / COUNT(*)
                ELSE 0
            END AS full_chain_pct,
            COUNT(*) AS total_provenance_rows
        FROM position_provenance
        GROUP BY LPAD(CAST(cik AS VARCHAR), 10, '0')
    """).fetchdf()


def audit_pct_of_net_assets(
    con: duckdb.DuckDBPyConnection,
) -> pd.DataFrame:
    """pct_of_net_assets sum per CIK-quarter."""
    holdings_cols = con.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name='holdings'"
    ).fetchdf()["column_name"].tolist()

    if "pct_of_net_assets" not in holdings_cols:
        return pd.DataFrame(columns=[
            "cik", "report_date", "pct_sum", "pct_flag",
        ])

    return con.execute("""
        SELECT
            LPAD(CAST(cik AS VARCHAR), 10, '0') AS cik,
            report_date,
            SUM(TRY_CAST(pct_of_net_assets AS DOUBLE)) AS pct_sum,
            CASE
                WHEN SUM(TRY_CAST(pct_of_net_assets AS DOUBLE)) > 120 THEN 'HIGH'
                WHEN SUM(TRY_CAST(pct_of_net_assets AS DOUBLE)) < 50
                     AND SUM(TRY_CAST(pct_of_net_assets AS DOUBLE)) > 0 THEN 'LOW'
                ELSE 'OK'
            END AS pct_flag
        FROM holdings
        WHERE report_date IS NOT NULL AND report_date != ''
        GROUP BY LPAD(CAST(cik AS VARCHAR), 10, '0'), report_date
        ORDER BY cik, report_date
    """).fetchdf()


def audit_wrapper_spec_complexity(
    entries: list[CohortEntry],
    wrapper_dir: Path = WRAPPER_DIR,
) -> pd.DataFrame:
    """Parse wrapper JSONs for structural complexity metrics."""
    results = []
    for entry in entries:
        wrapper_path = wrapper_dir / entry.wrapper_file
        row: dict[str, Any] = {
            "cik": entry.cik,
            "wrapper_exists": False,
            "wrapper_version": 0,
            "schema_version": "",
            "prefix_rule_count": 0,
            "leaf_marker_family_count": 0,
            "aggregate_marker_count": 0,
            "archetype_count": 0,
            "has_staging": False,
            "has_edge_cases": False,
            "invariant_count": 0,
        }
        if not wrapper_path.exists():
            results.append(row)
            continue

        try:
            with wrapper_path.open(encoding="utf-8") as fh:
                spec = json.load(fh)
        except (json.JSONDecodeError, OSError):
            results.append(row)
            continue

        row["wrapper_exists"] = True
        row["wrapper_version"] = spec.get("version", 0)
        row["schema_version"] = spec.get("schema_version", "")

        dispatch = spec.get("dispatch", {})
        row["prefix_rule_count"] = len(dispatch.get("prefix_rules", {}))
        leaf_markers = dispatch.get("leaf_markers_by_family", {})
        row["leaf_marker_family_count"] = len(leaf_markers)
        row["aggregate_marker_count"] = len(
            dispatch.get("aggregate_markers", [])
        )

        archetypes = spec.get("archetypes", {})
        row["archetype_count"] = len(archetypes)

        staging = spec.get("staging", {})
        row["has_staging"] = bool(staging)

        edge_cases = spec.get("known_edge_cases", [])
        row["has_edge_cases"] = bool(edge_cases)

        invariants = spec.get("invariants", {})
        row["invariant_count"] = len(invariants)

        results.append(row)

    return pd.DataFrame(results)


# ---------------------------------------------------------------------------
# Risk scoring
# ---------------------------------------------------------------------------

def compute_risk_score(detail: pd.DataFrame) -> pd.Series:
    """Weighted composite risk score, 0-100 (higher = more risk)."""
    scores = pd.Series(0.0, index=detail.index)

    # Source reconciliation gap: weight 0.25
    if "avg_reconciled_rate" in detail.columns:
        recon_gap = 1.0 - detail["avg_reconciled_rate"].fillna(0).clip(0, 1)
        scores += recon_gap * 25.0

    # Blocking issues: weight 0.20
    if "total_blocking_issues" in detail.columns:
        blocking = (detail["total_blocking_issues"].fillna(0) / 50.0).clip(0, 1)
        scores += blocking * 20.0

    # Unclassified rate: weight 0.15
    if "unclassified_pct" in detail.columns:
        unc = detail["unclassified_pct"].fillna(0).clip(0, 1)
        scores += unc * 15.0

    # FV coverage gap: weight 0.15
    if "fv_coverage_ratio" in detail.columns:
        fv_gap = (1.0 - detail["fv_coverage_ratio"].fillna(1)).abs().clip(0, 1)
        scores += fv_gap * 15.0

    # Position volatility: weight 0.10
    if "volatile_quarters" in detail.columns and "total_quarters" in detail.columns:
        vol_frac = detail.apply(
            lambda r: (r["volatile_quarters"] / r["total_quarters"])
            if r["total_quarters"] > 0 else 0,
            axis=1,
        ).clip(0, 1)
        scores += vol_frac * 10.0

    # Wrapper-global disagreement: weight 0.10
    if "disagreement_pct" in detail.columns:
        disagree = detail["disagreement_pct"].fillna(0).clip(0, 1)
        scores += disagree * 10.0

    # Provenance gap: weight 0.05
    if "full_chain_pct" in detail.columns:
        prov_gap = (100.0 - detail["full_chain_pct"].fillna(0)).clip(0, 100) / 100.0
        scores += prov_gap * 5.0

    return scores.round(1)


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------

def build_audit_detail(
    entries: list[CohortEntry],
    recon_cik: pd.DataFrame,
    fv_cov: pd.DataFrame,
    pos_cik: pd.DataFrame,
    class_dist: pd.DataFrame,
    wrapper_global: pd.DataFrame,
    corrections: pd.DataFrame,
    provenance: pd.DataFrame,
    wrapper_complexity: pd.DataFrame,
    gate_df: pd.DataFrame,
) -> pd.DataFrame:
    """Merge all per-CIK results into a wide DataFrame."""
    base = pd.DataFrame([{
        "cik": e.cik,
        "cohort_rank": e.rank,
        "wrapper_file": e.wrapper_file,
    } for e in entries])

    # Get entity names from gate if available
    if not gate_df.empty and "cik" in gate_df.columns:
        # Gate may not have entity_name; skip if missing
        pass

    out = base
    for df in [
        recon_cik, fv_cov, pos_cik, class_dist, wrapper_global,
        corrections, provenance, wrapper_complexity,
    ]:
        if not df.empty and "cik" in df.columns:
            # Drop duplicate cik columns from the right side
            merge_cols = [c for c in df.columns if c != "cik" or c == "cik"]
            out = out.merge(df, on="cik", how="left")

    # Merge gate status
    if not gate_df.empty and "cik" in gate_df.columns:
        gate_cols = ["cik", "status", "blocking_reasons"]
        available = [c for c in gate_cols if c in gate_df.columns]
        out = out.merge(gate_df[available], on="cik", how="left")
        if "status" in out.columns:
            out.rename(columns={"status": "gate_status"}, inplace=True)

    # Compute risk score
    out["risk_score"] = compute_risk_score(out)
    out = out.sort_values("risk_score", ascending=False).reset_index(drop=True)
    out["risk_rank"] = range(1, len(out) + 1)

    return out


def build_audit_quarterly(
    recon_q: pd.DataFrame,
    pos_q: pd.DataFrame,
    pct_q: pd.DataFrame,
) -> pd.DataFrame:
    """Merge time-series results into a per-CIK-quarter DataFrame."""
    # Start from position counts (most likely to have full coverage)
    if not pos_q.empty and "cik" in pos_q.columns:
        out = pos_q.copy()
    else:
        out = pd.DataFrame(columns=["cik", "report_date"])

    if not recon_q.empty and "cik" in recon_q.columns:
        if out.empty:
            out = recon_q.copy()
        else:
            out = out.merge(recon_q, on=["cik", "report_date"], how="outer")

    if not pct_q.empty and "cik" in pct_q.columns:
        if out.empty:
            out = pct_q.copy()
        else:
            out = out.merge(pct_q, on=["cik", "report_date"], how="outer")

    out = out.sort_values(["cik", "report_date"]).reset_index(drop=True)
    return out


# ---------------------------------------------------------------------------
# Markdown report
# ---------------------------------------------------------------------------

def _fmt_millions(value: Any) -> str:
    """Format a number as $XM or $XB."""
    v = _to_float(value)
    if v == 0:
        return "$0"
    if abs(v) >= 1e9:
        return f"${v / 1e9:.1f}B"
    return f"${v / 1e6:.0f}M"


def _fmt_pct(value: Any, default: str = "N/A") -> str:
    """Format a ratio as a percentage string."""
    v = _to_float(value)
    if v == 0 and default != "0%":
        return default
    return f"{v * 100:.1f}%"


def write_report_md(
    detail: pd.DataFrame,
    quarterly: pd.DataFrame,
    gate_df: pd.DataFrame,
    report_path: Path = DEFAULT_REPORT_OUT,
) -> None:
    """Render the markdown audit report."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    total_ciks = len(detail)

    # Cohort summary
    total_fv = detail["holdings_fv_sum"].fillna(0).sum() if "holdings_fv_sum" in detail.columns else 0
    avg_recon = detail["avg_reconciled_rate"].mean() if "avg_reconciled_rate" in detail.columns else 0
    avg_raw_recon = detail["avg_raw_reconciled_rate"].mean() if "avg_raw_reconciled_rate" in detail.columns else 0
    blocking_ciks = int((detail.get("total_blocking_issues", pd.Series(0, index=detail.index)).fillna(0) > 0).sum())
    blocking_ciks_metrics = int((detail.get("total_blocking_issues_metrics", pd.Series(0, index=detail.index)).fillna(0) > 0).sum())
    high_unc = int((detail.get("unclassified_pct", pd.Series(0, index=detail.index)).fillna(0) > 0.05).sum())
    gate_pass = int((detail.get("gate_status", pd.Series("", index=detail.index)) == "PASS").sum())
    gate_fail = total_ciks - gate_pass

    lines = [
        "# Wrapper V1 Cohort Audit Report",
        "",
        f"Generated: {now}",
        "",
        "## Cohort Summary",
        "",
        f"- {total_ciks} CIKs in cohort",
        f"- Total holdings FV: {_fmt_millions(total_fv)}",
        f"- Quality gate: {gate_pass} PASS / {gate_fail} FAIL",
        f"- Avg source reconciliation rate: {_fmt_pct(avg_recon)} calibrated, {_fmt_pct(avg_raw_recon)} raw",
        f"- CIKs with residual blocking issues: {blocking_ciks} (metrics-level: {blocking_ciks_metrics})",
        f"- CIKs with >5% unclassified: {high_unc}",
        "",
        "## Risk Rankings",
        "",
        "| Rank | CIK | Entity | Score | Gate | Top Risk Factors |",
        "|------|-----|--------|-------|------|------------------|",
    ]

    for _, row in detail.iterrows():
        rank = _safe_int(row.get("risk_rank", 0))
        cik = row.get("cik", "")
        entity = str(row.get("entity_name", cik))[:40]
        score = _safe_float(row.get("risk_score", 0))
        gate = str(row.get("gate_status", ""))
        # Top risk factors
        factors = []
        if _safe_float(row.get("total_blocking_issues", 0)) > 0:
            factors.append(f"blockers={_safe_int(row.get('total_blocking_issues', 0))}")
        if _safe_float(row.get("unclassified_pct", 0)) > 0.05:
            factors.append(f"unc={_fmt_pct(row.get('unclassified_pct', 0))}")
        if _safe_float(row.get("avg_reconciled_rate", 1)) < 0.9:
            factors.append(f"recon={_fmt_pct(row.get('avg_reconciled_rate', 0))}")
        fv_ratio = _safe_float(row.get("fv_coverage_ratio", 0))
        if fv_ratio > 0:
            gap = abs(1 - fv_ratio)
            if gap > 0.15:
                factors.append(f"fv_gap={_fmt_pct(1 - gap, '0%')}")
        if _safe_float(row.get("volatile_quarters", 0)) > 0:
            factors.append(f"vol_q={_safe_int(row.get('volatile_quarters', 0))}")
        factor_str = "; ".join(factors) if factors else "none"
        lines.append(f"| {rank} | {cik} | {entity} | {score:.1f} | {gate} | {factor_str} |")

    lines.extend(["", "## Per-CIK Detail", ""])

    for _, row in detail.iterrows():
        cik = row.get("cik", "")
        entity = str(row.get("entity_name", cik))
        score = _safe_float(row.get("risk_score", 0))
        gate = str(row.get("gate_status", ""))

        lines.append(f"### {entity} ({cik}) -- Risk: {score:.1f} -- Gate: {gate}")
        lines.append("")

        # Wrapper spec
        wv = _safe_int(row.get("wrapper_version", 0))
        prefix_rules = _safe_int(row.get("prefix_rule_count", 0))
        leaf_fam = _safe_int(row.get("leaf_marker_family_count", 0))
        lines.append(f"- Wrapper: v{wv}, {prefix_rules} prefix rules, {leaf_fam} leaf marker families")

        # Source recon
        recon_cal = row.get("avg_reconciled_rate")
        recon_raw = row.get("avg_raw_reconciled_rate")
        recon_q = _safe_int(row.get("recon_quarter_count", 0))
        blocking_res = _safe_int(row.get("total_blocking_issues", 0))
        blocking_met = _safe_int(row.get("total_blocking_issues_metrics", 0))
        recon_str = _fmt_pct(recon_cal)
        if recon_raw is not None and _safe_float(recon_raw) > 0:
            recon_str += f" calibrated ({_fmt_pct(recon_raw)} raw)"
        blocking_str = str(blocking_res)
        if blocking_met != blocking_res:
            blocking_str += f" residual ({blocking_met} metrics)"
        lines.append(f"- Source recon: {recon_str}, {blocking_str} blockers across {recon_q} quarters")

        # FV coverage
        fv = row.get("holdings_fv_sum", 0)
        ta = row.get("total_assets", 0)
        ratio = row.get("fv_coverage_ratio")
        ratio_str = _fmt_pct(ratio) if ratio is not None and _safe_float(ratio) > 0 else "N/A"
        lines.append(f"- Coverage: {_fmt_millions(fv)} FV / {_fmt_millions(ta)} total_assets = {ratio_str}")

        # Classification
        unc_pct = _fmt_pct(row.get("unclassified_pct", 0), "0%")
        breakdown = str(row.get("classification_breakdown", ""))[:80]
        lines.append(f"- Classification: {breakdown} (unclassified: {unc_pct})")

        # Wrapper-global disagreements
        disagree = _safe_int(row.get("disagreement_count", 0))
        disagree_pct = _fmt_pct(row.get("disagreement_pct", 0), "0%")
        lines.append(f"- Wrapper-global disagreements: {disagree} rows ({disagree_pct})")

        # Corrections
        row_corr = _safe_int(row.get("row_correction_count", 0))
        strat_corr = _safe_int(row.get("strategy_correction_count", 0))
        lines.append(f"- Corrections: {row_corr} row, {strat_corr} strategy")

        # Provenance
        prov_status = str(row.get("provenance_status", "not_available"))
        chain_pct = _fmt_pct(_safe_float(row.get("full_chain_pct", 0)) / 100.0, "0%")
        lines.append(f"- Provenance: {chain_pct} full chain ({prov_status})")

        # Position counts
        total_q = _safe_int(row.get("total_quarters", 0))
        avg_pos = _safe_int(row.get("avg_position_count", 0))
        vol_q = _safe_int(row.get("volatile_quarters", 0))
        lines.append(f"- Positions: avg {avg_pos}/quarter, {total_q} quarters, {vol_q} volatile")

        lines.append("")

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Entity name lookup
# ---------------------------------------------------------------------------

def _get_entity_names(con: duckdb.DuckDBPyConnection) -> dict[str, str]:
    """Get CIK -> entity_name mapping from holdings or fund_financials."""
    try:
        result = con.execute("""
            SELECT DISTINCT
                LPAD(CAST(cik AS VARCHAR), 10, '0') AS cik,
                FIRST(entity_name) AS entity_name
            FROM holdings
            WHERE entity_name IS NOT NULL AND entity_name != ''
            GROUP BY LPAD(CAST(cik AS VARCHAR), 10, '0')
        """).fetchdf()
        if not result.empty:
            return dict(zip(result["cik"], result["entity_name"]))
    except Exception:
        pass
    return {}


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def run_audit(
    manifest_path: Path = DEFAULT_MANIFEST,
    wrapper_dir: Path = WRAPPER_DIR,
    holdings_path: Path = HOLDINGS_FILE,
    fund_financials_path: Path = FUND_FINANCIALS_FILE,
    source_recon_metrics_path: Path = SOURCE_RECON_METRICS_FILE,
    source_recon_residual_path: Path = SOURCE_RECON_RESIDUAL_FILE,
    row_corrections_path: Path = ROW_CORRECTIONS_FILE,
    strategy_corrections_path: Path = FUND_STRATEGY_CORRECTIONS_FILE,
    provenance_path: Path = POSITION_PROVENANCE_FILE,
    quality_gate_path: Path = QUALITY_GATE_FILE,
    detail_out: Path = DEFAULT_DETAIL_OUT,
    quarterly_out: Path = DEFAULT_QUARTERLY_OUT,
    report_out: Path = DEFAULT_REPORT_OUT,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run the full cohort audit and write all artifacts.

    Returns (detail_df, quarterly_df).
    """
    manifest, entries = load_manifest(manifest_path)
    cohort_ciks = [e.cik for e in entries]

    print(f"Auditing {len(entries)} CIKs from cohort '{manifest['cohort_id']}'")

    # Setup DuckDB
    con = _setup_duckdb(
        cohort_ciks,
        holdings_path=holdings_path,
        fund_financials_path=fund_financials_path,
        source_recon_metrics_path=source_recon_metrics_path,
        source_recon_residual_path=source_recon_residual_path,
    )

    # Run all audit dimensions
    print("  [1/10] Source reconciliation...")
    recon_cik, recon_q = audit_source_reconciliation(con)

    print("  [2/10] FV coverage...")
    fv_cov = audit_fv_coverage(con)

    print("  [3/10] Position counts...")
    pos_cik, pos_q = audit_position_counts(con)

    print("  [4/10] Classification distribution...")
    class_dist = audit_classification_dist(con)

    print("  [5/10] Wrapper vs global agreement...")
    wrapper_global = audit_wrapper_vs_global(con)

    print("  [6/10] Corrections...")
    corrections = audit_corrections(
        cohort_ciks,
        row_corrections_path=row_corrections_path,
        strategy_corrections_path=strategy_corrections_path,
    )

    print("  [7/10] Provenance completeness...")
    provenance = audit_provenance_completeness(con, provenance_path=provenance_path)

    print("  [8/10] pct_of_net_assets...")
    pct_q = audit_pct_of_net_assets(con)

    print("  [9/10] Wrapper spec complexity...")
    wrapper_complexity = audit_wrapper_spec_complexity(entries, wrapper_dir=wrapper_dir)

    print("  [10/10] Loading quality gate...")
    gate_df = _read_csv(quality_gate_path)
    if not gate_df.empty and "cik" in gate_df.columns:
        gate_df["cik"] = gate_df["cik"].map(_norm_cik)

    # Entity names
    entity_names = _get_entity_names(con)

    con.close()

    # Build detail
    detail = build_audit_detail(
        entries, recon_cik, fv_cov, pos_cik, class_dist,
        wrapper_global, corrections, provenance, wrapper_complexity, gate_df,
    )
    # Add entity names
    detail["entity_name"] = detail["cik"].map(
        lambda c: entity_names.get(c, c)
    )

    # Build quarterly
    quarterly = build_audit_quarterly(recon_q, pos_q, pct_q)

    # Write artifacts
    detail_out.parent.mkdir(parents=True, exist_ok=True)
    detail.to_csv(detail_out, index=False)
    print(f"  Wrote {detail_out}")

    quarterly.to_csv(quarterly_out, index=False)
    print(f"  Wrote {quarterly_out}")

    write_report_md(detail, quarterly, gate_df, report_out)
    print(f"  Wrote {report_out}")

    # Summary
    avg_risk = detail["risk_score"].mean()
    max_risk = detail["risk_score"].max()
    top_cik = detail.iloc[0]["cik"] if not detail.empty else "none"
    print(f"\nAudit complete. Avg risk: {avg_risk:.1f}, Max: {max_risk:.1f} ({top_cik})")

    return detail, quarterly


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Deep per-CIK audit for the v1 39-wrapper BDC cohort"
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--wrapper-dir", type=Path, default=WRAPPER_DIR)
    parser.add_argument("--detail-out", type=Path, default=DEFAULT_DETAIL_OUT)
    parser.add_argument("--quarterly-out", type=Path, default=DEFAULT_QUARTERLY_OUT)
    parser.add_argument("--report-out", type=Path, default=DEFAULT_REPORT_OUT)
    args = parser.parse_args(argv)

    run_audit(
        manifest_path=args.manifest,
        wrapper_dir=args.wrapper_dir,
        detail_out=args.detail_out,
        quarterly_out=args.quarterly_out,
        report_out=args.report_out,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
