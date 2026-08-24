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

from pipeline import (
    classification,
    instrument_classification,
    lien_classification,
    staging_bdc,
    staging_nport,
)
from pipeline.config import (
    BDC_HOLDINGS_FILE,
    BDC_HOLDINGS_PARQUET_FILE,
    COMBINED_UNIVERSE_FILE,
    ENTITY_LOOKUP_FILE,
    FUND_FINANCIALS_FILE,
    FUND_STRATEGY_CORRECTION_CANDIDATES_FILE,
    FUND_STRATEGY_CORRECTION_CANDIDATES_PINNED_FILE,
    FUND_STRATEGY_REFERENCE_FILE,
    IDENTIFIER_EXTRACTION_LOOKUP_FILE,
    NPORT_HOLDINGS_FILE,
    NPORT_HOLDINGS_PARQUET_FILE,
    ROW_CORRECTIONS_FILE,
    UNCLASSIFIED_REVIEW_CACHE_FILE,
    UNIFIED_HOLDINGS_FILE,
    UNIFIED_HOLDINGS_PARQUET_FILE,
    UNIVERSE_ORPHAN_HOLDINGS_FILE,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WRAPPER_DUPLICATE_LOT_KEY_CIKS = frozenset({
    "0001772704",
    "0001784700",
})

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
    "fair_value_currency", "cost_currency",
    "principal_amount_currency", "principal_amount_usd",
    "principal_fx_rate_to_usd", "principal_fx_status",
    # Classification
    "asset_category", "issuer_category", "index_classification",
    "exposure_type", "asset_class",
    "fair_value_level",
    # Rate/spread
    "interest_rate", "interest_rate_source",
    "basis_spread", "basis_spread_source",
    "reference_rate_type",
    "reference_rate_source",
    "coupon_type", "pik_rate",
    # Debt details
    "maturity_date", "maturity_date_source",
    # Source-specific (BDC)
    "bdc_investment_identifier", "bdc_form_type", "bdc_dimensions_raw",
    "bdc_unrealized_gain_loss",
    "bdc_investment_country",
    "src_context_id",
    "src_context_count",
    "src_conflict_fields",
    "src_transforms",
    "src_field_overrides",
    "cost_source",
    "shares_held_source",
    "fair_value_source",
    "principal_amount_source",
    "pct_of_net_assets_source",
    "pik_rate_source",
    "bdc_unrealized_gain_loss_source",
    "src_facts",
    "src_filled_fields",
    "corrected_fields",
    # Non-accrual signals (BDC only -- extracted from XBRL footnotes/dimensions)
    "nonaccrual_footnote", "nonaccrual_dimension",
    # Source-specific (N-PORT)
    "nport_holding_id", "nport_series_name", "nport_series_id",
    "nport_asset_cat", "nport_issuer_type", "nport_payoff_profile",
    "nport_investment_country", "nport_is_restricted", "nport_quarter",
    "nport_is_default", "nport_are_interest_payments_in_arrears",
    "nport_is_paid_in_kind", "nport_currency_code",
    "nport_liquidity_classification",
    # Subsidiary flag (BDC only -- nonconsolidated JV/subsidiary positions)
    "is_subsidiary",
    # JV/subsidiary flag from agent review of unclassified positions
    "jv_subsidiary",
    # Entity resolution (populated by --entities step)
    "entity_id", "canonical_name",
    # LLM-extracted fields (populated by --extract step)
    "extracted_industry",
    # GICS classification (populated by --classify-gics step)
    "gics_sub_industry",
    # Lien position (First Lien / Second Lien / Unsecured; DIRECT_LENDING only)
    "lien_position",
    # Instrument type (Revolver / Delayed Draw Term Loan / Term Loan / Unitranche)
    "instrument_type",
    # Normalized position key for multi-tranche disambiguation
    "position_key",
    # Position tracking (populated by --returns step)
    "position_id",
]
# NOTE: the saved artifact carries one column beyond UNIFIED_COLUMNS: row_id,
# appended by _assign_row_ids as the last step of build_unified_holdings.
# It is deliberately NOT in UNIFIED_COLUMNS -- that list doubles as the
# in-flight SQL schema (union/stabilization passes) where row_id does not
# exist yet.

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

    lien_case = lien_classification._sql_classify_lien()

    override_set = {"index_classification", "asset_class", "lien_position"}
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
            {lien_case} AS _rule_lien,
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
           END AS asset_class,
           CASE WHEN _restore_classification
                THEN CASE WHEN _rule_index_classification = 'DIRECT_LENDING'
                          THEN CAST(_rule_lien AS VARCHAR) ELSE NULL END
                ELSE CAST(s.lien_position AS VARCHAR)
           END AS lien_position
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


def _apply_lien_cache(combined: pd.DataFrame) -> pd.DataFrame:
    """Apply cached lien position classifications from lien_cache.csv.

    Runs automatically during --unified so that agent-reviewed lien data
    survives rebuilds.  No LLM calls -- only the on-disk cache is read.
    """
    from pipeline.config import LIEN_CACHE_FILE

    if not LIEN_CACHE_FILE.exists():
        return combined

    result = lien_classification._apply_lien_cache(combined)
    return result


# Mapping from agent asset_class + new_index_classification to unified schema
_AGENT_EXPOSURE_MAP = {
    "FUND": "FUND",
    "LOAN": "DIRECT",
    "EQUITY_COMMON": "DIRECT",
    "EQUITY_PREFERRED": "DIRECT",
    "CASH": "LIQUID",
}

