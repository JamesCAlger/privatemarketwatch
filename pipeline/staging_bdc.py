"""BDC holdings staging for the unified holdings pipeline."""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import Union

import duckdb
import pandas as pd

from pipeline.bdc_identifier import (
    _AFFILIATION_PREFIX_RE,
    _AFFILIATION_SUFFIX_RE,
    _AFFILIATION_TAGS,
    _CRESCENT_HIERARCHY_INDUSTRIES,
    _INVESTMENTS_HIERARCHY_RE,
    _sql_is_bdc_aggregate,
)
from pipeline.bdc_aggregate_overrides import load_bdc_aggregate_overrides
from pipeline.classification import (
    _INDUSTRY_LABELS,
    _BDC_FUND_VEHICLE_KEYWORDS,
    _BDC_FUND_VEHICLE_POS_GUARD,
    _LEGAL_SUFFIX_RE_SQL,
    _PIPE_INSTRUMENT_KEYWORDS,
    _is_named_coinvest,
    _sql_classify_bdc_asset,
    _sql_exact_match,
    _sql_industry_label_in,
    _sql_is_bad_issuer_name,
    _sql_is_named_coinvest,
    _sql_keyword_check,
    _sql_money_market_check,
    _sql_normalize_name,
)
from pipeline.config import (
    AGGREGATE_HEADER_FLAGS_FILE,
    FX_RATES_FILE,
)

logger = logging.getLogger(__name__)

def _load_aggregate_header_flags() -> pd.DataFrame:
    """Load CC-reviewed aggregate header flags, if present.

    Returns a DataFrame with ``name_norm`` (lowercase, legal suffixes
    stripped) and ``identifier_raw`` (lowercased raw investment_identifier
    from bdc_holdings, populated by backfill script) columns.  The CTE
    join uses ``identifier_raw`` for exact matching against ``_lower_id``
    when available, falling back to normalised ``issuer_name`` matching
    via ``name_norm``.

    Only rows with verdict = 'AGGREGATE_HEADER' and confidence in
    ('high', 'medium') are returned -- JV_SUBSIDIARY and UNRESOLVABLE
    verdicts are informational and do NOT trigger exclusion.
    """
    if not AGGREGATE_HEADER_FLAGS_FILE.exists():
        return pd.DataFrame(columns=["name_norm", "identifier_raw"])
    try:
        df = pd.read_csv(AGGREGATE_HEADER_FLAGS_FILE, dtype=str)
    except Exception:
        return pd.DataFrame(columns=["name_norm", "identifier_raw"])
    if "verdict" not in df.columns or "name_norm" not in df.columns:
        return pd.DataFrame(columns=["name_norm", "identifier_raw"])
    mask = (
        (df["verdict"] == "AGGREGATE_HEADER")
        & df["confidence"].isin(["high", "medium"])
    )
    cols = ["name_norm"]
    if "identifier_raw" in df.columns:
        cols.append("identifier_raw")
    result = df.loc[mask, cols].copy()
    result["name_norm"] = result["name_norm"].str.strip().str.lower()
    if "identifier_raw" not in result.columns:
        result["identifier_raw"] = ""
    result["identifier_raw"] = result["identifier_raw"].fillna("").str.strip().str.lower()
    result = result[result["name_norm"].str.len() > 0].drop_duplicates()
    return result


def _reclassify_named_fund_positions(df: pd.DataFrame) -> pd.DataFrame:
    """Reclassify named co-invest and LP interest positions from FUND to EQUITY.

    For rows where asset_category == "FUND" and the holding identifies a
    specific operating company (via _is_named_coinvest), override:
      - asset_category -> EQUITY_PREFERRED if "preferred" in name, else EQUITY_COMMON
      - issuer_category -> CORPORATE

    This ensures _classify_index() returns PREFERRED_EQUITY or COMMON_EQUITY for these rows.
    """
    if "asset_category" not in df.columns or len(df) == 0:
        return df

    fund_mask = df["asset_category"] == "FUND"
    if not fund_mask.any():
        return df

    # Evaluate _is_named_coinvest for FUND rows only
    fund_idx = df.index[fund_mask]
    named_mask = df.loc[fund_idx].apply(
        lambda row: _is_named_coinvest(
            row.get("issuer_name", ""),
            row.get("instrument_description", ""),
            row.get("bdc_investment_identifier", row.get("investment_identifier", "")),
        ),
        axis=1,
    )
    named_idx = fund_idx[named_mask]

    if len(named_idx) == 0:
        return df

    # Determine preferred vs common
    for idx in named_idx:
        combined = ""
        for col in ["issuer_name", "instrument_description"]:
            val = df.at[idx, col] if col in df.columns else ""
            if val and isinstance(val, str):
                combined += " " + val.lower()
        if "preferred" in combined:
            df.at[idx, "asset_category"] = "EQUITY_PREFERRED"
        else:
            df.at[idx, "asset_category"] = "EQUITY_COMMON"
        df.at[idx, "issuer_category"] = "CORPORATE"

    logger.info("  Reclassified %d named co-invest/LP positions from FUND to EQUITY",
                len(named_idx))

    return df


# ---------------------------------------------------------------------------
# BDC preparation
# ---------------------------------------------------------------------------

