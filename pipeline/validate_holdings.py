"""Unified holdings validation -- spot-check, aggregate audit, coverage analysis.

Provides five validation functions plus an orchestrator:
  1. spot_check_top_ciks      -- stratified sample from top CIKs
  2. summarize_classification -- per-CIK classification breakdown with anomaly flags
  3. audit_aggregate_leaks    -- detect aggregates that passed the filter
  4. check_cross_source_overlap -- find CIKs in both BDC and N-PORT + duplicate detection
  5. check_coverage           -- compare holdings against the entity universe + total assets
  6. validate_holdings        -- orchestrator that runs all 5 and saves CSVs

All functions use DuckDB for data manipulation instead of pandas iterrows/apply.
"""

import logging
from typing import Optional

import duckdb
import pandas as pd

from pipeline.config import (
    COMBINED_UNIVERSE_FILE,
    HOLDINGS_COVERAGE_FILE,
    HOLDINGS_CROSS_SOURCE_FILE,
    HOLDINGS_SPOT_CHECK_FILE,
    HOLDINGS_TOTAL_ASSETS_FILE,
    HOLDINGS_VALIDATION_REPORT_FILE,
    NPORT_FUND_INFO_FILE,
    UNIFIED_HOLDINGS_FILE,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Extended aggregate keywords for audit (superset of _BDC_AGGREGATE_PATTERNS)
# ---------------------------------------------------------------------------
_AUDIT_AGGREGATE_KEYWORDS = [
    "non-control", "affiliate investments", "control investments",
    "total investments", "net assets", "subtotal",
    "total cash", "cash and cash equivalents", "total fair value",
    "total cost", "unfunded commitments", "total unfunded",
    "weighted average", "liabilities in excess",
    "investment debt investments", "investment equity securities",
    "investment unsecured", "placeholder",
    # Additional patterns for audit (not in main filter to avoid FP)
    "sub-total", "grand total", "total senior", "total junior",
    "total subordinated", "total first lien", "total second lien",
    "total equity", "total mezzanine", "total portfolio",
    "industry total", "sector total", "geography total",
]


def _get_connection(
    holdings_df: pd.DataFrame,
    universe_df: Optional[pd.DataFrame] = None,
    nport_fund_info_df: Optional[pd.DataFrame] = None,
) -> duckdb.DuckDBPyConnection:
    """Create a DuckDB connection and register DataFrames."""
    con = duckdb.connect()
    con.register("holdings", holdings_df)
    if universe_df is not None:
        con.register("universe", universe_df)
    if nport_fund_info_df is not None and len(nport_fund_info_df.columns) > 0:
        con.register("nport_fund_info", nport_fund_info_df)
    return con


# ---------------------------------------------------------------------------
# 1. Spot-check top CIKs
# ---------------------------------------------------------------------------

def spot_check_top_ciks(
    df: pd.DataFrame,
    top_n: int = 20,
    sample_per_cik: int = 50,
) -> pd.DataFrame:
    """Stratified sample from the top N CIKs by row count.

    For each CIK, samples up to ``sample_per_cik`` rows spread across
    all ``index_classification`` values.  Adds a ``classification_signals``
    column explaining why each row received its classification.

    Returns a DataFrame suitable for manual review.
    """
    if df.empty or "cik" not in df.columns:
        return pd.DataFrame()

    con = _get_connection(df)

    # Build signal explanation as SQL CASE WHEN
    signal_sql = """
        CASE WHEN source = 'nport' THEN
            concat_ws('; ',
                CASE WHEN COALESCE(CAST(nport_asset_cat AS VARCHAR), '') != '' THEN 'asset_cat=' || nport_asset_cat END,
                CASE WHEN COALESCE(CAST(nport_issuer_type AS VARCHAR), '') != '' THEN 'issuer_type=' || nport_issuer_type END
            )
        ELSE
            concat_ws('; ',
                CASE WHEN (
                    contains(COALESCE(lower(CAST(instrument_description AS VARCHAR)), ''), 'lien')
                    OR contains(COALESCE(lower(CAST(instrument_description AS VARCHAR)), ''), 'loan')
                    OR contains(COALESCE(lower(CAST(instrument_description AS VARCHAR)), ''), 'note')
                    OR contains(COALESCE(lower(CAST(instrument_description AS VARCHAR)), ''), 'revolving')
                    OR contains(COALESCE(lower(CAST(instrument_description AS VARCHAR)), ''), 'unitranche')
                    OR contains(COALESCE(lower(CAST(instrument_description AS VARCHAR)), ''), 'mezzanine')
                    OR contains(COALESCE(lower(CAST(instrument_description AS VARCHAR)), ''), 'credit')
                    OR contains(COALESCE(lower(CAST(instrument_description AS VARCHAR)), ''), 'secured')
                    OR contains(COALESCE(lower(CAST(instrument_description AS VARCHAR)), ''), 'one stop')
                ) THEN 'keyword:debt' END,
                CASE WHEN (
                    contains(COALESCE(lower(CAST(instrument_description AS VARCHAR)), ''), 'stock')
                    OR contains(COALESCE(lower(CAST(instrument_description AS VARCHAR)), ''), 'shares')
                    OR contains(COALESCE(lower(CAST(instrument_description AS VARCHAR)), ''), 'warrant')
                    OR contains(COALESCE(lower(CAST(instrument_description AS VARCHAR)), ''), 'units')
                    OR contains(COALESCE(lower(CAST(instrument_description AS VARCHAR)), ''), 'membership')
                    OR contains(COALESCE(lower(CAST(instrument_description AS VARCHAR)), ''), 'equity interest')
                ) THEN 'keyword:equity' END,
                CASE WHEN (
                    contains(COALESCE(lower(CAST(instrument_description AS VARCHAR)), ''), 'fund')
                    OR contains(COALESCE(lower(CAST(bdc_investment_identifier AS VARCHAR)), ''), 'fund')
                    OR contains(COALESCE(lower(CAST(instrument_description AS VARCHAR)), ''), 'lp interest')
                    OR contains(COALESCE(lower(CAST(bdc_investment_identifier AS VARCHAR)), ''), 'lp interest')
                ) THEN 'keyword:fund' END,
                CASE WHEN TRY_CAST(interest_rate AS DOUBLE) IS NOT NULL
                     AND TRY_CAST(interest_rate AS DOUBLE) != 0
                     THEN 'interest_rate=' || CAST(interest_rate AS VARCHAR) END,
                CASE WHEN TRY_CAST(basis_spread AS DOUBLE) IS NOT NULL
                     AND TRY_CAST(basis_spread AS DOUBLE) != 0
                     THEN 'basis_spread=' || CAST(basis_spread AS VARCHAR) END,
                CASE WHEN TRY_CAST(principal_amount AS DOUBLE) IS NOT NULL
                     AND TRY_CAST(principal_amount AS DOUBLE) != 0
                     THEN 'principal_amount=' || CAST(principal_amount AS VARCHAR) END,
                CASE WHEN TRY_CAST(shares_held AS DOUBLE) IS NOT NULL
                     AND TRY_CAST(shares_held AS DOUBLE) != 0
                     THEN 'shares_held=' || CAST(shares_held AS VARCHAR) END
            )
        END
    """

    sql = f"""
    WITH top_ciks AS (
        SELECT cik, COUNT(*) AS cnt
        FROM holdings
        GROUP BY cik
        ORDER BY cnt DESC
        LIMIT {top_n}
    ),
    with_signals AS (
        SELECT h.*,
            {signal_sql} AS classification_signals,
            ROW_NUMBER() OVER (
                PARTITION BY h.cik, h.index_classification
                ORDER BY random()
            ) AS _rn,
            GREATEST(
                {sample_per_cik} /
                    GREATEST(COUNT(DISTINCT h.index_classification) OVER (PARTITION BY h.cik), 1),
                1
            ) AS _per_group_limit
        FROM holdings h
        JOIN top_ciks t ON h.cik = t.cik
    ),
    sampled AS (
        SELECT * FROM with_signals
        WHERE _rn <= _per_group_limit
    ),
    capped AS (
        SELECT *,
            ROW_NUMBER() OVER (PARTITION BY cik ORDER BY random()) AS _cap_rn
        FROM sampled
    )
    SELECT * FROM capped WHERE _cap_rn <= {sample_per_cik}
    """

    result = con.execute(sql).fetchdf()
    con.close()

    # Fix empty signals -> 'no_signals'
    if "classification_signals" in result.columns:
        result["classification_signals"] = result["classification_signals"].fillna("")
        result.loc[result["classification_signals"] == "", "classification_signals"] = "no_signals"

    # Drop internal columns
    internal_cols = [c for c in result.columns if c.startswith("_")]
    result.drop(columns=internal_cols, inplace=True, errors="ignore")

    # Select useful columns for review
    review_cols = [
        "cik", "entity_name", "source", "issuer_name", "instrument_description",
        "fair_value", "interest_rate", "basis_spread", "principal_amount",
        "shares_held", "asset_category", "issuer_category",
        "index_classification", "bdc_investment_identifier",
        "nport_asset_cat", "nport_issuer_type", "classification_signals",
    ]
    available = [c for c in review_cols if c in result.columns]
    return result[available]


# ---------------------------------------------------------------------------
# 2. Per-CIK classification summary
# ---------------------------------------------------------------------------

def summarize_classification_by_cik(df: pd.DataFrame) -> pd.DataFrame:
    """Per-CIK summary with classification breakdown and anomaly flags.

    Returns DataFrame with one row per CIK.
    """
    if len(df) == 0:
        return pd.DataFrame()

    con = _get_connection(df)

    sql = """
    SELECT
        cik,
        FIRST(entity_name) AS entity_name,
        FIRST(source) AS source,
        COUNT(*) AS total_rows,
        SUM(TRY_CAST(fair_value AS DOUBLE)) AS total_fair_value,
        ROUND(100.0 * COUNT(*) FILTER (WHERE index_classification = 'DIRECT_LENDING') / COUNT(*), 1)
            AS pct_direct_lending,
        ROUND(100.0 * COUNT(*) FILTER (WHERE index_classification = 'PREFERRED_EQUITY') / COUNT(*), 1)
            AS pct_preferred_equity,
        ROUND(100.0 * COUNT(*) FILTER (WHERE index_classification = 'COMMON_EQUITY') / COUNT(*), 1)
            AS pct_common_equity,
        ROUND(100.0 * COUNT(*) FILTER (WHERE index_classification = 'PRIVATE_CREDIT_FUND') / COUNT(*), 1)
            AS pct_credit_fund,
        ROUND(100.0 * COUNT(*) FILTER (WHERE index_classification = 'PRIVATE_EQUITY_FUND') / COUNT(*), 1)
            AS pct_equity_fund,
        ROUND(100.0 * COUNT(*) FILTER (WHERE index_classification = 'UNCLASSIFIED') / COUNT(*), 1)
            AS pct_unclassified,
        MODE(index_classification) AS dominant_index,
        COUNT(DISTINCT issuer_name) AS num_unique_issuers,
        CASE
            WHEN FIRST(source) = 'bdc'
                 AND 100.0 * COUNT(*) FILTER (WHERE index_classification = 'UNCLASSIFIED') / COUNT(*) > 50
                THEN true
            WHEN FIRST(source) = 'nport'
                 AND 100.0 * COUNT(*) FILTER (WHERE index_classification = 'UNCLASSIFIED') / COUNT(*) > 80
                THEN true
            ELSE false
        END AS has_anomalous_mix
    FROM holdings
    GROUP BY cik
    """

    result = con.execute(sql).fetchdf()
    con.close()
    return result


# ---------------------------------------------------------------------------
# 3. Audit aggregate leaks
# ---------------------------------------------------------------------------

def _sql_audit_keyword_check() -> str:
    """Generate SQL OR chain for audit aggregate keywords."""
    clauses = []
    for kw in _AUDIT_AGGREGATE_KEYWORDS:
        escaped = kw.replace("'", "''")
        clauses.append(
            f"contains(COALESCE(lower(CAST(issuer_name AS VARCHAR)), ''), '{escaped}') "
            f"OR contains(COALESCE(lower(CAST(bdc_investment_identifier AS VARCHAR)), ''), '{escaped}')"
        )
    return " OR ".join(f"({c})" for c in clauses)


def _sql_audit_keyword_reason() -> str:
    """Generate SQL CASE WHEN to get the first matching keyword."""
    cases = []
    for kw in _AUDIT_AGGREGATE_KEYWORDS:
        escaped = kw.replace("'", "''")
        cases.append(
            f"WHEN contains(COALESCE(lower(CAST(issuer_name AS VARCHAR)), ''), '{escaped}') "
            f"OR contains(COALESCE(lower(CAST(bdc_investment_identifier AS VARCHAR)), ''), '{escaped}') "
            f"THEN 'keyword:{escaped}'"
        )
    return "CASE " + " ".join(cases) + " END"


def audit_aggregate_leaks(df: pd.DataFrame) -> pd.DataFrame:
    """Detect suspected aggregate/subtotal rows that passed the main filter.

    BDC-only scan.  Uses extended keyword list to find section headers,
    subtotals, and category summaries that slipped through the primary filter.

    Returns DataFrame of suspected aggregates with reason.
    """
    empty_result = pd.DataFrame(columns=[
        "cik", "entity_name", "issuer_name", "fair_value",
        "bdc_investment_identifier", "reason",
    ])

    if df.empty or "source" not in df.columns:
        return empty_result

    # Check if any BDC rows exist
    if not (df["source"] == "bdc").any():
        return empty_result

    con = _get_connection(df)

    kw_check = _sql_audit_keyword_check()
    kw_reason = _sql_audit_keyword_reason()

    sql = f"""
    SELECT
        cik, entity_name, issuer_name, fair_value,
        bdc_investment_identifier,
        {kw_reason} AS reason
    FROM holdings
    WHERE source = 'bdc'
      AND ({kw_check})
    """

    result = con.execute(sql).fetchdf()
    con.close()

    if result.empty:
        return empty_result
    return result


# ---------------------------------------------------------------------------
# 4. Cross-source overlap (V4 enhanced with duplicate detection)
# ---------------------------------------------------------------------------

def check_cross_source_overlap(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Find CIKs present in both BDC and N-PORT sources + detect duplicate holdings.

    Returns a tuple of (overlap_summary, duplicate_holdings):
      - overlap_summary: DataFrame of overlapping CIKs with row counts per source
      - duplicate_holdings: DataFrame of actual duplicate holding pairs with
        fair_value comparison (matched on CIK + report_date + similar issuer name)
    """
    empty_summary = pd.DataFrame(columns=["cik", "bdc_rows", "nport_rows"])
    empty_dupes = pd.DataFrame(columns=[
        "cik", "bdc_issuer", "nport_issuer", "report_date",
        "bdc_fair_value", "nport_fair_value", "pct_diff",
    ])

    if df.empty or "source" not in df.columns:
        logger.info("  Cross-source overlap: 0 CIKs (no data)")
        return empty_summary, empty_dupes

    con = _get_connection(df)

    # Step 1: Find overlapping CIKs and row counts
    summary_sql = """
    WITH overlap_ciks AS (
        SELECT cik FROM holdings WHERE source = 'bdc'
        INTERSECT
        SELECT cik FROM holdings WHERE source = 'nport'
    )
    SELECT
        h.cik,
        COUNT(*) FILTER (WHERE h.source = 'bdc') AS bdc_rows,
        COUNT(*) FILTER (WHERE h.source = 'nport') AS nport_rows
    FROM holdings h
    JOIN overlap_ciks o ON h.cik = o.cik
    GROUP BY h.cik
    ORDER BY h.cik
    """
    overlap_summary = con.execute(summary_sql).fetchdf()

    if overlap_summary.empty:
        logger.info("  Cross-source overlap: 0 CIKs (expected)")
        con.close()
        return empty_summary, empty_dupes

    logger.warning("  Cross-source overlap: %d CIKs found!", len(overlap_summary))

    # Step 2: Find actual duplicate holdings (fuzzy match on issuer + period + fair_value)
    dupes_sql = """
    WITH overlap_ciks AS (
        SELECT cik FROM holdings WHERE source = 'bdc'
        INTERSECT
        SELECT cik FROM holdings WHERE source = 'nport'
    )
    SELECT
        b.cik,
        b.issuer_name AS bdc_issuer,
        n.issuer_name AS nport_issuer,
        b.report_date,
        b.fair_value AS bdc_fair_value,
        n.fair_value AS nport_fair_value,
        CASE
            WHEN TRY_CAST(b.fair_value AS DOUBLE) > 0
            THEN ABS(TRY_CAST(b.fair_value AS DOUBLE) - TRY_CAST(n.fair_value AS DOUBLE))
                 / TRY_CAST(b.fair_value AS DOUBLE)
            ELSE NULL
        END AS pct_diff
    FROM holdings b
    JOIN holdings n
        ON b.cik = n.cik
        AND b.report_date = n.report_date
        AND jaro_winkler_similarity(
            lower(CAST(b.issuer_name AS VARCHAR)),
            lower(CAST(n.issuer_name AS VARCHAR))
        ) > 0.85
    WHERE b.source = 'bdc'
      AND n.source = 'nport'
      AND b.cik IN (SELECT cik FROM overlap_ciks)
    """
    duplicate_holdings = con.execute(dupes_sql).fetchdf()
    con.close()

    if duplicate_holdings.empty:
        logger.info("  Duplicate holdings in overlapping CIKs: 0")
    else:
        logger.warning("  Duplicate holdings found: %d pairs across %d CIKs",
                        len(duplicate_holdings), duplicate_holdings["cik"].nunique())

    return overlap_summary, duplicate_holdings


# ---------------------------------------------------------------------------
# 5. Coverage check (V5 enhanced with total assets + temporal detail)
# ---------------------------------------------------------------------------

def check_coverage(
    df: pd.DataFrame,
    universe_df: Optional[pd.DataFrame] = None,
    nport_fund_info_df: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """Compare holdings against the entity universe for coverage gaps.

    Flags CIKs with no holdings, single period, or low fair_value.
    Enhanced with total assets sanity check and temporal detail.
    """
    if universe_df is None:
        if not COMBINED_UNIVERSE_FILE.exists():
            logger.warning("  Universe file not found: %s", COMBINED_UNIVERSE_FILE)
            return pd.DataFrame()
        universe_df = pd.read_csv(COMBINED_UNIVERSE_FILE, dtype=str)

    # Handle empty holdings
    if df.empty or "fair_value" not in df.columns:
        result = universe_df[["cik", "entity_name", "vehicle_type"]].copy()
        result["in_universe"] = True
        result["has_holdings"] = False
        result["num_holdings"] = 0
        result["total_fair_value"] = 0
        result["num_periods"] = 0
        result["earliest_period"] = ""
        result["latest_period"] = ""
        result["reported_net_assets"] = None
        result["holdings_to_assets_ratio"] = None
        result["issue"] = "no_holdings"
        return result

    # Load N-PORT fund info if available
    if nport_fund_info_df is None and NPORT_FUND_INFO_FILE.exists():
        try:
            nport_fund_info_df = pd.read_csv(NPORT_FUND_INFO_FILE, dtype=str)
        except Exception:
            nport_fund_info_df = None

    con = _get_connection(df, universe_df=universe_df,
                          nport_fund_info_df=nport_fund_info_df)

    # Build the total assets CTE based on available data
    nport_assets_cte = ""
    if (nport_fund_info_df is not None and not nport_fund_info_df.empty
            and len(nport_fund_info_df.columns) > 0):
        nport_assets_cte = """
        nport_assets AS (
            SELECT
                CAST(cik AS VARCHAR) AS cik,
                MAX(TRY_CAST(net_assets AS DOUBLE)) AS reported_net_assets
            FROM nport_fund_info
            WHERE net_assets IS NOT NULL AND net_assets != ''
            GROUP BY cik
        ),
        """
    else:
        nport_assets_cte = """
        nport_assets AS (
            SELECT CAST(NULL AS VARCHAR) AS cik, CAST(NULL AS DOUBLE) AS reported_net_assets
            WHERE false
        ),
        """

    sql = f"""
    WITH holdings_stats AS (
        SELECT
            CAST(cik AS VARCHAR) AS cik,
            COUNT(*) AS num_holdings,
            SUM(TRY_CAST(fair_value AS DOUBLE)) AS total_fair_value,
            COUNT(DISTINCT report_date) AS num_periods,
            MIN(report_date) AS earliest_period,
            MAX(report_date) AS latest_period
        FROM holdings
        GROUP BY cik
    ),
    {nport_assets_cte}
    bdc_assets AS (
        SELECT
            CAST(cik AS VARCHAR) AS cik,
            report_date,
            CASE WHEN SUM(TRY_CAST(pct_of_net_assets AS DOUBLE)) > 10
                 THEN SUM(TRY_CAST(fair_value AS DOUBLE)) /
                      (SUM(TRY_CAST(pct_of_net_assets AS DOUBLE)) / 100.0)
            END AS estimated_total_assets
        FROM holdings
        WHERE source = 'bdc'
          AND pct_of_net_assets IS NOT NULL
          AND pct_of_net_assets != ''
        GROUP BY cik, report_date
    ),
    bdc_latest_assets AS (
        SELECT cik, estimated_total_assets AS reported_net_assets
        FROM bdc_assets
        WHERE estimated_total_assets IS NOT NULL
        QUALIFY ROW_NUMBER() OVER (PARTITION BY cik ORDER BY report_date DESC) = 1
    ),
    all_assets AS (
        SELECT * FROM nport_assets
        UNION ALL
        SELECT * FROM bdc_latest_assets
    ),
    best_assets AS (
        SELECT cik, MAX(reported_net_assets) AS reported_net_assets
        FROM all_assets
        WHERE reported_net_assets IS NOT NULL
        GROUP BY cik
    ),
    joined AS (
        SELECT
            CAST(u.cik AS VARCHAR) AS cik,
            u.entity_name,
            u.vehicle_type,
            COALESCE(h.num_holdings, 0) AS num_holdings,
            COALESCE(h.total_fair_value, 0) AS total_fair_value,
            COALESCE(h.num_periods, 0) AS num_periods,
            COALESCE(h.earliest_period, '') AS earliest_period,
            COALESCE(h.latest_period, '') AS latest_period,
            a.reported_net_assets,
            CASE WHEN a.reported_net_assets > 0 AND h.total_fair_value IS NOT NULL
                 THEN h.total_fair_value / a.reported_net_assets
            END AS holdings_to_assets_ratio,
            CASE
                WHEN h.num_holdings IS NULL OR h.num_holdings = 0 THEN 'no_holdings'
                WHEN h.num_periods <= 1 THEN 'single_period'
                WHEN h.total_fair_value < 1000 THEN 'low_fair_value'
                ELSE 'ok'
            END AS issue
        FROM universe u
        LEFT JOIN holdings_stats h ON CAST(u.cik AS VARCHAR) = h.cik
        LEFT JOIN best_assets a ON CAST(u.cik AS VARCHAR) = a.cik
    )
    SELECT *,
        true AS in_universe,
        (num_holdings > 0) AS has_holdings
    FROM joined
    """

    result = con.execute(sql).fetchdf()
    con.close()

    return result


# ---------------------------------------------------------------------------
# 6. Orchestrator
# ---------------------------------------------------------------------------

def validate_holdings(
    unified_df: Optional[pd.DataFrame] = None,
    universe_df: Optional[pd.DataFrame] = None,
) -> dict:
    """Run all validation checks and save CSVs.

    Returns dict of result DataFrames keyed by check name.
    """
    if unified_df is None:
        if not UNIFIED_HOLDINGS_FILE.exists():
            logger.error("Unified holdings file not found: %s", UNIFIED_HOLDINGS_FILE)
            return {}
        logger.info("Loading unified holdings from %s", UNIFIED_HOLDINGS_FILE.name)
        unified_df = pd.read_csv(UNIFIED_HOLDINGS_FILE, dtype=str)
        logger.info("  Loaded %d rows", len(unified_df))

    reports = {}

    # 1. Spot-check
    logger.info("Running spot-check on top CIKs...")
    spot = spot_check_top_ciks(unified_df)
    reports["spot_check"] = spot
    logger.info("  Spot-check: %d sample rows from %d CIKs",
                len(spot), spot["cik"].nunique() if len(spot) > 0 else 0)

    # 2. Per-CIK summary
    logger.info("Building per-CIK classification summary...")
    summary = summarize_classification_by_cik(unified_df)
    reports["cik_summary"] = summary
    anomalous = summary[summary["has_anomalous_mix"]] if len(summary) > 0 else summary
    logger.info("  Summary: %d CIKs, %d with anomalous mix",
                len(summary), len(anomalous))

    # 3. Aggregate audit
    logger.info("Auditing for aggregate leaks...")
    agg = audit_aggregate_leaks(unified_df)
    reports["aggregate_leaks"] = agg
    logger.info("  Aggregate suspects: %d rows", len(agg))

    # 4. Cross-source overlap (V4 enhanced)
    logger.info("Checking cross-source overlap...")
    overlap_summary, duplicate_holdings = check_cross_source_overlap(unified_df)
    reports["cross_source_overlap"] = overlap_summary
    reports["duplicate_holdings"] = duplicate_holdings

    # 5. Coverage (V5 enhanced)
    logger.info("Checking coverage against universe...")
    coverage = check_coverage(unified_df, universe_df=universe_df)
    reports["coverage"] = coverage
    if len(coverage) > 0:
        no_hold = (coverage["issue"] == "no_holdings").sum()
        single = (coverage["issue"] == "single_period").sum()
        logger.info("  Coverage: %d entities, %d with no holdings, %d single-period",
                    len(coverage), no_hold, single)
        # Log total assets ratio stats
        if "holdings_to_assets_ratio" in coverage.columns:
            ratio = pd.to_numeric(coverage["holdings_to_assets_ratio"], errors="coerce")
            valid_ratio = ratio.dropna()
            if len(valid_ratio) > 0:
                logger.info("  Holdings/assets ratio: %.2f median, %d CIKs with data",
                            valid_ratio.median(), len(valid_ratio))
                outliers = valid_ratio[(valid_ratio > 2.0) | (valid_ratio < 0.3)]
                if len(outliers) > 0:
                    logger.warning("  %d CIKs with outlier holdings/assets ratio",
                                   len(outliers))

    # Save CSVs
    if len(summary) > 0:
        summary.to_csv(HOLDINGS_VALIDATION_REPORT_FILE, index=False)
        logger.info("  Saved %s", HOLDINGS_VALIDATION_REPORT_FILE.name)

    if len(spot) > 0:
        spot.to_csv(HOLDINGS_SPOT_CHECK_FILE, index=False)
        logger.info("  Saved %s", HOLDINGS_SPOT_CHECK_FILE.name)

    if len(coverage) > 0:
        coverage.to_csv(HOLDINGS_COVERAGE_FILE, index=False)
        logger.info("  Saved %s", HOLDINGS_COVERAGE_FILE.name)

    if len(overlap_summary) > 0 or len(duplicate_holdings) > 0:
        overlap_summary.to_csv(HOLDINGS_CROSS_SOURCE_FILE, index=False)
        logger.info("  Saved %s", HOLDINGS_CROSS_SOURCE_FILE.name)

    if len(coverage) > 0 and "holdings_to_assets_ratio" in coverage.columns:
        assets_df = coverage[coverage["reported_net_assets"].notna()].copy()
        if len(assets_df) > 0:
            assets_df.to_csv(HOLDINGS_TOTAL_ASSETS_FILE, index=False)
            logger.info("  Saved %s", HOLDINGS_TOTAL_ASSETS_FILE.name)

    return reports