_AGENT_ASSET_CLASS_MAP: dict[tuple[str, str], str] = {
    ("FUND", "HEDGE_FUND"): "HEDGE_FUND",
    ("FUND", "PRIVATE_EQUITY_FUND"): "PRIVATE_EQUITY",
    ("FUND", "PRIVATE_CREDIT_FUND"): "PRIVATE_CREDIT",
    ("FUND", "REAL_ESTATE_FUND"): "REAL_ESTATE",
    ("LOAN", "DIRECT_LENDING"): "PRIVATE_CREDIT",
    ("LOAN", "STRUCTURED_CREDIT"): "STRUCTURED_CREDIT",
    ("EQUITY_COMMON", "COMMON_EQUITY"): "PRIVATE_EQUITY",
    ("EQUITY_PREFERRED", "PREFERRED_EQUITY"): "PRIVATE_EQUITY",
    ("CASH", "CASH"): "CASH",
}


def _apply_unclassified_cache(combined: pd.DataFrame) -> pd.DataFrame:
    """Apply agent-reviewed classifications to UNCLASSIFIED holdings.

    Loads ``unclassified_review_cache.csv`` and applies:
    - CLASSIFIED/AUTO_CLASSIFIED verdicts: reclassify UNCLASSIFIED rows
    - JV_SUBSIDIARY verdicts: flag rows with ``jv_subsidiary='Y'``

    Only updates rows where ``index_classification='UNCLASSIFIED'``.
    Existing classifications are never changed.
    """
    if not UNCLASSIFIED_REVIEW_CACHE_FILE.exists():
        if "jv_subsidiary" not in combined.columns:
            combined["jv_subsidiary"] = ""
        return combined

    from pipeline.gics_classification import _normalize_company_name

    cache = pd.read_csv(UNCLASSIFIED_REVIEW_CACHE_FILE, dtype=str).fillna("")

    # Split into classification and JV lookups
    classify_mask = (
        cache["verdict"].isin(["CLASSIFIED", "AUTO_CLASSIFIED"])
        & cache["confidence"].isin(["high", "medium"])
        & (cache["new_index_classification"] != "")
    )
    jv_mask = cache["verdict"] == "JV_SUBSIDIARY"

    classify_cache = cache.loc[classify_mask, ["name_norm", "new_index_classification", "asset_class"]].copy()
    jv_cache = cache.loc[jv_mask, ["name_norm"]].copy()

    if classify_cache.empty and jv_cache.empty:
        if "jv_subsidiary" not in combined.columns:
            combined["jv_subsidiary"] = ""
        return combined

    # Build classification lookup with derived exposure_type and unified asset_class.
    classify_df = classify_cache.rename(
        columns={
            "new_index_classification": "new_idx",
            "asset_class": "agent_asset_class",
        }
    ).copy()
    classify_df["name_norm"] = classify_df["name_norm"].str.strip()
    classify_df["new_idx"] = classify_df["new_idx"].str.strip()
    classify_df["agent_asset_class"] = classify_df["agent_asset_class"].str.strip()
    classify_df["new_exp"] = (
        classify_df["agent_asset_class"].map(_AGENT_EXPOSURE_MAP).fillna("DIRECT")
    )
    classify_df["new_ac"] = [
        _AGENT_ASSET_CLASS_MAP.get((asset_class, index_classification), "OTHER")
        for asset_class, index_classification in zip(
            classify_df["agent_asset_class"],
            classify_df["new_idx"],
        )
    ]
    classify_df = classify_df[
        ["name_norm", "new_idx", "new_exp", "new_ac"]
    ].drop_duplicates(subset=["name_norm"], keep="first")

    jv_names = set(jv_cache["name_norm"].str.strip().values)

    # Pre-compute normalized issuer_name for matching
    combined = combined.copy()
    combined["_row_idx"] = range(len(combined))
    issuer_col = combined["issuer_name"].fillna("").astype(str)
    combined["_name_norm"] = issuer_col.map(_normalize_company_name)

    # Build JV flag column
    combined["jv_subsidiary"] = ""
    combined.loc[combined["_name_norm"].isin(jv_names), "jv_subsidiary"] = "Y"

    if classify_df.empty:
        combined = combined.drop(columns=["_row_idx", "_name_norm"])
        logger.info("Unclassified cache: 0 classify entries, %d JV flags applied",
                    (combined["jv_subsidiary"] == "Y").sum())
        return combined

    # Use DuckDB for efficient LEFT JOIN reclassification
    con = duckdb.connect()
    con.register("holdings", combined)
    con.register("unclass_lookup", classify_df)

    result = con.execute("""
        SELECT h.* EXCLUDE (index_classification, exposure_type, asset_class,
                            _row_idx, _name_norm),
               CASE WHEN CAST(h.index_classification AS VARCHAR) = 'UNCLASSIFIED'
                         AND ul.new_idx IS NOT NULL
                    THEN ul.new_idx
                    ELSE CAST(h.index_classification AS VARCHAR)
               END AS index_classification,
               CASE WHEN CAST(h.index_classification AS VARCHAR) = 'UNCLASSIFIED'
                         AND ul.new_exp IS NOT NULL
                    THEN ul.new_exp
                    ELSE CAST(h.exposure_type AS VARCHAR)
               END AS exposure_type,
               CASE WHEN CAST(h.index_classification AS VARCHAR) = 'UNCLASSIFIED'
                         AND ul.new_ac IS NOT NULL
                    THEN ul.new_ac
                    ELSE CAST(h.asset_class AS VARCHAR)
               END AS asset_class
        FROM holdings h
        LEFT JOIN unclass_lookup ul ON h._name_norm = ul.name_norm
        ORDER BY h._row_idx
    """).fetchdf()
    con.close()

    # Restore column order (EXCLUDE moves overridden columns to end)
    result = result[[c for c in UNIFIED_COLUMNS if c in result.columns]]

    # Count reclassifications
    before_unclass = (combined["index_classification"].astype(str) == "UNCLASSIFIED").sum()
    after_unclass = (result["index_classification"].astype(str) == "UNCLASSIFIED").sum()
    reclassified = before_unclass - after_unclass
    jv_count = (result["jv_subsidiary"] == "Y").sum()

    logger.info(
        "Unclassified cache: %d classify entries, reclassified %d rows "
        "(UNCLASSIFIED %d -> %d), %d JV flags",
        len(classify_df), reclassified, before_unclass, after_unclass, jv_count,
    )

    return result


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def build_unified_holdings(
    bdc_df: Optional[pd.DataFrame] = None,
    nport_df: Optional[pd.DataFrame] = None,
    *,
    output_file: Optional[Path] = None,
    orphan_file: Optional[Path] = None,
    agent_rules_dir: Optional[Path] = None,
    b2_corrections_dir: Optional[Path] = None,
) -> pd.DataFrame:
    """Build unified private markets holdings from BDC + N-PORT data.

    If DataFrames are not provided, reads from disk (BDC_HOLDINGS_FILE,
    NPORT_HOLDINGS_FILE).

    Parameters
    ----------
    output_file : Path, optional
        Write the unified CSV (and parquet companion) to this path instead
        of the default ``UNIFIED_HOLDINGS_FILE``.
    orphan_file : Path, optional
        Write orphan holdings to this path instead of the default
        ``UNIVERSE_ORPHAN_HOLDINGS_FILE``.
    agent_rules_dir, b2_corrections_dir : Path, optional
        Promoted agent-fix stores (gap 1). Default to the config stores
        (``AGENT_INVESTIGATE_RULES_DIR`` / ``AGENT_B2_CORRECTIONS_DIR``);
        fixture-based tests pass an empty directory so promoted production
        fixes never leak into fixtures that use real CIKs. Every application
        is audited to ``agent_fix_application_audit.csv`` next to the output.

    Returns the combined DataFrame and saves to *output_file* (or the
    default production path).
    """
    t0 = time.time()

    # Promoted agent fixes (gap 1): Layer B (raw-staging comparative filters) applies
    # inside BDC staging while the frame still carries XBRL `period`; Layer C
    # (investigator rules) applies at the tail. One code path for production, trial,
    # and rebuild_outputs -- parity by construction.
    from pipeline import agent_promoted
    _agent_fix_audits: list[dict] = []
    _raw_exclusions = agent_promoted.raw_staging_exclusions(
        agent_promoted.load_promoted_corrections(b2_corrections_dir))

    # Prepare BDC: prefer Parquet > CSV file path (DuckDB direct read)
    # over pandas DataFrame.  This bypasses the slow pandas CSV parse +
    # DuckDB registration path that was the main staging bottleneck.
    if bdc_df is None:
        bdc_file = (
            BDC_HOLDINGS_PARQUET_FILE
            if BDC_HOLDINGS_PARQUET_FILE.exists()
            else BDC_HOLDINGS_FILE
        )
        logger.info("Loading BDC holdings from %s (via DuckDB)", bdc_file.name)
        bdc_unified = staging_bdc._prepare_bdc(
            bdc_file=bdc_file, raw_exclusions=_raw_exclusions,
            raw_exclusion_audits=_agent_fix_audits)
    else:
        bdc_unified = staging_bdc._prepare_bdc(
            bdc_df=bdc_df, raw_exclusions=_raw_exclusions,
            raw_exclusion_audits=_agent_fix_audits)

    # Prepare N-PORT: same pattern -- file path for DuckDB direct read.
    nport_input: Union[pd.DataFrame, Path]
    if nport_df is None:
        nport_file = (
            NPORT_HOLDINGS_PARQUET_FILE
            if NPORT_HOLDINGS_PARQUET_FILE.exists()
            else NPORT_HOLDINGS_FILE
        )
        logger.info("Loading N-PORT holdings from %s (via DuckDB)", nport_file.name)
        nport_input = nport_file
    else:
        nport_input = nport_df
    nport_unified = staging_nport._prepare_nport(nport_input)
    _out_file = output_file or UNIFIED_HOLDINGS_FILE
    _orphan_file = orphan_file or (UNIFIED_HOLDINGS_FILE.parent / UNIVERSE_ORPHAN_HOLDINGS_FILE.name)
    if bdc_unified.empty and nport_unified.empty:
        combined = pd.DataFrame(columns=UNIFIED_COLUMNS)
        _write_empty_orphan_report(_orphan_file)
        _out_file.parent.mkdir(parents=True, exist_ok=True)
        combined.to_csv(_out_file, index=False)
        logger.info("Unified holdings built with no eligible rows")
        return combined

    # Combine via DuckDB UNION ALL + index classification
    con = duckdb.connect()
    con.register("bdc_part", bdc_unified)
    con.register("nport_part", nport_unified)

    idx_case = classification._sql_classify_index()
    exposure_case = classification._sql_classify_exposure_type()
    asset_class_case = classification._sql_classify_asset_class()
    lien_case = lien_classification._sql_classify_lien()
    instr_case = instrument_classification._sql_classify_instrument_type()
    _special_cols = {
        "index_classification", "exposure_type", "asset_class", "lien_position",
        "instrument_type",
        "principal_amount", "principal_amount_usd", "principal_fx_status", "cusip",
    }
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
                    COALESCE(CAST(shares_held AS VARCHAR), ''),
                    COALESCE(CAST(nport_holding_id AS VARCHAR), ''),
                    COALESCE(CAST(accession_number AS VARCHAR), '')
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
                    COALESCE(CAST(shares_held AS VARCHAR), ''),
                    COALESCE(CAST(src_context_id AS VARCHAR), ''),
                    COALESCE(CAST(nport_holding_id AS VARCHAR), '')
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
                    COALESCE(CAST(accession_number AS VARCHAR), ''),
                    COALESCE(CAST(src_context_id AS VARCHAR), '')
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
            {asset_class_case} AS _asset_class,
            -- Keyword classifier first; fall back to the iXBRL section-header lien
            -- (staging lien_position is populated ONLY by the reconciled iXBRL
            -- field-status overlay, so this is additive: it fills lien where the
            -- keyword rule is blank without overriding existing classifications).
            COALESCE(NULLIF(TRIM({lien_case}), ''), NULLIF(TRIM(lien_position), '')) AS _lien_raw,
            -- Instrument type from row text (keyword), falling back to any staged
            -- value. Applies to all rows; the keywords only fire on debt products.
            COALESCE(NULLIF(TRIM({instr_case}), ''), NULLIF(TRIM(instrument_type), '')) AS _instr_raw
        FROM with_fund_text
    ),
    -- Cost proxy: fill NULL/zero cost with first observed fair_value
    -- for that specific position, ordered by report_date.  The partition
    -- key includes instrument_description and cusip so each tranche gets
    -- its own proxy (e.g. Term Loan A vs Term Loan B).  The tiebreaker
    -- fair_value and the anchor keys src_context_id / nport_holding_id
    -- make the result deterministic when multiple rows share the earliest
    -- report_date.  (Amended per tiebreak-hardening plan to append anchor
    -- keys after the existing ORDER BY keys.)
    --
    -- Provenance: when the proxy fires (original cost NULL/zero but a
    -- non-zero FV proxy is available), cost_source is set to
    -- 'derived_proxy' and 'cost:cost_proxy_fv' is appended to
    -- src_transforms.  Rows with a real non-zero cost keep cost_source
    -- and src_transforms unchanged.
    with_cost AS (
        SELECT * EXCLUDE (cost, cost_source, src_transforms, _cost_orig, _cost_proxy),
            COALESCE(_cost_orig, _cost_proxy) AS cost,
            CASE WHEN _cost_orig IS NULL AND _cost_proxy IS NOT NULL
                 THEN 'derived_proxy'
                 ELSE cost_source
            END AS cost_source,
            CASE WHEN _cost_orig IS NULL AND _cost_proxy IS NOT NULL
                 THEN concat_ws(';', NULLIF(src_transforms, ''), 'cost:cost_proxy_fv')
                 ELSE src_transforms
            END AS src_transforms
        FROM (
            SELECT *,
                NULLIF(TRY_CAST(cost AS DOUBLE), 0) AS _cost_orig,
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
                        COALESCE(CAST(shares_held AS VARCHAR), ''),
                        COALESCE(CAST(src_context_id AS VARCHAR), ''),
                        COALESCE(CAST(nport_holding_id AS VARCHAR), '')
                    ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
                ) AS _cost_proxy
            FROM classified
        )
    ),
    -- Shares normalization: detect power-of-10 unit mismatches within
    -- the same position (cik + issuer_name) by comparing each row's
    -- per-unit price (fair_value / shares_held) against the group median.
    -- Outliers are replaced with the nearest non-outlier shares value.
    -- The window ORDER BY terminates with anchor keys src_context_id /
    -- nport_holding_id for deterministic donor selection on ties.
    -- (Amended per tiebreak-hardening plan; prior byte-identical contract
    -- from the provenance migration is hereby superseded.)
    --
    -- Provenance: when the outlier flag fires, shares_held_source is set
    -- to 'derived_proxy' and 'shares_held:pow10_shares' is appended to
    -- src_transforms.  Non-outlier rows keep both columns unchanged.
    with_shares_fix AS (
        SELECT * EXCLUDE (shares_held, shares_held_source, src_transforms),
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
                            COALESCE(CAST(_sh_val AS VARCHAR), ''),
                            COALESCE(CAST(src_context_id AS VARCHAR), ''),
                            COALESCE(CAST(nport_holding_id AS VARCHAR), '')
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
                            COALESCE(CAST(_sh_val AS VARCHAR), ''),
                            COALESCE(CAST(src_context_id AS VARCHAR), ''),
                            COALESCE(CAST(nport_holding_id AS VARCHAR), '')
                        ROWS BETWEEN 1 FOLLOWING AND UNBOUNDED FOLLOWING)
                )
                ELSE _sh_val
            END AS shares_held,
            CASE WHEN _is_outlier THEN 'derived_proxy'
                 ELSE shares_held_source
            END AS shares_held_source,
            CASE WHEN _is_outlier
                 THEN concat_ws(';', NULLIF(src_transforms, ''), 'shares_held:pow10_shares')
                 ELSE src_transforms
            END AS src_transforms
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
        CASE WHEN _index_class IN (
                 'COMMON_EQUITY', 'PREFERRED_EQUITY',
                 'PRIVATE_EQUITY_FUND', 'PRIVATE_CREDIT_FUND',
                 'REAL_ESTATE_FUND', 'HEDGE_FUND'
             ) THEN NULL ELSE principal_amount_usd END AS principal_amount_usd,
        CASE WHEN _index_class IN (
                 'COMMON_EQUITY', 'PREFERRED_EQUITY',
                 'PRIVATE_EQUITY_FUND', 'PRIVATE_CREDIT_FUND',
                 'REAL_ESTATE_FUND', 'HEDGE_FUND'
             ) THEN '' ELSE principal_fx_status END AS principal_fx_status,
        _index_class AS index_classification,
        _exposure_type AS exposure_type,
        _asset_class AS asset_class,
        CASE WHEN _index_class = 'DIRECT_LENDING' THEN _lien_raw
             ELSE NULL END AS lien_position,
        _instr_raw AS instrument_type
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

    combined = _apply_universe_gate(combined, orphan_path=_orphan_file)

    # Log subsidiary stats
    if "is_subsidiary" in combined.columns:
        sub_count = (combined["is_subsidiary"].astype(str) == "1").sum()
        if sub_count > 0:
            logger.info("  Subsidiary positions: %d rows flagged (is_subsidiary=1)", sub_count)

    # Entity enrichment: join against existing entity_lookup if available
    if ENTITY_LOOKUP_FILE.exists() and not combined.empty:
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
    if IDENTIFIER_EXTRACTION_LOOKUP_FILE.exists() and not combined.empty:
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

    # Fund-level asset_class override for RE-strategy funds (runs last so it
    # catches everything the row-level correction system missed)
    combined = _apply_fund_strategy_asset_class_override(combined)

    # Promoted B2 stage-2 corrections (2026-08-13, gap-1 Layer B post-staging): the
    # non-comparative correction classes apply to the unified frame here, per CIK,
    # BDC rows only -- BEFORE Layer C rules so rules see corrected values. The
    # comparative_period_filter family already applied at raw staging above.
    _promoted_corrections = agent_promoted.load_promoted_corrections(b2_corrections_dir)
    if _promoted_corrections:
        combined, _b2_audits = agent_promoted.apply_promoted_stage2_corrections(
            combined, _promoted_corrections)
        _agent_fix_audits.extend(_b2_audits)

    # Promoted investigator rules (gap 1 Layer C): gate-PASS rules from the audited
    # override store, applied per CIK to BDC-source rows only. Runs after
    # classification (rule predicates reference unified-frame columns) and before the
    # write, so validation, position matching, and frontend export all see corrected
    # data -- no forked views.
    _promoted_rules = agent_promoted.load_promoted_rules(agent_rules_dir)
    if _promoted_rules:
        combined, _rule_audits = agent_promoted.apply_promoted_rules(combined, _promoted_rules)
        _agent_fix_audits.extend(_rule_audits)

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

    # Apply cached lien position classifications (if cache exists on disk)
    combined = _apply_lien_cache(combined)

    # Apply agent-reviewed unclassified reclassifications + JV flags
    combined = _apply_unclassified_cache(combined)

    # Override position_key with wrapper-generated keys for wrapped BDC CIKs
    combined = _apply_wrapper_position_keys(combined)

    # Remap GICS sub-industry for RE-strategy fund holdings (runs after
    # _apply_gics_cache so that the LLM-assigned codes are already in place)
    combined = _apply_re_fund_gics_overrides(combined)

    # Rebuild-time agent-fix audit: per-rule matched rows + FV deltas vs the rule's
    # authoring-time measured_impact. Written whenever any promoted store is non-empty
    # (drift there is the re-validation trigger; nothing promoted -> no artifact).
    if _raw_exclusions or _promoted_rules:
        agent_promoted.write_application_audit(
            _agent_fix_audits, _out_file.parent / "agent_fix_application_audit.csv")

    # Rebuild-stable per-row identifier, computed on the FINAL frame (after all
    # correction/cache layers) so the id reflects the row as published.
    combined = _assign_row_ids(combined)

    # Save CSV + Parquet companion
    _out_file.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(_out_file, index=False)
    logger.info("Saved to %s (%.1f MB)",
                _out_file.name,
                _out_file.stat().st_size / (1024 * 1024))
    from pipeline.utils import write_parquet_companion
    write_parquet_companion(_out_file)

    # Log summary statistics
    _log_summary(combined)

    elapsed = time.time() - t0
    logger.info("Unified holdings built in %.1f s", elapsed)

    return combined


