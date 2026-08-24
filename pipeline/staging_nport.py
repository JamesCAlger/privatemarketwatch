"""N-PORT holdings staging for the unified holdings pipeline."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Union

import duckdb
import pandas as pd

from pipeline.classification import (
    _NPORT_ASSET_MAP,
    _NPORT_CREDIT_FUND_NAME_KEYWORDS,
    _NPORT_FUND_NAME_KEYWORDS,
    _NPORT_GOVT_NAME_RE,
    _NPORT_ISSUER_MAP,
    _NPORT_LP_FUND_CO_KEYWORDS,
    _sql_normalize_name,
)

logger = logging.getLogger(__name__)


def _prepare_nport(nport_input: Union[pd.DataFrame, Path, str]) -> pd.DataFrame:
    """Filter to Level 3, classify, and map N-PORT holdings to unified schema.

    Uses a DuckDB CTE pipeline for all data manipulation.

    Parameters
    ----------
    nport_input : pd.DataFrame | Path | str
        Either a pre-loaded DataFrame or a path to the N-PORT CSV file.
        When a path is provided, the CSV is loaded directly by DuckDB
        (avoids pandas memory overhead for large files).
    """
    from pipeline.unified_holdings import UNIFIED_COLUMNS

    con = duckdb.connect()
    _nport_loaded_from_file = False

    if isinstance(nport_input, (str, Path)):
        _nport_loaded_from_file = True
        nport_path = str(nport_input).replace("\\", "/")
        # Use CREATE TABLE (not VIEW) so DuckDB loads the file once into its
        # memory-efficient columnar format.  A VIEW would re-scan the file
        # for every downstream query.
        if str(nport_input).endswith(".parquet"):
            read_expr = f"read_parquet('{nport_path}')"
        else:
            read_expr = f"read_csv_auto('{nport_path}', header=true, all_varchar=true)"
        con.execute(f"CREATE TABLE nport_raw AS SELECT * FROM {read_expr}")
        row_count = con.execute("SELECT COUNT(*) FROM nport_raw").fetchone()[0]
        logger.info("Preparing N-PORT holdings: %d input rows", row_count)
        if row_count == 0:
            con.close()
            return pd.DataFrame(columns=UNIFIED_COLUMNS)

        # Ensure expected columns exist (handles older nport_holdings.csv)
        existing_cols = {r[0] for r in con.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'nport_raw'"
        ).fetchall()}
        for col in ["are_any_interest_payment",
                     "is_any_portion_interest_paid",
                     "liquidity_classification",
                     "is_default", "currency_code", "exchange_rate"]:
            if col not in existing_cols:
                con.execute(f"ALTER TABLE nport_raw ADD COLUMN {col} VARCHAR DEFAULT ''")
    else:
        nport_df = nport_input
        logger.info("Preparing N-PORT holdings: %d input rows", len(nport_df))
        if nport_df.empty:
            con.close()
            return pd.DataFrame(columns=UNIFIED_COLUMNS)

        # Ensure expected columns exist (handles older nport_holdings.csv)
        for col in ["are_any_interest_payment", "is_any_portion_interest_paid",
                     "liquidity_classification", "is_default", "currency_code",
                     "exchange_rate"]:
            if col not in nport_df.columns:
                nport_df[col] = ""

        con.register("nport_raw", nport_df)

    # Build CASE WHEN for asset_cat mapping
    asset_cases = "\n".join(
        f"        WHEN upper(trim(asset_cat)) = '{code}' THEN '{cat}'"
        for code, cat in _NPORT_ASSET_MAP.items()
    )
    # Build CASE WHEN for issuer_type mapping
    issuer_cases = "\n".join(
        f"        WHEN upper(trim(issuer_type)) = '{code}' THEN '{cat}'"
        for code, cat in _NPORT_ISSUER_MAP.items()
    )

    # Build fund-name keyword SQL for N-PORT fund detection
    fund_kw_checks = " OR ".join(
        f"contains(lower(issuer_name), '{kw}')" for kw in _NPORT_FUND_NAME_KEYWORDS
    )
    # Build credit-fund-name keyword SQL for EC+CORPORATE -> FUND reclassification
    credit_fund_kw_checks = " OR ".join(
        f"contains(lower(issuer_name), '{kw}')" for kw in _NPORT_CREDIT_FUND_NAME_KEYWORDS
    )
    # Build L.P. fund co-keyword SQL (L.P. only triggers FUND when paired with these)
    lp_co_kw_checks = " OR ".join(
        f"contains(lower(issuer_name), '{kw}')" for kw in _NPORT_LP_FUND_CO_KEYWORDS
    )
    # Fall back to issuer_title when issuer_name is NULL/empty or a placeholder
    # such as "NC" (rescues issuer/title filings that otherwise produce
    # non-identifying keys like "nc nc").
    _name_coalesce = (
        "COALESCE(NULLIF(TRIM(CASE "
        "WHEN upper(trim(CAST(issuer_name AS VARCHAR))) IN "
        "('', 'N/A', 'NA', 'NONE', 'NULL', 'UNKNOWN', 'NC') "
        "THEN '' ELSE CAST(issuer_name AS VARCHAR) END), ''), issuer_title)"
    )
    name_norm = _sql_normalize_name(_name_coalesce)

    sql = f"""
    WITH
    -- CTE 1: Filter to Level 3 or NULL/empty fair_value_level
    level3 AS (
        SELECT *, ROW_NUMBER() OVER (ORDER BY accession_number, holding_id) AS _row_id
        FROM nport_raw
        WHERE TRY_CAST(fair_value_level AS INTEGER) = 3
           OR fair_value_level IS NULL
           OR TRIM(CAST(fair_value_level AS VARCHAR)) = ''
    ),

    -- CTE 1b: Filter out negative fair_value rows (borrowings/liabilities)
    no_negative_fv AS (
        SELECT * FROM level3
        WHERE TRY_CAST(currency_value AS DOUBLE) >= 0
           OR TRY_CAST(currency_value AS DOUBLE) IS NULL
    ),

    -- CTE 1c: Require fair value (removes derivatives/stubs with no FV)
    has_fv AS (
        SELECT * FROM no_negative_fv
        WHERE TRY_CAST(currency_value AS DOUBLE) IS NOT NULL
    ),

    -- CTE 2: Classify assets
    with_asset AS (
        SELECT *,
            CASE
{asset_cases}
                ELSE 'OTHER'
            END AS asset_category
        FROM has_fv
    ),

    -- CTE 3: Classify issuers
    with_issuer AS (
        SELECT *,
            CASE
{issuer_cases}
                ELSE 'OTHER'
            END AS issuer_category
        FROM with_asset
    ),

    -- CTE 4: RE + FUND -> OTHER; LON/DBT + OTHER -> CORPORATE; NUSS name-gated GOVERNMENT
    adjusted AS (
        SELECT *,
            CASE
                WHEN asset_cat = 'RE' AND issuer_category = 'FUND' THEN 'OTHER'
                ELSE asset_category
            END AS asset_category_final,
            CASE
                -- NUSS with government keyword in name -> GOVERNMENT
                WHEN upper(trim(issuer_type)) = 'NUSS'
                     AND regexp_matches(upper(COALESCE(issuer_name, '')), '{_NPORT_GOVT_NAME_RE}')
                THEN 'GOVERNMENT'
                WHEN asset_category IN ('LOAN', 'DEBT') AND issuer_category = 'OTHER'
                    THEN 'CORPORATE'
                ELSE issuer_category
            END AS issuer_category_final
        FROM with_issuer
    ),

    -- CTE 4b: Detect fund-like issuer names in CORP+OTHER holdings
    with_fund_detect AS (
        SELECT *,
            CASE
                WHEN asset_category_final IN ('OTHER', 'EQUITY_COMMON')
                     AND issuer_category_final = 'CORPORATE'
                     AND (
                         -- L.P. suffix + fund co-keyword (but exclude operating companies)
                         (contains(lower(issuer_name), 'l.p.')
                          AND NOT (contains(lower(issuer_name), 'inc.')
                                OR contains(lower(issuer_name), 'llc')
                                OR contains(lower(issuer_name), 'corp.'))
                          AND ({lp_co_kw_checks}))
                         -- Explicit fund keywords
                         OR regexp_matches(lower(issuer_name), '\\bfunds?\\b')
                         OR {fund_kw_checks}
                     )
                THEN 'FUND'
                -- EC+CORPORATE with BDC/credit fund name -> FUND (fast path)
                WHEN asset_category_final = 'EQUITY_COMMON'
                     AND issuer_category_final = 'CORPORATE'
                     AND ({credit_fund_kw_checks})
                THEN 'FUND'
                ELSE issuer_category_final
            END AS issuer_category_reclassed
        FROM adjusted
    ),

    -- CTE 5: Map to unified schema
    unified AS (
        SELECT
            'nport' AS source,
            LPAD(CAST(cik AS VARCHAR), 10, '0') AS cik,
            registrant_name AS entity_name,
            accession_number,
            filing_date,
            report_date,
            {name_norm} AS issuer_name,
            CASE WHEN TRIM(CAST(issuer_name AS VARCHAR)) IS NOT NULL
                      AND TRIM(CAST(issuer_name AS VARCHAR)) != ''
                 THEN issuer_title
                 ELSE '' END AS instrument_description,
            issuer_cusip AS cusip,
            identifier_isin AS isin,
            issuer_lei AS lei,
            identifier_ticker AS ticker,
            TRY_CAST(currency_value AS DOUBLE) AS fair_value,
            NULL AS cost,
            TRY_CAST(percentage AS DOUBLE) AS pct_of_net_assets,
            asset_category_final AS asset_category,
            issuer_category_reclassed AS issuer_category,
            '' AS index_classification,
            '' AS exposure_type,
            '' AS asset_class,
            CAST(TRY_CAST(fair_value_level AS INTEGER) AS VARCHAR) AS fair_value_level,
            CASE WHEN TRY_CAST(annualized_rate AS DOUBLE) >= 50 THEN NULL
                 ELSE TRY_CAST(annualized_rate AS DOUBLE) END AS interest_rate,
            CASE WHEN TRY_CAST(annualized_rate AS DOUBLE) IS NOT NULL
                      AND TRY_CAST(annualized_rate AS DOUBLE) < 50 THEN 'nport'
                 ELSE '' END AS interest_rate_source,
            NULL AS basis_spread,
            '' AS basis_spread_source,
            '' AS reference_rate_type,
            '' AS reference_rate_source,
            coupon_type,
            NULL AS pik_rate,
            CASE WHEN TRY_CAST(maturity_date AS DATE) >= DATE '1950-01-01'
                      AND YEAR(TRY_CAST(maturity_date AS DATE)) < 2099
                 THEN maturity_date ELSE '' END AS maturity_date,
            CASE WHEN TRY_CAST(maturity_date AS DATE) >= DATE '1950-01-01'
                      AND YEAR(TRY_CAST(maturity_date AS DATE)) < 2099
                 THEN 'nport' ELSE '' END AS maturity_date_source,
            CASE WHEN upper(trim(unit)) = 'NS'
                 THEN TRY_CAST(balance AS DOUBLE) END AS shares_held,
            CASE WHEN upper(trim(unit)) = 'PA'
                 THEN TRY_CAST(balance AS DOUBLE) END AS principal_amount,
            CASE WHEN upper(trim(unit)) = 'PA'
                 THEN COALESCE(NULLIF(upper(trim(CAST(currency_code AS VARCHAR))), ''), 'USD')
                 ELSE '' END AS principal_amount_currency,
            CASE
                WHEN upper(trim(unit)) = 'PA'
                     AND (currency_code IS NULL OR trim(CAST(currency_code AS VARCHAR)) = ''
                          OR upper(trim(CAST(currency_code AS VARCHAR))) = 'USD')
                THEN TRY_CAST(balance AS DOUBLE)
                WHEN upper(trim(unit)) = 'PA'
                     AND TRY_CAST(exchange_rate AS DOUBLE) > 0
                THEN TRY_CAST(balance AS DOUBLE) / TRY_CAST(exchange_rate AS DOUBLE)
                ELSE NULL
            END AS principal_amount_usd,
            CASE
                WHEN upper(trim(unit)) = 'PA'
                     AND upper(trim(CAST(currency_code AS VARCHAR))) NOT IN ('', 'USD')
                     AND TRY_CAST(exchange_rate AS DOUBLE) > 0
                THEN 1.0 / TRY_CAST(exchange_rate AS DOUBLE)
                WHEN upper(trim(unit)) = 'PA'
                     AND (currency_code IS NULL OR trim(CAST(currency_code AS VARCHAR)) = ''
                          OR upper(trim(CAST(currency_code AS VARCHAR))) = 'USD')
                THEN 1.0
                ELSE NULL
            END AS principal_fx_rate_to_usd,
            CASE
                WHEN upper(trim(unit)) != 'PA' THEN ''
                WHEN currency_code IS NULL OR trim(CAST(currency_code AS VARCHAR)) = ''
                     OR upper(trim(CAST(currency_code AS VARCHAR))) = 'USD' THEN 'source_usd'
                WHEN TRY_CAST(exchange_rate AS DOUBLE) > 0 THEN 'nport_exchange_rate'
                ELSE 'invalid_nport_exchange_rate'
            END AS principal_fx_status,
            CASE WHEN upper(trim(unit)) = 'PA'
                 THEN COALESCE(NULLIF(upper(trim(CAST(currency_code AS VARCHAR))), ''), 'USD')
                 ELSE '' END AS fair_value_currency,
            '' AS cost_currency,
            '' AS bdc_investment_identifier,
            '' AS bdc_form_type,
            '' AS bdc_dimensions_raw,
            NULL AS bdc_unrealized_gain_loss,
            '' AS bdc_investment_country,
            '' AS src_context_id,
            '' AS src_context_count,
            '' AS src_conflict_fields,
            '' AS src_transforms,
            '' AS src_field_overrides,
            '' AS cost_source,
            '' AS shares_held_source,
            '' AS fair_value_source,
            '' AS principal_amount_source,
            '' AS pct_of_net_assets_source,
            '' AS pik_rate_source,
            '' AS bdc_unrealized_gain_loss_source,
            '' AS src_facts,
            '' AS src_filled_fields,
            '' AS corrected_fields,
            holding_id AS nport_holding_id,
            series_name AS nport_series_name,
            series_id AS nport_series_id,
            asset_cat AS nport_asset_cat,
            issuer_type AS nport_issuer_type,
            payoff_profile AS nport_payoff_profile,
            investment_country AS nport_investment_country,
            is_restricted_security AS nport_is_restricted,
            CASE WHEN TRY_CAST(report_date AS DATE) IS NOT NULL THEN
                CAST(YEAR(TRY_CAST(report_date AS DATE)) AS VARCHAR)
                || 'q'
                || CAST(QUARTER(TRY_CAST(report_date AS DATE)) AS VARCHAR)
            ELSE quarter END AS nport_quarter,
            COALESCE(CAST(is_default AS VARCHAR), '') AS nport_is_default,
            COALESCE(CAST(are_any_interest_payment AS VARCHAR), '') AS nport_are_interest_payments_in_arrears,
            COALESCE(CAST(is_any_portion_interest_paid AS VARCHAR), '') AS nport_is_paid_in_kind,
            COALESCE(CAST(currency_code AS VARCHAR), '') AS nport_currency_code,
            COALESCE(CAST(liquidity_classification AS VARCHAR), '') AS nport_liquidity_classification,
            FALSE AS nonaccrual_footnote,
            FALSE AS nonaccrual_dimension,
            0 AS is_subsidiary,
            '' AS jv_subsidiary,
            '' AS entity_id,
            '' AS canonical_name,
            '' AS extracted_industry,
            '' AS gics_sub_industry,
            '' AS lien_position,
            '' AS instrument_type,
            -- Position key: issuer/title based. issuer_cusip is issuer-level in
            -- N-PORT and cannot be the whole key for position-level matching.
            TRIM(REGEXP_REPLACE(
                REGEXP_REPLACE(
                    LOWER(
                        CAST({name_norm} AS VARCHAR)
                        || ' '
                        || COALESCE(CAST(issuer_title AS VARCHAR), '')
                        || CASE
                            WHEN TRIM(COALESCE(CAST(issuer_cusip AS VARCHAR), '')) != ''
                                 AND regexp_matches(
                                     upper(trim(CAST(issuer_cusip AS VARCHAR))),
                                     '^[A-Z0-9]{9}$'
                                 )
                                 AND upper(trim(CAST(issuer_cusip AS VARCHAR))) NOT IN (
                                     '000000000', '999999999', 'N/A', 'NONE', 'NULL',
                                     'UNKNOWN', 'NC'
                                 )
                            THEN ' ' || CAST(issuer_cusip AS VARCHAR)
                            ELSE ''
                        END),
                    '[^a-z0-9 ]', ' ', 'g'),
                '\\s+', ' ', 'g')) AS position_key,
            '' AS position_id,
            _row_id
        FROM with_fund_detect
    )

    SELECT * FROM unified ORDER BY _row_id
    """

    result = con.execute(sql).fetchdf()

    # Log rate cap stats (count from input, since SQL already capped)
    if _nport_loaded_from_file:
        rate_capped = con.execute(
            "SELECT COUNT(*) FROM nport_raw "
            "WHERE TRY_CAST(annualized_rate AS DOUBLE) > 50"
        ).fetchone()[0]
    else:
        rate_capped = 0
        if "annualized_rate" in nport_df.columns:
            raw_rates = pd.to_numeric(nport_df["annualized_rate"], errors="coerce")
            rate_capped = int((raw_rates > 50).sum())

    con.close()

    # Drop internal row id column
    result.drop(columns=["_row_id"], inplace=True)

    logger.info("  After Level 3 filter: %d rows", len(result))

    if rate_capped > 0:
        logger.info("  N-PORT rates capped at 50%%: %d rows", rate_capped)

    if result.empty:
        return pd.DataFrame(columns=UNIFIED_COLUMNS)

    logger.info("  N-PORT asset breakdown:")
    for cat, count in result["asset_category"].value_counts().items():
        logger.info("    %s: %d (%.1f%%)", cat, count, 100 * count / len(result))

    return result


# ---------------------------------------------------------------------------
# Classification stabilization
# ---------------------------------------------------------------------------
