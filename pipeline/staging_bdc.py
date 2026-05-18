"""BDC holdings staging for the unified holdings pipeline."""

from __future__ import annotations

import logging

import duckdb
import pandas as pd

from pipeline.bdc_identifier import (
    _AFFILIATION_PREFIX_RE,
    _AFFILIATION_SUFFIX_RE,
    _AFFILIATION_TAGS,
    _sql_is_bdc_aggregate,
)
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

logger = logging.getLogger(__name__)


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

def _prepare_bdc(bdc_df: pd.DataFrame) -> pd.DataFrame:
    """Filter, parse, classify, and map BDC holdings to unified schema.

    Uses a DuckDB CTE pipeline for all data manipulation. The pandas
    DataFrame is registered as a virtual table, transformed entirely in
    SQL, and the result is fetched back as a pandas DataFrame.
    """
    logger.info("Preparing BDC holdings: %d input rows", len(bdc_df))

    if bdc_df.empty:
        from pipeline.unified_holdings import UNIFIED_COLUMNS
        return pd.DataFrame(columns=UNIFIED_COLUMNS)

    con = duckdb.connect()
    con.register("bdc_raw", bdc_df)

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
    affil_in = _sql_exact_match(
        "lower(trim(string_split(_raw_id, ' | ')[-1]))", _AFFILIATION_TAGS
    )
    # 3-pipe format detection helpers
    seg1_has_suffix = (
        f"regexp_matches(lower(trim(string_split(_raw_id, ' | ')[1])), "
        f"'{_LEGAL_SUFFIX_RE_SQL}')"
    )
    seg2_has_suffix = (
        f"regexp_matches(lower(trim(string_split(_raw_id, ' | ')[2])), "
        f"'{_LEGAL_SUFFIX_RE_SQL}')"
    )
    seg3_is_instrument = _sql_keyword_check(
        "lower(trim(string_split(_raw_id, ' | ')[3]))", _PIPE_INSTRUMENT_KEYWORDS
    )
    seg2_is_industry = _sql_exact_match(
        "lower(trim(string_split(_raw_id, ' | ')[2]))", _INDUSTRY_LABELS
    )
    name_norm = _sql_normalize_name("issuer_name")

    # Normalised raw identifier: em-dash -> ' - ', en-dash -> '-'
    _norm_raw = "regexp_replace(replace(_raw_id, '\u2014', ' - '), '\u2013', '-', 'g')"

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
    has_period = "period" in bdc_df.columns
    date_cutoff = ("AND (TRY_CAST(report_date AS DATE) >= '2022-01-01'"
                   " OR TRY_CAST(report_date AS DATE) IS NULL)")
    if has_period:
        period_sort_expr = "COALESCE(CAST(period AS VARCHAR), '')"
        period_filter = (
            f"""WHERE (TRY_CAST(period AS DATE) = TRY_CAST(report_date AS DATE)
               OR period IS NULL
               OR CAST(period AS VARCHAR) = '')
            {date_cutoff}"""
        )
    else:
        period_sort_expr = "''"
        period_filter = f"WHERE TRUE {date_cutoff}"

    sql = f"""
    WITH
    -- CTE 1: Normalise text columns, cast numerics, add row id
    -- Filter to current-period rows only (period = report_date).
    -- Comparative rows (period < report_date) are preserved in raw
    -- bdc_holdings.csv for position matching but excluded from the
    -- unified index to avoid double-counting.
    raw AS (
        SELECT
            *,
            ROW_NUMBER() OVER (
                ORDER BY
                    COALESCE(CAST(cik AS VARCHAR), ''),
                    COALESCE(CAST(report_date AS VARCHAR), ''),
                    COALESCE(CAST(filing_date AS VARCHAR), ''),
                    COALESCE(CAST(accession_number AS VARCHAR), ''),
                    COALESCE(CAST(form_type AS VARCHAR), ''),
                    {period_sort_expr},
                    COALESCE(CAST(investment_identifier AS VARCHAR), ''),
                    COALESCE(CAST(dimensions_raw AS VARCHAR), ''),
                    COALESCE(CAST(fair_value AS VARCHAR), ''),
                    COALESCE(CAST(cost AS VARCHAR), ''),
                    COALESCE(CAST(principal_amount AS VARCHAR), ''),
                    COALESCE(CAST(shares_held AS VARCHAR), '')
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
    strip_affil AS (
        SELECT * EXCLUDE (_raw_id, _lower_id),
            regexp_replace(
                regexp_replace(
                    _raw_id,
                    '{_AFFILIATION_PREFIX_RE}',
                    ''
                ),
                '{_AFFILIATION_SUFFIX_RE}',
                ''
            ) AS _raw_id,
            lower(trim(regexp_replace(
                regexp_replace(
                    _raw_id,
                    '{_AFFILIATION_PREFIX_RE}',
                    ''
                ),
                '{_AFFILIATION_SUFFIX_RE}',
                ''
            ))) AS _lower_id
        FROM no_amendments
    ),

    -- CTE 2: Filter aggregate/subtotal rows
    no_aggregates AS (
        SELECT * FROM strip_affil
        WHERE NOT ({agg_filter})
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

    -- CTE 4: Filter hierarchical prefix subtotals via self-join
    -- Requires the child row to also carry fair value (has_fv) to avoid
    -- false removal when an industry-suffixed metadata row (no FV) extends
    -- the identifier of a FV-carrying parent (e.g. CIK 845385:
    -- "Rockfish Seafood Grill, Inc. - First Lien Loan" vs
    -- "...First Lien Loan - Casual Dining" which has cost but no FV).
    no_subtotals AS (
        SELECT a.* FROM has_fv a
        WHERE NOT EXISTS (
            SELECT 1 FROM has_fv b
            WHERE a.cik = b.cik
              AND a.accession_number = b.accession_number
              AND b._raw_id LIKE a._raw_id || '%'
              AND LENGTH(b._raw_id) > LENGTH(a._raw_id) + 10
              AND a._raw_id IS NOT NULL
              AND LENGTH(a._raw_id) >= 3
        )
    ),

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
                WHEN contains(_raw_id, ' | ') AND len(string_split(_raw_id, ' | ')) >= 3
                     AND {affil_in}
                THEN trim(string_split(_raw_id, ' | ')[1])
                -- 3 pipes: seg1 has legal suffix -> company-first
                WHEN contains(_raw_id, ' | ') AND len(string_split(_raw_id, ' | ')) = 3
                     AND {seg1_has_suffix}
                THEN trim(string_split(_raw_id, ' | ')[1])
                -- 3 pipes: seg3 is instrument AND seg2 has legal suffix -> company in seg2
                WHEN contains(_raw_id, ' | ') AND len(string_split(_raw_id, ' | ')) = 3
                     AND {seg3_is_instrument}
                     AND {seg2_has_suffix}
                THEN trim(string_split(_raw_id, ' | ')[2])
                -- 3 pipes: seg3 is instrument AND seg2 is known industry -> company in seg1
                WHEN contains(_raw_id, ' | ') AND len(string_split(_raw_id, ' | ')) = 3
                     AND {seg3_is_instrument}
                     AND {seg2_is_industry}
                THEN trim(string_split(_raw_id, ' | ')[1])
                -- 3+ pipes: default SLR -> issuer = seg3
                WHEN contains(_raw_id, ' | ') AND len(string_split(_raw_id, ' | ')) >= 3
                THEN trim(string_split(_raw_id, ' | ')[3])
                -- 2 pipes
                WHEN contains(_raw_id, ' | ') AND len(string_split(_raw_id, ' | ')) = 2
                THEN trim(string_split(_raw_id, ' | ')[1])
                ELSE NULL
            END AS _pipe_issuer,
            -- Track which pipe variant for instrument_description assembly
            CASE
                WHEN contains(_raw_id, ' | ') AND len(string_split(_raw_id, ' | ')) >= 3
                     AND {affil_in}
                THEN 'affil_last'
                WHEN contains(_raw_id, ' | ') AND len(string_split(_raw_id, ' | ')) = 3
                     AND {seg1_has_suffix}
                THEN 'company_first'
                WHEN contains(_raw_id, ' | ') AND len(string_split(_raw_id, ' | ')) = 3
                     AND {seg3_is_instrument}
                     AND {seg2_has_suffix}
                THEN 'company_seg2'
                WHEN contains(_raw_id, ' | ') AND len(string_split(_raw_id, ' | ')) = 3
                     AND {seg3_is_instrument}
                     AND {seg2_is_industry}
                THEN 'company_first'
                WHEN contains(_raw_id, ' | ') AND len(string_split(_raw_id, ' | ')) >= 3
                THEN 'slr'
                WHEN contains(_raw_id, ' | ') AND len(string_split(_raw_id, ' | ')) = 2
                THEN 'two_pipe'
                ELSE NULL
            END AS _pipe_format,
        FROM no_subtotals
    ),

    -- CTE 5b: Re-parse with industry-prefix detection and pipe-format override
    parsed AS (
        SELECT * EXCLUDE (_issuer_raw, _issuer_lower, _pipe_issuer, _pipe_format, _segments),
            CASE
                -- Pipe format takes priority
                WHEN _pipe_issuer IS NOT NULL THEN _pipe_issuer
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
                THEN trim(string_split(_raw_id, ' | ')[2])
                -- Affiliation-last (3+): instrument = segment 2
                WHEN _pipe_issuer IS NOT NULL AND _pipe_format = 'affil_last'
                THEN trim(string_split(_raw_id, ' | ')[2])
                -- Company-first (3): instrument = segment 3
                WHEN _pipe_issuer IS NOT NULL AND _pipe_format = 'company_first'
                THEN trim(string_split(_raw_id, ' | ')[3])
                -- Company in seg2 (3): instrument = segment 3
                WHEN _pipe_issuer IS NOT NULL AND _pipe_format = 'company_seg2'
                THEN trim(string_split(_raw_id, ' | ')[3])
                -- SLR (3+): combine segments 1, 2, and 4+ as instrument
                WHEN _pipe_issuer IS NOT NULL AND _pipe_format = 'slr'
                THEN trim(string_split(_raw_id, ' | ')[1]) || ', ' || trim(string_split(_raw_id, ' | ')[2])
                     || CASE
                         WHEN len(string_split(_raw_id, ' | ')) >= 4
                         THEN ', ' || trim(array_to_string(string_split(_raw_id, ' | ')[4:], ' | '))
                         ELSE ''
                     END
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
            FROM no_bad_issuers
        ) sub
        WHERE _affil_rank = 1
    ),

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
        FROM no_affil_dupes
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
            ) AS _text_maturity_raw
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
                ELSE ''
            END AS maturity_date,
            _sh AS shares_held,
            _pa AS principal_amount,
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
            '' AS entity_id,
            '' AS canonical_name,
            '' AS extracted_industry,
            '' AS gics_sub_industry,
            '' AS position_id,
            _row_id
        FROM with_enrichment
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

    result = con.execute(sql).fetchdf()

    # Log 1000x scale corrections (if any)
    try:
        scale_log = con.execute("""
            SELECT q.cik, q.report_date, q.total_fv, m.median_fv,
                   ROUND(q.total_fv / m.median_fv, 0) AS ratio
            FROM _quarterly_fv q
            JOIN _cik_medians m ON q.cik = m.cik
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

    con.close()

    # Drop internal row id column
    result.drop(columns=["_row_id"], inplace=True)

    # Log filtering stats
    input_count = len(bdc_df)
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