def _assign_row_ids(df: pd.DataFrame) -> pd.DataFrame:
    """Populate ``row_id`` and ``row_id_basis`` (appended, not in UNIFIED_COLUMNS).

    ``row_id`` = ``ROW-`` + first 16 hex chars of md5 over the row's source
    anchor when one exists (``row_id_basis='src_anchor'``):

        bdc:   source|accession_number|src_context_id
        nport: source|accession_number|nport_holding_id

    The anchor names the filing fact context (accessions are immutable), so
    the id survives rebuilds, staging reorders, value corrections, and parser
    fixes. It is an as-filed claim: an amendment (new accession) is a new id.
    Rows missing accession or the per-source anchor part fall back to the
    legacy drift-resistant natural key from
    ``position_id_registry.compute_natural_keys``
    (``row_id_basis='natural_key'``; content-sensitive by design).

    NOT a cross-quarter identity -- ``position_id`` owns that layer.
    """
    if df.empty:
        df["row_id"] = pd.Series(dtype=str)
        df["row_id_basis"] = pd.Series(dtype=str)
        return df
    from pipeline.position_id_registry import compute_natural_keys

    def _col(name: str) -> pd.Series:
        if name in df.columns:
            return df[name].fillna("").astype(str).str.strip()
        return pd.Series("", index=df.index, dtype=str)

    source = _col("source").str.lower()
    accession = _col("accession_number")
    anchor_part = _col("src_context_id").where(
        source.ne("nport"), _col("nport_holding_id"))
    has_anchor = accession.ne("") & anchor_part.ne("")

    keys = (source + "|" + accession + "|" + anchor_part).where(
        has_anchor, compute_natural_keys(df))
    # Reset to RangeIndex so rank_frame construction aligns by position, not
    # by the caller frame's (potentially non-contiguous) index labels.
    keys = keys.reset_index(drop=True)

    def _col_r(name: str) -> pd.Series:
        """Like _col but always RangeIndex-aligned (safe inside rank_frame)."""
        s = _col(name)
        return s.reset_index(drop=True)

    # Collision suffix: rows sharing an anchor key get content-ranked |dup<k>
    # suffixes (k>=1); rank 0 keeps the bare key so existing ids never change.
    # Content rank (not frame order) keeps the ids rebuild-stable.
    #
    # For each content column we add a null-indicator (0=value present,
    # 1=null/empty) sorted BEFORE the stringified value so that null rows
    # always rank LAST within a collision group.
    def _null_ind(series: pd.Series) -> pd.Series:
        """Return 0 where series has a non-empty value, 1 where null/empty."""
        return series.eq("").astype("int8")

    fv = _col_r("fair_value")
    cost = _col_r("cost")
    pa = _col_r("principal_amount")
    sh = _col_r("shares_held")
    bid = _col_r("bdc_investment_identifier")
    rank_frame = pd.DataFrame({
        "k": keys,
        "_fv_null": _null_ind(fv),   "_fv": fv,
        "_co_null": _null_ind(cost),  "_cost": cost,
        "_pa_null": _null_ind(pa),    "_pa": pa,
        "_sh_null": _null_ind(sh),    "_sh": sh,
        "_bi_null": _null_ind(bid),   "_bid": bid,
    })
    dup_rank = (
        rank_frame
        .sort_values(
            ["k", "_fv_null", "_fv",
             "_co_null", "_cost",
             "_pa_null", "_pa",
             "_sh_null", "_sh",
             "_bi_null", "_bid"],
            kind="mergesort",
        )
        .groupby("k")          # sort=True (default) -- stable re-sort on key only
        .cumcount()
        .reindex(rank_frame.index)
    )
    keys = keys.where(dup_rank == 0, keys + "|dup" + dup_rank.astype(str))

    con = duckdb.connect()
    con.register("nk", pd.DataFrame({"i": range(len(keys)), "k": keys}))
    hashed = con.execute(
        "SELECT 'ROW-' || substr(md5(k), 1, 16) AS row_id FROM nk ORDER BY i"
    ).fetchdf()["row_id"]
    df["row_id"] = hashed.values
    df["row_id_basis"] = has_anchor.map(
        {True: "src_anchor", False: "natural_key"}).values
    n_anchor = int(has_anchor.sum())
    n_dup = int(df["row_id"].duplicated().sum())
    if n_dup:
        logger.warning(
            "row_id uniqueness violated on %d rows after "
            "collision suffixing -- investigate", n_dup)
    logger.info("row_id: %d assigned (%d src_anchor, %d natural_key)",
                len(df), n_anchor, len(df) - n_anchor)
    return df