def _prepare_bdc(
    bdc_df: pd.DataFrame | None = None,
    bdc_file: Union[Path, str, None] = None,
) -> pd.DataFrame:
    """Filter, parse, classify, and map BDC holdings to unified schema.

    Uses a DuckDB CTE pipeline for all data manipulation.

    Parameters
    ----------
    bdc_df : pd.DataFrame, optional
        Pre-loaded BDC holdings DataFrame.
    bdc_file : Path or str, optional
        Path to BDC holdings file (Parquet or CSV). When provided, DuckDB
        reads the file directly -- much faster than loading via pandas then
        registering.  Falls back to *bdc_df* when the file does not exist.
    """
    from pipeline.unified_holdings import UNIFIED_COLUMNS

    _optional_cols = (
        "fair_value_unit", "cost_unit", "principal_amount_unit",
        "industry", "investment_type", "affiliation",
    )

    con = duckdb.connect()

    # --- data source selection ------------------------------------------------
    if bdc_file is not None and Path(bdc_file).exists():
        fpath = str(bdc_file).replace("\\", "/")
        if str(bdc_file).endswith(".parquet"):
            read_expr = f"read_parquet('{fpath}')"
        else:
            read_expr = f"read_csv_auto('{fpath}', header=true, all_varchar=true)"

        # Materialise once into DuckDB columnar storage (faster than a VIEW
        # when the table is referenced by many downstream CTEs).
        con.execute(f"CREATE TABLE bdc_raw AS SELECT * FROM {read_expr}")
        input_count = con.execute("SELECT COUNT(*) FROM bdc_raw").fetchone()[0]
        logger.info("Preparing BDC holdings: %d input rows (from %s)",
                     input_count, Path(bdc_file).name)

        if input_count == 0:
            con.close()
            return pd.DataFrame(columns=UNIFIED_COLUMNS)

        # Ensure optional columns exist
        existing_cols = {
            r[0] for r in con.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'bdc_raw'"
            ).fetchall()
        }
        for col in _optional_cols:
            if col not in existing_cols:
                con.execute(f"ALTER TABLE bdc_raw ADD COLUMN {col} VARCHAR DEFAULT ''")

    elif bdc_df is not None:
        input_count = len(bdc_df)
        logger.info("Preparing BDC holdings: %d input rows", input_count)

        if bdc_df.empty:
            con.close()
            return pd.DataFrame(columns=UNIFIED_COLUMNS)

        bdc_df = bdc_df.copy()
        for col in _optional_cols:
            if col not in bdc_df.columns:
                bdc_df[col] = ""
        # Materialise into a TABLE (not a view) so pre-filter DELETEs work
        con.register("_bdc_raw_view", bdc_df)
        con.execute("CREATE TABLE bdc_raw AS SELECT * FROM _bdc_raw_view")

    else:
        raise ValueError("Either bdc_df or bdc_file must be provided")
    # --- end data source selection --------------------------------------------
    if FX_RATES_FILE.exists():
        fx_path = str(FX_RATES_FILE).replace("\\", "/")
        con.execute(f"""
            CREATE TEMP TABLE fx_rates AS
            SELECT upper(trim(CAST(currency AS VARCHAR))) AS currency,
                   CAST(rate_date AS VARCHAR) AS rate_date,
                   TRY_CAST(usd_per_currency AS DOUBLE) AS usd_per_currency
            FROM read_csv_auto('{fx_path}', header=true, all_varchar=true)
            WHERE TRY_CAST(usd_per_currency AS DOUBLE) > 0
        """)
    else:
        con.register("fx_rates", pd.DataFrame(columns=[
            "currency", "rate_date", "usd_per_currency",
        ]))
    aggregate_overrides = load_bdc_aggregate_overrides()
    con.register("bdc_aggregate_overrides", aggregate_overrides)
    agg_header_flags = _load_aggregate_header_flags()
    con.register("cc_aggregate_header_flags", agg_header_flags)
    _has_agg_flags = len(agg_header_flags) > 0

    # Pre-generate SQL fragments from Python constants
    agg_filter = _sql_is_bdc_aggregate()
    bad_issuer_filter = _sql_is_bad_issuer_name()
    # Entity signal check on raw identifier -- when issuer_name is bad but raw
    # has company signals (LLC, Inc, etc.), keep the row with raw as issuer_name
    _entity_sigs = [
        "inc.", "inc,", " inc ", " inc-",
        "llc", "l.l.c", "corp.", "corp,",
        "ltd.", "ltd,", " ltd ", ", lp", " lp,", "l.p.",
        "holdings", "group", "gmbh", " co.", " plc",
    ]
    _sql_has_entity_in_raw = " OR ".join(
        f"contains(lower(_raw_id), '{s}')" for s in _entity_sigs
    )
    asset_case = _sql_classify_bdc_asset()
    coinvest_expr = _sql_is_named_coinvest()
    mm_check = _sql_money_market_check()
    industry_in = _sql_industry_label_in()
    pipe_parts = "regexp_split_to_array(_raw_id, '\\s*\\|\\s*')"
    has_pipe = "regexp_matches(_raw_id, '\\|')"
    affil_in = _sql_exact_match(
        f"lower(trim({pipe_parts}[-1]))", _AFFILIATION_TAGS
    )
    # 3-pipe format detection helpers
    seg1_has_suffix = (
        f"regexp_matches(lower(trim({pipe_parts}[1])), "
        f"'{_LEGAL_SUFFIX_RE_SQL}')"
    )
    seg2_has_suffix = (
        f"regexp_matches(lower(trim({pipe_parts}[2])), "
        f"'{_LEGAL_SUFFIX_RE_SQL}')"
    )
    seg3_is_instrument = _sql_keyword_check(
        f"lower(trim({pipe_parts}[3]))", _PIPE_INSTRUMENT_KEYWORDS
    )
    seg2_is_industry = _sql_exact_match(
        f"lower(trim({pipe_parts}[2]))", _INDUSTRY_LABELS
    )
    slr_seg2_is_leaf_issuer = (
        f"len({pipe_parts}) >= 3 "
        "AND regexp_matches(lower(trim("
        f"{pipe_parts}[1])), '^equipment\\s+financing\\s*-\\s*-?\\d[\\d.]*%$') "
        "AND NOT starts_with(lower(trim("
        f"{pipe_parts}[2])), 'total ') "
        f"AND NOT {_sql_exact_match(f'lower(trim({pipe_parts}[2]))', _INDUSTRY_LABELS)} "
        "AND NOT regexp_matches(lower(trim("
        f"{pipe_parts}[2])), '^(?:sofr|libor|euribor|prime|s\\s*\\+|e\\s*\\+|\\d|maturity|interest|reference\\s+rate)')"
    )
    name_norm = _sql_normalize_name("issuer_name")

    # Normalised raw identifier: em-dash -> ' - ', en-dash -> '-'
    _norm_raw = "regexp_replace(replace(_raw_id, '\u2014', ' - '), '\u2013', '-', 'g')"
    _msd_extra_industry_labels = {
        "Beverage, Food & Tobacco",
        "Capital Equipment",
        "Chemicals, Plastics & Rubber",
        "Consumer",
        "Environmental Industries",
    }
    _industry_prefix_re = "|".join(
        re.escape(label).replace(r"\ ", r"\s+")
        for label in sorted(_INDUSTRY_LABELS | _msd_extra_industry_labels, key=len, reverse=True)
    )
    _msd_hierarchy_prefix_re = (
        r"(?i)^Investments\s+Investments\s*-\s*"
        r"(?:non-?\s*control(?:led)?(?:\s*/\s*non-?\s*affiliat(?:e|ed))?"
        r"|control(?:led)?(?:\s*/\s*affiliat(?:e|ed))?"
        r"|affiliat(?:e|ed))"
        r"\s+"
        r"(?:first\s+lien\s+debt|second\s+lien\s+debt|subordinated\s+debt"
        r"|senior\s+secured\s+debt|common\s+equity|preferred\s+equity"
        r"|equity|debt|warrants?)"
        r"\s+"
        rf"(?:{_industry_prefix_re})\s+"
    )
    _msd_hierarchy_condition = (
        "LPAD(REGEXP_REPLACE(CAST(cik AS VARCHAR), '[^0-9]', '', 'g'), 10, '0') = '0001849894' "
        f"AND regexp_matches(_raw_id, '{_msd_hierarchy_prefix_re}')"
    )
    _msd_clean_raw = f"regexp_replace(_raw_id, '{_msd_hierarchy_prefix_re}', '')"

    # Entity signal check on seg[1] (for pct-prefix category detection)
    _seg1_entity_sql = " OR ".join(
        f"contains(lower(trim(_segments[1])), '{s}')" for s in _entity_sigs
    )

    # Keyword boundary regex for extracting company name from pct-prefix segments
    _kw_boundary_re = (
        r"^(.+?)\s+(?:Industry|Interest Rate|Current Coupon|Maturity"
        r"|Reference Rate|Basis Point|Floor|PIK)(?:\s|$)"
    )

    # Industry label check on seg[3] (for geography-prefix detection in Blue Owl)
    _seg3_is_industry = _sql_exact_match(
        "lower(trim(_segments[3]))", _INDUSTRY_LABELS
    )
    _crescent_cik_sql = (
        "LPAD(REGEXP_REPLACE(CAST(cik AS VARCHAR), '[^0-9]', '', 'g'), 10, '0') "
        "IN ('0001633336', '0001954360')"
    )
    _crescent_clean_raw = (
        "regexp_replace(replace(CAST(_raw_id AS VARCHAR), '\u00a0', ' '), '\\s+', ' ', 'g')"
    )
    _crescent_industry_re = "|".join(
        re.escape(label).replace("\\ ", "\\s+")
        for label in _CRESCENT_HIERARCHY_INDUSTRIES
    )
    _crescent_issuer_re = (
        r"^Investments\s+.+?\s+(?:Debt|Equity)\s+Investments\s+"
        rf"(?:{_crescent_industry_re})\s+(.+?)\s+Investment\s+Type\s+"
    )
    _crescent_instrument_re = (
        r"Investment\s+Type\s+(.+?)(?:\s+Interest\s+Term\b|\s+Interest\s+Rate\b|"
        r"\s+Maturity\s*/\s*Dissolution\s+Date\b|\s+Maturity\b|$)"
    )
    _crescent_trailing_re = (
        r"Maturity\s*/\s*Dissolution\s+Date\s+\d{1,2}/\d{4}\s+(.+)$"
    )
    _crescent_condition = (
        f"{_crescent_cik_sql} "
        f"AND starts_with(lower({_crescent_clean_raw}), 'investments ') "
        f"AND contains(lower({_crescent_clean_raw}), ' investment type ') "
        f"AND regexp_matches(lower({_crescent_clean_raw}), "
        "'\\b(unitranche|first\\s+lien|second\\s+lien|term\\s+loan|"
        "delayed\\s+draw|revolver|revolving|senior\\s+secured|subordinated|"
        "notes?|bonds?|common\\s+(stock|equity)|preferred|warrants?|equity)\\b') "
        f"AND regexp_matches(lower({_crescent_clean_raw}), "
        "'\\b(interest\\s+(term|rate)|reference\\s+rate|sofr|libor|euribor|"
        "maturity\\s*/\\s*dissolution|maturity|due)\\b')"
    )

    # Fund vehicle/manager detection: equity-type positions with these name
    # signals get issuer_category = FUND (overrides the default CORPORATE).
    fund_vehicle_clauses = []
    for kw in _BDC_FUND_VEHICLE_KEYWORDS:
        kw_escaped = kw.replace("'", "''")
        if kw == "asset management":
            # Position guard: must appear within first N chars
            fund_vehicle_clauses.append(
                f"(strpos(lower(CAST(issuer_name AS VARCHAR)), '{kw_escaped}') > 0"
                f" AND strpos(lower(CAST(issuer_name AS VARCHAR)), '{kw_escaped}')"
                f" <= {_BDC_FUND_VEHICLE_POS_GUARD})"
            )
        else:
            fund_vehicle_clauses.append(
                f"contains(lower(CAST(issuer_name AS VARCHAR)), '{kw_escaped}')"
            )
    fund_vehicle_sql = " OR ".join(fund_vehicle_clauses)

    # Filter comparative-period rows if the 'period' column exists.
    # Also exclude pre-2022 BDC data (unreliable partial XBRL coverage).
    # Rows with NULL/empty report_date pass the cutoff (test compatibility).
    _bdc_raw_cols = {
        r[0] for r in con.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'bdc_raw'"
        ).fetchall()
    }
    has_period = "period" in _bdc_raw_cols

    # -- Pre-filter: DELETE comparative-period and pre-2022 rows from the
    # materialized table BEFORE any CTE processing.  This drops ~50% of rows
    # so every downstream CTE, regex, and join operates on half the data.
    pre_filter_count = con.execute("SELECT COUNT(*) FROM bdc_raw").fetchone()[0]
    if has_period:
        con.execute("""
            DELETE FROM bdc_raw
            WHERE NOT (
                TRY_CAST(period AS DATE) = TRY_CAST(report_date AS DATE)
                OR period IS NULL
                OR CAST(period AS VARCHAR) = ''
            )
            OR (TRY_CAST(report_date AS DATE) < '2022-01-01'
                AND TRY_CAST(report_date AS DATE) IS NOT NULL)
        """)
    else:
        con.execute("""
            DELETE FROM bdc_raw
            WHERE TRY_CAST(report_date AS DATE) < '2022-01-01'
              AND TRY_CAST(report_date AS DATE) IS NOT NULL
        """)
    post_filter_count = con.execute("SELECT COUNT(*) FROM bdc_raw").fetchone()[0]
    removed = pre_filter_count - post_filter_count
    if removed > 0:
        logger.info("  Pre-filtered: %d -> %d rows (%d comparative/pre-2022 removed)",
                    pre_filter_count, post_filter_count, removed)

    # Period/date filtering already applied via DELETE above
    period_filter = "WHERE TRUE"

    # Conditional CTE for CC-reviewed aggregate header exclusion.
    # When the aggregate_header_flags.csv file has entries, inject a CTE
    # that LEFT JOINs against the flags and filters out matches.
    # Two-pass matching:
    #   1. Exact match on identifier_raw (backfilled raw investment_identifier)
    #      against _lower_id -- precise, no normalization loss.
    #   2. Fallback: normalized issuer_name against name_norm (original logic).
    # Safety guard: skip exclusion when the row has position-level detail
    # fields (interest_rate, maturity, principal, shares) to prevent
    # false positives from normalization collisions.
    _legal_suffix_sql = (
        r",?\s*\b(llc|l\.l\.c\.|inc\.?|incorporated|corp\.?|corporation"
        r"|ltd\.?|limited|l\.p\.?|lp|co\.?|company|holdings|holding"
        r"|group|enterprises?|plc|p\.l\.c\.|n\.v\.|s\.a\.|ag|gmbh"
        r"|international|intl\.?)\b\.?\s*$"
    )
    _detail_guard = (
        "n._ir IS NULL "
        "AND n._pa IS NULL AND n._sh IS NULL"
    )
    if _has_agg_flags:
        _cc_agg_header_cte = (
            "-- CTE 5c2: Exclude CC-reviewed aggregate headers.\n"
            "    -- Two-pass: (1) exact identifier_raw match on _lower_id,\n"
            "    -- (2) fallback normalized issuer_name match on name_norm.\n"
            "    -- Safety guard: rows with detail fields are never excluded.\n"
            "    no_cc_agg_headers AS (\n"
            "        SELECT n.* FROM no_bad_issuers n\n"
            "        LEFT JOIN cc_aggregate_header_flags f1\n"
            "            ON f1.identifier_raw != ''\n"
            "            AND lower(TRIM(CAST(n._lower_id AS VARCHAR))) = f1.identifier_raw\n"
            "        LEFT JOIN cc_aggregate_header_flags f2\n"
            "            ON f1.identifier_raw IS NULL\n"
            "            AND TRIM(REGEXP_REPLACE(\n"
            "                   REGEXP_REPLACE(\n"
            "                       lower(TRIM(CAST(n.issuer_name AS VARCHAR))),\n"
            f"                       '{_legal_suffix_sql}',\n"
            "                       '', 'i'),\n"
            "                   '\\s+', ' ', 'g')\n"
            "               ) = f2.name_norm\n"
            "        WHERE (f1.identifier_raw IS NULL AND f2.name_norm IS NULL)\n"
            f"           OR NOT ({_detail_guard})\n"
            "    ),"
        )
        _affil_dedup_source = "no_cc_agg_headers"
    else:
        _cc_agg_header_cte = "-- (no aggregate header flags loaded)"
        _affil_dedup_source = "no_bad_issuers"

    # =========================================================================
    # Phase A: Row-level normalization, scale correction, amendment dedup,
    # affiliation stripping, aggregate/artifact filtering, and prefix rollup.
    # Materializes into _bdc_phase_a temp table so downstream phases read a
    # clean columnar scan instead of re-deriving through the CTE chain.
    # =========================================================================
    _t_phase = time.time()
    sql_phase_a = f"""
    CREATE TEMP TABLE _bdc_phase_a AS
    WITH
    -- CTE 1: Normalise text columns, cast numerics, add row id
    -- Comparative-period and pre-2022 rows already removed by pre-filter DELETE.
    raw AS (
        SELECT
            *,
            ROW_NUMBER() OVER (
                ORDER BY
                    COALESCE(CAST(cik AS VARCHAR), ''),
                    COALESCE(CAST(report_date AS VARCHAR), ''),
                    COALESCE(CAST(accession_number AS VARCHAR), ''),
                    COALESCE(CAST(investment_identifier AS VARCHAR), ''),
                    COALESCE(CAST(dimensions_raw AS VARCHAR), ''),
                    COALESCE(CAST(fair_value AS VARCHAR), '')
            ) AS _row_id,
            COALESCE(CAST(investment_identifier AS VARCHAR), '') AS _raw_id,
            COALESCE(lower(trim(CAST(investment_identifier AS VARCHAR))), '') AS _lower_id,
            TRY_CAST(fair_value AS DOUBLE) AS _fv,
            TRY_CAST(interest_rate AS DOUBLE) AS _ir,
            TRY_CAST(principal_amount AS DOUBLE) AS _pa,
            TRY_CAST(shares_held AS DOUBLE) AS _sh,
            TRY_CAST(basis_spread AS DOUBLE) AS _bs,
            TRY_CAST(cost AS DOUBLE) AS _cost,
            TRY_CAST(pct_of_net_assets AS DOUBLE) AS _pct,
            TRY_CAST(pik_rate AS DOUBLE) AS _pik,
            TRY_CAST(unrealized_gain_loss AS DOUBLE) AS _ugl
        FROM bdc_raw
        {period_filter}
    ),

    -- CTE 1a-i: Detect 1000x scale errors by comparing each CIK-quarter's
    -- total FV against the CIK's median across all quarters.  Requires >= 3
    -- quarters so the median is robust.  Only fires when ratio > 100x, which
    -- catches clear filer errors (observed: CIK 1825265/2023-03-31 and
    -- CIK 1916608/2023-06-30) without risking false positives on genuine
    -- portfolio growth.
    _quarterly_fv AS (
        SELECT cik, CAST(report_date AS VARCHAR) AS report_date,
               SUM(_fv) AS total_fv
        FROM raw
        WHERE _fv IS NOT NULL AND _fv > 0
        GROUP BY cik, CAST(report_date AS VARCHAR)
    ),
    _cik_medians AS (
        SELECT cik, MEDIAN(total_fv) AS median_fv, COUNT(*) AS n_quarters
        FROM _quarterly_fv
        GROUP BY cik
    ),
    _scale_errors AS (
        SELECT q.cik, q.report_date
        FROM _quarterly_fv q
        JOIN _cik_medians m ON q.cik = m.cik
        WHERE m.n_quarters >= 3
          AND m.median_fv > 0
          AND q.total_fv / m.median_fv > 100
    ),
    scale_corrected AS (
        SELECT r.* EXCLUDE (_fv, _cost, _pa),
            CASE WHEN s.cik IS NOT NULL THEN r._fv / 1000 ELSE r._fv END AS _fv,
            CASE WHEN s.cik IS NOT NULL THEN r._cost / 1000 ELSE r._cost END AS _cost,
            CASE WHEN s.cik IS NOT NULL THEN r._pa / 1000 ELSE r._pa END AS _pa
        FROM raw r
        LEFT JOIN _scale_errors s
          ON r.cik = s.cik
         AND CAST(r.report_date AS VARCHAR) = s.report_date
    ),

    -- CTE 1b: Amendment dedup -- when a CIK has both a 10-K and 10-K/A
    -- (or 10-Q and 10-Q/A) for the same report_date, keep only the rows
    -- from the latest-filed accession.  If the amendment's XBRL had no
    -- investment data (common: 21/27 amendments in our dataset), the
    -- original is the only accession with rows and is kept automatically.
    no_amendments AS (
        SELECT r.* FROM scale_corrected r
        INNER JOIN (
            SELECT cik, report_date, accession_number,
                ROW_NUMBER() OVER (
                    PARTITION BY cik, CAST(report_date AS VARCHAR),
                        REGEXP_REPLACE(CAST(form_type AS VARCHAR), '/A$', '')
                    ORDER BY
                        CAST(filing_date AS VARCHAR) DESC,
                        COALESCE(CAST(accession_number AS VARCHAR), '') DESC
                ) AS _amd_rank
            FROM scale_corrected
            GROUP BY cik, report_date, accession_number, form_type, filing_date
        ) ranked
          ON r.cik = ranked.cik
         AND r.report_date = ranked.report_date
         AND r.accession_number = ranked.accession_number
        WHERE ranked._amd_rank = 1
    ),

    -- CTE 1c: Strip affiliation prefixes/suffixes from _raw_id
    -- Handles PhenixFIN-style identifiers where the XBRL identifier
    -- has the affiliation category as a prefix or suffix, e.g.:
    --   "Non-Controlled/Non-Affiliated Investments - Acme Corp - Term Loan"
    --   -> "Acme Corp - Term Loan"
    -- Must run BEFORE aggregate filter so cleaned _raw_id/_lower_id
    -- are used for aggregate detection.
    -- Compute stripped value once, derive _lower_id from it (3 regex
    -- calls instead of 6).
    strip_affil AS (
        SELECT * EXCLUDE (_raw_id, _lower_id, _stripped),
            _stripped AS _raw_id,
            lower(trim(_stripped)) AS _lower_id
        FROM (
            SELECT *,
                regexp_replace(
                    regexp_replace(
                        regexp_replace(
                            _raw_id,
                            '{_AFFILIATION_PREFIX_RE}',
                            ''
                        ),
                        '{_AFFILIATION_SUFFIX_RE}',
                        ''
                    ),
                    '{_INVESTMENTS_HIERARCHY_RE}',
                    ''
                ) AS _stripped
            FROM no_amendments
        )
    ),

    aggregate_override_matches AS (
        SELECT
            s._row_id,
            MAX(CASE WHEN o.action = 'include' THEN 1 ELSE 0 END) AS force_include,
            MAX(CASE WHEN o.action = 'exclude' THEN 1 ELSE 0 END) AS force_exclude
        FROM strip_affil s
        JOIN bdc_aggregate_overrides o
          ON LPAD(REGEXP_REPLACE(CAST(s.cik AS VARCHAR), '[^0-9]', '', 'g'), 10, '0') = o.cik
         AND (o.report_date = '' OR CAST(s.report_date AS VARCHAR) = o.report_date)
         AND (o.accession_number = '' OR CAST(s.accession_number AS VARCHAR) = o.accession_number)
         AND (
             (o.match_mode = 'exact' AND lower(trim(CAST(s._raw_id AS VARCHAR))) = o.match_text_lower)
             OR (o.match_mode = 'contains' AND contains(lower(CAST(s._raw_id AS VARCHAR)), o.match_text_lower))
         )
        GROUP BY s._row_id
    ),

    -- CTE 2: Filter aggregate/subtotal rows
    no_aggregates AS (
        SELECT s.* FROM strip_affil s
        LEFT JOIN aggregate_override_matches o
          ON s._row_id = o._row_id
        WHERE COALESCE(o.force_exclude, 0) = 0
          AND (
              COALESCE(o.force_include, 0) = 1
              OR ({_msd_hierarchy_condition})
              OR NOT ({agg_filter})
          )
    ),

    -- CTE 3: Filter XBRL artifacts (no financial data at all)
    no_artifacts AS (
        SELECT * FROM no_aggregates
        WHERE _fv IS NOT NULL
           OR _ir IS NOT NULL
           OR _pa IS NOT NULL
           OR _sh IS NOT NULL
    ),

    -- CTE 3b: Require fair value (removes unfunded commitments,
    -- tranche detail duplicates, and equity stubs with no FV)
    has_fv AS (
        SELECT * FROM no_artifacts
        WHERE _fv IS NOT NULL
    ),

    -- CTE 4: Filter deterministic hierarchical prefix rollups.
    -- A shorter row is removed only when at least two FV-carrying child rows
    -- extend the identifier and their fair values tie exactly to the parent.
    -- This avoids dropping real same-borrower positions just because another
    -- position starts with the same text.
    prefix_rollup_parents AS (
        SELECT
            a._row_id,
            COUNT(b._row_id) AS child_count,
            SUM(b._fv) AS child_fv
        FROM has_fv a
        JOIN has_fv b
          ON a.cik = b.cik
         AND a.accession_number = b.accession_number
         AND b._raw_id LIKE a._raw_id || '%'
         AND LENGTH(b._raw_id) >= LENGTH(a._raw_id) + 10
         AND a._raw_id IS NOT NULL
         AND LENGTH(a._raw_id) >= 3
        GROUP BY a._row_id, a._fv
        HAVING COUNT(b._row_id) >= 2
           AND abs(a._fv - SUM(b._fv))
               <= greatest(1.0, 0.0001 * greatest(abs(a._fv), abs(SUM(b._fv))))
    ),

    no_subtotals AS (
        SELECT a.* FROM has_fv a
        LEFT JOIN prefix_rollup_parents p
          ON a._row_id = p._row_id
        WHERE p._row_id IS NULL
    )

    SELECT * FROM no_subtotals
    """
    con.execute(sql_phase_a)

    # Log 1000x scale corrections (diagnostic, uses bdc_raw which is still alive)
    try:
        scale_log = con.execute("""
            WITH _qfv AS (
                SELECT cik, CAST(report_date AS VARCHAR) AS report_date,
                       SUM(TRY_CAST(fair_value AS DOUBLE)) AS total_fv
                FROM bdc_raw
                WHERE TRY_CAST(fair_value AS DOUBLE) IS NOT NULL
                  AND TRY_CAST(fair_value AS DOUBLE) > 0
                GROUP BY cik, CAST(report_date AS VARCHAR)
            ),
            _cm AS (
                SELECT cik, MEDIAN(total_fv) AS median_fv, COUNT(*) AS n_quarters
                FROM _qfv GROUP BY cik
            )
            SELECT q.cik, q.report_date, q.total_fv, m.median_fv,
                   ROUND(q.total_fv / m.median_fv, 0) AS ratio
            FROM _qfv q
            JOIN _cm m ON q.cik = m.cik
            WHERE m.n_quarters >= 3 AND m.median_fv > 0
              AND q.total_fv / m.median_fv > 100
        """).fetchdf()
        for _, row in scale_log.iterrows():
            logger.info("  1000x scale correction: CIK %s %s "
                        "(total_fv=%.0f, median=%.0f, ratio=%.0fx)",
                        row["cik"], row["report_date"],
                        row["total_fv"], row["median_fv"], row["ratio"])
    except Exception:
        pass  # Diagnostic only

    _phase_a_count = con.execute(
        "SELECT COUNT(*) FROM _bdc_phase_a"
    ).fetchone()[0]
    logger.info("  Phase A (filter+dedup): %d rows in %.1f s",
                _phase_a_count, time.time() - _t_phase)

    # =========================================================================
    # Phase B: Identifier parsing, issuer/instrument extraction, bad-issuer
    # cleanup, CC aggregate header exclusion, and affiliation-axis dedup.
    # Reads from materialized _bdc_phase_a, writes to _bdc_phase_b.
    # =========================================================================
    _t_phase = time.time()
    sql_phase_b = f"""
    CREATE TEMP TABLE _bdc_phase_b AS
    WITH
    -- CTE 5a: Initial split + helper columns for re-parsing
    -- Normalise em-dash (U+2014) to ' - ' and en-dash (U+2013) to '-' before
    -- splitting so that PennantPark (em-dash) and Goldman Sachs (en-dash) BDCs
    -- are handled consistently.
    initial_split AS (
        SELECT *,
            string_split({_norm_raw}, ' - ') AS _segments,
            CASE
                WHEN NOT contains({_norm_raw}, ' - ')
                THEN trim(_raw_id)
                ELSE trim(string_split({_norm_raw}, ' - ')[1])
            END AS _issuer_raw,
            CASE
                WHEN NOT contains({_norm_raw}, ' - ')
                THEN lower(trim(_raw_id))
                ELSE lower(trim(string_split({_norm_raw}, ' - ')[1]))
            END AS _issuer_lower,
            -- Pipe-separator detection: four 3-pipe sub-formats
            --   affil_last:    "Company | Instrument | Affiliation"  -> issuer = seg1
            --   company_first: "Company | Industry | Instrument"     -> issuer = seg1
            --   company_seg2:  "Category | Company | Instrument"     -> issuer = seg2
            --   slr:           "Type | Industry | Company | ..."     -> issuer = seg3
            CASE
                -- 3+ pipes: last segment is affiliation tag
                WHEN {has_pipe} AND len({pipe_parts}) >= 3
                     AND {affil_in}
                THEN trim({pipe_parts}[1])
                -- 3 pipes: seg1 has legal suffix -> company-first
                WHEN {has_pipe} AND len({pipe_parts}) = 3
                     AND {seg1_has_suffix}
                THEN trim({pipe_parts}[1])
                -- 3 pipes: seg3 is instrument AND seg2 has legal suffix -> company in seg2
                WHEN {has_pipe} AND len({pipe_parts}) = 3
                     AND {seg3_is_instrument}
                     AND {seg2_has_suffix}
                THEN trim({pipe_parts}[2])
                -- 3 pipes: seg3 is instrument AND seg2 is known industry -> company in seg1
                WHEN {has_pipe} AND len({pipe_parts}) = 3
                     AND {seg3_is_instrument}
                     AND {seg2_is_industry}
                THEN trim({pipe_parts}[1])
                -- SLR equipment-financing leaf: "Equipment Financing - 24.1% | Company | Industry | ..."
                WHEN {has_pipe} AND {slr_seg2_is_leaf_issuer}
                THEN trim({pipe_parts}[2])
                -- 3+ pipes: default SLR -> issuer = seg3
                WHEN {has_pipe} AND len({pipe_parts}) >= 3
                THEN trim({pipe_parts}[3])
                -- 2 pipes
                WHEN {has_pipe} AND len({pipe_parts}) = 2
                THEN trim({pipe_parts}[1])
                ELSE NULL
            END AS _pipe_issuer,
            -- Track which pipe variant for instrument_description assembly
            CASE
                WHEN {has_pipe} AND len({pipe_parts}) >= 3
                     AND {affil_in}
                THEN 'affil_last'
                WHEN {has_pipe} AND len({pipe_parts}) = 3
                     AND {seg1_has_suffix}
                THEN 'company_first'
                WHEN {has_pipe} AND len({pipe_parts}) = 3
                     AND {seg3_is_instrument}
                     AND {seg2_has_suffix}
                THEN 'company_seg2'
                WHEN {has_pipe} AND len({pipe_parts}) = 3
                     AND {seg3_is_instrument}
                     AND {seg2_is_industry}
                THEN 'company_first'
                WHEN {has_pipe} AND {slr_seg2_is_leaf_issuer}
                THEN 'slr_seg2_leaf'
                WHEN {has_pipe} AND len({pipe_parts}) >= 3
                THEN 'slr'
                WHEN {has_pipe} AND len({pipe_parts}) = 2
                THEN 'two_pipe'
                ELSE NULL
            END AS _pipe_format,
        FROM _bdc_phase_a
    ),

    -- CTE 5b: Re-parse with industry-prefix detection and pipe-format override
    parsed AS (
        SELECT * EXCLUDE (_issuer_raw, _issuer_lower, _pipe_issuer, _pipe_format, _segments),
            CASE
                -- Pipe format takes priority
                WHEN _pipe_issuer IS NOT NULL THEN _pipe_issuer
                -- Crescent-family hierarchy rows:
                -- Investments {{country}} {{Debt/Equity Investments}} {{industry}}
                -- {{issuer}} Investment Type {{instrument}} Interest/Maturity ...
                WHEN {_crescent_condition}
                THEN trim(regexp_extract(
                    {_crescent_clean_raw},
                    '{_crescent_issuer_re}',
                    1
                ))
                -- MSD Investment Corp. embeds the full SOI hierarchy in one
                -- typed-dimension value. Valid borrowers often lack LLC/Inc
                -- suffixes, so parse only this CIK's hierarchy instead of
                -- widening the generic bad-issuer guard.
                WHEN {_msd_hierarchy_condition}
                THEN COALESCE(
                    NULLIF(regexp_extract(
                        {_msd_clean_raw},
                        '^(.+?)\\s+(?:-|Reference Rate|Rate and Spread|Interest Rate|Maturity Date|Equity Interest Rate)(?:\\s|$)',
                        1
                    ), ''),
                    {_msd_clean_raw}
                )
                -- Industry prefix with 3+ segments: take segment 2 as issuer
                WHEN {industry_in}
                     AND len(_segments) >= 3
                THEN trim(_segments[2])
                -- Pct-prefix category + geography prefix (Blue Owl CIK 1817825):
                -- seg[1] = "NNN.N% of Shareholder's Equity", seg[2] = "Investments made in <Country>",
                -- seg[3] = <Industry>, seg[4] = <Company>
                WHEN len(_segments) >= 5
                     AND regexp_matches(trim(_segments[1]), '^\d[\d.]*%\s+')
                     AND NOT ({_seg1_entity_sql})
                     AND lower(trim(_segments[2])) LIKE 'investments made in%'
                     AND {_seg3_is_industry}
                THEN trim(_segments[4])
                -- Pct-prefix category + geography prefix (non-industry seg[3]):
                -- seg[3] = <Company> (not a known industry label)
                WHEN len(_segments) >= 4
                     AND regexp_matches(trim(_segments[1]), '^\d[\d.]*%\s+')
                     AND NOT ({_seg1_entity_sql})
                     AND lower(trim(_segments[2])) LIKE 'investments made in%'
                THEN trim(_segments[3])
                -- Pct-prefix category skip (PennantPark / Blue Owl):
                -- seg[1] = "NNN.N% Category", seg[2] = "NNN.N% Company ... Industry ..."
                WHEN len(_segments) >= 2
                     AND regexp_matches(trim(_segments[1]), '^\d[\d.]*%\s+')
                     AND NOT ({_seg1_entity_sql})
                     AND regexp_matches(trim(_segments[2]), '^\d[\d.]*%')
                THEN COALESCE(
                    NULLIF(regexp_extract(
                        regexp_replace(
                            regexp_replace(trim(_segments[2]), '^\d[\d.]*%\s+', ''),
                            '^(?i)Issuer Name\s+', ''
                        ),
                        '{_kw_boundary_re}',
                        1
                    ), ''),
                    regexp_replace(
                        regexp_replace(trim(_segments[2]), '^\d[\d.]*%\s+', ''),
                        '^(?i)Issuer Name\s+', ''
                    )
                )
                -- No-dash "Issuer Name" label (PennantPark variant):
                -- "Category Issuer Name <Company> Industry ..."
                WHEN NOT contains({_norm_raw}, ' - ')
                     AND NOT _issuer_lower LIKE 'investment %'
                     AND regexp_matches(_raw_id, '(?i)\\bIssuer Name\\s+')
                THEN COALESCE(
                    NULLIF(regexp_extract(
                        regexp_replace(_raw_id, '^.*?(?i)\\bIssuer Name\\s+', ''),
                        '{_kw_boundary_re}',
                        1
                    ), ''),
                    regexp_replace(_raw_id, '^.*?(?i)\\bIssuer Name\\s+', '')
                )
                -- Goldman Sachs hierarchical format (2-4 segments):
                -- seg[1] starts with "Investment ", last segment has
                -- "<pct>% <company> Industry ..." or "<pct>% <company> Interest Rate ..."
                -- Works for 2-seg ("Investment <type> - <pct>% <co> ..."),
                -- 3-seg ("Investment <cat> - <pct>% <geo+type> - <pct>% <co> ..."),
                -- 4-seg ("Investment <cat> - <pct>% <geo> - <pct>% <type> - <pct>% <co> ...").
                WHEN len(_segments) >= 2
                     AND _issuer_lower LIKE 'investment %'
                     AND regexp_matches(trim(_segments[-1]), '^-?\d[\d.]*%\s+\S')
                THEN COALESCE(
                    NULLIF(regexp_extract(
                        regexp_replace(trim(_segments[-1]), '^-?\d[\d.]*%\s+', ''),
                        '^(.+?)\s+(?:Industry|Interest Rate|Reference Rate|Maturity|Floor|PIK)(?:\s|$)',
                        1
                    ), ''),
                    regexp_replace(trim(_segments[-1]), '^-?\d[\d.]*%\s+', '')
                )
                -- Goldman Sachs 1-segment (no dash separator):
                -- "Investment <type> <pct>% <company> Industry ..."
                WHEN NOT contains(_raw_id, ' - ')
                     AND _issuer_lower LIKE 'investment %'
                     AND regexp_matches(_raw_id, '\d[\d.]*%\s+\S')
                THEN COALESCE(
                    NULLIF(regexp_extract(
                        regexp_replace(_raw_id, '^.*?\d[\d.]*%\s+', ''),
                        '^(.+?)\s+(?:Industry|Interest Rate|Reference Rate|Maturity|Floor|PIK)(?:\s|$)',
                        1
                    ), ''),
                    regexp_replace(_raw_id, '^.*?\d[\d.]*%\s+', '')
                )
                -- Default: first segment
                ELSE _issuer_raw
            END AS issuer_name,
            CASE
                -- 2-pipe: instrument = segment 2
                WHEN _pipe_issuer IS NOT NULL AND _pipe_format = 'two_pipe'
                THEN trim({pipe_parts}[2])
                -- Affiliation-last (3+): instrument = segment 2
                WHEN _pipe_issuer IS NOT NULL AND _pipe_format = 'affil_last'
                THEN trim({pipe_parts}[2])
                -- Company-first (3): instrument = segment 3
                WHEN _pipe_issuer IS NOT NULL AND _pipe_format = 'company_first'
                THEN trim({pipe_parts}[3])
                -- Company in seg2 (3): instrument = segment 3
                WHEN _pipe_issuer IS NOT NULL AND _pipe_format = 'company_seg2'
                THEN trim({pipe_parts}[3])
                -- SLR equipment-financing leaf: issuer = seg2, instrument = seg1 + seg3+
                WHEN _pipe_issuer IS NOT NULL AND _pipe_format = 'slr_seg2_leaf'
                THEN trim({pipe_parts}[1])
                     || CASE
                         WHEN len({pipe_parts}) >= 3
                         THEN ', ' || trim(array_to_string({pipe_parts}[3:], ' | '))
                         ELSE ''
                     END
                -- SLR (3+): combine segments 1, 2, and 4+ as instrument
                WHEN _pipe_issuer IS NOT NULL AND _pipe_format = 'slr'
                THEN trim({pipe_parts}[1]) || ', ' || trim({pipe_parts}[2])
                     || CASE
                         WHEN len({pipe_parts}) >= 4
                         THEN ', ' || trim(array_to_string({pipe_parts}[4:], ' | '))
                         ELSE ''
                     END
                -- Crescent-family hierarchy rows. If a trailing tranche label
                -- follows the month/year maturity (e.g. One/Four/Five), keep it
                -- in the instrument key so equal-FV borrower tranches do not
                -- collapse during staging deduplication.
                WHEN {_crescent_condition}
                THEN trim(regexp_extract(
                    {_crescent_clean_raw},
                    '{_crescent_instrument_re}',
                    1
                )) || COALESCE(
                    NULLIF(' - ' || trim(regexp_extract(
                        {_crescent_clean_raw},
                        '{_crescent_trailing_re}',
                        1
                    )), ' - '),
                    ''
                )
                WHEN {_msd_hierarchy_condition}
                THEN trim(COALESCE(
                    NULLIF(regexp_extract({_msd_clean_raw}, '^.+?\\s+-\\s+(.+)$', 1), ''),
                    NULLIF(regexp_extract(
                        {_msd_clean_raw},
                        '^.+?\\s+((?:Reference Rate|Rate and Spread|Interest Rate|Maturity Date|Equity Interest Rate).+)$',
                        1
                    ), ''),
                    ''
                ))
                -- Industry prefix with 3+ segments: segments 3+ as instrument
                WHEN {industry_in}
                     AND len(_segments) >= 3
                THEN regexp_replace(
                    trim(array_to_string(_segments[3:], ' - ')),
                    '^\\$?[\\d,.]+ ?', ''
                )
                -- Pct-prefix + geography + industry: instrument = category + segs 5+
                WHEN len(_segments) >= 5
                     AND regexp_matches(trim(_segments[1]), '^\d[\d.]*%\s+')
                     AND NOT ({_seg1_entity_sql})
                     AND lower(trim(_segments[2])) LIKE 'investments made in%'
                     AND {_seg3_is_industry}
                THEN regexp_replace(trim(_segments[1]), '^\d[\d.]*%\s+', '')
                     || CASE WHEN len(_segments) >= 6
                        THEN ' - ' || trim(array_to_string(_segments[5:], ' - '))
                        ELSE '' END
                -- Pct-prefix + geography (non-industry seg[3]): instrument = category + segs 4+
                WHEN len(_segments) >= 4
                     AND regexp_matches(trim(_segments[1]), '^\d[\d.]*%\s+')
                     AND NOT ({_seg1_entity_sql})
                     AND lower(trim(_segments[2])) LIKE 'investments made in%'
                THEN regexp_replace(trim(_segments[1]), '^\d[\d.]*%\s+', '')
                     || CASE WHEN len(_segments) >= 5
                        THEN ' - ' || trim(array_to_string(_segments[4:], ' - '))
                        ELSE '' END
                -- Pct-prefix category skip: instrument = category from seg[1]
                WHEN len(_segments) >= 2
                     AND regexp_matches(trim(_segments[1]), '^\d[\d.]*%\s+')
                     AND NOT ({_seg1_entity_sql})
                     AND regexp_matches(trim(_segments[2]), '^\d[\d.]*%')
                THEN regexp_replace(trim(_segments[1]), '^\d[\d.]*%\s+', '')
                -- No-dash "Issuer Name" label: instrument = text before "Issuer Name"
                WHEN NOT contains({_norm_raw}, ' - ')
                     AND NOT _issuer_lower LIKE 'investment %'
                     AND regexp_matches(_raw_id, '(?i)\\bIssuer Name\\s+')
                THEN regexp_replace(
                    regexp_replace(_raw_id, '(?i)\\bIssuer Name\\s+.*$', ''),
                    '^\d[\d.]*%\s+', ''
                )
                -- Goldman Sachs multi-segment: instrument = seg[1] minus "Investment " prefix
                WHEN len(_segments) >= 2
                     AND _issuer_lower LIKE 'investment %'
                     AND regexp_matches(trim(_segments[-1]), '^-?\d[\d.]*%\s+\S')
                THEN regexp_replace(trim(_segments[1]), '^(?i)Investment\s+', '')
                -- Goldman Sachs 1-segment: instrument from "Investment <type> ..."
                WHEN NOT contains(_raw_id, ' - ')
                     AND _issuer_lower LIKE 'investment %'
                     AND regexp_matches(_raw_id, '\d[\d.]*%\s+\S')
                THEN COALESCE(
                    NULLIF(regexp_extract(
                        regexp_replace(_raw_id, '^(?i)Investment\s+', ''),
                        '^(.+?)\s+\d[\d.]*%',
                        1
                    ), ''),
                    ''
                )
                -- No dash: empty instrument
                WHEN NOT contains(_raw_id, ' - ') THEN ''
                -- Default: segments 2+ as instrument
                ELSE regexp_replace(
                    trim(array_to_string(_segments[2:], ' - ')),
                    '^\\$?[\\d,.]+ ?', ''
                )
            END AS instrument_description
        FROM initial_split
    ),

    -- CTE 5c: Fix bad issuer names (extraction artifacts from dimension paths)
    -- When issuer_name is a generic label (e.g., "Investments") but the raw
    -- identifier contains entity signals (LLC, Inc, etc.), replace issuer_name
    -- with the full raw identifier to preserve the position data.
    -- Only filter rows where both issuer_name AND raw identifier are generic.
    no_bad_issuers AS (
        SELECT * EXCLUDE (issuer_name),
            CASE
                WHEN ({bad_issuer_filter})
                     AND ({_sql_has_entity_in_raw})
                THEN _raw_id
                ELSE issuer_name
            END AS issuer_name
        FROM parsed
        WHERE NOT (({bad_issuer_filter}) AND NOT ({_sql_has_entity_in_raw}))
    ),

    {_cc_agg_header_cte}

    -- CTE 5d: Affiliation-axis dedup -- same position tagged under multiple
    -- affiliation dimension members (e.g. Non-Controlled vs Affiliated) in
    -- the same filing.  This must stay position-level: distinct instruments
    -- for the same issuer and FV are separate holdings.
    no_affil_dupes AS (
        SELECT * FROM (
            SELECT *,
                ROW_NUMBER() OVER (
                    PARTITION BY cik, accession_number, report_date,
                                 regexp_replace(
                                     lower(trim(CAST(issuer_name AS VARCHAR))),
                                     '[^a-z0-9]+', ' ', 'g'
                                 ),
                                 regexp_replace(
                                     lower(trim(CAST(instrument_description AS VARCHAR))),
                                     '[^a-z0-9]+', ' ', 'g'
                                 ),
                                 ROUND(COALESCE(_fv, 0), 0),
                                 ROUND(COALESCE(_cost, 0), 0),
                                 ROUND(COALESCE(_pa, 0), 0),
                                 ROUND(COALESCE(_sh, 0), 0)
                    ORDER BY
                        CASE WHEN contains(COALESCE(lower(CAST(_raw_id AS VARCHAR)), ''), 'non-controlled') THEN 1 ELSE 0 END
                      + CASE WHEN contains(COALESCE(lower(CAST(_raw_id AS VARCHAR)), ''), 'non-control') THEN 1 ELSE 0 END
                      + CASE WHEN contains(COALESCE(lower(CAST(_raw_id AS VARCHAR)), ''), 'non-affiliated') THEN 1 ELSE 0 END
                      + CASE WHEN contains(COALESCE(lower(CAST(_raw_id AS VARCHAR)), ''), 'non-affiliate') THEN 1 ELSE 0 END
                      + CASE WHEN contains(COALESCE(lower(CAST(_raw_id AS VARCHAR)), ''), 'affiliated') THEN 1 ELSE 0 END
                      + CASE WHEN contains(COALESCE(lower(CAST(_raw_id AS VARCHAR)), ''), 'affiliate') THEN 1 ELSE 0 END
                      + CASE WHEN contains(COALESCE(lower(CAST(_raw_id AS VARCHAR)), ''), 'controlled') THEN 1 ELSE 0 END
                      + CASE WHEN contains(COALESCE(lower(CAST(_raw_id AS VARCHAR)), ''), 'control') THEN 1 ELSE 0 END,
                        LENGTH(COALESCE(CAST(_raw_id AS VARCHAR), '')),
                        COALESCE(CAST(_raw_id AS VARCHAR), ''),
                        COALESCE(CAST(dimensions_raw AS VARCHAR), ''),
                        COALESCE(CAST(affiliation AS VARCHAR), ''),
                        _row_id
                ) AS _affil_rank
            FROM {_affil_dedup_source}
        ) sub
        WHERE _affil_rank = 1
    )

    SELECT * FROM no_affil_dupes
    """
    con.execute(sql_phase_b)

    _phase_b_count = con.execute(
        "SELECT COUNT(*) FROM _bdc_phase_b"
    ).fetchone()[0]
    logger.info("  Phase B (parse+dedup): %d rows in %.1f s",
                _phase_b_count, time.time() - _t_phase)

    # =========================================================================
    # Phase C: Classification, schema mapping, enrichment, casing normalization.
    # Reads from materialized _bdc_phase_b, produces the final result.
    # =========================================================================
    _t_phase = time.time()
    sql_phase_c = f"""
    WITH
    -- CTE 6: Classify asset category
    classified AS (
        SELECT *,
            -- Precompute lowercase fields for classification
            COALESCE(lower(trim(CAST(instrument_description AS VARCHAR))), '') AS _lower_instr,
            COALESCE(lower(trim(CAST(investment_type AS VARCHAR))), '') AS _lower_type,
            COALESCE(lower(trim(CAST(_raw_id AS VARCHAR))), '') AS _lower_full,
            (_ir IS NOT NULL AND _ir != 0) AS _has_interest_rate,
            (_sh IS NOT NULL AND _sh != 0) AS _has_shares,
            (_bs IS NOT NULL AND _bs != 0) AS _has_basis_spread,
            (_pa IS NOT NULL AND _pa != 0) AS _has_principal_amount
        FROM _bdc_phase_b
    ),

    with_asset AS (
        SELECT *,
            {asset_case} AS asset_category
        FROM classified
    ),

    -- CTE 7: Classify issuer
    with_issuer AS (
        SELECT *,
            CASE
                WHEN asset_category = 'FUND' THEN 'FUND'
                -- Equity stakes in fund managers / lending vehicles
                WHEN asset_category IN ('EQUITY_COMMON', 'EQUITY_PREFERRED', 'OTHER')
                     AND ({fund_vehicle_sql})
                THEN 'FUND'
                ELSE 'CORPORATE'
            END AS issuer_category
        FROM with_asset
    ),

    -- CTE 8: Named co-invest reclassification
    reclassified AS (
        SELECT *,
            -- Precompute fields for coinvest detection
            COALESCE(lower(trim(CAST(issuer_name AS VARCHAR))), '') AS _lower_issuer,
            COALESCE(lower(trim(CAST(issuer_name AS VARCHAR))), '') || ' ' ||
                COALESCE(lower(trim(CAST(instrument_description AS VARCHAR))), '') || ' ' ||
                COALESCE(lower(trim(CAST(_raw_id AS VARCHAR))), '') AS _combined_coinvest,
            COALESCE(lower(trim(CAST(_raw_id AS VARCHAR))), '') AS _lower_bdc_id
        FROM with_issuer
    ),

    with_reclass AS (
        SELECT *,
            CASE
                WHEN {coinvest_expr} AND contains(
                    COALESCE(lower(CAST(issuer_name AS VARCHAR)), '') || ' ' || COALESCE(lower(CAST(instrument_description AS VARCHAR)), ''),
                    'preferred'
                ) THEN 'EQUITY_PREFERRED'
                WHEN {coinvest_expr} THEN 'EQUITY_COMMON'
                ELSE asset_category
            END AS asset_category_final,
            CASE
                WHEN {coinvest_expr} THEN 'CORPORATE'
                ELSE issuer_category
            END AS issuer_category_final
        FROM reclassified
    ),

    -- CTE 9: Filter money market funds
    no_mm AS (
        SELECT * FROM with_reclass
        WHERE NOT ({mm_check})
    ),

    -- CTE 10: Infer coupon type
    with_coupon AS (
        SELECT *,
            CASE
                WHEN _bs IS NOT NULL AND _bs != 0 THEN 'Floating'
                WHEN _ir IS NOT NULL AND _ir != 0 THEN 'Fixed'
                ELSE ''
            END AS coupon_type
        FROM no_mm
    ),

    -- CTE 10b: Text enrichment from investment_identifier
    with_enrichment AS (
        SELECT *,
            -- Reference rate type: SOFR/LIBOR/PRIME from identifier text
            CASE
                WHEN regexp_matches(lower(_raw_id), '\\bsofr\\b') THEN 'SOFR'
                WHEN regexp_matches(lower(_raw_id), '\\blibor\\b') THEN 'LIBOR'
                WHEN regexp_matches(lower(_raw_id), '\\bprime\\b') THEN 'PRIME'
                ELSE NULL
            END AS _text_ref_rate,
            -- Maturity date: extract from "M/D/YYYY Maturity", "Due M/D/YY",
            -- "Maturity Date MM/DD/YYYY", "Maturity M/D/YYYY" patterns
            COALESCE(
                NULLIF(regexp_extract(_raw_id,
                    '(\\d{{1,2}}/\\d{{1,2}}/\\d{{2,4}})\\s+[Mm]aturity', 1), ''),
                NULLIF(regexp_extract(_raw_id,
                    '(?:[Mm]aturity|[Dd]ue)\\s+(?:[Dd]ate\\s+)?(\\d{{1,2}}/\\d{{1,2}}/\\d{{2,4}})', 1), '')
            ) AS _text_maturity_raw,
            NULLIF(regexp_extract(
                replace(CAST(_raw_id AS VARCHAR), '\u00a0', ' '),
                '(?:[Mm]aturity\\s*/\\s*[Dd]issolution\\s+[Dd]ate|[Mm]aturity/\\s*[Dd]issolution\\s+[Dd]ate)\\s+(\\d{{1,2}}/\\d{{4}})',
                1
            ), '') AS _text_maturity_month_raw
        FROM with_coupon
    ),

    -- CTE 11: Map to unified schema
    unified AS (
        SELECT
            'bdc' AS source,
            LPAD(CAST(cik AS VARCHAR), 10, '0') AS cik,
            entity_name,
            accession_number,
            filing_date,
            report_date,
            {name_norm} AS issuer_name,
            instrument_description,
            '' AS cusip,
            '' AS isin,
            '' AS lei,
            '' AS ticker,
            _fv AS fair_value,
            _cost AS cost,
            upper(trim(regexp_replace(COALESCE(CAST(fair_value_unit AS VARCHAR), ''), '^.*:', ''))) AS fair_value_currency,
            upper(trim(regexp_replace(COALESCE(CAST(cost_unit AS VARCHAR), ''), '^.*:', ''))) AS cost_currency,
            CASE WHEN _pct IS NOT NULL AND _pct <= 0.50 THEN _pct * 100
                 WHEN _pct IS NOT NULL AND _pct > 50 THEN _pct / 100
                 ELSE _pct END AS pct_of_net_assets,
            asset_category_final AS asset_category,
            issuer_category_final AS issuer_category,
            '' AS index_classification,
            '' AS exposure_type,
            '' AS asset_class,
            '' AS fair_value_level,
            CASE WHEN _ir IS NOT NULL AND _ir < 0 THEN NULL
                 WHEN _ir IS NOT NULL AND _ir <= 0.50 THEN _ir * 100
                 WHEN _ir IS NOT NULL AND _ir >= 50 THEN _ir / 100
                 ELSE _ir END AS interest_rate,
            CASE WHEN _bs IS NOT NULL AND _bs < 0 THEN NULL
                 WHEN _bs IS NOT NULL AND _bs <= 0.50 THEN _bs * 100
                 WHEN _bs IS NOT NULL AND _bs >= 50 THEN _bs / 100
                 ELSE _bs END AS basis_spread,
            COALESCE(NULLIF(CAST(reference_rate_type AS VARCHAR), ''), _text_ref_rate, '')
                AS reference_rate_type,
            coupon_type,
            CASE WHEN _pik IS NOT NULL AND _pik < 0 THEN NULL
                 WHEN _pik IS NOT NULL AND _pik <= 0.50 THEN _pik * 100
                 WHEN _pik IS NOT NULL AND _pik >= 50 THEN _pik / 100
                 ELSE _pik END AS pik_rate,
            -- Maturity date with guard: reject dates before 1950
            -- and sentinel year 2099 (BDC convention for perpetual instruments)
            CASE
                WHEN maturity_date IS NOT NULL AND CAST(maturity_date AS VARCHAR) != ''
                     AND TRY_CAST(maturity_date AS DATE) >= DATE '1950-01-01'
                     AND YEAR(TRY_CAST(maturity_date AS DATE)) < 2099
                    THEN CAST(maturity_date AS VARCHAR)
                WHEN maturity_date IS NOT NULL AND CAST(maturity_date AS VARCHAR) != ''
                    THEN ''
                WHEN _text_maturity_raw IS NOT NULL THEN
                    CASE WHEN (
                        CASE WHEN LENGTH(regexp_extract(
                                 _text_maturity_raw, '/(\\d+)$', 1)) <= 2
                             THEN TRY_STRPTIME(_text_maturity_raw, '%m/%d/%y')
                             ELSE TRY_STRPTIME(_text_maturity_raw, '%m/%d/%Y')
                        END) >= DATE '1950-01-01'
                    AND YEAR(
                        CASE WHEN LENGTH(regexp_extract(
                                 _text_maturity_raw, '/(\\d+)$', 1)) <= 2
                             THEN TRY_STRPTIME(_text_maturity_raw, '%m/%d/%y')
                             ELSE TRY_STRPTIME(_text_maturity_raw, '%m/%d/%Y')
                        END) < 2099
                    THEN strftime(
                        CASE WHEN LENGTH(regexp_extract(
                                 _text_maturity_raw, '/(\\d+)$', 1)) <= 2
                             THEN TRY_STRPTIME(_text_maturity_raw, '%m/%d/%y')
                             ELSE TRY_STRPTIME(_text_maturity_raw, '%m/%d/%Y')
                        END,
                        '%Y-%m-%d')
                    ELSE '' END
                WHEN _text_maturity_month_raw IS NOT NULL THEN
                    CASE WHEN last_day(TRY_STRPTIME(_text_maturity_month_raw, '%m/%Y')) >= DATE '1950-01-01'
                          AND YEAR(last_day(TRY_STRPTIME(_text_maturity_month_raw, '%m/%Y'))) < 2099
                    THEN strftime(last_day(TRY_STRPTIME(_text_maturity_month_raw, '%m/%Y')), '%Y-%m-%d')
                    ELSE '' END
                ELSE ''
            END AS maturity_date,
            _sh AS shares_held,
            _pa AS principal_amount,
            upper(trim(regexp_replace(COALESCE(CAST(principal_amount_unit AS VARCHAR), ''), '^.*:', ''))) AS principal_amount_currency,
            CASE
                WHEN _pa IS NULL THEN NULL
                WHEN upper(trim(regexp_replace(COALESCE(CAST(principal_amount_unit AS VARCHAR), ''), '^.*:', ''))) IN ('', 'USD')
                THEN _pa
                WHEN fx.usd_per_currency IS NOT NULL THEN _pa * fx.usd_per_currency
                ELSE NULL
            END AS principal_amount_usd,
            CASE
                WHEN _pa IS NULL THEN NULL
                WHEN upper(trim(regexp_replace(COALESCE(CAST(principal_amount_unit AS VARCHAR), ''), '^.*:', ''))) IN ('', 'USD')
                THEN 1.0
                ELSE fx.usd_per_currency
            END AS principal_fx_rate_to_usd,
            CASE
                WHEN _pa IS NULL THEN ''
                WHEN upper(trim(regexp_replace(COALESCE(CAST(principal_amount_unit AS VARCHAR), ''), '^.*:', ''))) IN ('', 'USD')
                THEN 'source_usd'
                WHEN fx.usd_per_currency IS NOT NULL THEN 'reference_fx'
                ELSE 'missing_reference_fx'
            END AS principal_fx_status,
            _raw_id AS bdc_investment_identifier,
            form_type AS bdc_form_type,
            dimensions_raw AS bdc_dimensions_raw,
            _ugl AS bdc_unrealized_gain_loss,
            '' AS nport_holding_id,
            '' AS nport_series_name,
            '' AS nport_series_id,
            '' AS nport_asset_cat,
            '' AS nport_issuer_type,
            '' AS nport_payoff_profile,
            '' AS nport_investment_country,
            '' AS nport_is_restricted,
            '' AS nport_quarter,
            '' AS nport_is_default,
            '' AS nport_are_interest_payments_in_arrears,
            '' AS nport_is_paid_in_kind,
            '' AS nport_currency_code,
            '' AS nport_liquidity_classification,
            CASE WHEN lower(COALESCE(CAST(dimensions_raw AS VARCHAR), ''))
                          LIKE '%nonconsolidatedsubsidiar%'
                      OR lower(COALESCE(CAST(dimensions_raw AS VARCHAR), ''))
                          LIKE '%subsidiar%'
                 THEN 1 ELSE 0 END AS is_subsidiary,
            '' AS jv_subsidiary,
            '' AS entity_id,
            '' AS canonical_name,
            '' AS extracted_industry,
            '' AS gics_sub_industry,
            '' AS lien_position,
            '' AS position_id,
            _row_id
        FROM with_enrichment w
        LEFT JOIN fx_rates fx
          ON upper(trim(regexp_replace(COALESCE(CAST(w.principal_amount_unit AS VARCHAR), ''), '^.*:', ''))) = fx.currency
         AND CAST(w.report_date AS VARCHAR) = fx.rate_date
    ),

    -- CTE 12a: Fix PIK rate boundary errors.
    -- Raw XBRL pik_rate at 0.20-0.50 (20-50 bps) gets wrongly *100'd to 20-50%.
    -- If normalized pik_rate >= 20 and exceeds interest_rate, it was bps: /100.
    unified_pik_fixed AS (
        SELECT * EXCLUDE (pik_rate),
            CASE WHEN pik_rate >= 20
                  AND interest_rate IS NOT NULL
                  AND pik_rate > interest_rate
                 THEN pik_rate / 100
                 ELSE pik_rate END AS pik_rate
        FROM unified
    ),

    -- CTE 12: Normalize issuer_name casing within each CIK.
    -- When the same issuer appears with different casing across XBRL
    -- dimension paths, pick the most frequent variant per CIK.
    -- Tiebreak: prefer mixed-case over ALL-CAPS, then alphabetical.
    _casing_vote AS (
        SELECT cik, issuer_name, COUNT(*) AS _cnt
        FROM unified_pik_fixed
        WHERE issuer_name IS NOT NULL AND issuer_name != ''
        GROUP BY cik, issuer_name
    ),
    _canonical_casing AS (
        SELECT cik,
            LOWER(issuer_name) AS _name_lower,
            issuer_name AS _canonical
        FROM _casing_vote
        QUALIFY ROW_NUMBER() OVER (
            PARTITION BY cik, LOWER(issuer_name)
            ORDER BY _cnt DESC,
                CASE WHEN issuer_name = UPPER(issuer_name) THEN 1 ELSE 0 END,
                issuer_name
        ) = 1
    ),
    with_casing AS (
        SELECT u.* EXCLUDE (issuer_name),
            COALESCE(cc._canonical, u.issuer_name) AS issuer_name
        FROM unified_pik_fixed u
        LEFT JOIN _canonical_casing cc
            ON u.cik = cc.cik
            AND LOWER(u.issuer_name) = cc._name_lower
    )

    SELECT * FROM with_casing ORDER BY _row_id
    """

    result = con.execute(sql_phase_c).fetchdf()
    logger.info("  Phase C (classify+map): %d rows in %.1f s",
                len(result), time.time() - _t_phase)

    con.close()

    # Drop internal row id column
    result.drop(columns=["_row_id"], inplace=True)

    # Log filtering stats (input_count set during data source selection above)
    output_count = len(result)
    logger.info("  After all BDC filters: %d rows (%d removed)",
                output_count, input_count - output_count)

    logger.info("  BDC asset breakdown:")
    for cat, count in result["asset_category"].value_counts().items():
        logger.info("    %s: %d (%.1f%%)", cat, count, 100 * count / len(result))

    # Log text enrichment stats
    n = len(result)
    ref_filled = (result["reference_rate_type"] != "").sum()
    mat_filled = (result["maturity_date"] != "").sum()
    logger.info("  Text enrichment: reference_rate_type %d (%.1f%%), "
                "maturity_date %d (%.1f%%)",
                ref_filled, 100 * ref_filled / n if n else 0,
                mat_filled, 100 * mat_filled / n if n else 0)

    return result


# ---------------------------------------------------------------------------
# N-PORT preparation
# ---------------------------------------------------------------------------
