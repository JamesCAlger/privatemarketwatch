"""Unified private markets holdings -- combines BDC and N-PORT data.

Produces a single private_markets_holdings.csv with standardised schema,
asset/issuer/index classification, and parsed identifiers suitable for
index construction and dashboard analytics.
"""

import logging
import time
from pathlib import Path
from typing import Optional, Union

import duckdb
import pandas as pd

from pipeline import classification, staging_bdc, staging_nport
from pipeline.config import (
    BDC_HOLDINGS_FILE,
    COMBINED_UNIVERSE_FILE,
    ENTITY_LOOKUP_FILE,
    FUND_FINANCIALS_FILE,
    FUND_STRATEGY_CORRECTION_CANDIDATES_FILE,
    IDENTIFIER_EXTRACTION_LOOKUP_FILE,
    NPORT_EXCLUDE_CIKS,
    NPORT_HOLDINGS_FILE,
    ROW_CORRECTIONS_FILE,
    UNIFIED_HOLDINGS_FILE,
    UNIVERSE_ORPHAN_HOLDINGS_FILE,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Unified output column order
UNIFIED_COLUMNS = [
    # Identity
    "source", "cik", "entity_name", "accession_number",
    "filing_date", "report_date",
    # Holding identification
    "issuer_name", "instrument_description",
    # Identifiers (N-PORT only)
    "cusip", "isin", "lei", "ticker",
    # Valuation
    "fair_value", "cost", "pct_of_net_assets",
    "shares_held", "principal_amount",
    # Classification
    "asset_category", "issuer_category", "index_classification",
    "exposure_type", "asset_class",
    "fair_value_level",
    # Rate/spread
    "interest_rate", "basis_spread", "reference_rate_type",
    "coupon_type", "pik_rate",
    # Debt details
    "maturity_date",
    # Source-specific (BDC)
    "bdc_investment_identifier", "bdc_form_type", "bdc_dimensions_raw",
    "bdc_unrealized_gain_loss",
    # Source-specific (N-PORT)
    "nport_holding_id", "nport_series_name", "nport_series_id",
    "nport_asset_cat", "nport_issuer_type", "nport_payoff_profile",
    "nport_investment_country", "nport_is_restricted", "nport_quarter",
    "nport_is_default", "nport_are_interest_payments_in_arrears",
    "nport_is_paid_in_kind", "nport_currency_code",
    "nport_liquidity_classification",
    # Subsidiary flag (BDC only -- nonconsolidated JV/subsidiary positions)
    "is_subsidiary",
    # Entity resolution (populated by --entities step)
    "entity_id", "canonical_name",
    # LLM-extracted fields (populated by --extract step)
    "extracted_industry",
    # GICS classification (populated by --classify-gics step)
    "gics_sub_industry",
    # Position tracking (populated by --returns step)
    "position_id",
]

ORPHAN_HOLDINGS_COLUMNS = [
    "cik", "entity_name", "source", "first_report_date", "last_report_date",
    "row_count", "fair_value", "reason",
]


def _normalize_cik_series(series: pd.Series) -> pd.Series:
    return (
        series.astype(str)
        .str.replace(r"[^0-9]", "", regex=True)
        .str.zfill(10)
    )


def _write_empty_orphan_report(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(columns=ORPHAN_HOLDINGS_COLUMNS).to_csv(path, index=False)


def _apply_universe_gate(
    df: pd.DataFrame,
    universe_path: Optional[Path] = None,
    orphan_path: Optional[Path] = None,
) -> pd.DataFrame:
    """Remove holdings for CIKs outside combined_universe and write review residuals."""
    path = universe_path or (UNIFIED_HOLDINGS_FILE.parent / COMBINED_UNIVERSE_FILE.name)
    out_path = orphan_path or (UNIFIED_HOLDINGS_FILE.parent / UNIVERSE_ORPHAN_HOLDINGS_FILE.name)
    if df.empty:
        _write_empty_orphan_report(out_path)
        return df
    if not path.exists():
        logger.warning("Combined universe file not found; skipping universe gate: %s", path)
        _write_empty_orphan_report(out_path)
        return df

    universe = pd.read_csv(path, dtype=str)
    if "cik" not in universe.columns:
        logger.warning("Combined universe file missing cik column; skipping universe gate: %s", path)
        _write_empty_orphan_report(out_path)
        return df

    allowed = set(_normalize_cik_series(universe["cik"]))
    gated = df.copy()
    gated["_norm_cik"] = _normalize_cik_series(gated["cik"])
    gated["cik"] = gated["_norm_cik"]
    orphan_mask = ~gated["_norm_cik"].isin(allowed)
    orphan_rows = gated[orphan_mask].copy()

    if orphan_rows.empty:
        _write_empty_orphan_report(out_path)
        return gated.drop(columns=["_norm_cik"])

    orphan_rows["fair_value"] = pd.to_numeric(orphan_rows["fair_value"], errors="coerce")
    orphan_summary = (
        orphan_rows.groupby(["_norm_cik", "entity_name", "source"], dropna=False)
        .agg(
            first_report_date=("report_date", "min"),
            last_report_date=("report_date", "max"),
            row_count=("source", "size"),
            fair_value=("fair_value", "sum"),
        )
        .reset_index()
        .rename(columns={"_norm_cik": "cik"})
    )
    orphan_summary["reason"] = "cik_absent_from_combined_universe"
    orphan_summary = orphan_summary[ORPHAN_HOLDINGS_COLUMNS]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    orphan_summary.to_csv(out_path, index=False)

    logger.warning(
        "Universe gate removed %d holdings across %d CIK/source groups; review %s",
        len(orphan_rows), len(orphan_summary), out_path.name,
    )
    return gated[~orphan_mask].drop(columns=["_norm_cik"]).reset_index(drop=True)

def _stabilize_classification(df: pd.DataFrame) -> pd.DataFrame:
    """Stabilize QoQ classification flips using 2x majority rule.

    For each position-level group that has multiple distinct values for
    index_classification (or exposure_type / asset_class), if the most frequent
    value has >= 2x the quarter-count of the second most frequent, override all
    minority rows to the majority value.

    This prevents spurious flips caused by BDC identifier format changes between
    filings (e.g., pipe vs comma delimiters, 10-K vs 10-Q naming differences).
    Stabilization is intentionally keyed below borrower level so a loan,
    common equity stake, and preferred equity stake in the same borrower do not
    overwrite each other's classifications.
    """
    if df.empty:
        return df

    con = duckdb.connect()
    con.register("src", df)

    # Build stabilization CTEs for all three classification columns
    cte_parts = []
    select_overrides = []
    join_clauses = []

    for i, col in enumerate(("index_classification", "exposure_type", "asset_class")):
        alias = f"_stab{i}"
        cte_parts.append(f"""
        {alias}_base AS (
            SELECT *,
                regexp_replace(
                    lower(trim(COALESCE(CAST(issuer_name AS VARCHAR), ''))),
                    '[^a-z0-9]+', ' ', 'g'
                ) AS _stab_issuer,
                regexp_replace(
                    lower(trim(COALESCE(CAST(instrument_description AS VARCHAR), ''))),
                    '[^a-z0-9]+', ' ', 'g'
                ) AS _stab_instrument,
                COALESCE(CAST(source AS VARCHAR), '') AS _stab_source,
                COALESCE(CAST(asset_category AS VARCHAR), '') AS _stab_asset,
                COALESCE(CAST(issuer_category AS VARCHAR), '') AS _stab_issuer_cat
            FROM src
        ),
        {alias}_counts AS (
            SELECT cik, _stab_source, _stab_issuer, _stab_instrument,
                   _stab_asset, _stab_issuer_cat,
                   CAST({col} AS VARCHAR) AS cls, COUNT(*) AS n_q
            FROM {alias}_base
            WHERE {col} IS NOT NULL
              AND CAST({col} AS VARCHAR) != ''
            GROUP BY 1, 2, 3, 4, 5, 6, 7
        ),
        {alias}_ranked AS (
            SELECT *,
                ROW_NUMBER() OVER (
                    PARTITION BY cik, _stab_source, _stab_issuer,
                        _stab_instrument, _stab_asset, _stab_issuer_cat
                    ORDER BY n_q DESC, cls
                ) AS rn
            FROM {alias}_counts
        ),
        {alias}_stable AS (
            SELECT r1.cik, r1._stab_source, r1._stab_issuer,
                   r1._stab_instrument, r1._stab_asset,
                   r1._stab_issuer_cat, r1.cls AS stable_val
            FROM {alias}_ranked r1
            JOIN {alias}_ranked r2
              ON r1.cik = r2.cik
             AND r1._stab_source = r2._stab_source
             AND r1._stab_issuer = r2._stab_issuer
             AND r1._stab_instrument = r2._stab_instrument
             AND r1._stab_asset = r2._stab_asset
             AND r1._stab_issuer_cat = r2._stab_issuer_cat
             AND r2.rn = 2
            WHERE r1.rn = 1
              AND r1.n_q >= 2 * r2.n_q
        )""")
        select_overrides.append(
            f"COALESCE({alias}.stable_val, CAST(s.{col} AS VARCHAR)) AS {col}"
        )
        join_clauses.append(
            f"LEFT JOIN {alias}_stable {alias}"
            f" ON s.cik = {alias}.cik"
            f" AND COALESCE(CAST(s.source AS VARCHAR), '') = {alias}._stab_source"
            f" AND regexp_replace(lower(trim(COALESCE(CAST(s.issuer_name AS VARCHAR), ''))), '[^a-z0-9]+', ' ', 'g') = {alias}._stab_issuer"
            f" AND regexp_replace(lower(trim(COALESCE(CAST(s.instrument_description AS VARCHAR), ''))), '[^a-z0-9]+', ' ', 'g') = {alias}._stab_instrument"
            f" AND COALESCE(CAST(s.asset_category AS VARCHAR), '') = {alias}._stab_asset"
            f" AND COALESCE(CAST(s.issuer_category AS VARCHAR), '') = {alias}._stab_issuer_cat"
        )

    # Build list of columns to pass through (everything except the 3 we override)
    override_set = {"index_classification", "exposure_type", "asset_class"}
    pass_cols = [f"s.{c}" for c in UNIFIED_COLUMNS if c not in override_set]

    sql = "WITH " + ",".join(cte_parts) + f"""
    SELECT {', '.join(pass_cols)},
           {', '.join(select_overrides)}
    FROM src s
    {chr(10).join(join_clauses)}
    """

    result = con.execute(sql).fetchdf()

    # Log stabilization impact
    for col in ("index_classification", "exposure_type", "asset_class"):
        changed = (df[col].astype(str) != result[col].astype(str)).sum()
        if changed > 0:
            logger.info("  Classification stabilization: %d rows changed for %s",
                        changed, col)

    con.close()

    # Restore column order
    result = result[UNIFIED_COLUMNS]
    return result


def _restore_deterministic_classification_rules(df: pd.DataFrame) -> pd.DataFrame:
    """Reapply high-confidence deterministic rules after QoQ stabilization.

    Stabilization is useful for noisy issuer/instrument parsing, but it should
    not erase explicit current-row signals such as structured-credit keywords
    or BDC fund-vehicle names.
    """
    if df.empty:
        return df

    con = duckdb.connect()
    con.register("src", df)

    idx_case = classification._sql_classify_index()
    asset_class_case = classification._sql_classify_asset_class()
    sc_kw = classification._sql_keyword_check(
        "_combined_fund_text",
        classification._STRUCTURED_CREDIT_KEYWORDS,
    )
    bdc_vehicle_fund = classification._sql_is_bdc_vehicle_fund()
    restore_predicate = f"({sc_kw} OR {bdc_vehicle_fund})"

    override_set = {"index_classification", "asset_class"}
    pass_cols = [f"s.{c}" for c in UNIFIED_COLUMNS if c not in override_set]
    sql = f"""
    WITH keyed AS (
        SELECT *,
            COALESCE(lower(trim(issuer_name)), '') || ' ' ||
            COALESCE(lower(trim(instrument_description)), '') AS _combined_fund_text
        FROM src
    ),
    reclassified AS (
        SELECT *,
            {idx_case} AS _rule_index_classification,
            {asset_class_case} AS _rule_asset_class,
            {restore_predicate} AS _restore_classification
        FROM keyed
    )
    SELECT {', '.join(pass_cols)},
           CASE WHEN _restore_classification
                THEN _rule_index_classification
                ELSE CAST(s.index_classification AS VARCHAR)
           END AS index_classification,
           CASE WHEN _restore_classification
                THEN _rule_asset_class
                ELSE CAST(s.asset_class AS VARCHAR)
           END AS asset_class
    FROM reclassified s
    """

    result = con.execute(sql).fetchdf()
    con.close()

    for col in ("index_classification", "asset_class"):
        changed = (df[col].astype(str) != result[col].astype(str)).sum()
        if changed > 0:
            logger.info("  Deterministic classification restore: %d rows changed for %s",
                        changed, col)

    result = result[UNIFIED_COLUMNS]
    return result


# ---------------------------------------------------------------------------
# pct_of_net_assets correction for multi-entity BDCs
# ---------------------------------------------------------------------------


def _correct_pct_of_net_assets(df: pd.DataFrame) -> pd.DataFrame:
    """Correct pct_of_net_assets for multi-entity BDCs using consolidated net_assets.

    Multi-entity BDCs (holding companies with multiple subsidiaries) report
    pct_of_net_assets per sub-entity rather than consolidated, causing
    pct_sum per CIK-quarter to reach 200-5000%.  Where consolidated
    net_assets is available from fund_financials.csv, recalculate
    pct_of_net_assets = fair_value / net_assets * 100.
    """
    if not FUND_FINANCIALS_FILE.exists():
        logger.info("pct_of_net_assets correction: no fund_financials file, skipping")
        return df

    con = duckdb.connect()
    con.register("holdings", df)
    ff_path = str(FUND_FINANCIALS_FILE).replace("\\", "/")

    # Step 1: Find BDC CIK-quarters with pct_sum > 200%
    # Step 2: Join to fund_financials for net_assets
    # Step 3: Recalculate pct_of_net_assets where possible
    sql = f"""
    WITH pct_sums AS (
        SELECT cik, report_date,
               SUM(TRY_CAST(pct_of_net_assets AS DOUBLE)) AS pct_sum
        FROM holdings
        WHERE source = 'bdc'
          AND pct_of_net_assets IS NOT NULL
          AND CAST(pct_of_net_assets AS VARCHAR) != ''
        GROUP BY cik, report_date
    ),
    high_pct AS (
        SELECT cik, report_date, pct_sum
        FROM pct_sums
        WHERE pct_sum > 200
    ),
    ff AS (
        SELECT LPAD(CAST(cik AS VARCHAR), 10, '0') AS cik,
               CAST(report_date AS VARCHAR) AS report_date,
               TRY_CAST(net_assets AS DOUBLE) AS net_assets
        FROM read_csv_auto('{ff_path}', header=true, all_varchar=true)
        WHERE net_assets IS NOT NULL
          AND CAST(net_assets AS VARCHAR) != ''
          AND TRY_CAST(net_assets AS DOUBLE) > 0
    ),
    -- Total FV per CIK-quarter to sanity-check net_assets
    fv_totals AS (
        SELECT cik, report_date,
               SUM(TRY_CAST(fair_value AS DOUBLE)) AS total_fv
        FROM holdings
        WHERE source = 'bdc'
          AND TRY_CAST(fair_value AS DOUBLE) IS NOT NULL
        GROUP BY cik, report_date
    ),
    corrections AS (
        SELECT h.cik, h.report_date, ff.net_assets
        FROM high_pct h
        INNER JOIN ff ON h.cik = ff.cik AND h.report_date = ff.report_date
        INNER JOIN fv_totals fv ON h.cik = fv.cik AND h.report_date = fv.report_date
        -- Guard: reject net_assets that would make pct_sum worse (higher)
        -- than the original.  If net_assets is implausibly small (e.g. $1M
        -- against $335M in holdings), the recalculated pct_sum would be
        -- enormous and the correction is skipped.
        WHERE (fv.total_fv / ff.net_assets * 100) < h.pct_sum
    )
    SELECT h.* EXCLUDE (pct_of_net_assets),
        CASE
            WHEN c.net_assets IS NOT NULL
                 AND TRY_CAST(h.fair_value AS DOUBLE) IS NOT NULL
                 AND TRY_CAST(h.fair_value AS DOUBLE) != 0
            THEN TRY_CAST(h.fair_value AS DOUBLE) / c.net_assets * 100
            ELSE TRY_CAST(h.pct_of_net_assets AS DOUBLE)
        END AS pct_of_net_assets
    FROM holdings h
    LEFT JOIN corrections c
        ON h.cik = c.cik AND h.report_date = c.report_date
        AND h.source = 'bdc'
    """

    result = con.execute(sql).fetchdf()

    # Log stats
    try:
        stats = con.execute(f"""
        WITH pct_sums AS (
            SELECT cik, report_date,
                   SUM(TRY_CAST(pct_of_net_assets AS DOUBLE)) AS pct_sum
            FROM holdings
            WHERE source = 'bdc'
              AND pct_of_net_assets IS NOT NULL
              AND CAST(pct_of_net_assets AS VARCHAR) != ''
            GROUP BY cik, report_date
        ),
        high_pct AS (
            SELECT cik, report_date FROM pct_sums WHERE pct_sum > 200
        ),
        ff AS (
            SELECT LPAD(CAST(cik AS VARCHAR), 10, '0') AS cik,
                   CAST(report_date AS VARCHAR) AS report_date,
                   TRY_CAST(net_assets AS DOUBLE) AS net_assets
            FROM read_csv_auto('{ff_path}', header=true, all_varchar=true)
            WHERE net_assets IS NOT NULL
              AND CAST(net_assets AS VARCHAR) != ''
              AND TRY_CAST(net_assets AS DOUBLE) > 0
        ),
        fv_totals AS (
            SELECT cik, report_date,
                   SUM(TRY_CAST(fair_value AS DOUBLE)) AS total_fv
            FROM holdings
            WHERE source = 'bdc'
              AND TRY_CAST(fair_value AS DOUBLE) IS NOT NULL
            GROUP BY cik, report_date
        ),
        correctable AS (
            SELECT h.cik, h.report_date
            FROM high_pct h
            INNER JOIN ff ON h.cik = ff.cik AND h.report_date = ff.report_date
            INNER JOIN fv_totals fv ON h.cik = fv.cik AND h.report_date = fv.report_date
            INNER JOIN pct_sums ps ON h.cik = ps.cik AND h.report_date = ps.report_date
            WHERE (fv.total_fv / ff.net_assets * 100) < ps.pct_sum
        ),
        affected_rows AS (
            SELECT COUNT(*) AS n
            FROM holdings h
            INNER JOIN correctable c ON h.cik = c.cik AND h.report_date = c.report_date
            WHERE h.source = 'bdc'
        )
        SELECT
            (SELECT COUNT(*) FROM high_pct) AS n_high_pct,
            (SELECT COUNT(*) FROM correctable) AS n_correctable,
            (SELECT n FROM affected_rows) AS n_rows_affected
        """).fetchone()
        if stats:
            logger.info("pct_of_net_assets correction: %d high-pct CIK-quarters, "
                        "%d correctable (have net_assets), %d rows affected",
                        stats[0], stats[1], stats[2])
    except Exception:
        pass  # Diagnostic only

    con.close()

    # Restore column order
    result = result[[c for c in UNIFIED_COLUMNS if c in result.columns]]
    for col in UNIFIED_COLUMNS:
        if col not in result.columns:
            result[col] = ""
    result = result[UNIFIED_COLUMNS]

    return result


# ---------------------------------------------------------------------------
# GICS cache application (zero-cost, no LLM)
# ---------------------------------------------------------------------------


def _apply_gics_cache(combined: pd.DataFrame) -> pd.DataFrame:
    """Apply cached GICS classifications from company_gics_cache.csv.

    This runs automatically during --unified so that GICS data survives
    rebuilds without requiring a separate --classify-gics step.  No LLM
    calls are made -- only the on-disk cache is read.
    """
    from pipeline.config import COMPANY_GICS_CACHE_FILE

    if not COMPANY_GICS_CACHE_FILE.exists():
        return combined

    from pipeline.gics_classification import (
        _apply_gics_to_holdings,
        _load_cache,
    )

    cache = _load_cache()
    if not cache:
        return combined

    logger.info("Applying GICS cache (%d entries) to unified holdings...", len(cache))
    combined = _apply_gics_to_holdings(combined, cache)
    classified = (combined["gics_sub_industry"] != "").sum()
    logger.info("  GICS: %d/%d rows (%.1f%%) classified from cache",
                classified, len(combined),
                100 * classified / len(combined) if len(combined) else 0)
    return combined


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def build_unified_holdings(
    bdc_df: Optional[pd.DataFrame] = None,
    nport_df: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """Build unified private markets holdings from BDC + N-PORT data.

    If DataFrames are not provided, reads from disk (BDC_HOLDINGS_FILE,
    NPORT_HOLDINGS_FILE).

    Returns the combined DataFrame and saves to UNIFIED_HOLDINGS_FILE.
    """
    t0 = time.time()

    # Load from disk if not provided
    if bdc_df is None:
        logger.info("Loading BDC holdings from %s", BDC_HOLDINGS_FILE.name)
        bdc_df = pd.read_csv(BDC_HOLDINGS_FILE, dtype=str)
        # Restore numeric columns
        for col in ["fair_value", "cost", "principal_amount", "interest_rate",
                     "basis_spread", "pik_rate", "pct_of_net_assets",
                     "shares_held", "unrealized_gain_loss"]:
            if col in bdc_df.columns:
                bdc_df[col] = pd.to_numeric(bdc_df[col], errors="coerce")
        logger.info("  Loaded %d BDC rows", len(bdc_df))

    # Determine N-PORT input: use file path (DuckDB) for disk loads to avoid
    # pandas OOM on very large CSVs; use DataFrame if already provided.
    nport_input: Union[pd.DataFrame, Path]
    if nport_df is None:
        logger.info("Loading N-PORT holdings from %s (via DuckDB)", NPORT_HOLDINGS_FILE.name)
        nport_input = NPORT_HOLDINGS_FILE
    else:
        nport_input = nport_df

    # Prepare each source
    bdc_unified = staging_bdc._prepare_bdc(bdc_df)
    nport_unified = staging_nport._prepare_nport(nport_input)
    if bdc_unified.empty and nport_unified.empty:
        combined = pd.DataFrame(columns=UNIFIED_COLUMNS)
        _write_empty_orphan_report(UNIFIED_HOLDINGS_FILE.parent / UNIVERSE_ORPHAN_HOLDINGS_FILE.name)
        UNIFIED_HOLDINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        combined.to_csv(UNIFIED_HOLDINGS_FILE, index=False)
        logger.info("Unified holdings built with no eligible rows")
        return combined

    # Combine via DuckDB UNION ALL + index classification
    con = duckdb.connect()
    con.register("bdc_part", bdc_unified)
    con.register("nport_part", nport_unified)

    idx_case = classification._sql_classify_index()
    exposure_case = classification._sql_classify_exposure_type()
    asset_class_case = classification._sql_classify_asset_class()
    _special_cols = {"index_classification", "exposure_type", "asset_class", "principal_amount", "cusip"}
    col_list = ", ".join(c for c in UNIFIED_COLUMNS if c not in _special_cols)
    # Use explicit column list for UNION ALL to avoid positional mismatch
    union_cols = ", ".join(UNIFIED_COLUMNS)

    sql = f"""
    WITH nport_deduped AS (
        -- N-PORT within-source dedup: the same monthly filing can appear in
        -- adjacent quarterly bulk datasets (e.g. Nov-2021 in both 2021q4 and
        -- 2022q1 TSVs), and the same position can appear multiple times
        -- within a single filing.  Collapse these duplicates before
        -- cross-source dedup so the _source_count guard below only protects
        -- genuinely distinct positions (different CUSIPs/maturities/types).
        SELECT * EXCLUDE (_nport_rank) FROM (
            SELECT *,
                ROW_NUMBER() OVER (
                    PARTITION BY cik, report_date,
                        regexp_replace(
                            lower(trim(COALESCE(CAST(issuer_name AS VARCHAR), ''))),
                            '[^a-z0-9]+', ' ', 'g'
                        ),
                        regexp_replace(
                            lower(trim(COALESCE(CAST(instrument_description AS VARCHAR), ''))),
                            '[^a-z0-9]+', ' ', 'g'
                        ),
                        ROUND(TRY_CAST(fair_value AS DOUBLE), -2),
                        ROUND(COALESCE(TRY_CAST(principal_amount AS DOUBLE), 0), 0),
                        ROUND(COALESCE(TRY_CAST(shares_held AS DOUBLE), 0), 0),
                        COALESCE(CAST(maturity_date AS VARCHAR), ''),
                        COALESCE(CAST(nport_asset_cat AS VARCHAR), ''),
                        COALESCE(
                            NULLIF(NULLIF(NULLIF(CAST(cusip AS VARCHAR), ''),
                                         '000000000'), '999999999'),
                            ''
                        )
                ORDER BY
                    COALESCE(CAST(nport_quarter AS VARCHAR), '') DESC,
                    COALESCE(CAST(accession_number AS VARCHAR), '') DESC,
                    COALESCE(CAST(nport_holding_id AS VARCHAR), ''),
                    COALESCE(CAST(cusip AS VARCHAR), ''),
                    COALESCE(CAST(fair_value AS VARCHAR), ''),
                    COALESCE(CAST(cost AS VARCHAR), ''),
                    COALESCE(CAST(shares_held AS VARCHAR), '')
                ) AS _nport_rank
            FROM nport_part
        ) sub
        WHERE _nport_rank = 1
    ),
    combined AS (
        SELECT {union_cols} FROM bdc_part
        UNION ALL
        SELECT {union_cols} FROM nport_deduped
    ),
    -- Cross-source dedup: if the same holding appears in both BDC and N-PORT
    -- (same CIK + period + similar issuer name + similar fair_value),
    -- keep the BDC source row.  The _source_count guard preserves
    -- same-source groups (genuinely distinct positions that share the
    -- narrower cross-source key, e.g. different CUSIPs / maturities).
    deduped AS (
        SELECT *,
            COUNT(DISTINCT source) OVER (
                PARTITION BY cik, report_date,
                    regexp_replace(
                        lower(trim(COALESCE(CAST(issuer_name AS VARCHAR), ''))),
                        '[^a-z0-9]+', ' ', 'g'
                    ),
                    regexp_replace(
                        lower(trim(COALESCE(CAST(instrument_description AS VARCHAR), ''))),
                        '[^a-z0-9]+', ' ', 'g'
                    ),
                    ROUND(TRY_CAST(fair_value AS DOUBLE), -2),
                    ROUND(COALESCE(TRY_CAST(principal_amount AS DOUBLE), 0), 0),
                    ROUND(COALESCE(TRY_CAST(shares_held AS DOUBLE), 0), 0)
            ) AS _source_count,
            ROW_NUMBER() OVER (
                PARTITION BY cik, report_date,
                    regexp_replace(
                        lower(trim(COALESCE(CAST(issuer_name AS VARCHAR), ''))),
                        '[^a-z0-9]+', ' ', 'g'
                    ),
                    regexp_replace(
                        lower(trim(COALESCE(CAST(instrument_description AS VARCHAR), ''))),
                        '[^a-z0-9]+', ' ', 'g'
                    ),
                    ROUND(TRY_CAST(fair_value AS DOUBLE), -2),
                    ROUND(COALESCE(TRY_CAST(principal_amount AS DOUBLE), 0), 0),
                    ROUND(COALESCE(TRY_CAST(shares_held AS DOUBLE), 0), 0)
                ORDER BY
                    CASE WHEN source = 'bdc' THEN 0 ELSE 1 END,
                    COALESCE(CAST(accession_number AS VARCHAR), '') DESC,
                    COALESCE(CAST(bdc_investment_identifier AS VARCHAR), ''),
                    COALESCE(CAST(nport_holding_id AS VARCHAR), ''),
                    COALESCE(CAST(cusip AS VARCHAR), ''),
                    COALESCE(CAST(fair_value AS VARCHAR), ''),
                    COALESCE(CAST(cost AS VARCHAR), ''),
                    COALESCE(CAST(shares_held AS VARCHAR), '')
            ) AS _dedup_rank
        FROM combined
    ),
    no_dupes AS (
        SELECT * FROM deduped WHERE _source_count = 1 OR _dedup_rank = 1
    ),
    -- Within-filing subsidiary dedup: when the same position appears under
    -- both parent entity and subsidiary/JV contexts, keep the parent row and
    -- discard the subsidiary duplicate.  The match must be position-level:
    -- same accession/report date, same issuer, same instrument, and matching
    -- economics.  Subsidiary/JV rows for the same issuer but different
    -- tranches or fair values are separate positions and must be preserved.
    no_sub_dupes AS (
        SELECT * FROM no_dupes
        WHERE COALESCE(TRY_CAST(is_subsidiary AS INT), 0) = 0
           OR NOT EXISTS (
               SELECT 1 FROM no_dupes nd2
               WHERE nd2.cik = no_dupes.cik
                 AND nd2.accession_number = no_dupes.accession_number
                 AND nd2.report_date = no_dupes.report_date
                 AND regexp_replace(
                         lower(trim(COALESCE(CAST(nd2.issuer_name AS VARCHAR), ''))),
                         '[^a-z0-9]+', ' ', 'g'
                     ) = regexp_replace(
                         lower(trim(COALESCE(CAST(no_dupes.issuer_name AS VARCHAR), ''))),
                         '[^a-z0-9]+', ' ', 'g'
                     )
                 AND regexp_replace(
                         lower(trim(COALESCE(CAST(nd2.instrument_description AS VARCHAR), ''))),
                         '[^a-z0-9]+', ' ', 'g'
                     ) = regexp_replace(
                         lower(trim(COALESCE(CAST(no_dupes.instrument_description AS VARCHAR), ''))),
                         '[^a-z0-9]+', ' ', 'g'
                     )
                 AND ROUND(COALESCE(TRY_CAST(nd2.fair_value AS DOUBLE), 0), 0)
                     = ROUND(COALESCE(TRY_CAST(no_dupes.fair_value AS DOUBLE), 0), 0)
                 AND ROUND(COALESCE(TRY_CAST(nd2.principal_amount AS DOUBLE), 0), 0)
                     = ROUND(COALESCE(TRY_CAST(no_dupes.principal_amount AS DOUBLE), 0), 0)
                 AND ROUND(COALESCE(TRY_CAST(nd2.shares_held AS DOUBLE), 0), 0)
                     = ROUND(COALESCE(TRY_CAST(no_dupes.shares_held AS DOUBLE), 0), 0)
                 AND COALESCE(TRY_CAST(nd2.is_subsidiary AS INT), 0) = 0
           )
    ),
    -- BDC-only dimension-path dedup: same XBRL position can appear under
    -- multiple dimension paths with case/punctuation issuer variants and
    -- occasionally different cost values. Keep cost out of this key so the
    -- duplicate residue collapses without collapsing real tranches.
    bdc_dim_ranked AS (
        SELECT *,
            ROW_NUMBER() OVER (
                PARTITION BY cik, accession_number, report_date,
                    regexp_replace(
                        lower(trim(COALESCE(CAST(issuer_name AS VARCHAR), ''))),
                        '[^a-z0-9]+', ' ', 'g'
                    ),
                    regexp_replace(
                        lower(trim(COALESCE(CAST(instrument_description AS VARCHAR), ''))),
                        '[^a-z0-9]+', ' ', 'g'
                    ),
                    ROUND(COALESCE(TRY_CAST(fair_value AS DOUBLE), 0), 0),
                    ROUND(COALESCE(TRY_CAST(principal_amount AS DOUBLE), 0), 0),
                    ROUND(COALESCE(TRY_CAST(shares_held AS DOUBLE), 0), 0)
                ORDER BY
                    LENGTH(COALESCE(CAST(issuer_name AS VARCHAR), '')),
                    COALESCE(CAST(issuer_name AS VARCHAR), ''),
                    COALESCE(CAST(bdc_investment_identifier AS VARCHAR), ''),
                    COALESCE(CAST(accession_number AS VARCHAR), '')
            ) AS _dim_rank
        FROM no_sub_dupes
        WHERE source = 'bdc'
    ),
    no_dim_dupes AS (
        SELECT * EXCLUDE (_dim_rank)
        FROM bdc_dim_ranked
        WHERE _dim_rank = 1
        UNION ALL
        SELECT *
        FROM no_sub_dupes
        WHERE source != 'bdc'
    ),
    with_fund_text AS (
        SELECT *,
            COALESCE(lower(trim(issuer_name)), '') || ' ' ||
            COALESCE(lower(trim(instrument_description)), '') AS _combined_fund_text
        FROM no_dim_dupes
    ),
    classified AS (
        SELECT *,
            {idx_case} AS _index_class,
            {exposure_case} AS _exposure_type,
            {asset_class_case} AS _asset_class
        FROM with_fund_text
    ),
    -- Cost proxy: fill NULL/zero cost with first observed fair_value
    -- for that specific position, ordered by report_date.  The partition
    -- key includes instrument_description and cusip so each tranche gets
    -- its own proxy (e.g. Term Loan A vs Term Loan B).  The tiebreaker
    -- fair_value makes the result deterministic when multiple rows share
    -- the earliest report_date.
    with_cost AS (
        SELECT * EXCLUDE (cost),
            COALESCE(
                NULLIF(TRY_CAST(cost AS DOUBLE), 0),
                FIRST_VALUE(
                    NULLIF(TRY_CAST(fair_value AS DOUBLE), 0)
                    IGNORE NULLS
                ) OVER (
                    PARTITION BY cik, issuer_name,
                        regexp_replace(
                            lower(trim(COALESCE(CAST(instrument_description AS VARCHAR), ''))),
                            '[^a-z0-9]+', ' ', 'g'
                        ),
                        COALESCE(NULLIF(CAST(cusip AS VARCHAR), ''), '')
                    ORDER BY
                        report_date,
                        fair_value,
                        COALESCE(CAST(accession_number AS VARCHAR), ''),
                        COALESCE(CAST(bdc_investment_identifier AS VARCHAR), ''),
                        COALESCE(CAST(nport_holding_id AS VARCHAR), ''),
                        COALESCE(CAST(shares_held AS VARCHAR), '')
                    ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
                )
            ) AS cost
        FROM classified
    ),
    -- Shares normalization: detect power-of-10 unit mismatches within
    -- the same position (cik + issuer_name) by comparing each row's
    -- per-unit price (fair_value / shares_held) against the group median.
    -- Outliers are replaced with the nearest non-outlier shares value.
    with_shares_fix AS (
        SELECT * EXCLUDE (shares_held),
            CASE
                WHEN _is_outlier THEN COALESCE(
                    -- Nearest previous non-outlier shares
                    LAST_VALUE(CASE WHEN NOT _is_outlier THEN _sh_val END
                        IGNORE NULLS) OVER (
                        PARTITION BY cik, issuer_name
                        ORDER BY
                            report_date,
                            COALESCE(CAST(accession_number AS VARCHAR), ''),
                            COALESCE(CAST(bdc_investment_identifier AS VARCHAR), ''),
                            COALESCE(CAST(nport_holding_id AS VARCHAR), ''),
                            COALESCE(CAST(_sh_val AS VARCHAR), '')
                        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING),
                    -- Nearest following non-outlier shares
                    FIRST_VALUE(CASE WHEN NOT _is_outlier THEN _sh_val END
                        IGNORE NULLS) OVER (
                        PARTITION BY cik, issuer_name
                        ORDER BY
                            report_date,
                            COALESCE(CAST(accession_number AS VARCHAR), ''),
                            COALESCE(CAST(bdc_investment_identifier AS VARCHAR), ''),
                            COALESCE(CAST(nport_holding_id AS VARCHAR), ''),
                            COALESCE(CAST(_sh_val AS VARCHAR), '')
                        ROWS BETWEEN 1 FOLLOWING AND UNBOUNDED FOLLOWING)
                )
                ELSE _sh_val
            END AS shares_held
        FROM (
            SELECT *,
                TRY_CAST(shares_held AS DOUBLE) AS _sh_val,
                TRY_CAST(fair_value AS DOUBLE) AS _fv_val,
                -- Median per-unit price across the group
                MEDIAN(
                    ABS(TRY_CAST(fair_value AS DOUBLE)
                        / NULLIF(TRY_CAST(shares_held AS DOUBLE), 0))
                ) OVER (PARTITION BY cik, issuer_name)
                    AS _med_upx,
                -- Group size (only rows with valid shares)
                COUNT(CASE WHEN TRY_CAST(shares_held AS DOUBLE) IS NOT NULL
                           AND TRY_CAST(shares_held AS DOUBLE) != 0
                           AND TRY_CAST(fair_value AS DOUBLE) IS NOT NULL
                           AND TRY_CAST(fair_value AS DOUBLE) != 0
                      THEN 1 END
                ) OVER (PARTITION BY cik, issuer_name)
                    AS _sh_group_size,
                -- Outlier flag
                (TRY_CAST(shares_held AS DOUBLE) IS NOT NULL
                 AND TRY_CAST(shares_held AS DOUBLE) != 0
                 AND TRY_CAST(fair_value AS DOUBLE) IS NOT NULL
                 AND TRY_CAST(fair_value AS DOUBLE) != 0
                 AND COUNT(CASE WHEN TRY_CAST(shares_held AS DOUBLE) IS NOT NULL
                                AND TRY_CAST(shares_held AS DOUBLE) != 0
                                AND TRY_CAST(fair_value AS DOUBLE) IS NOT NULL
                                AND TRY_CAST(fair_value AS DOUBLE) != 0
                           THEN 1 END
                     ) OVER (PARTITION BY cik, issuer_name) >= 2
                 AND ABS(LOG10(NULLIF(
                     ABS(TRY_CAST(fair_value AS DOUBLE)
                         / TRY_CAST(shares_held AS DOUBLE))
                     / NULLIF(MEDIAN(
                         ABS(TRY_CAST(fair_value AS DOUBLE)
                             / NULLIF(TRY_CAST(shares_held AS DOUBLE), 0))
                       ) OVER (PARTITION BY cik, issuer_name), 0)
                 , 0))) > 1.5
                ) AS _is_outlier
            FROM with_cost
        ) _sh_sub
    )
    SELECT
        {col_list},
        CASE WHEN COALESCE(CAST(cusip AS VARCHAR), '') IN ('999999999', '000000000', '00000000')
             THEN NULL ELSE cusip END AS cusip,
        CASE WHEN _index_class IN (
                 'COMMON_EQUITY', 'PREFERRED_EQUITY',
                 'PRIVATE_EQUITY_FUND', 'PRIVATE_CREDIT_FUND',
                 'REAL_ESTATE_FUND', 'HEDGE_FUND'
             ) THEN NULL ELSE principal_amount END AS principal_amount,
        _index_class AS index_classification,
        _exposure_type AS exposure_type,
        _asset_class AS asset_class
    FROM with_shares_fix
    """

    combined = con.execute(sql).fetchdf()

    # Diagnostic: count shares corrections
    try:
        shares_diag = con.execute(f"""
        WITH combined AS (
            SELECT * FROM bdc_part
            UNION ALL
            SELECT * FROM nport_part
        ),
        deduped AS (
            SELECT *,
                COUNT(DISTINCT source) OVER (
                    PARTITION BY cik, report_date,
                        regexp_replace(
                            lower(trim(COALESCE(CAST(issuer_name AS VARCHAR), ''))),
                            '[^a-z0-9]+', ' ', 'g'
                        ),
                        regexp_replace(
                            lower(trim(COALESCE(CAST(instrument_description AS VARCHAR), ''))),
                            '[^a-z0-9]+', ' ', 'g'
                        ),
                        ROUND(TRY_CAST(fair_value AS DOUBLE), -2),
                        ROUND(COALESCE(TRY_CAST(principal_amount AS DOUBLE), 0), 0),
                        ROUND(COALESCE(TRY_CAST(shares_held AS DOUBLE), 0), 0)
                ) AS _source_count,
                ROW_NUMBER() OVER (
                    PARTITION BY cik, report_date,
                        regexp_replace(
                            lower(trim(COALESCE(CAST(issuer_name AS VARCHAR), ''))),
                            '[^a-z0-9]+', ' ', 'g'
                        ),
                        regexp_replace(
                            lower(trim(COALESCE(CAST(instrument_description AS VARCHAR), ''))),
                            '[^a-z0-9]+', ' ', 'g'
                        ),
                        ROUND(TRY_CAST(fair_value AS DOUBLE), -2),
                        ROUND(COALESCE(TRY_CAST(principal_amount AS DOUBLE), 0), 0),
                        ROUND(COALESCE(TRY_CAST(shares_held AS DOUBLE), 0), 0)
                    ORDER BY
                        CASE WHEN source = 'bdc' THEN 0 ELSE 1 END,
                        COALESCE(CAST(accession_number AS VARCHAR), '') DESC,
                        COALESCE(CAST(bdc_investment_identifier AS VARCHAR), ''),
                        COALESCE(CAST(nport_holding_id AS VARCHAR), ''),
                        COALESCE(CAST(cusip AS VARCHAR), ''),
                        COALESCE(CAST(fair_value AS VARCHAR), ''),
                        COALESCE(CAST(cost AS VARCHAR), ''),
                        COALESCE(CAST(shares_held AS VARCHAR), '')
                ) AS _dedup_rank
            FROM combined
        ),
        no_dupes AS (
            SELECT * FROM deduped WHERE _source_count = 1 OR _dedup_rank = 1
        ),
        _sh_check AS (
            SELECT
                TRY_CAST(shares_held AS DOUBLE) AS orig_sh,
                TRY_CAST(fair_value AS DOUBLE) AS fv,
                ABS(TRY_CAST(fair_value AS DOUBLE)
                    / NULLIF(TRY_CAST(shares_held AS DOUBLE), 0)) AS _upx,
                MEDIAN(ABS(TRY_CAST(fair_value AS DOUBLE)
                    / NULLIF(TRY_CAST(shares_held AS DOUBLE), 0)))
                    OVER (PARTITION BY cik, issuer_name) AS _med_upx,
                COUNT(CASE WHEN TRY_CAST(shares_held AS DOUBLE) IS NOT NULL
                           AND TRY_CAST(shares_held AS DOUBLE) != 0
                           AND TRY_CAST(fair_value AS DOUBLE) IS NOT NULL
                           AND TRY_CAST(fair_value AS DOUBLE) != 0
                      THEN 1 END) OVER (PARTITION BY cik, issuer_name) AS _grp
            FROM no_dupes
            WHERE TRY_CAST(shares_held AS DOUBLE) IS NOT NULL
              AND TRY_CAST(shares_held AS DOUBLE) != 0
              AND TRY_CAST(fair_value AS DOUBLE) IS NOT NULL
              AND TRY_CAST(fair_value AS DOUBLE) != 0
        )
        SELECT COUNT(*) AS n_corrected,
               COUNT(DISTINCT orig_sh) AS n_distinct
        FROM _sh_check
        WHERE _grp >= 2
          AND ABS(LOG10(_upx / NULLIF(_med_upx, 0))) > 1.5
        """).fetchone()
        if shares_diag and shares_diag[0] > 0:
            logger.info("  Shares normalization: corrected %d rows (%d distinct original values)",
                        shares_diag[0], shares_diag[1])
    except Exception:
        pass  # Diagnostic only, don't fail the pipeline

    con.close()

    # Ensure column order
    combined = combined[[c for c in UNIFIED_COLUMNS if c in combined.columns]]
    for col in UNIFIED_COLUMNS:
        if col not in combined.columns:
            combined[col] = ""
    combined = combined[UNIFIED_COLUMNS]

    pre_dedup = len(bdc_unified) + len(nport_unified)
    dedup_removed = pre_dedup - len(combined)
    logger.info("Combined: %d total rows (BDC %d + N-PORT %d, %d cross-source dupes removed)",
                len(combined), len(bdc_unified), len(nport_unified), dedup_removed)

    combined = _apply_universe_gate(combined)

    # Log subsidiary stats
    if "is_subsidiary" in combined.columns:
        sub_count = (combined["is_subsidiary"].astype(str) == "1").sum()
        if sub_count > 0:
            logger.info("  Subsidiary positions: %d rows flagged (is_subsidiary=1)", sub_count)

    # Entity enrichment: join against existing entity_lookup if available
    if ENTITY_LOOKUP_FILE.exists():
        con2 = duckdb.connect()
        con2.register("holdings", combined)
        lookup_str = str(ENTITY_LOOKUP_FILE).replace("\\", "/")
        combined = con2.execute(f"""
            SELECT h.* EXCLUDE (entity_id, canonical_name),
                   COALESCE(e.entity_id, '') AS entity_id,
                   COALESCE(e.canonical_name, '') AS canonical_name
            FROM holdings h
            LEFT JOIN read_csv_auto('{lookup_str}',
                          header=true, all_varchar=true) e
              ON CAST(h.issuer_name AS VARCHAR) = e.issuer_name_variant
              AND CAST(h.source AS VARCHAR) = e.source
        """).fetchdf()
        con2.close()
        # Re-apply column order (EXCLUDE moves columns to end)
        combined = combined[UNIFIED_COLUMNS]
        eid_count = (combined["entity_id"] != "").sum()
        logger.info("Entity enrichment: %d/%d rows (%.1f%%) with entity_id",
                     eid_count, len(combined),
                     100 * eid_count / len(combined) if len(combined) else 0)

    # Industry enrichment: join against identifier_extraction_lookup if available
    if IDENTIFIER_EXTRACTION_LOOKUP_FILE.exists():
        con3 = duckdb.connect()
        con3.register("holdings", combined)
        ilookup_str = str(IDENTIFIER_EXTRACTION_LOOKUP_FILE).replace("\\", "/")
        combined = con3.execute(f"""
            SELECT h.* EXCLUDE (extracted_industry),
                   CASE
                       WHEN (h.extracted_industry IS NULL
                             OR CAST(h.extracted_industry AS VARCHAR) = '')
                            AND e.extracted_industry IS NOT NULL
                            AND e.extracted_industry != ''
                            AND e.extracted_industry != 'None'
                       THEN e.extracted_industry
                       ELSE COALESCE(h.extracted_industry, '')
                   END AS extracted_industry
            FROM holdings h
            LEFT JOIN read_csv_auto('{ilookup_str}',
                          header=true, all_varchar=true) e
              ON CAST(h.bdc_investment_identifier AS VARCHAR)
               = CAST(e.bdc_investment_identifier AS VARCHAR)
        """).fetchdf()
        con3.close()
        combined = combined[UNIFIED_COLUMNS]
        ind_count = (combined["extracted_industry"] != "").sum()
        logger.info("Industry enrichment: %d/%d rows (%.1f%%) with extracted_industry",
                     ind_count, len(combined),
                     100 * ind_count / len(combined) if len(combined) else 0)

    # Classification stabilization: override QoQ flips where one class
    # has >= 2x the quarters of the second-most-frequent for same position.
    combined = _stabilize_classification(combined)
    combined = _restore_deterministic_classification_rules(combined)

    # Correct pct_of_net_assets for multi-entity BDCs
    combined = _correct_pct_of_net_assets(combined)

    # Apply manual row corrections
    combined = _apply_row_corrections(combined)

    # Apply fund strategy correction candidates (if file exists on disk)
    combined = _apply_fund_strategy_corrections(combined)

    # Log cost proxy stats
    cost_filled = combined["cost"].notna() & (combined["cost"] != 0)
    logger.info("  Cost coverage: %d rows (%.1f%%)",
                cost_filled.sum(), 100 * cost_filled.sum() / len(combined) if len(combined) else 0)

    # Schema enforcement
    violations = _enforce_schema(combined)
    if violations:
        logger.warning("Schema enforcement: %d check(s) failed", len(violations))
        for name, count in violations:
            logger.warning("  FAIL %s: %d rows", name, count)
    else:
        logger.info("Schema enforcement: all checks passed")

    # Keep downstream position IDs stable across DuckDB/pandas incidental
    # ordering changes.  These columns identify source row identity before
    # returns populate position_id.
    sort_cols = [
        "source", "cik", "report_date", "filing_date", "accession_number",
        "bdc_investment_identifier", "nport_holding_id", "issuer_name",
        "instrument_description", "fair_value", "cost", "principal_amount",
        "shares_held",
    ]
    combined = combined.sort_values(
        [c for c in sort_cols if c in combined.columns],
        kind="mergesort",
        na_position="last",
    ).reset_index(drop=True)

    # Apply cached GICS classifications (if cache exists on disk)
    combined = _apply_gics_cache(combined)

    # Save
    combined.to_csv(UNIFIED_HOLDINGS_FILE, index=False)
    logger.info("Saved to %s (%.1f MB)",
                UNIFIED_HOLDINGS_FILE.name,
                UNIFIED_HOLDINGS_FILE.stat().st_size / (1024 * 1024))

    # Log summary statistics
    _log_summary(combined)

    elapsed = time.time() - t0
    logger.info("Unified holdings built in %.1f s", elapsed)

    return combined


def _apply_fund_strategy_corrections(
    df: pd.DataFrame,
    candidates_path: Optional[Path] = None,
) -> pd.DataFrame:
    """Apply fund strategy correction candidates from disk (if file exists).

    Loads the correction candidates CSV, delegates to
    ``fund_strategy_validation.apply_fund_strategy_correction_candidates``
    which handles APPLY filtering, excluded-transition guards, and DuckDB join.
    """
    path = candidates_path or FUND_STRATEGY_CORRECTION_CANDIDATES_FILE
    if not path.exists():
        return df

    from pipeline.fund_strategy_validation import (
        apply_fund_strategy_correction_candidates,
    )

    candidates = pd.read_csv(path, dtype=str).fillna("")
    if candidates.empty:
        return df

    logger.info(
        "Applying fund strategy corrections from %s (%d candidate rows)",
        path.name,
        len(candidates),
    )
    return apply_fund_strategy_correction_candidates(df, candidates)


# Fields that row_corrections.csv is allowed to override.
_CORRECTABLE_FIELDS = frozenset({
    "fair_value", "cost", "principal_amount",
    "interest_rate", "basis_spread", "pik_rate", "shares_held",
    "index_classification", "exposure_type", "asset_class",
    "issuer_name", "instrument_description",
})

# Required columns in row_corrections.csv.
_CORRECTIONS_REQUIRED_COLS = {
    "cik", "report_date", "accession_number",
    "bdc_investment_identifier", "field", "value",
    "reason", "source_evidence", "author", "date_added",
}


def _apply_row_corrections(
    df: pd.DataFrame,
    corrections_path: Optional[Path] = None,
) -> pd.DataFrame:
    """Apply manual row-level corrections from an override CSV.

    Each row in the corrections file identifies one (row, field) to patch.
    Match key: (cik, report_date, accession_number, bdc_investment_identifier).

    Returns the dataframe with corrections applied.  Logs every correction
    applied and warns on unmatched correction rows.
    """
    path = corrections_path or ROW_CORRECTIONS_FILE
    if not path.exists():
        return df

    corrections = pd.read_csv(path, dtype=str).fillna("")

    # --- Schema validation ---------------------------------------------------
    missing_cols = _CORRECTIONS_REQUIRED_COLS - set(corrections.columns)
    if missing_cols:
        logger.warning(
            "row_corrections.csv missing required columns: %s -- skipping",
            ", ".join(sorted(missing_cols)),
        )
        return df

    if corrections.empty:
        return df

    bad_fields = set(corrections["field"].unique()) - _CORRECTABLE_FIELDS
    if bad_fields:
        logger.warning(
            "row_corrections.csv contains uncorrectable field(s): %s -- "
            "these rows will be skipped",
            ", ".join(sorted(bad_fields)),
        )
        corrections = corrections[corrections["field"].isin(_CORRECTABLE_FIELDS)]

    if corrections.empty:
        return df

    # --- Normalize match keys ------------------------------------------------
    # Pad CIK to 10 digits to match unified holdings format.
    corrections["cik"] = corrections["cik"].str.strip().str.zfill(10)

    # Build a match key in the unified dataframe.
    key_cols = ["cik", "report_date", "accession_number",
                "bdc_investment_identifier"]
    df["_corr_key"] = (
        df["cik"].astype(str).str.strip().str.zfill(10) + "|"
        + df["report_date"].astype(str).str.strip() + "|"
        + df["accession_number"].astype(str).str.strip() + "|"
        + df["bdc_investment_identifier"].astype(str).str.strip()
    )

    corrections["_corr_key"] = (
        corrections["cik"] + "|"
        + corrections["report_date"].str.strip() + "|"
        + corrections["accession_number"].str.strip() + "|"
        + corrections["bdc_investment_identifier"].str.strip()
    )

    # --- Apply corrections ---------------------------------------------------
    n_applied = 0
    n_unmatched = 0

    # Group corrections by key for efficient lookup.
    corr_by_key: dict[str, list[tuple[str, str, str]]] = {}
    for _, row in corrections.iterrows():
        corr_by_key.setdefault(row["_corr_key"], []).append(
            (row["field"], row["value"], row["reason"])
        )

    # Build a set of keys present in the dataframe for fast membership test.
    df_keys = set(df["_corr_key"])

    for key, patches in corr_by_key.items():
        if key not in df_keys:
            for field, value, reason in patches:
                logger.warning(
                    "Row correction unmatched: field=%s reason=%r key=%s",
                    field, reason, key,
                )
            n_unmatched += len(patches)
            continue

        mask = df["_corr_key"] == key
        match_count = mask.sum()
        if match_count > 1:
            logger.warning(
                "Row correction matches %d rows (expected 1): key=%s -- "
                "applying to all matches",
                match_count, key,
            )

        for field, value, reason in patches:
            df.loc[mask, field] = value
            n_applied += 1
            logger.info(
                "Row correction applied: field=%s value=%s reason=%r key=%s",
                field, value, reason, key,
            )

    df.drop(columns=["_corr_key"], inplace=True)

    logger.info(
        "Row corrections: %d applied, %d unmatched (from %s)",
        n_applied, n_unmatched, path.name,
    )
    return df


def _enforce_schema(df: pd.DataFrame) -> list[tuple[str, int]]:
    """Run schema assertions on the unified output.

    Returns [(check_name, fail_count), ...] for any check with violations > 0.
    Checks are non-fatal -- callers decide how to handle violations.
    """
    if df.empty:
        return []

    con = duckdb.connect()
    con.register("unified", df)

    # --- Layer 1: Type and format (should never fail) ---
    checks: list[tuple[str, str]] = [
        ("cik_format",
         "SELECT COUNT(*) FROM unified"
         " WHERE LENGTH(CAST(cik AS VARCHAR)) != 10"
         "    OR regexp_matches(CAST(cik AS VARCHAR), '[^0-9]')"),
        ("source_enum",
         "SELECT COUNT(*) FROM unified"
         " WHERE CAST(source AS VARCHAR) NOT IN ('bdc', 'nport')"),
        ("asset_category_enum",
         "SELECT COUNT(*) FROM unified"
         " WHERE CAST(asset_category AS VARCHAR) NOT IN"
         " ('LOAN','DEBT','EQUITY_COMMON','EQUITY_PREFERRED','FUND','OTHER')"),
        ("issuer_category_enum",
         "SELECT COUNT(*) FROM unified"
         " WHERE CAST(issuer_category AS VARCHAR) NOT IN"
         " ('CORPORATE','FUND','GOVERNMENT','OTHER')"),
        ("index_classification_enum",
         "SELECT COUNT(*) FROM unified"
         " WHERE CAST(index_classification AS VARCHAR) NOT IN"
         " ('DIRECT_LENDING','COMMON_EQUITY','PREFERRED_EQUITY',"
         "  'PRIVATE_CREDIT_FUND','PRIVATE_EQUITY_FUND',"
         "  'REAL_ESTATE_FUND','DIRECT_REAL_ESTATE',"
         "  'STRUCTURED_CREDIT','HEDGE_FUND','CASH','UNCLASSIFIED')"),
        ("exposure_type_enum",
         "SELECT COUNT(*) FROM unified"
         " WHERE CAST(exposure_type AS VARCHAR) NOT IN"
         " ('DIRECT','FUND','LIQUID')"),
        ("asset_class_enum",
         "SELECT COUNT(*) FROM unified"
         " WHERE CAST(asset_class AS VARCHAR) NOT IN"
         " ('PRIVATE_CREDIT','PRIVATE_EQUITY','REAL_ESTATE',"
         "  'STRUCTURED_CREDIT','HEDGE_FUND','CASH','OTHER')"),
        ("report_date_parseable",
         "SELECT COUNT(*) FROM unified"
         " WHERE CAST(report_date AS VARCHAR) IS NOT NULL"
         "   AND CAST(report_date AS VARCHAR) != ''"
         "   AND TRY_CAST(report_date AS DATE) IS NULL"),
        ("fair_value_is_null",
         "SELECT COUNT(*) FROM unified"
         " WHERE TRY_CAST(fair_value AS DOUBLE) IS NULL"),
        ("coupon_type_enum",
         "SELECT COUNT(*) FROM unified"
         " WHERE CAST(coupon_type AS VARCHAR) NOT IN ('Fixed', 'Floating', '')"),

        # --- Layer 2: Domain range (catches transform errors) ---
        ("interest_rate_range",
         "SELECT COUNT(*) FROM unified"
         " WHERE TRY_CAST(interest_rate AS DOUBLE) IS NOT NULL"
         "   AND (TRY_CAST(interest_rate AS DOUBLE) < 0"
         "        OR TRY_CAST(interest_rate AS DOUBLE) > 50)"),
        ("basis_spread_range",
         "SELECT COUNT(*) FROM unified"
         " WHERE TRY_CAST(basis_spread AS DOUBLE) IS NOT NULL"
         "   AND (TRY_CAST(basis_spread AS DOUBLE) < 0"
         "        OR TRY_CAST(basis_spread AS DOUBLE) > 30)"),
        ("pik_rate_range",
         "SELECT COUNT(*) FROM unified"
         " WHERE TRY_CAST(pik_rate AS DOUBLE) IS NOT NULL"
         "   AND (TRY_CAST(pik_rate AS DOUBLE) < 0"
         "        OR TRY_CAST(pik_rate AS DOUBLE) > 25)"),
        ("pct_net_assets_range",
         "SELECT COUNT(*) FROM unified"
         " WHERE TRY_CAST(pct_of_net_assets AS DOUBLE) IS NOT NULL"
         "   AND ABS(TRY_CAST(pct_of_net_assets AS DOUBLE)) > 150"),
        ("shares_not_negative",
         "SELECT COUNT(*) FROM unified"
         " WHERE TRY_CAST(shares_held AS DOUBLE) IS NOT NULL"
         "   AND TRY_CAST(shares_held AS DOUBLE) < 0"),
        ("principal_not_negative",
         "SELECT COUNT(*) FROM unified"
         " WHERE TRY_CAST(principal_amount AS DOUBLE) IS NOT NULL"
         "   AND TRY_CAST(principal_amount AS DOUBLE) < 0"),

        # --- Layer 3: Relational / logical (catches transform logic bugs) ---
        ("bdc_has_identifier",
         "SELECT COUNT(*) FROM unified"
         " WHERE CAST(source AS VARCHAR) = 'bdc'"
         "   AND (bdc_investment_identifier IS NULL"
         "        OR CAST(bdc_investment_identifier AS VARCHAR) = '')"),
        ("dl_implies_loan_or_debt_corporate",
         "SELECT COUNT(*) FROM unified"
         " WHERE CAST(index_classification AS VARCHAR) = 'DIRECT_LENDING'"
         "   AND (CAST(asset_category AS VARCHAR) NOT IN ('LOAN', 'DEBT')"
         "        OR CAST(issuer_category AS VARCHAR) != 'CORPORATE')"),
        ("fund_index_implies_fund_issuer",
         "SELECT COUNT(*) FROM unified"
         " WHERE CAST(index_classification AS VARCHAR)"
         "       IN ('PRIVATE_CREDIT_FUND', 'PRIVATE_EQUITY_FUND', 'REAL_ESTATE_FUND', 'HEDGE_FUND')"
         "   AND CAST(issuer_category AS VARCHAR) != 'FUND'"),
    ]

    violations: list[tuple[str, int]] = []
    for name, sql in checks:
        try:
            count = con.execute(sql).fetchone()[0]
            if count > 0:
                violations.append((name, count))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Schema check '%s' failed to execute: %s", name, exc)
            violations.append((name, -1))

    con.close()
    return violations


def _log_summary(df: pd.DataFrame) -> None:
    """Log summary statistics about the unified dataset."""
    total = len(df)
    bdc_count = (df["source"] == "bdc").sum()
    nport_count = (df["source"] == "nport").sum()

    logger.info("")
    logger.info("Unified holdings: %d total", total)
    logger.info("  BDC:    %d (%.1f%%)", bdc_count, 100 * bdc_count / total if total else 0)
    logger.info("  N-PORT: %d (%.1f%%)", nport_count, 100 * nport_count / total if total else 0)

    logger.info("")
    logger.info("By index:")
    for idx_name, count in df["index_classification"].value_counts().items():
        logger.info("  %-25s %d (%.1f%%)", idx_name + ":", count, 100 * count / total)

    logger.info("")
    logger.info("Analytics coverage:")
    for col, label in [
        ("interest_rate", "interest_rate filled"),
        ("basis_spread", "basis_spread filled (BDC only)"),
        ("reference_rate_type", "reference_rate_type filled"),
        ("cost", "cost filled (BDC real + N-PORT proxy)"),
        ("maturity_date", "maturity_date filled"),
        ("principal_amount", "principal_amount filled"),
        ("shares_held", "shares_held filled"),
        ("pct_of_net_assets", "pct_of_net_assets"),
    ]:
        if col in df.columns:
            filled = df[col].notna() & (df[col] != "") & (df[col] != 0)
            pct = 100 * filled.sum() / total if total else 0
            logger.info("  %-30s %.1f%%", label + ":", pct)

    # Quarter range
    quarters = set()
    # From N-PORT quarter column
    nport_q = df.loc[df["nport_quarter"] != "", "nport_quarter"].dropna().unique()
    quarters.update(nport_q)
    # From BDC report_date -> approximate quarter
    bdc_dates = df.loc[df["source"] == "bdc", "report_date"].dropna()
    for d in bdc_dates.unique():
        try:
            dt = pd.to_datetime(d)
            q = f"{dt.year}q{(dt.month - 1) // 3 + 1}"
            quarters.add(q)
        except (ValueError, TypeError):
            pass

    if quarters:
        sorted_q = sorted(quarters)
        logger.info("  Quarters covered: %s - %s", sorted_q[0], sorted_q[-1])