def _apply_fund_strategy_corrections(
    df: pd.DataFrame,
    candidates_path: Optional[Path] = None,
) -> pd.DataFrame:
    """Apply fund strategy correction candidates from disk (if file exists).

    Loads the correction candidates CSV, delegates to
    ``fund_strategy_validation.apply_fund_strategy_correction_candidates``
    which handles APPLY filtering, excluded-transition guards, and DuckDB join.

    When a per-pass PINNED copy exists (written by the run_quarter_pass pin stage),
    it takes precedence over the live file: the validate stage regenerates the live
    candidates from CURRENT holdings, so consuming them directly feeds validation
    output back into the next rebuild and oscillates marginal classifications
    (~20 non-corrected CIKs, 2026-08-13 known residual). The pin freezes the
    inputs for the whole pass round.
    """
    path = candidates_path
    if path is None:
        path = (FUND_STRATEGY_CORRECTION_CANDIDATES_PINNED_FILE
                if FUND_STRATEGY_CORRECTION_CANDIDATES_PINNED_FILE.exists()
                else FUND_STRATEGY_CORRECTION_CANDIDATES_FILE)
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


# Asset classes that should NOT be overridden by the fund-level RE strategy.
_RE_OVERRIDE_BLOCKED_ASSET_CLASSES = frozenset({"CASH", "STRUCTURED_CREDIT", "HEDGE_FUND"})


