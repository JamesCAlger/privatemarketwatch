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

from pipeline.bdc_identifier import _sql_is_bdc_aggregate
from pipeline.config import (
    CLASSIFICATION_VALIDATION_FILE,
    COLUMN_QUALITY_METRICS_FILE,
    COMBINED_UNIVERSE_FILE,
    DATA_QUALITY_METRICS_FILE,
    FEE_UPLIFT_FILE,
    BDC_HOLDINGS_FILE,
    FUND_FINANCIALS_FILE,
    HOLDINGS_COUNT_STABILITY_FILE,
    HOLDINGS_COVERAGE_FILE,
    HOLDINGS_CROSS_SOURCE_FILE,
    HOLDINGS_GAV_RECONCILIATION_FILE,
    HOLDINGS_INCOME_YIELD_FILE,
    HOLDINGS_PCT_SUM_FILE,
    HOLDINGS_SPOT_CHECK_FILE,
    HOLDINGS_TOTAL_ASSETS_FILE,
    HOLDINGS_VALIDATION_REPORT_FILE,
    NPORT_FUND_INFO_FILE,
    NPORT_EXCLUDE_CIKS,
    ROW_VALIDATION_ISSUES_FILE,
    UNIFIED_HOLDINGS_FILE,
    VALIDATE_ALL_RESIDUAL_SUMMARY_FILE,
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
        ROUND(100.0 * COUNT(*) FILTER (WHERE index_classification = 'REAL_ESTATE_FUND') / COUNT(*), 1)
            AS pct_real_estate_fund,
        ROUND(100.0 * COUNT(*) FILTER (WHERE index_classification = 'DIRECT_REAL_ESTATE') / COUNT(*), 1)
            AS pct_direct_real_estate,
        ROUND(100.0 * COUNT(*) FILTER (WHERE index_classification = 'STRUCTURED_CREDIT') / COUNT(*), 1)
            AS pct_structured_credit,
        ROUND(100.0 * COUNT(*) FILTER (WHERE index_classification = 'HEDGE_FUND') / COUNT(*), 1)
            AS pct_hedge_fund,
        ROUND(100.0 * COUNT(*) FILTER (WHERE index_classification = 'CASH') / COUNT(*), 1)
            AS pct_cash,
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
          AND TRY_CAST(pct_of_net_assets AS DOUBLE) IS NOT NULL
          AND TRY_CAST(pct_of_net_assets AS DOUBLE) != 0
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
# 6. Classification cross-reference validation
# ---------------------------------------------------------------------------

# Expected mappings: N-PORT structured codes -> exposure_type / asset_class.
# These are deterministic ground truth from the SEC filing format.
_EXPOSURE_RULES = {
    # (issuer_category from our mapping) -> expected exposure_type
    "GOVERNMENT": "LIQUID",
    "FUND": "FUND",
    # CORPORATE and OTHER -> DIRECT (unless cash keywords override)
}
_ASSET_CLASS_RULES = [
    # (condition_sql, expected_asset_class, description)
    ("issuer_category = 'GOVERNMENT'", "CASH", "Government issuers should be CASH"),
    ("asset_category IN ('LOAN', 'DEBT') AND issuer_category = 'CORPORATE'",
     "PRIVATE_CREDIT", "LOAN/DEBT + CORPORATE should be PRIVATE_CREDIT"),
    ("asset_category IN ('EQUITY_COMMON', 'EQUITY_PREFERRED') AND issuer_category = 'CORPORATE'",
     "PRIVATE_EQUITY", "Equity + CORPORATE should be PRIVATE_EQUITY"),
]


def validate_classification(
    unified_df: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """Cross-reference exposure_type and asset_class against structural ground truth.

    Uses N-PORT's issuer_type/asset_cat codes and BDC asset/issuer categories
    as deterministic validators. Reports disagreements per rule.

    Returns a DataFrame with columns:
      rule, expected, actual, disagreement_count, disagreement_pct, sample_names
    """
    if unified_df is None:
        if not UNIFIED_HOLDINGS_FILE.exists():
            logger.error("Unified holdings file not found")
            return pd.DataFrame()
        unified_df = pd.read_csv(UNIFIED_HOLDINGS_FILE, dtype=str)

    con = duckdb.connect()
    con.register("h", unified_df)

    rules_results = []

    # --- Exposure type cross-reference ---
    # Rule E1: GOVERNMENT issuer -> LIQUID
    rules_results.append(_check_rule(
        con, "E1: GOVERNMENT -> LIQUID",
        "exposure_type", "LIQUID",
        "issuer_category = 'GOVERNMENT'",
    ))
    # Rule E2: FUND issuer -> FUND
    rules_results.append(_check_rule(
        con, "E2: FUND issuer -> FUND",
        "exposure_type", "FUND",
        "issuer_category = 'FUND'",
    ))
    # Rule E3: CORPORATE issuer (no cash keywords) -> DIRECT
    rules_results.append(_check_rule(
        con, "E3: CORPORATE -> DIRECT",
        "exposure_type", "DIRECT",
        "issuer_category = 'CORPORATE' AND asset_class != 'CASH'",
    ))

    # --- Asset class cross-reference ---
    # Rule A1: GOVERNMENT -> CASH
    rules_results.append(_check_rule(
        con, "A1: GOVERNMENT -> CASH",
        "asset_class", "CASH",
        "issuer_category = 'GOVERNMENT'",
    ))
    # Rule A2: LOAN/DEBT + CORPORATE -> PRIVATE_CREDIT (unless structured credit)
    rules_results.append(_check_rule(
        con, "A2: LOAN/DEBT+CORP -> PRIVATE_CREDIT",
        "asset_class", "PRIVATE_CREDIT",
        "asset_category IN ('LOAN', 'DEBT') AND issuer_category = 'CORPORATE'"
        " AND asset_class != 'STRUCTURED_CREDIT' AND asset_class != 'REAL_ESTATE'",
    ))
    # Rule A3: EQUITY + CORPORATE -> PRIVATE_EQUITY (unless RE)
    rules_results.append(_check_rule(
        con, "A3: EQUITY+CORP -> PRIVATE_EQUITY",
        "asset_class", "PRIVATE_EQUITY",
        "asset_category IN ('EQUITY_COMMON', 'EQUITY_PREFERRED')"
        " AND issuer_category = 'CORPORATE'"
        " AND asset_class != 'REAL_ESTATE'",
    ))
    # Rule A4: N-PORT issuer_type=PF with no credit/PE signal -> HEDGE_FUND
    rules_results.append(_check_rule(
        con, "A4: nport PF+no signal -> HEDGE_FUND",
        "asset_class", "HEDGE_FUND",
        "source = 'nport'"
        " AND UPPER(TRIM(CAST(nport_issuer_type AS VARCHAR))) = 'PF'"
        " AND UPPER(TRIM(CAST(nport_asset_cat AS VARCHAR))) = 'OTHER'"
        " AND index_classification = 'HEDGE_FUND'",
    ))

    # --- Index classification consistency ---
    # Rule I1: DIRECT_LENDING -> exposure_type=DIRECT, asset_class=PRIVATE_CREDIT
    rules_results.append(_check_rule(
        con, "I1: DL -> DIRECT",
        "exposure_type", "DIRECT",
        "index_classification = 'DIRECT_LENDING'",
    ))
    rules_results.append(_check_rule(
        con, "I2: DL -> PRIVATE_CREDIT",
        "asset_class", "PRIVATE_CREDIT",
        "index_classification = 'DIRECT_LENDING'"
        " AND asset_class != 'STRUCTURED_CREDIT' AND asset_class != 'REAL_ESTATE'",
    ))
    # Rule I3: fund indices -> exposure_type=FUND
    rules_results.append(_check_rule(
        con, "I3: fund idx -> FUND exposure",
        "exposure_type", "FUND",
        "index_classification IN ('PRIVATE_CREDIT_FUND', 'PRIVATE_EQUITY_FUND',"
        " 'REAL_ESTATE_FUND', 'HEDGE_FUND')",
    ))

    con.close()

    result = pd.DataFrame(rules_results)
    logger.info("Classification cross-reference: %d rules checked", len(result))
    passing = (result["disagreement_count"] == 0).sum()
    logger.info("  %d/%d rules pass (0 disagreements)", passing, len(result))
    failing = result[result["disagreement_count"] > 0]
    for _, row in failing.iterrows():
        logger.warning("  DISAGREE %s: %d rows (%.1f%%) -- samples: %s",
                       row["rule"], row["disagreement_count"],
                       row["disagreement_pct"], row["sample_names"])

    return result


def _check_rule(con, rule_name: str, column: str, expected: str,
                condition: str) -> dict:
    """Check a single cross-reference rule. Returns dict with results."""
    sql = f"""
    SELECT
        COUNT(*) AS total,
        COUNT(*) FILTER (WHERE CAST({column} AS VARCHAR) != '{expected}') AS disagree,
        ROUND(100.0 * COUNT(*) FILTER (WHERE CAST({column} AS VARCHAR) != '{expected}')
              / GREATEST(COUNT(*), 1), 2) AS pct,
        ARRAY_AGG(DISTINCT issuer_name ORDER BY issuer_name)
            FILTER (WHERE CAST({column} AS VARCHAR) != '{expected}')[:5]
            AS samples,
        ARRAY_AGG(DISTINCT CAST({column} AS VARCHAR))
            FILTER (WHERE CAST({column} AS VARCHAR) != '{expected}')[:3]
            AS actual_values
    FROM h
    WHERE {condition}
    """
    try:
        row = con.execute(sql).fetchone()
        return {
            "rule": rule_name,
            "expected": expected,
            "condition": condition,
            "total_rows": row[0],
            "disagreement_count": row[1],
            "disagreement_pct": row[2],
            "sample_names": str(row[3] or []),
            "actual_values": str(row[4] or []),
        }
    except Exception as exc:
        logger.warning("Rule '%s' failed: %s", rule_name, exc)
        return {
            "rule": rule_name,
            "expected": expected,
            "condition": condition,
            "total_rows": -1,
            "disagreement_count": -1,
            "disagreement_pct": -1,
            "sample_names": f"ERROR: {exc}",
            "actual_values": "",
        }


def validate_classification_llm(
    unified_df: Optional[pd.DataFrame] = None,
    sample_size: int = 200,
    dry_run: bool = False,
) -> pd.DataFrame:
    """LLM-based accuracy audit of exposure_type and asset_class.

    Samples positions from boundary categories (HEDGE_FUND, REAL_ESTATE,
    STRUCTURED_CREDIT, OTHER, UNCLASSIFIED) and asks GPT-4o-mini to
    classify them independently. Compares LLM output against rule-based.

    Args:
        unified_df: The unified holdings DataFrame. Loaded from disk if None.
        sample_size: Total number of positions to sample (stratified).
        dry_run: If True, builds sample and prompt but skips API call.

    Returns DataFrame with columns:
        issuer_name, instrument_description, rule_exposure_type,
        rule_asset_class, rule_index_classification,
        llm_exposure_type, llm_asset_class, agrees_exposure, agrees_asset
    """
    try:
        from openai import OpenAI
    except ImportError:
        OpenAI = None

    if unified_df is None:
        if not UNIFIED_HOLDINGS_FILE.exists():
            logger.error("Unified holdings file not found")
            return pd.DataFrame()
        unified_df = pd.read_csv(UNIFIED_HOLDINGS_FILE, dtype=str)

    con = duckdb.connect()
    con.register("h", unified_df)

    # Stratified sample: oversample boundary categories
    # 40% from HEDGE_FUND/REAL_ESTATE/STRUCTURED_CREDIT/CASH/UNCLASSIFIED
    # 30% from FUND exposure_type
    # 30% from DIRECT (random)
    boundary_n = int(sample_size * 0.4)
    fund_n = int(sample_size * 0.3)
    direct_n = sample_size - boundary_n - fund_n

    _cols = """issuer_name, instrument_description, asset_category,
            issuer_category, index_classification, exposure_type, asset_class,
            nport_asset_cat, nport_issuer_type, source"""
    sample_sql = f"""
    (SELECT {_cols} FROM (
        SELECT {_cols} FROM h
        WHERE index_classification IN ('HEDGE_FUND', 'REAL_ESTATE_FUND',
              'STRUCTURED_CREDIT', 'CASH', 'UNCLASSIFIED', 'DIRECT_REAL_ESTATE')
     ) USING SAMPLE {boundary_n})
    UNION ALL
    (SELECT {_cols} FROM (
        SELECT {_cols} FROM h
        WHERE exposure_type = 'FUND'
          AND index_classification NOT IN ('HEDGE_FUND', 'REAL_ESTATE_FUND',
              'STRUCTURED_CREDIT', 'CASH', 'UNCLASSIFIED', 'DIRECT_REAL_ESTATE')
     ) USING SAMPLE {fund_n})
    UNION ALL
    (SELECT {_cols} FROM (
        SELECT {_cols} FROM h
        WHERE exposure_type = 'DIRECT'
     ) USING SAMPLE {direct_n})
    """
    sample = con.execute(sample_sql).fetchdf()
    con.close()

    logger.info("Classification LLM audit: sampled %d positions", len(sample))
    logger.info("  Boundary: %d, Fund: %d, Direct: %d",
                (sample["index_classification"].isin([
                    "HEDGE_FUND", "REAL_ESTATE_FUND", "STRUCTURED_CREDIT",
                    "CASH", "UNCLASSIFIED", "DIRECT_REAL_ESTATE"
                ])).sum(),
                ((sample["exposure_type"] == "FUND") & ~sample["index_classification"].isin([
                    "HEDGE_FUND", "REAL_ESTATE_FUND", "STRUCTURED_CREDIT",
                    "CASH", "UNCLASSIFIED", "DIRECT_REAL_ESTATE"
                ])).sum(),
                (sample["exposure_type"] == "DIRECT").sum())

    if dry_run:
        logger.info("  Dry run -- returning sample without LLM calls")
        sample["llm_exposure_type"] = ""
        sample["llm_asset_class"] = ""
        sample["agrees_exposure"] = ""
        sample["agrees_asset"] = ""
        return sample

    if OpenAI is None:
        logger.error("openai SDK not installed. Install with: pip install openai")
        return sample

    # Build batches (50 positions per batch to stay within context)
    import json
    import time
    batch_size = 50
    client = OpenAI()
    all_results = []

    system_prompt = """You are a financial classification expert. For each position, provide:
1. exposure_type: How the investor gains exposure.
   - DIRECT: A direct loan, bond, or equity stake in an operating company.
   - FUND: An interest in a pooled investment vehicle (LP interest, fund shares).
   - LIQUID: Government securities, money market funds, cash equivalents.

2. asset_class: What the underlying economic exposure is.
   - PRIVATE_CREDIT: Loans, bonds, or debt from/to private companies.
   - PRIVATE_EQUITY: Equity stakes in private companies.
   - REAL_ESTATE: Real estate funds, REITs, property investments.
   - STRUCTURED_CREDIT: CLOs, CDOs, ABS, securitized products.
   - HEDGE_FUND: Hedge fund interests (long/short, macro, multi-strategy, no clear PE/RE/credit signal).
   - CASH: Government bonds, treasury bills, money market.
   - OTHER: Cannot determine from available information.

Input fields:
- issuer_name: Name of the investment position.
- instrument_description: Description of the instrument type (may be empty).
- source: "bdc" (from BDC 10-K/10-Q filings) or "nport" (from N-PORT filings).
- issuer_category: CORPORATE (operating company), FUND (pooled vehicle), GOVERNMENT, or OTHER.
- asset_category: LOAN, DEBT, EQUITY_COMMON, EQUITY_PREFERRED, or OTHER.
- nport_asset_cat (N-PORT only): EC=equity common, EP=equity preferred, DBT=debt, ABS-O=other ABS, ABS-MBS=mortgage-backed, RE=real estate, OTHER=other.
- nport_issuer_type (N-PORT only): CORP=corporate, PF=private fund, RF=registered fund, SOV=sovereign, MUN=municipal.

Use ALL available fields to make your determination. Do NOT default to OTHER when structural codes provide clear signal.

Respond with JSON array. Each element: {"id": N, "exposure_type": "...", "asset_class": "..."}"""

    for batch_start in range(0, len(sample), batch_size):
        batch = sample.iloc[batch_start:batch_start + batch_size]
        positions = []
        for i, (_, row) in enumerate(batch.iterrows()):
            pos = {
                "id": batch_start + i,
                "issuer_name": str(row.get("issuer_name", "")),
                "instrument_description": str(row.get("instrument_description", "")),
                "source": str(row.get("source", "")),
                "issuer_category": str(row.get("issuer_category", "")),
                "asset_category": str(row.get("asset_category", "")),
            }
            if row.get("nport_asset_cat") and str(row["nport_asset_cat"]) != "nan":
                pos["nport_asset_cat"] = str(row["nport_asset_cat"])
            if row.get("nport_issuer_type") and str(row["nport_issuer_type"]) != "nan":
                pos["nport_issuer_type"] = str(row["nport_issuer_type"])
            positions.append(pos)

        prompt = f"Classify these {len(positions)} positions:\n\n{json.dumps(positions, indent=1)}"

        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                max_tokens=4096,
                temperature=0,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
            )
            content = response.choices[0].message.content or ""
            # Extract JSON from response
            start = content.find("[")
            end = content.rfind("]") + 1
            if start >= 0 and end > start:
                parsed = json.loads(content[start:end])
                all_results.extend(parsed)
            else:
                logger.warning("  Batch %d: no JSON array in response",
                               batch_start // batch_size + 1)
        except Exception as exc:
            logger.error("  Batch %d failed: %s", batch_start // batch_size + 1, exc)

        if batch_start + batch_size < len(sample):
            time.sleep(0.5)

    # Merge LLM results back
    llm_map = {r["id"]: r for r in all_results if isinstance(r, dict) and "id" in r}
    llm_exp = []
    llm_ac = []
    for i in range(len(sample)):
        r = llm_map.get(i, {})
        llm_exp.append(r.get("exposure_type", ""))
        llm_ac.append(r.get("asset_class", ""))

    sample["llm_exposure_type"] = llm_exp
    sample["llm_asset_class"] = llm_ac
    sample["agrees_exposure"] = sample["exposure_type"] == sample["llm_exposure_type"]
    sample["agrees_asset"] = sample["asset_class"] == sample["llm_asset_class"]

    # Log accuracy
    valid = sample[sample["llm_exposure_type"] != ""]
    if len(valid) > 0:
        exp_acc = valid["agrees_exposure"].mean() * 100
        ac_acc = valid["agrees_asset"].mean() * 100
        logger.info("  LLM agreement: exposure_type %.1f%%, asset_class %.1f%% (%d positions)",
                    exp_acc, ac_acc, len(valid))

        # Per-category breakdown for asset_class
        for cat in ["PRIVATE_CREDIT", "PRIVATE_EQUITY", "HEDGE_FUND",
                    "REAL_ESTATE", "STRUCTURED_CREDIT", "CASH", "OTHER"]:
            subset = valid[valid["asset_class"] == cat]
            if len(subset) > 0:
                acc = subset["agrees_asset"].mean() * 100
                logger.info("    %s: %.1f%% (%d positions)",
                            cat, acc, len(subset))
    else:
        logger.warning("  No LLM responses received")

    return sample


# ---------------------------------------------------------------------------
# 7. Orchestrator
# ---------------------------------------------------------------------------

def check_gav_reconciliation(
    unified_df: Optional[pd.DataFrame] = None,
    fund_financials_df: Optional[pd.DataFrame] = None,
    nport_fund_info_df: Optional[pd.DataFrame] = None,
    bdc_source_df: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """Per-quarter GAV reconciliation: compare holdings FV sum against reported values.

    For each (CIK, report_date), computes sum(fair_value) from holdings and
    compares to:
    1. investments_at_fair_value from fund_financials (preferred)
    2. total_assets from fund_financials (BDC fallback)
    3. total_assets from N-PORT fund info (N-PORT fallback)

    For BDC rows, also computes a source-reconciliation numerator from the
    raw BDC extraction artifact before the unified aggregate/indexability
    filters.  That source numerator is evidence for whether source FV exists;
    it does not make source bucket rows indexable constituents.
    """
    load_default_sources = unified_df is None
    if unified_df is None:
        if not UNIFIED_HOLDINGS_FILE.exists():
            logger.error("Unified holdings file not found")
            return pd.DataFrame()
        unified_df = pd.read_csv(UNIFIED_HOLDINGS_FILE, dtype=str)

    if fund_financials_df is None and FUND_FINANCIALS_FILE.exists():
        try:
            fund_financials_df = pd.read_csv(FUND_FINANCIALS_FILE, dtype=str)
        except Exception:
            fund_financials_df = None

    # Ensure investments_at_fair_value column exists (may be missing in older files)
    if (fund_financials_df is not None and not fund_financials_df.empty
            and "investments_at_fair_value" not in fund_financials_df.columns):
        fund_financials_df["investments_at_fair_value"] = ""

    if nport_fund_info_df is None and load_default_sources and NPORT_FUND_INFO_FILE.exists():
        try:
            nport_fund_info_df = pd.read_csv(NPORT_FUND_INFO_FILE, dtype=str)
        except Exception:
            nport_fund_info_df = None

    if bdc_source_df is None and load_default_sources and BDC_HOLDINGS_FILE.exists():
        try:
            bdc_source_df = pd.read_csv(BDC_HOLDINGS_FILE, dtype=str)
        except Exception:
            bdc_source_df = None

    con = duckdb.connect()
    con.register("holdings", unified_df)
    nport_non_indexable_ciks = {str(c).zfill(10) for c in NPORT_EXCLUDE_CIKS}
    nport_non_indexable_ciks.add("0001547580")
    nport_non_indexable_sql = ", ".join(
        f"'{c}'" for c in sorted(nport_non_indexable_ciks)
    ) or "''"

    if bdc_source_df is not None and not bdc_source_df.empty:
        bdc_aggregate_filter = _sql_is_bdc_aggregate()
        bdc_source_df = bdc_source_df.copy()
        had_investment_identifier = "investment_identifier" in bdc_source_df.columns
        for col in [
            "cik",
            "report_date",
            "period",
            "fair_value",
            "investment_identifier",
            "accession_number",
            "form_type",
            "filing_date",
        ]:
            if col not in bdc_source_df.columns:
                bdc_source_df[col] = "__missing_identifier__" if col == "investment_identifier" else ""
        if not had_investment_identifier:
            bdc_source_df["investment_identifier"] = "__missing_identifier__"
        con.register("bdc_source", bdc_source_df)
        bdc_source_cte = f"""
        bdc_source_rows AS (
            SELECT
                *,
                LPAD(CAST(cik AS VARCHAR), 10, '0') AS _cik,
                CAST(report_date AS VARCHAR) AS _report_date,
                TRY_CAST(fair_value AS DOUBLE) AS _source_fv,
                COALESCE(CAST(investment_identifier AS VARCHAR), '') AS _raw_id,
                COALESCE(lower(trim(CAST(investment_identifier AS VARCHAR))), '') AS _lower_id
            FROM bdc_source
            WHERE TRY_CAST(fair_value AS DOUBLE) IS NOT NULL
              AND TRY_CAST(report_date AS DATE) >= '2022-01-01'
              AND (
                  TRY_CAST(period AS DATE) = TRY_CAST(report_date AS DATE)
                  OR period IS NULL
                  OR CAST(period AS VARCHAR) = ''
              )
        ),
        bdc_source_current AS (
            SELECT r.* FROM bdc_source_rows r
            INNER JOIN (
                SELECT _cik, _report_date, accession_number,
                    ROW_NUMBER() OVER (
                        PARTITION BY _cik, _report_date,
                            REGEXP_REPLACE(CAST(form_type AS VARCHAR), '/A$', '')
                        ORDER BY CAST(filing_date AS VARCHAR) DESC
                    ) AS _amd_rank
                FROM bdc_source_rows
                GROUP BY _cik, _report_date, accession_number, form_type, filing_date
            ) ranked
              ON r._cik = ranked._cik
             AND r._report_date = ranked._report_date
             AND r.accession_number = ranked.accession_number
            WHERE ranked._amd_rank = 1
        ),
        bdc_source_agg AS (
            SELECT
                _cik AS cik,
                _report_date AS report_date,
                SUM(_source_fv) AS bdc_source_raw_fv,
                SUM(CASE WHEN {bdc_aggregate_filter} THEN _source_fv ELSE 0 END)
                    AS bdc_source_aggregate_filtered_fv,
                SUM(CASE WHEN NOT ({bdc_aggregate_filter}) THEN _source_fv ELSE 0 END)
                    AS bdc_source_reconciliation_fv,
                COUNT(*) AS bdc_source_reconciliation_rows,
                SUM(CASE WHEN {bdc_aggregate_filter} THEN 1 ELSE 0 END)
                    AS bdc_source_aggregate_filtered_rows
            FROM bdc_source_current
            GROUP BY _cik, _report_date
        ),
        """
    else:
        bdc_source_cte = """
        bdc_source_agg AS (
            SELECT CAST(NULL AS VARCHAR) AS cik,
                   CAST(NULL AS VARCHAR) AS report_date,
                   CAST(NULL AS DOUBLE) AS bdc_source_raw_fv,
                   CAST(NULL AS DOUBLE) AS bdc_source_aggregate_filtered_fv,
                   CAST(NULL AS DOUBLE) AS bdc_source_reconciliation_fv,
                   CAST(NULL AS BIGINT) AS bdc_source_reconciliation_rows,
                   CAST(NULL AS BIGINT) AS bdc_source_aggregate_filtered_rows
            WHERE false
        ),
        """

    # Build fund_financials CTE
    if fund_financials_df is not None and not fund_financials_df.empty:
        con.register("fund_fin", fund_financials_df)
        ff_cte = """
        ff_values AS (
            SELECT
                LPAD(CAST(cik AS VARCHAR), 10, '0') AS cik,
                CAST(report_date AS VARCHAR) AS report_date,
                TRY_CAST(investments_at_fair_value AS DOUBLE) AS inv_fv,
                TRY_CAST(total_assets AS DOUBLE) AS total_assets
            FROM fund_fin
            WHERE report_date IS NOT NULL AND report_date != ''
        ),
        """
    else:
        ff_cte = """
        ff_values AS (
            SELECT CAST(NULL AS VARCHAR) AS cik,
                   CAST(NULL AS VARCHAR) AS report_date,
                   CAST(NULL AS DOUBLE) AS inv_fv,
                   CAST(NULL AS DOUBLE) AS total_assets
            WHERE false
        ),
        """

    # Build N-PORT fund info CTE
    if (nport_fund_info_df is not None and not nport_fund_info_df.empty
            and len(nport_fund_info_df.columns) > 0):
        con.register("nport_fi", nport_fund_info_df)
        nport_cte = """
        nport_values AS (
            SELECT
                LPAD(CAST(cik AS VARCHAR), 10, '0') AS cik,
                CAST(report_date AS VARCHAR) AS report_date,
                TRY_CAST(total_assets AS DOUBLE) AS nport_total_assets
            FROM nport_fi
            WHERE total_assets IS NOT NULL AND total_assets != ''
        ),
        """
    else:
        nport_cte = """
        nport_values AS (
            SELECT CAST(NULL AS VARCHAR) AS cik,
                   CAST(NULL AS VARCHAR) AS report_date,
                   CAST(NULL AS DOUBLE) AS nport_total_assets
            WHERE false
        ),
        """

    sql = f"""
    WITH holdings_agg AS (
        SELECT
            LPAD(CAST(cik AS VARCHAR), 10, '0') AS cik,
            FIRST(entity_name) AS entity_name,
            CAST(report_date AS VARCHAR) AS report_date,
            SUM(TRY_CAST(fair_value AS DOUBLE)) AS sum_holdings_fv,
            SUM(CASE WHEN COALESCE(TRY_CAST(is_subsidiary AS INT), 0) = 0
                     THEN TRY_CAST(fair_value AS DOUBLE) ELSE 0 END)
                AS sum_holdings_fv_ex_sub,
            MAX(CASE WHEN COALESCE(TRY_CAST(is_subsidiary AS INT), 0) = 1
                     THEN 1 ELSE 0 END) AS has_subsidiary_positions,
            MAX(CASE WHEN LOWER(CAST(source AS VARCHAR)) = 'bdc'
                     THEN 1 ELSE 0 END) AS has_bdc_positions,
            MAX(CASE WHEN LOWER(CAST(source AS VARCHAR)) = 'nport'
                     THEN 1 ELSE 0 END) AS has_nport_positions
        FROM holdings
        WHERE TRY_CAST(fair_value AS DOUBLE) IS NOT NULL
          AND TRY_CAST(report_date AS DATE) >= '2022-01-01'
        GROUP BY cik, report_date
    ),
    {bdc_source_cte}
    {ff_cte}
    {nport_cte}
    joined AS (
        SELECT
            h.cik,
            h.entity_name,
            h.report_date,
            h.sum_holdings_fv,
            h.sum_holdings_fv_ex_sub,
            h.has_subsidiary_positions,
            h.has_bdc_positions,
            h.has_nport_positions,
            s.bdc_source_raw_fv,
            s.bdc_source_aggregate_filtered_fv,
            s.bdc_source_reconciliation_fv,
            s.bdc_source_reconciliation_rows,
            s.bdc_source_aggregate_filtered_rows,
            -- Reliability gate: inv_fv that is <10% or >5x of total_assets
            -- is likely partial/wrong (catches Kayne 66x, SCP 13x outliers).
            -- Corroboration: if the gate rejects inv_fv BUT holdings sum
            -- corroborates it (ratio 0.3-5.0x), use inv_fv anyway -- the
            -- fund genuinely has a small investment book relative to total
            -- assets (e.g. NEWT bank/BDC hybrid).
            CASE WHEN f.inv_fv IS NOT NULL AND f.total_assets IS NOT NULL
                      AND f.total_assets > 0
                      AND (f.inv_fv / f.total_assets < 0.1
                           OR f.inv_fv / f.total_assets > 5)
                      AND NOT (f.inv_fv > 0
                               AND h.sum_holdings_fv / f.inv_fv BETWEEN 0.3 AND 5.0)
                 THEN NULL ELSE f.inv_fv END AS inv_fv_checked,
            f.inv_fv AS inv_fv_raw,
            COALESCE(
                CASE WHEN f.inv_fv IS NOT NULL AND f.total_assets IS NOT NULL
                          AND f.total_assets > 0
                          AND (f.inv_fv / f.total_assets < 0.1
                               OR f.inv_fv / f.total_assets > 5)
                          AND NOT (f.inv_fv > 0
                                   AND h.sum_holdings_fv / f.inv_fv BETWEEN 0.3 AND 5.0)
                     THEN NULL ELSE f.inv_fv END,
                f.total_assets,
                n.nport_total_assets
            ) AS comparison_value,
            CASE
                WHEN f.inv_fv IS NOT NULL
                     AND (f.total_assets IS NULL OR f.total_assets = 0
                          OR (f.inv_fv / f.total_assets >= 0.1
                              AND f.inv_fv / f.total_assets <= 5)
                          OR (f.inv_fv > 0
                              AND h.sum_holdings_fv / f.inv_fv BETWEEN 0.3 AND 5.0))
                     THEN 'investments_at_fair_value'
                WHEN f.total_assets IS NOT NULL THEN 'total_assets_companyfacts'
                WHEN n.nport_total_assets IS NOT NULL THEN 'total_assets_nport'
                ELSE NULL
            END AS comparison_source
        FROM holdings_agg h
        LEFT JOIN bdc_source_agg s
            ON h.cik = s.cik AND h.report_date = s.report_date
        LEFT JOIN ff_values f
            ON h.cik = f.cik AND h.report_date = f.report_date
        LEFT JOIN nport_values n
            ON h.cik = n.cik AND h.report_date = n.report_date
    )
    SELECT
        cik, entity_name, report_date,
        sum_holdings_fv,
        sum_holdings_fv AS indexable_position_fv,
        sum_holdings_fv_ex_sub,
        bdc_source_reconciliation_fv,
        bdc_source_reconciliation_fv AS bdc_source_indexable_candidate_fv,
        bdc_source_raw_fv,
        bdc_source_aggregate_filtered_fv,
        GREATEST(
            COALESCE(bdc_source_reconciliation_fv, 0) - COALESCE(sum_holdings_fv, 0),
            0
        ) AS bdc_source_non_indexable_filtered_fv,
        bdc_source_reconciliation_rows,
        bdc_source_aggregate_filtered_rows,
        has_subsidiary_positions,
        CASE
            WHEN has_bdc_positions = 1 AND has_nport_positions = 0 THEN 'bdc'
            WHEN has_nport_positions = 1 AND has_bdc_positions = 0 THEN 'nport'
            WHEN has_bdc_positions = 1 AND has_nport_positions = 1 THEN 'mixed'
            ELSE ''
        END AS holdings_source,
        CASE
            WHEN has_bdc_positions = 1 AND has_nport_positions = 0 THEN 'bdc_schedule'
            WHEN has_nport_positions = 1 AND has_bdc_positions = 0 THEN 'nport_private_markets_filter'
            WHEN has_bdc_positions = 1 AND has_nport_positions = 1 THEN 'mixed_holdings'
            ELSE ''
        END AS holdings_scope,
        comparison_value,
        comparison_source,
        comparison_source AS comparison_denominator_source,
        CASE
            WHEN comparison_source = 'investments_at_fair_value' THEN 'investment_fair_value'
            WHEN comparison_source IN ('total_assets_companyfacts', 'total_assets_nport') THEN 'full_fund_assets'
            ELSE ''
        END AS denominator_scope,
        CASE
            WHEN comparison_source = 'investments_at_fair_value' THEN 'investment_fair_value'
            WHEN comparison_source IN ('total_assets_companyfacts', 'total_assets_nport') THEN 'full_fund_assets'
            ELSE ''
        END AS comparison_denominator_scope,
        CASE
            WHEN has_bdc_positions = 1 AND has_nport_positions = 0 THEN 'GAV_BDC01'
            WHEN has_nport_positions = 1 AND has_bdc_positions = 0 THEN 'GAV_NPORT01'
            ELSE 'GAV_SCOPE01'
        END AS gav_rule_id,
        CASE WHEN comparison_value > 0
             THEN ROUND(sum_holdings_fv / comparison_value, 4)
        END AS gav_ratio,
        CASE WHEN comparison_value > 0 AND bdc_source_reconciliation_fv IS NOT NULL
             THEN ROUND(bdc_source_reconciliation_fv / comparison_value, 4)
        END AS bdc_source_reconciliation_ratio,
        -- Adjusted ratio: use ex-sub numerator when CIK has subsidiary positions
        CASE WHEN comparison_value > 0 AND has_subsidiary_positions = 1
             THEN ROUND(sum_holdings_fv_ex_sub / comparison_value, 4)
             WHEN comparison_value > 0
             THEN ROUND(sum_holdings_fv / comparison_value, 4)
        END AS gav_ratio_adjusted,
        CASE
            WHEN comparison_value IS NULL THEN 'no_comparison'
            WHEN has_nport_positions = 1
                 AND has_bdc_positions = 0
                 AND cik IN ({nport_non_indexable_sql})
                THEN 'non_indexable_denominator'
            WHEN comparison_value > 0
                 AND (CASE WHEN has_subsidiary_positions = 1
                           THEN sum_holdings_fv_ex_sub
                           ELSE sum_holdings_fv END)
                     / comparison_value > 1.2 THEN 'over_coverage'
            WHEN comparison_value > 0
                 AND (CASE WHEN has_subsidiary_positions = 1
                           THEN sum_holdings_fv_ex_sub
                           ELSE sum_holdings_fv END)
                     / comparison_value < 0.3 THEN 'under_coverage'
            ELSE 'ok'
        END AS flag,
        CASE
            WHEN has_bdc_positions != 1 THEN ''
            WHEN comparison_value IS NULL THEN 'no_comparison'
            WHEN bdc_source_reconciliation_fv IS NULL THEN 'no_source_fv'
            WHEN comparison_value > 0
                 AND bdc_source_reconciliation_fv / comparison_value > 1.2
                THEN 'over_coverage'
            WHEN comparison_value > 0
                 AND bdc_source_reconciliation_fv / comparison_value < 0.3
                THEN 'under_coverage'
            ELSE 'ok'
        END AS bdc_source_reconciliation_flag,
        CASE
            WHEN has_bdc_positions = 1
                 AND comparison_value > 0
                 AND bdc_source_reconciliation_fv IS NOT NULL
                 AND bdc_source_reconciliation_fv / comparison_value BETWEEN 0.3 AND 1.2
                 AND (CASE WHEN has_subsidiary_positions = 1
                           THEN sum_holdings_fv_ex_sub
                           ELSE sum_holdings_fv END) / comparison_value < 0.3
                THEN 'source_fv_present_not_indexable'
            WHEN has_bdc_positions = 1
                 AND comparison_value > 0
                 AND (bdc_source_reconciliation_fv IS NULL
                      OR bdc_source_reconciliation_fv / comparison_value < 0.3)
                THEN 'source_fv_missing_or_under_extracted'
            WHEN has_bdc_positions = 1 THEN 'indexable_fv_reconciled'
            WHEN has_nport_positions = 1
                 AND has_bdc_positions = 0
                 AND cik IN ({nport_non_indexable_sql})
                THEN 'non_indexable_denominator'
            ELSE ''
        END AS gav_evidence_scope
    FROM joined
    ORDER BY cik, report_date
    """

    result = con.execute(sql).fetchdf()
    con.close()

    if not result.empty:
        with_comparison = result[result["comparison_source"].notna()
                                 & (result["comparison_source"] != "")]
        if len(with_comparison) > 0:
            ratio = pd.to_numeric(with_comparison["gav_ratio"], errors="coerce").dropna()
            adj_ratio = pd.to_numeric(
                with_comparison["gav_ratio_adjusted"], errors="coerce"
            ).dropna()
            if len(ratio) > 0:
                logger.info("  GAV reconciliation: %d CIK-quarters with comparison, "
                            "median ratio %.3f (adjusted %.3f)",
                            len(ratio), ratio.median(),
                            adj_ratio.median() if len(adj_ratio) > 0 else 0)
                in_range = ((adj_ratio >= 0.8) & (adj_ratio <= 1.2)).sum()
                logger.info("  GAV within 0.8-1.2x: %d/%d (%.1f%%)",
                            in_range, len(adj_ratio),
                            100 * in_range / len(adj_ratio) if len(adj_ratio) else 0)
                over = (with_comparison["flag"] == "over_coverage").sum()
                under = (with_comparison["flag"] == "under_coverage").sum()
                if over > 0 or under > 0:
                    logger.warning("  GAV outliers: %d over_coverage, %d under_coverage",
                                   over, under)
                # Log subsidiary impact
                sub_ciks = with_comparison[
                    with_comparison["has_subsidiary_positions"].astype(str) == "1"
                ]
                if len(sub_ciks) > 0:
                    logger.info("  GAV subsidiary adjustment: %d CIK-quarters affected",
                                len(sub_ciks))
        else:
            logger.info("  GAV reconciliation: no comparison values available")

    return result


# ---------------------------------------------------------------------------
# 8. Pct of net assets sum
# ---------------------------------------------------------------------------

def check_pct_of_net_assets_sum(df: pd.DataFrame) -> pd.DataFrame:
    """Sum pct_of_net_assets per (CIK, report_date) for BDC positions.

    BDCs are levered, so the sum should typically be 100-170%.
    Catches subtotal leakage (inflates sum) and missing positions (deflates sum).

    Flag logic:
      - pct_sum > 200 -> high_pct_sum
      - pct_sum < 50  -> low_pct_sum
      - else           -> ok

    Returns DataFrame with columns: cik, report_date, pct_sum, position_count,
    total_fv, flag
    """
    empty = pd.DataFrame(columns=[
        "cik", "report_date", "pct_sum", "position_count", "total_fv", "flag",
    ])

    if df.empty or "source" not in df.columns:
        return empty

    if not (df["source"] == "bdc").any():
        return empty

    con = duckdb.connect()
    con.register("holdings", df)

    sql = """
    WITH agg AS (
        SELECT cik, report_date,
            SUM(TRY_CAST(pct_of_net_assets AS DOUBLE)) AS pct_sum,
            COUNT(*) AS position_count,
            SUM(TRY_CAST(fair_value AS DOUBLE)) AS total_fv
        FROM holdings
        WHERE source = 'bdc'
          AND TRY_CAST(pct_of_net_assets AS DOUBLE) IS NOT NULL
          AND TRY_CAST(pct_of_net_assets AS DOUBLE) != 0
        GROUP BY cik, report_date
        HAVING COUNT(*) >= 5
    )
    SELECT *,
        CASE
            WHEN pct_sum > 200 THEN 'high_pct_sum'
            WHEN pct_sum < 50 THEN 'low_pct_sum'
            ELSE 'ok'
        END AS flag
    FROM agg
    ORDER BY cik, report_date
    """

    result = con.execute(sql).fetchdf()
    con.close()

    if result.empty:
        return empty

    if len(result) > 0:
        high = (result["flag"] == "high_pct_sum").sum()
        low = (result["flag"] == "low_pct_sum").sum()
        ok = (result["flag"] == "ok").sum()
        logger.info("  Pct-of-net-assets sum: %d CIK-quarters (%d ok, %d high, %d low)",
                    len(result), ok, high, low)
        if high > 0:
            logger.warning("  %d CIK-quarters with pct_sum > 200%% (possible subtotal leak)",
                          high)

    return result


# ---------------------------------------------------------------------------
# 9. Position count stability
# ---------------------------------------------------------------------------

def check_position_count_stability(df: pd.DataFrame) -> pd.DataFrame:
    """QoQ position count stability per CIK.

    Position count shouldn't jump >2.5x or drop <0.4x without M&A.
    Also flags count_fv_divergence: count changes >2x but FV is stable
    (count_ratio >2 AND fv_ratio BETWEEN 0.7 AND 1.3), which suggests
    subtotal rows crept in or a parsing issue doubled positions.

    Returns DataFrame with columns: cik, report_date, position_count,
    total_fv, prev_count, prev_fv, count_ratio, fv_ratio, flag
    """
    empty = pd.DataFrame(columns=[
        "cik", "report_date", "position_count", "total_fv",
        "prev_count", "prev_fv", "count_ratio", "fv_ratio", "flag",
    ])

    if df.empty or "fair_value" not in df.columns:
        return empty

    con = duckdb.connect()
    con.register("holdings", df)

    sql = """
    WITH quarterly AS (
        SELECT cik, report_date,
            COUNT(*) AS position_count,
            SUM(TRY_CAST(fair_value AS DOUBLE)) AS total_fv
        FROM holdings
        WHERE TRY_CAST(fair_value AS DOUBLE) IS NOT NULL
        GROUP BY cik, report_date
    ),
    with_lag AS (
        SELECT *,
            LAG(position_count) OVER (PARTITION BY cik ORDER BY report_date) AS prev_count,
            LAG(total_fv) OVER (PARTITION BY cik ORDER BY report_date) AS prev_fv
        FROM quarterly
    ),
    flagged AS (
        SELECT *,
            position_count * 1.0 / NULLIF(prev_count, 0) AS count_ratio,
            total_fv / NULLIF(prev_fv, 0) AS fv_ratio,
            CASE
                WHEN prev_count IS NULL THEN NULL
                WHEN (position_count * 1.0 / NULLIF(prev_count, 0) > 2.0)
                     AND (total_fv / NULLIF(prev_fv, 0) BETWEEN 0.7 AND 1.3)
                     THEN 'count_fv_divergence'
                WHEN position_count * 1.0 / NULLIF(prev_count, 0) > 2.5
                     OR position_count * 1.0 / NULLIF(prev_count, 0) < 0.4
                     THEN 'unstable_count'
                ELSE 'ok'
            END AS flag
        FROM with_lag
    )
    SELECT * FROM flagged
    WHERE prev_count IS NOT NULL
    ORDER BY cik, report_date
    """

    result = con.execute(sql).fetchdf()
    con.close()

    if result.empty:
        return empty

    if len(result) > 0:
        unstable = (result["flag"] == "unstable_count").sum()
        diverge = (result["flag"] == "count_fv_divergence").sum()
        ok = (result["flag"] == "ok").sum()
        logger.info("  Position count stability: %d transitions (%d ok, %d unstable, %d divergence)",
                    len(result), ok, unstable, diverge)
        if unstable > 0:
            logger.warning("  %d transitions with count ratio outside 0.4-2.5x", unstable)
        if diverge > 0:
            logger.warning("  %d transitions with count >2x but FV stable (possible subtotal leak)",
                          diverge)

    return result


# ---------------------------------------------------------------------------
# 10. Income yield consistency
# ---------------------------------------------------------------------------

def check_income_yield_consistency(
    unified_df: Optional[pd.DataFrame] = None,
    fee_uplift_path=None,
) -> pd.DataFrame:
    """Check income yield consistency using fee_uplift.csv.

    Derives yield_ratio = total_income_yield / median_all_in_coupon from
    fee_uplift.csv. This tests rate and principal fields against fund-level
    income, completely independent from FV-based GAV.

    Only covers BDCs with DL positions and fund income data (~128 CIKs).

    Flag logic:
      - yield_ratio < 0.5 or > 2.5 -> yield_outlier
      - else                        -> ok

    Returns DataFrame with columns: cik, total_income_yield,
    median_all_in_coupon, yield_ratio, flag
    """
    empty = pd.DataFrame(columns=[
        "cik", "total_income_yield", "median_all_in_coupon",
        "yield_ratio", "flag",
    ])

    fee_path = fee_uplift_path if fee_uplift_path is not None else FEE_UPLIFT_FILE

    if not fee_path.exists():
        logger.info("  Income yield: fee_uplift file not found, skipping")
        return empty

    try:
        fee_df = pd.read_csv(fee_path, dtype=str)
    except Exception:
        logger.warning("  Income yield: failed to read fee_uplift file")
        return empty

    if fee_df.empty:
        return empty

    # Need both columns to compute ratio
    if "total_income_yield" not in fee_df.columns or "median_all_in_coupon" not in fee_df.columns:
        logger.info("  Income yield: required columns not in fee_uplift, skipping")
        return empty

    con = duckdb.connect()
    con.register("fee", fee_df)

    sql = """
    SELECT
        cik,
        total_income_yield,
        median_all_in_coupon,
        CASE WHEN TRY_CAST(median_all_in_coupon AS DOUBLE) > 0
             THEN ROUND(TRY_CAST(total_income_yield AS DOUBLE)
                        / TRY_CAST(median_all_in_coupon AS DOUBLE), 4)
        END AS yield_ratio,
        CASE
            WHEN TRY_CAST(median_all_in_coupon AS DOUBLE) IS NULL
                 OR TRY_CAST(median_all_in_coupon AS DOUBLE) = 0
                 THEN 'no_coupon_data'
            WHEN TRY_CAST(total_income_yield AS DOUBLE)
                 / TRY_CAST(median_all_in_coupon AS DOUBLE) < 0.5
                 THEN 'yield_outlier'
            WHEN TRY_CAST(total_income_yield AS DOUBLE)
                 / TRY_CAST(median_all_in_coupon AS DOUBLE) > 2.5
                 THEN 'yield_outlier'
            ELSE 'ok'
        END AS flag
    FROM fee
    WHERE TRY_CAST(total_income_yield AS DOUBLE) IS NOT NULL
    ORDER BY cik
    """

    result = con.execute(sql).fetchdf()
    con.close()

    if result.empty:
        return empty

    if len(result) > 0:
        outliers = (result["flag"] == "yield_outlier").sum()
        ok = (result["flag"] == "ok").sum()
        no_data = (result["flag"] == "no_coupon_data").sum()
        logger.info("  Income yield consistency: %d CIKs (%d ok, %d outliers, %d no coupon data)",
                    len(result), ok, outliers, no_data)
        if outliers > 0:
            logger.warning("  %d CIKs with yield_ratio outside 0.5-2.5x", outliers)

    return result


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

    # 6. Classification cross-reference (free, runs every time)
    logger.info("Validating classification cross-reference...")
    class_val = validate_classification(unified_df)
    reports["classification_validation"] = class_val
    if len(class_val) > 0:
        class_val.to_csv(CLASSIFICATION_VALIDATION_FILE, index=False)
        logger.info("  Saved %s", CLASSIFICATION_VALIDATION_FILE.name)

    # 7. GAV reconciliation
    logger.info("Running GAV reconciliation...")
    gav = check_gav_reconciliation(unified_df)
    reports["gav_reconciliation"] = gav
    if len(gav) > 0:
        gav.to_csv(HOLDINGS_GAV_RECONCILIATION_FILE, index=False)
        logger.info("  Saved %s", HOLDINGS_GAV_RECONCILIATION_FILE.name)

    # 8. Pct of net assets sum
    logger.info("Checking pct_of_net_assets sum...")
    pct_sum = check_pct_of_net_assets_sum(unified_df)
    reports["pct_sum"] = pct_sum
    if len(pct_sum) > 0:
        pct_sum.to_csv(HOLDINGS_PCT_SUM_FILE, index=False)
        logger.info("  Saved %s", HOLDINGS_PCT_SUM_FILE.name)

    # 9. Position count stability
    logger.info("Checking position count stability...")
    stability = check_position_count_stability(unified_df)
    reports["count_stability"] = stability
    if len(stability) > 0:
        stability.to_csv(HOLDINGS_COUNT_STABILITY_FILE, index=False)
        logger.info("  Saved %s", HOLDINGS_COUNT_STABILITY_FILE.name)

    # 10. Income yield consistency
    logger.info("Checking income yield consistency...")
    income = check_income_yield_consistency(unified_df)
    reports["income_yield"] = income
    if len(income) > 0:
        income.to_csv(HOLDINGS_INCOME_YIELD_FILE, index=False)
        logger.info("  Saved %s", HOLDINGS_INCOME_YIELD_FILE.name)

    # 11. Column-level quality contract + unified issue schema
    logger.info("Running column-level quality validation...")
    try:
        from pipeline.column_validation import run_column_quality_validation

        quality_reports = run_column_quality_validation(
            unified_df,
            existing_reports=reports,
        )
        reports.update(quality_reports)

        row_issues = quality_reports["row_validation_issues"]
        column_metrics = quality_reports["column_quality_metrics"]
        quality_summary = quality_reports["data_quality_metrics"]
        residual_summary = quality_reports["validate_all_residual_summary"]

        row_issues.to_csv(ROW_VALIDATION_ISSUES_FILE, index=False)
        logger.info("  Saved %s", ROW_VALIDATION_ISSUES_FILE.name)
        column_metrics.to_csv(COLUMN_QUALITY_METRICS_FILE, index=False)
        logger.info("  Saved %s", COLUMN_QUALITY_METRICS_FILE.name)
        quality_summary.to_csv(DATA_QUALITY_METRICS_FILE, index=False)
        logger.info("  Saved %s", DATA_QUALITY_METRICS_FILE.name)
        residual_summary.to_csv(VALIDATE_ALL_RESIDUAL_SUMMARY_FILE, index=False)
        logger.info("  Saved %s", VALIDATE_ALL_RESIDUAL_SUMMARY_FILE.name)
    except Exception as exc:
        logger.error("Column-level quality validation failed: %s", exc,
                     exc_info=True)

    return reports