def _apply_fund_strategy_asset_class_override(
    df: pd.DataFrame,
    reference_path: Optional[Path] = None,
) -> pd.DataFrame:
    """Override asset_class to REAL_ESTATE for all holdings in RE-strategy funds.

    The row-level classification system assigns asset_class based on instrument
    type (loans -> PRIVATE_CREDIT, equity -> PRIVATE_EQUITY) without considering
    the underlying collateral.  Real estate mortgage loans, mezzanine loans, and
    property SPV equity are indistinguishable from corporate credit/equity at the
    row level.

    This fund-level override sets asset_class='REAL_ESTATE' for all positions in
    funds whose strategy is REAL_ESTATE, except positions with asset_class in
    {CASH, STRUCTURED_CREDIT, HEDGE_FUND} which are explicitly blocked.

    index_classification and exposure_type are left unchanged -- the instrument
    type is correct, only the asset_class dimension needs the fund-level signal.
    """
    path = reference_path or FUND_STRATEGY_REFERENCE_FILE
    if not path.exists():
        logger.info("Fund strategy asset_class override: no reference file, skipping")
        return df

    if df.empty:
        return df

    ref = pd.read_csv(path, dtype=str).fillna("")
    if ref.empty or "strategy" not in ref.columns or "cik" not in ref.columns:
        return df

    re_ciks = set(
        ref.loc[ref["strategy"] == "REAL_ESTATE", "cik"]
        .str.strip()
        .str.zfill(10)
    )
    if not re_ciks:
        return df

    blocked = _RE_OVERRIDE_BLOCKED_ASSET_CLASSES
    norm_cik = df["cik"].astype(str).str.strip().str.zfill(10)
    mask = norm_cik.isin(re_ciks) & ~df["asset_class"].isin(blocked)

    n_affected = mask.sum()
    if n_affected == 0:
        logger.info("Fund strategy asset_class override: 0 rows matched RE-strategy CIKs")
        return df

    # Log breakdown by previous asset_class
    prev_classes = df.loc[mask, "asset_class"].value_counts()
    fv_affected = pd.to_numeric(df.loc[mask, "fair_value"], errors="coerce").sum()
    logger.info(
        "Fund strategy asset_class override: %d rows (FV $%.1fB) across %d RE-strategy CIKs",
        n_affected,
        fv_affected / 1e9 if pd.notna(fv_affected) else 0,
        norm_cik[mask].nunique(),
    )
    for cls, count in prev_classes.items():
        if cls != "REAL_ESTATE":
            logger.info("  %s -> REAL_ESTATE: %d rows", cls, count)

    df.loc[mask, "asset_class"] = "REAL_ESTATE"

    return df


# GICS sub-industry remapping for holdings in RE-strategy funds.
# The LLM classifier assigns GICS based on issuer name without fund context,
# so e.g. "BX Trust 2022-GPA" (a CMBS trust) gets "Asset Management & Custody
# Banks" instead of a mortgage-finance code.  These 11 rules correct the most
# common misclassifications (693 rows, $33.6B FV).
_RE_FUND_GICS_REMAP = {
    "Diversified Financial Services": "Diversified Real Estate Activities",
    "Publishing": "Diversified Real Estate Activities",
    "Industrial Conglomerates": "Industrial REITs",
    "Diversified Support Services": "Industrial REITs",
    "Asset Management & Custody Banks": "Commercial & Residential Mortgage Finance",
    "Health Care Facilities": "Health Care REITs",
    "Health Care Equipment": "Health Care REITs",
    "Agricultural Products & Services": "Diversified Real Estate Activities",
    "Air Freight & Logistics": "Industrial REITs",
    "Health Care Services": "Health Care REITs",
    "Data Processing & Outsourced Services": "Data Center REITs",
}


def _apply_wrapper_position_keys(df: pd.DataFrame) -> pd.DataFrame:
    """Override position_key with wrapper-generated keys for wrapped BDC CIKs.

    For BDC rows where the wrapper classifies the identifier as a position
    leaf and produces a non-empty ``wrapper_position_key``, replace the
    generic staging ``position_key`` with the wrapper's per-CIK curated key.
    The wrapper applies CIK-specific rules (``canonical_strip_re``,
    ``identifier_format``, etc.) that the one-size-fits-all staging SQL
    cannot.  Non-wrapped CIKs and N-PORT rows are unaffected.
    """
    from pipeline.bdc_xbrl_wrapper import add_bdc_xbrl_wrapper_columns

    if df.empty or "source" not in df.columns:
        return df

    bdc_mask = df["source"].eq("bdc")
    if not bdc_mask.any() or "bdc_investment_identifier" not in df.columns:
        return df

    bdc_rows = df.loc[bdc_mask].copy()
    wrapped = add_bdc_xbrl_wrapper_columns(
        bdc_rows,
        identifier_col="bdc_investment_identifier",
        cik_col="cik",
    )

    # Only override where wrapper produced a position leaf with a key
    has_key = (
        wrapped["wrapper_position_key"].ne("")
        & wrapped["wrapper_disposition"].str.endswith("_position_leaf", na=False)
    )
    override_count = has_key.sum()
    if override_count > 0:
        df.loc[has_key[has_key].index, "position_key"] = (
            wrapped.loc[has_key, "wrapper_position_key"]
        )
        df = _append_duplicate_wrapper_lot_keys(df, has_key[has_key].index)
        logger.info(
            "  Wrapper position_key override: %d rows across %d CIKs",
            override_count,
            df.loc[has_key[has_key].index, "cik"].nunique(),
        )
    return df


def _append_duplicate_wrapper_lot_keys(
    df: pd.DataFrame,
    candidate_index: pd.Index,
) -> pd.DataFrame:
    """Append deterministic lot suffixes for repeated wrapper keys.

    Some BDC XBRL schedules disclose multiple separate rows with the same
    issuer, spread, and maturity. For configured CIKs, keep those rows as
    separate position-level constituents by ranking repeated wrapper keys
    within a CIK/source/report-date group. The suffix is applied only to keys
    that would otherwise repeat in that quarter.
    """
    required = {
        "cik", "source", "report_date", "position_key",
        "principal_amount", "fair_value", "cost",
    }
    if df.empty or not required.issubset(df.columns):
        return df

    cik_norm = (
        df["cik"].astype(str)
        .str.replace(r"[^0-9]", "", regex=True)
        .str.zfill(10)
    )
    candidate_mask = df.index.isin(candidate_index)
    scoped = (
        candidate_mask
        & cik_norm.isin(WRAPPER_DUPLICATE_LOT_KEY_CIKS)
        & df["position_key"].astype(str).ne("")
    )
    if not scoped.any():
        return df

    key_cols = ["cik", "source", "report_date", "position_key"]
    group_sizes = df.loc[scoped].groupby(key_cols, dropna=False)["position_key"].transform("size")
    duplicate_index = group_sizes[group_sizes.gt(1)].index
    if len(duplicate_index) == 0:
        return df

    work = df.loc[duplicate_index, key_cols + ["principal_amount", "fair_value", "cost"]].copy()
    work["_principal_abs"] = pd.to_numeric(work["principal_amount"], errors="coerce").abs().fillna(-1)
    work["_fair_value_abs"] = pd.to_numeric(work["fair_value"], errors="coerce").abs().fillna(-1)
    work["_cost_abs"] = pd.to_numeric(work["cost"], errors="coerce").abs().fillna(-1)
    work["_source_index"] = range(len(work))
    work = work.sort_values(
        key_cols + ["_principal_abs", "_fair_value_abs", "_cost_abs", "_source_index"],
        ascending=[True, True, True, True, False, False, False, True],
        kind="mergesort",
    )
    work["_lot_rank"] = work.groupby(key_cols, dropna=False).cumcount() + 1
    suffix = " lot " + work["_lot_rank"].astype(str)
    df.loc[work.index, "position_key"] = df.loc[work.index, "position_key"].astype(str) + suffix
    return df


def _apply_re_fund_gics_overrides(
    df: pd.DataFrame,
    reference_path: Optional[Path] = None,
) -> pd.DataFrame:
    """Override GICS sub-industry for holdings in RE-strategy funds.

    The LLM GICS classifier assigns codes based on issuer name without fund
    context.  For RE-strategy funds, many holdings have misleading names
    (e.g. "Industrial - Lambert Farms" -> "Industrial Conglomerates" when it
    is actually a warehouse property).  This remaps the 11 most common
    misclassified GICS sub-industries to their correct RE-sector equivalents.

    Only applies to holdings where:
    - The fund CIK is in the RE-strategy set (from fund_strategy_reference.csv)
    - The current gics_sub_industry matches one of the 11 remapping rules
    """
    path = reference_path or FUND_STRATEGY_REFERENCE_FILE
    if not path.exists():
        logger.info("RE fund GICS override: no reference file, skipping")
        return df

    if df.empty:
        return df

    ref = pd.read_csv(path, dtype=str).fillna("")
    if ref.empty or "strategy" not in ref.columns or "cik" not in ref.columns:
        return df

    re_ciks = set(
        ref.loc[ref["strategy"] == "REAL_ESTATE", "cik"]
        .str.strip()
        .str.zfill(10)
    )
    if not re_ciks:
        return df

    norm_cik = df["cik"].astype(str).str.strip().str.zfill(10)
    gics_col = df.get("gics_sub_industry")
    if gics_col is None:
        return df

    mask = norm_cik.isin(re_ciks) & gics_col.isin(_RE_FUND_GICS_REMAP)

    n_affected = mask.sum()
    if n_affected == 0:
        logger.info("RE fund GICS override: 0 rows matched")
        return df

    # Log breakdown by old -> new GICS
    old_gics = df.loc[mask, "gics_sub_industry"].value_counts()
    fv_affected = pd.to_numeric(df.loc[mask, "fair_value"], errors="coerce").sum()
    logger.info(
        "RE fund GICS override: %d rows (FV $%.1fB) remapped",
        n_affected,
        fv_affected / 1e9 if pd.notna(fv_affected) else 0,
    )
    for old_val, count in old_gics.items():
        new_val = _RE_FUND_GICS_REMAP[old_val]
        logger.info("  %s -> %s: %d rows", old_val, new_val, count)

    df.loc[mask, "gics_sub_industry"] = df.loc[mask, "gics_sub_industry"].map(
        _RE_FUND_GICS_REMAP
    )

    return df


# Fields that row_corrections.csv is allowed to override.
_CORRECTABLE_FIELDS = frozenset({
    "fair_value", "cost", "principal_amount", "principal_amount_usd",
    "principal_amount_currency", "principal_fx_rate_to_usd", "principal_fx_status",
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
            if "corrected_fields" in df.columns:
                from pipeline.agent_promoted import append_corrected_fields
                append_corrected_fields(df, df.index[mask], [field])
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

    missing_columns = [col for col in UNIFIED_COLUMNS if col not in df.columns]
    if missing_columns:
        df = df.copy()
        for col in missing_columns:
            df[col] = ""

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
        ("principal_usd_not_negative",
         "SELECT COUNT(*) FROM unified"
         " WHERE TRY_CAST(principal_amount_usd AS DOUBLE) IS NOT NULL"
         "   AND TRY_CAST(principal_amount_usd AS DOUBLE) < 0"),

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

    _log_fx_coverage(df)

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


def _log_fx_coverage(df: pd.DataFrame) -> None:
    """Log USD-normalized principal coverage for rows with source-native par."""
    if df.empty or "principal_amount" not in df.columns:
        return

    principal = pd.to_numeric(df.get("principal_amount"), errors="coerce")
    principal_usd = pd.to_numeric(df.get("principal_amount_usd"), errors="coerce")
    fair_value = pd.to_numeric(df.get("fair_value"), errors="coerce").fillna(0)
    currency = df.get("principal_amount_currency", pd.Series("", index=df.index))
    currency = currency.fillna("").astype(str).str.upper().str.strip()

    has_principal = principal.notna()
    non_usd = has_principal & ~currency.isin(["", "USD"])
    converted = has_principal & principal_usd.notna()
    missing = has_principal & principal_usd.isna()
    affected_fv = float(fair_value[non_usd].sum())
    total_fv = float(fair_value.sum())
    affected_share = affected_fv / total_fv if total_fv else 0

    logger.info(
        "  Principal FX coverage: %d rows with principal, %d non-USD, "
        "%d converted, %d missing USD principal, %.2f%% FV non-USD affected",
        int(has_principal.sum()),
        int(non_usd.sum()),
        int((non_usd & converted).sum()),
        int((non_usd & missing).sum()),
        affected_share * 100,
    )
