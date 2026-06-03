"""Position matching -- link the same instrument across consecutive quarters.

5-tier matching cascade with row-ID-based 1:1 enforcement:
  A: BDC within-filing comparatives (exact)
  B: Exact name / CUSIP match (exact)
  C: Regex-normalized name match (exact after normalization)
  D: Jaro-Winkler fuzzy match (approximate)
  E: Entity-constrained fingerprint match (entity_id + classification + principal bucket)

All data manipulation uses DuckDB SQL CTEs.
"""

import logging
import time
from pathlib import Path
from typing import Optional

import duckdb
import pandas as pd

from pipeline.config import (
    BDC_HOLDINGS_FILE,
    POSITION_ID_EDGES_FILE,
    POSITION_MATCHES_FILE,
    UNIFIED_HOLDINGS_FILE,
)
from pipeline.utils import UnionFind

logger = logging.getLogger(__name__)

# Maximum times a CUSIP may appear per CIK/quarter before being excluded
MAX_CUSIP_MULTIPLICITY = 5

# Maximum times an issuer_name may appear per CIK/quarter before being
# excluded from exact/normalized/fuzzy name matching.  Generic category
# headers (e.g. "Investment 1st Lien/Senior Secured Debt") can appear
# 100+ times per CIK-quarter and create thousands of false match pairs.
# P99 of legitimate name multiplicity is ~4; threshold of 10 is generous.
MAX_NAME_MULTIPLICITY = 10

# Jaro-Winkler threshold for fuzzy matching
MIN_JW_SIMILARITY = 0.88

# Max FV ratio for fuzzy match candidates (prevents nonsense matches)
MAX_FV_RATIO = 5.0

# FV ratio guards for higher-confidence tiers (catches unit-scale mismatches)
MAX_FV_RATIO_WITHIN_FILING = 100.0  # Tier A: generous (same filing)
MAX_FV_RATIO_IDENTIFIER = 50.0     # Tiers B1/B2/C: tighter

# Tokens that do not make a position_key independently identifying.  These
# are useful instrument descriptors, but a key made only of these words can
# merge unrelated issuers into one position chain.
_GENERIC_POSITION_KEY_TOKEN_RE = (
    "a|b|c|d|e|f|i|ii|iii|iv|v|class|series|common|preferred|prefs?|"
    "units?|shares?|stock|warrants?|term|loan|loans|revolver|revolving|"
    "first|second|third|lien|senior|secured|subordinated|unsecured|debt|"
    "equity|investment|investments|interest|rate|maturity|date|due|"
    "llc|inc|corp|corporation|company|co|ltd|lp|l|p|and|the|of|"
    "nc|na|n|a|none|null|unknown|lass|nits"
)


def _strong_position_key_sql(col: str) -> str:
    """Return SQL expression for keys safe enough for B1b matching.

    B1b is allowed to be stronger than exact-name matching only when the key
    contains issuer-specific substance.  Short or generic keys such as
    "lass units" and N-PORT placeholders such as "nc nc" must fall through.
    """
    norm = (
        f"regexp_replace(lower(trim(CAST({col} AS VARCHAR))), "
        "'[^a-z0-9]+', ' ', 'g')"
    )
    distinctive = (
        "trim(regexp_replace(' ' || "
        f"{norm}"
        f" || ' ', '\\b(?:{_GENERIC_POSITION_KEY_TOKEN_RE})\\b', ' ', 'g'))"
    )
    return (
        f"{norm} != '' "
        f"AND length({norm}) >= 12 "
        f"AND len(regexp_split_to_array({norm}, '\\s+')) >= 3 "
        f"AND regexp_matches({distinctive}, '[a-z0-9]{{4,}}') "
        f"AND NOT regexp_matches({norm}, "
        "'^(?:nc|na|n a|none|null|unknown)(?:\\s+(?:nc|na|n a|none|null|unknown))*$')"
    )

# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------

MATCH_COLUMNS = [
    "cik", "entity_name", "source", "index_classification",
    "begin_quarter", "begin_report_date", "begin_issuer_name",
    "begin_fair_value", "begin_cost", "begin_principal_amount",
    "begin_interest_rate", "begin_basis_spread", "begin_shares_held",
    "end_quarter", "end_report_date", "end_issuer_name",
    "end_fair_value", "end_cost", "end_principal_amount",
    "end_interest_rate", "end_basis_spread", "end_shares_held",
    "match_method", "match_key", "match_score", "span_months",
    "asset_category", "issuer_category", "maturity_date", "coupon_type",
    "position_id",
]

UNIFIED_SORT_COLUMNS = [
    "source", "cik", "report_date", "filing_date", "accession_number",
    "bdc_investment_identifier", "nport_holding_id", "issuer_name",
    "instrument_description", "fair_value", "cost", "principal_amount",
    "principal_amount_usd", "shares_held",
]

MATCH_SORT_COLUMNS = [c for c in MATCH_COLUMNS if c != "position_id"]

POSITION_ID_EDGE_COLUMNS = [
    "edge_type", "position_id", "cik", "source",
    "begin_report_date", "begin_quarter", "begin_issuer_name",
    "begin_fair_value",
    "end_report_date", "end_quarter", "end_issuer_name", "end_fair_value",
    "match_method", "match_key", "match_score", "span_months",
]


def _sort_existing(
    df: pd.DataFrame,
    columns: list[str],
) -> pd.DataFrame:
    """Return df sorted by the subset of columns it has."""
    sort_cols = [c for c in columns if c in df.columns]
    if not sort_cols or df.empty:
        return df.reset_index(drop=True)
    return df.sort_values(
        sort_cols,
        kind="mergesort",
        na_position="last",
    ).reset_index(drop=True)


def _write_position_id_edges(edges: list[dict]) -> None:
    """Persist auditable edges used to form position_id chains."""
    edges_df = pd.DataFrame(edges, columns=POSITION_ID_EDGE_COLUMNS)
    edges_df = _sort_existing(edges_df, POSITION_ID_EDGE_COLUMNS)
    POSITION_ID_EDGES_FILE.parent.mkdir(parents=True, exist_ok=True)
    edges_df.to_csv(POSITION_ID_EDGES_FILE, index=False)


def _validate_unique_position_ids(unified_df: pd.DataFrame) -> None:
    """Ensure one position_id appears at most once per CIK/source/report date."""
    required = {"cik", "source", "report_date", "position_id"}
    if unified_df.empty or not required.issubset(unified_df.columns):
        return

    ids = unified_df["position_id"].fillna("").astype(str).str.strip()
    check_df = unified_df.loc[ids.ne(""), [
        "cik", "source", "report_date", "position_id", "issuer_name",
        "fair_value",
    ]].copy()
    if check_df.empty:
        return

    counts = (
        check_df.groupby(
            ["cik", "source", "report_date", "position_id"],
            dropna=False,
        )
        .size()
        .reset_index(name="_count")
    )
    dupes = counts[counts["_count"] > 1]
    if dupes.empty:
        return

    sample_keys = dupes.sort_values(
        ["_count", "cik", "source", "report_date", "position_id"],
        ascending=[False, True, True, True, True],
    ).head(5)
    sample = check_df.merge(
        sample_keys[["cik", "source", "report_date", "position_id", "_count"]],
        on=["cik", "source", "report_date", "position_id"],
        how="inner",
    ).sort_values(["_count", "cik", "report_date", "position_id"], ascending=False)

    examples = []
    for _, row in sample.head(12).iterrows():
        examples.append(
            f"{row['cik']} {row['source']} {row['report_date']} "
            f"{row['position_id']} {row['issuer_name']} fv={row['fair_value']}"
        )
    raise ValueError(
        "position_id uniqueness violation: "
        f"{len(dupes)} duplicate (cik, source, report_date, position_id) "
        "groups. Examples: " + " | ".join(examples)
    )


# ---------------------------------------------------------------------------
# SQL helpers
# ---------------------------------------------------------------------------

def _quarter_label_sql(date_col: str) -> str:
    """SQL expression that maps a date column to 'YYYYqN' format."""
    return (
        f"CAST(YEAR(TRY_CAST({date_col} AS DATE)) AS VARCHAR) || "
        f"'q' || CAST(QUARTER(TRY_CAST({date_col} AS DATE)) AS VARCHAR)"
    )


def _quarter_from_date(value: object) -> str:
    """Return YYYYqN from a date-like value for edge artifact rows."""
    ts = pd.to_datetime(value, errors="coerce")
    if pd.isna(ts):
        return ""
    return f"{ts.year}q{((ts.month - 1) // 3) + 1}"


def _next_quarter_sql(qtr_col: str) -> str:
    """SQL expression that computes the next calendar quarter label.

    E.g. '2024q1' -> '2024q2', '2024q4' -> '2025q1'.
    """
    return (
        f"CASE "
        f"  WHEN CAST(SUBSTR({qtr_col}, 6, 1) AS INT) = 4 "
        f"  THEN CAST(CAST(SUBSTR({qtr_col}, 1, 4) AS INT) + 1 AS VARCHAR) || 'q1' "
        f"  ELSE SUBSTR({qtr_col}, 1, 4) || 'q' || "
        f"       CAST(CAST(SUBSTR({qtr_col}, 6, 1) AS INT) + 1 AS VARCHAR) "
        f"END"
    )


def _span_months_sql(begin_date: str, end_date: str) -> str:
    """SQL for approximate month span between two date columns."""
    return (
        f"DATEDIFF('month', TRY_CAST({begin_date} AS DATE), "
        f"TRY_CAST({end_date} AS DATE))"
    )


def _normalize_name_sql(col: str) -> str:
    """Aggressive regex normalization for matching (not display).

    Strips pipe suffixes, parentheticals, trailing ordinals, trailing
    punctuation, and collapses whitespace. More aggressive than the display
    normalizer in unified_holdings.py.
    """
    return (
        f"LOWER(TRIM("
        f"REGEXP_REPLACE("
        f"REGEXP_REPLACE("
        f"REGEXP_REPLACE("
        f"REGEXP_REPLACE("
        f"REGEXP_REPLACE({col}, "
        f"'\\s*\\|.*$', ''), "           # strip pipe suffixes
        f"'\\s*\\([^)]*\\)', '', 'g'), "  # strip parentheticals
        f"'\\s+\\d+$', ''), "             # strip trailing ordinals
        f"'[.,;:\\s]+$', ''), "           # strip trailing punctuation
        f"'\\s+', ' ', 'g')"             # collapse whitespace
        f"))"
    )


def _fv_proximity_sql(begin_fv: str, end_fv: str) -> str:
    """Log-ratio of fair values for tiebreaking. Lower = closer."""
    return (
        f"ABS(LN(GREATEST({begin_fv}, 1.0) / GREATEST({end_fv}, 1.0)))"
    )


# ---------------------------------------------------------------------------
# Tier A: BDC Within-Filing Comparatives
# ---------------------------------------------------------------------------

def _match_bdc_within_filing(con: duckdb.DuckDBPyConnection) -> str:
    """Tier A: pair current-period and prior-period rows from the same filing.

    Returns the name of the result table registered in con.
    """
    sql = f"""
    CREATE OR REPLACE TEMP TABLE tier_a AS
    WITH
    raw AS (
        SELECT *,
            ROW_NUMBER() OVER (
                ORDER BY
                    CAST(cik AS VARCHAR),
                    CAST(accession_number AS VARCHAR),
                    CAST(report_date AS VARCHAR),
                    CAST(period AS VARCHAR),
                    CAST(investment_identifier AS VARCHAR),
                    TRY_CAST(fair_value AS DOUBLE),
                    TRY_CAST(cost AS DOUBLE)
            ) AS _raw_row_id,
            {_quarter_label_sql('report_date')} AS qtr,
            {_quarter_label_sql('period')} AS period_qtr,
            TRY_CAST(fair_value AS DOUBLE) AS fv,
            TRY_CAST(cost AS DOUBLE) AS cost_val,
            TRY_CAST(principal_amount AS DOUBLE) AS pa,
            TRY_CAST(interest_rate AS DOUBLE) AS ir,
            TRY_CAST(basis_spread AS DOUBLE) AS bs,
            TRY_CAST(shares_held AS DOUBLE) AS sh,
            CAST(investment_identifier AS VARCHAR) AS _inv_id,
            CAST(accession_number AS VARCHAR) AS _acc,
            CAST(cik AS VARCHAR) AS _cik,
            CAST(entity_name AS VARCHAR) AS _ename
        FROM bdc_raw
        WHERE TRY_CAST(period AS DATE) IS NOT NULL
          AND TRY_CAST(report_date AS DATE) IS NOT NULL
    ),
    -- Amendment dedup: within same CIK + report_date + form family,
    -- keep only rows from the latest-filed accession.
    no_amendments AS (
        SELECT r.* FROM raw r
        INNER JOIN (
            SELECT _cik, report_date, accession_number,
                ROW_NUMBER() OVER (
                    PARTITION BY _cik, CAST(report_date AS VARCHAR),
                        REGEXP_REPLACE(CAST(form_type AS VARCHAR), '/A$', '')
                    ORDER BY CAST(filing_date AS VARCHAR) DESC
                ) AS _amd_rank
            FROM raw
            GROUP BY _cik, report_date, accession_number, form_type, filing_date
        ) ranked
          ON r._cik = ranked._cik
         AND r.report_date = ranked.report_date
         AND r.accession_number = ranked.accession_number
        WHERE ranked._amd_rank = 1
    ),
    current_rows AS (
        SELECT r.* FROM no_amendments r
        WHERE TRY_CAST(r.period AS DATE) = TRY_CAST(r.report_date AS DATE)
          AND r.fv IS NOT NULL AND r.fv != 0
          AND EXISTS (
              SELECT 1
              FROM unified_base u
              WHERE u.source = 'bdc'
                AND LPAD(REGEXP_REPLACE(CAST(u.cik AS VARCHAR), '[^0-9]', '', 'g'), 10, '0')
                  = LPAD(REGEXP_REPLACE(r._cik, '[^0-9]', '', 'g'), 10, '0')
                AND CAST(u.report_date AS VARCHAR) = CAST(r.report_date AS VARCHAR)
                AND CAST(u.bdc_investment_identifier AS VARCHAR) = r._inv_id
          )
    ),
    comparative_rows AS (
        SELECT * FROM no_amendments
        WHERE TRY_CAST(period AS DATE) < TRY_CAST(report_date AS DATE)
          AND fv IS NOT NULL AND fv != 0
    ),
    pairs AS (
        SELECT
            c._cik AS cik,
            c._ename AS entity_name,
            'bdc' AS source,
            comp.period_qtr AS begin_quarter,
            CAST(comp.period AS VARCHAR) AS begin_report_date,
            COALESCE(comp._inv_id, '') AS begin_issuer_name,
            comp.fv AS begin_fair_value,
            comp.cost_val AS begin_cost,
            comp.pa AS begin_principal_amount,
            CASE WHEN comp.ir IS NOT NULL AND comp.ir < 0 THEN NULL
                 WHEN comp.ir IS NOT NULL AND comp.ir <= 0.50 THEN comp.ir * 100
                 WHEN comp.ir IS NOT NULL AND comp.ir >= 50 THEN comp.ir / 100
                 ELSE comp.ir END AS begin_interest_rate,
            CASE WHEN comp.bs IS NOT NULL AND comp.bs < 0 THEN NULL
                 WHEN comp.bs IS NOT NULL AND comp.bs <= 0.50 THEN comp.bs * 100
                 WHEN comp.bs IS NOT NULL AND comp.bs >= 50 THEN comp.bs / 100
                 ELSE comp.bs END AS begin_basis_spread,
            comp.sh AS begin_shares_held,
            c.qtr AS end_quarter,
            CAST(c.report_date AS VARCHAR) AS end_report_date,
            COALESCE(c._inv_id, '') AS end_issuer_name,
            c.fv AS end_fair_value,
            c.cost_val AS end_cost,
            c.pa AS end_principal_amount,
            CASE WHEN c.ir IS NOT NULL AND c.ir < 0 THEN NULL
                 WHEN c.ir IS NOT NULL AND c.ir <= 0.50 THEN c.ir * 100
                 WHEN c.ir IS NOT NULL AND c.ir >= 50 THEN c.ir / 100
                 ELSE c.ir END AS end_interest_rate,
            CASE WHEN c.bs IS NOT NULL AND c.bs < 0 THEN NULL
                 WHEN c.bs IS NOT NULL AND c.bs <= 0.50 THEN c.bs * 100
                 WHEN c.bs IS NOT NULL AND c.bs >= 50 THEN c.bs / 100
                 ELSE c.bs END AS end_basis_spread,
            c.sh AS end_shares_held,
            'A_within_filing' AS match_method,
            CAST(c._acc AS VARCHAR) AS match_key,
            1.0 AS match_score,
            {_span_months_sql('comp.period', 'c.report_date')} AS span_months,
            comp._raw_row_id AS _begin_raw_id,
            c._raw_row_id AS _end_raw_id
        FROM current_rows c
        JOIN comparative_rows comp
          ON c._acc = comp._acc
         AND LOWER(c._inv_id) = LOWER(comp._inv_id)
         AND c._cik = comp._cik
        WHERE {_span_months_sql('comp.period', 'c.report_date')} >= 2
          AND {_span_months_sql('comp.period', 'c.report_date')} <= 13
          AND comp.fv > 0 AND c.fv > 0
          AND comp.fv / c.fv BETWEEN (1.0 / {MAX_FV_RATIO_WITHIN_FILING}) AND {MAX_FV_RATIO_WITHIN_FILING}
    ),
    -- 1:1 enforcement: double ROW_NUMBER on both end-side and begin-side
    rn_end AS (
        SELECT *,
            ROW_NUMBER() OVER (
                PARTITION BY _end_raw_id
                ORDER BY span_months ASC, _begin_raw_id ASC
            ) AS rn_e
        FROM pairs
    ),
    rn_begin AS (
        SELECT *,
            ROW_NUMBER() OVER (
                PARTITION BY _begin_raw_id
                ORDER BY span_months ASC, _end_raw_id ASC
            ) AS rn_b
        FROM rn_end WHERE rn_e = 1
    )
    SELECT cik, entity_name, source,
        begin_quarter, begin_report_date, begin_issuer_name,
        begin_fair_value, begin_cost, begin_principal_amount,
        begin_interest_rate, begin_basis_spread, begin_shares_held,
        end_quarter, end_report_date, end_issuer_name,
        end_fair_value, end_cost, end_principal_amount,
        end_interest_rate, end_basis_spread, end_shares_held,
        match_method, match_key, match_score, span_months
    FROM rn_begin
    WHERE rn_b = 1
    """
    con.execute(sql)
    return "tier_a"


# ---------------------------------------------------------------------------
# Tier A -> Unified Row ID mapping (end-side only)
# ---------------------------------------------------------------------------

def _map_tier_a_end_side_ids(con: duckdb.DuckDBPyConnection) -> None:
    """Create a mapping table of unified _row_ids matched by Tier A END side.

    Only excludes end-side (current-period) positions from B/C/D because
    end-side uses the same filing as unified (bdc_investment_identifier is
    reliable).  Begin-side positions are RELEASED to B/C/D because their
    raw identifiers come from a different filing and may not map to unified
    (the D2c cascade exclusion gap).
    """
    sql = """
    CREATE OR REPLACE TEMP TABLE tier_a_unified_ids AS
    SELECT DISTINCT u._row_id
    FROM tier_a a
    JOIN unified_base u
      ON a.cik = u.cik
     AND a.end_report_date = CAST(u.report_date AS VARCHAR)
     AND a.end_issuer_name = CAST(u.bdc_investment_identifier AS VARCHAR)
     AND u.source = 'bdc'
    """
    con.execute(sql)


# ---------------------------------------------------------------------------
# Tier B: Exact Name / CUSIP Match
# ---------------------------------------------------------------------------

def _match_exact_name(con: duckdb.DuckDBPyConnection) -> str:
    """Tier B: Exact CUSIP (B1) and exact issuer_name (B2) matching.

    Returns the name of the result table.
    """
    next_qtr = _next_quarter_sql("b.quarter")

    sql = f"""
    CREATE OR REPLACE TEMP TABLE tier_b AS
    WITH
    remaining AS (
        SELECT *
        FROM unified_base
        WHERE _row_id NOT IN (SELECT _row_id FROM tier_a_unified_ids)
    ),
    -- CUSIP: clean out placeholders and high-multiplicity values
    cusip_counts AS (
        SELECT cik, quarter, _cusip, COUNT(*) AS n
        FROM remaining
        WHERE _cusip IS NOT NULL AND _cusip != ''
        GROUP BY cik, quarter, _cusip
    ),
    with_cusip AS (
        SELECT r.*,
            CASE
                WHEN cc.n IS NOT NULL AND cc.n <= {MAX_CUSIP_MULTIPLICITY}
                     AND r._cusip NOT IN ('000000000', '999999999',
                                         '00000000', 'N/A', 'NONE', 'NA')
                THEN r._cusip
                ELSE NULL
            END AS clean_cusip
        FROM remaining r
        LEFT JOIN cusip_counts cc
          ON r.cik = cc.cik AND r.quarter = cc.quarter
         AND r._cusip = cc._cusip
    ),
    -- B1: CUSIP match
    pairs_cusip AS (
        SELECT
            e.cik, e.entity_name, e.source,
            b.quarter AS begin_quarter,
            CAST(b.report_date AS VARCHAR) AS begin_report_date,
            CAST(b.issuer_name AS VARCHAR) AS begin_issuer_name,
            b.fv AS begin_fair_value, b.cost_val AS begin_cost,
            b.pa AS begin_principal_amount, b.ir AS begin_interest_rate,
            b.bs AS begin_basis_spread, b.sh AS begin_shares_held,
            e.quarter AS end_quarter,
            CAST(e.report_date AS VARCHAR) AS end_report_date,
            CAST(e.issuer_name AS VARCHAR) AS end_issuer_name,
            e.fv AS end_fair_value, e.cost_val AS end_cost,
            e.pa AS end_principal_amount, e.ir AS end_interest_rate,
            e.bs AS end_basis_spread, e.sh AS end_shares_held,
            'B1_cusip' AS match_method,
            CAST(b.clean_cusip AS VARCHAR) AS match_key,
            1.0 AS match_score,
            3 AS span_months,
            b._row_id AS _begin_row_id,
            e._row_id AS _end_row_id,
            {_fv_proximity_sql('b.fv', 'e.fv')} AS _fv_prox
        FROM with_cusip b
        JOIN with_cusip e
          ON b.cik = e.cik
         AND e.quarter = ({next_qtr})
         AND b.clean_cusip IS NOT NULL
         AND b.clean_cusip = e.clean_cusip
         AND b.source = e.source
        WHERE b.fv > 0 AND e.fv > 0
          AND b.fv / e.fv BETWEEN (1.0 / {MAX_FV_RATIO_IDENTIFIER}) AND {MAX_FV_RATIO_IDENTIFIER}
    ),
    -- B1: 1:1 enforcement
    cusip_rn_begin AS (
        SELECT *,
            ROW_NUMBER() OVER (
                PARTITION BY _begin_row_id
                ORDER BY _fv_prox ASC, _end_row_id ASC
            ) AS rn_b
        FROM pairs_cusip
    ),
    cusip_rn_end AS (
        SELECT *,
            ROW_NUMBER() OVER (
                PARTITION BY _end_row_id
                ORDER BY _fv_prox ASC, _begin_row_id ASC
            ) AS rn_e
        FROM cusip_rn_begin WHERE rn_b = 1
    ),
    cusip_final AS (
        SELECT * FROM cusip_rn_end WHERE rn_e = 1
    ),
    -- Row IDs consumed by CUSIP matches
    cusip_used AS (
        SELECT _begin_row_id AS _row_id FROM cusip_final
        UNION
        SELECT _end_row_id FROM cusip_final
    ),
    -- B1b: Position key match (excluding CUSIP-matched rows)
    poskey_remaining AS (
        SELECT *,
            ({_strong_position_key_sql('_position_key')}) AS _position_key_strong
        FROM with_cusip
        WHERE _row_id NOT IN (SELECT _row_id FROM cusip_used)
    ),
    -- Position keys are allowed to link periods only when they are unique
    -- within each fund/source/report quarter. Repeated keys are issuer-level
    -- or otherwise lossy, so using them would collapse distinct positions.
    poskey_counts AS (
        SELECT cik, source, quarter, _position_key, COUNT(*) AS n
        FROM poskey_remaining
        WHERE _position_key_strong
        GROUP BY cik, source, quarter, _position_key
    ),
    high_mult_poskeys AS (
        SELECT cik, source, quarter, _position_key
        FROM poskey_counts
        WHERE n > 1
    ),
    pairs_poskey AS (
        SELECT
            e.cik, e.entity_name, e.source,
            b.quarter AS begin_quarter,
            CAST(b.report_date AS VARCHAR) AS begin_report_date,
            CAST(b.issuer_name AS VARCHAR) AS begin_issuer_name,
            b.fv AS begin_fair_value, b.cost_val AS begin_cost,
            b.pa AS begin_principal_amount, b.ir AS begin_interest_rate,
            b.bs AS begin_basis_spread, b.sh AS begin_shares_held,
            e.quarter AS end_quarter,
            CAST(e.report_date AS VARCHAR) AS end_report_date,
            CAST(e.issuer_name AS VARCHAR) AS end_issuer_name,
            e.fv AS end_fair_value, e.cost_val AS end_cost,
            e.pa AS end_principal_amount, e.ir AS end_interest_rate,
            e.bs AS end_basis_spread, e.sh AS end_shares_held,
            'B1b_position_key' AS match_method,
            CAST(b._position_key AS VARCHAR) AS match_key,
            1.0 AS match_score,
            3 AS span_months,
            b._row_id AS _begin_row_id,
            e._row_id AS _end_row_id,
            {_fv_proximity_sql('b.fv', 'e.fv')} AS _fv_prox,
            ABS(COALESCE(b.ir, 0) - COALESCE(e.ir, 0)) AS _rate_prox,
            {_fv_proximity_sql('COALESCE(b.pa, 1.0)', 'COALESCE(e.pa, 1.0)')}
                AS _pa_prox
        FROM poskey_remaining b
        JOIN poskey_remaining e
          ON b.cik = e.cik
         AND e.quarter = ({next_qtr})
         AND b._position_key = e._position_key
         AND b._position_key != ''
         AND b.source = e.source
        WHERE b._position_key_strong
        AND e._position_key_strong
        AND b._position_key NOT IN (
            SELECT _position_key FROM high_mult_poskeys
            WHERE cik = b.cik AND source = b.source AND quarter = b.quarter
        )
        AND e._position_key NOT IN (
            SELECT _position_key FROM high_mult_poskeys
            WHERE cik = e.cik AND source = e.source AND quarter = e.quarter
        )
        AND b.fv > 0 AND e.fv > 0
        AND b.fv / e.fv BETWEEN (1.0 / {MAX_FV_RATIO_IDENTIFIER}) AND {MAX_FV_RATIO_IDENTIFIER}
    ),
    -- B1b: 1:1 enforcement (composite tiebreaker: FV + rate + principal)
    poskey_rn_begin AS (
        SELECT *,
            ROW_NUMBER() OVER (
                PARTITION BY _begin_row_id
                ORDER BY _fv_prox ASC, _rate_prox ASC, _pa_prox ASC,
                    _end_row_id ASC
            ) AS rn_b
        FROM pairs_poskey
    ),
    poskey_rn_end AS (
        SELECT *,
            ROW_NUMBER() OVER (
                PARTITION BY _end_row_id
                ORDER BY _fv_prox ASC, _rate_prox ASC, _pa_prox ASC,
                    _begin_row_id ASC
            ) AS rn_e
        FROM poskey_rn_begin WHERE rn_b = 1
    ),
    poskey_final AS (
        SELECT * FROM poskey_rn_end WHERE rn_e = 1
    ),
    -- Row IDs consumed by position key matches
    poskey_used AS (
        SELECT _begin_row_id AS _row_id FROM poskey_final
        UNION
        SELECT _end_row_id FROM poskey_final
    ),
    -- B2: Exact issuer_name match (excluding CUSIP- and position-key-matched rows)
    name_remaining AS (
        SELECT * FROM with_cusip
        WHERE _row_id NOT IN (SELECT _row_id FROM cusip_used)
          AND _row_id NOT IN (SELECT _row_id FROM poskey_used)
    ),
    -- Name multiplicity: exclude generic names appearing too often
    name_counts AS (
        SELECT cik, quarter, _name_lower, COUNT(*) AS n
        FROM name_remaining
        WHERE _name_lower IS NOT NULL AND _name_lower != ''
        GROUP BY cik, quarter, _name_lower
    ),
    high_mult_names AS (
        SELECT cik, quarter, _name_lower
        FROM name_counts
        WHERE n > {MAX_NAME_MULTIPLICITY}
    ),
    pairs_name AS (
        SELECT
            e.cik, e.entity_name, e.source,
            b.quarter AS begin_quarter,
            CAST(b.report_date AS VARCHAR) AS begin_report_date,
            CAST(b.issuer_name AS VARCHAR) AS begin_issuer_name,
            b.fv AS begin_fair_value, b.cost_val AS begin_cost,
            b.pa AS begin_principal_amount, b.ir AS begin_interest_rate,
            b.bs AS begin_basis_spread, b.sh AS begin_shares_held,
            e.quarter AS end_quarter,
            CAST(e.report_date AS VARCHAR) AS end_report_date,
            CAST(e.issuer_name AS VARCHAR) AS end_issuer_name,
            e.fv AS end_fair_value, e.cost_val AS end_cost,
            e.pa AS end_principal_amount, e.ir AS end_interest_rate,
            e.bs AS end_basis_spread, e.sh AS end_shares_held,
            'B2_exact_name' AS match_method,
            CAST(b._name_lower AS VARCHAR) AS match_key,
            1.0 AS match_score,
            3 AS span_months,
            b._row_id AS _begin_row_id,
            e._row_id AS _end_row_id,
            {_fv_proximity_sql('b.fv', 'e.fv')} AS _fv_prox,
            ABS(COALESCE(b.ir, 0) - COALESCE(e.ir, 0)) AS _rate_prox,
            {_fv_proximity_sql('COALESCE(b.pa, 1.0)', 'COALESCE(e.pa, 1.0)')}
                AS _pa_prox
        FROM name_remaining b
        JOIN name_remaining e
          ON b.cik = e.cik
         AND e.quarter = ({next_qtr})
         AND b._name_lower = e._name_lower
         AND b._name_lower != ''
         AND b.source = e.source
        WHERE b._name_lower NOT IN (
            SELECT _name_lower FROM high_mult_names
            WHERE cik = b.cik AND quarter = b.quarter
        )
        AND e._name_lower NOT IN (
            SELECT _name_lower FROM high_mult_names
            WHERE cik = e.cik AND quarter = e.quarter
        )
        AND b.fv > 0 AND e.fv > 0
        AND b.fv / e.fv BETWEEN (1.0 / {MAX_FV_RATIO_IDENTIFIER}) AND {MAX_FV_RATIO_IDENTIFIER}
    ),
    -- B2: 1:1 enforcement (composite tiebreaker: FV + rate + principal)
    name_rn_begin AS (
        SELECT *,
            ROW_NUMBER() OVER (
                PARTITION BY _begin_row_id
                ORDER BY _fv_prox ASC, _rate_prox ASC, _pa_prox ASC,
                    _end_row_id ASC
            ) AS rn_b
        FROM pairs_name
    ),
    name_rn_end AS (
        SELECT *,
            ROW_NUMBER() OVER (
                PARTITION BY _end_row_id
                ORDER BY _fv_prox ASC, _rate_prox ASC, _pa_prox ASC,
                    _begin_row_id ASC
            ) AS rn_e
        FROM name_rn_begin WHERE rn_b = 1
    ),
    name_final AS (
        SELECT * FROM name_rn_end WHERE rn_e = 1
    ),
    -- Combine
    combined AS (
        SELECT cik, entity_name, source,
            begin_quarter, begin_report_date, begin_issuer_name,
            begin_fair_value, begin_cost, begin_principal_amount,
            begin_interest_rate, begin_basis_spread, begin_shares_held,
            end_quarter, end_report_date, end_issuer_name,
            end_fair_value, end_cost, end_principal_amount,
            end_interest_rate, end_basis_spread, end_shares_held,
            match_method, match_key, match_score, span_months,
            _begin_row_id, _end_row_id
        FROM cusip_final
        UNION ALL
        SELECT cik, entity_name, source,
            begin_quarter, begin_report_date, begin_issuer_name,
            begin_fair_value, begin_cost, begin_principal_amount,
            begin_interest_rate, begin_basis_spread, begin_shares_held,
            end_quarter, end_report_date, end_issuer_name,
            end_fair_value, end_cost, end_principal_amount,
            end_interest_rate, end_basis_spread, end_shares_held,
            match_method, match_key, match_score, span_months,
            _begin_row_id, _end_row_id
        FROM poskey_final
        UNION ALL
        SELECT cik, entity_name, source,
            begin_quarter, begin_report_date, begin_issuer_name,
            begin_fair_value, begin_cost, begin_principal_amount,
            begin_interest_rate, begin_basis_spread, begin_shares_held,
            end_quarter, end_report_date, end_issuer_name,
            end_fair_value, end_cost, end_principal_amount,
            end_interest_rate, end_basis_spread, end_shares_held,
            match_method, match_key, match_score, span_months,
            _begin_row_id, _end_row_id
        FROM name_final
    )
    SELECT * FROM combined
    """
    con.execute(sql)
    return "tier_b"


# ---------------------------------------------------------------------------
# Tier C: Regex-Normalized Name Match
# ---------------------------------------------------------------------------

def _match_normalized_name(con: duckdb.DuckDBPyConnection) -> str:
    """Tier C: Match after aggressive name normalization.

    Catches pipe suffix additions, parenthetical changes, trailing ordinals,
    and punctuation differences.

    Returns the name of the result table.
    """
    next_qtr = _next_quarter_sql("b.quarter")
    norm_sql = _normalize_name_sql("CAST(issuer_name AS VARCHAR)")

    sql = f"""
    CREATE OR REPLACE TEMP TABLE tier_c AS
    WITH
    all_used AS (
        SELECT _row_id FROM tier_a_unified_ids
        UNION
        SELECT _begin_row_id AS _row_id FROM tier_b
        UNION
        SELECT _end_row_id AS _row_id FROM tier_b
    ),
    remaining AS (
        SELECT u.*,
            {norm_sql} AS _norm_name
        FROM unified_base u
        WHERE u._row_id NOT IN (SELECT _row_id FROM all_used)
    ),
    -- Normalized-name multiplicity cap
    norm_name_counts AS (
        SELECT cik, quarter, _norm_name, COUNT(*) AS n
        FROM (
            SELECT cik, quarter, {norm_sql} AS _norm_name
            FROM unified_base
            WHERE _row_id NOT IN (SELECT _row_id FROM all_used)
        )
        WHERE _norm_name IS NOT NULL AND _norm_name != ''
        GROUP BY cik, quarter, _norm_name
    ),
    high_mult_norm AS (
        SELECT cik, quarter, _norm_name
        FROM norm_name_counts
        WHERE n > {MAX_NAME_MULTIPLICITY}
    ),
    pairs AS (
        SELECT
            e.cik, e.entity_name, e.source,
            b.quarter AS begin_quarter,
            CAST(b.report_date AS VARCHAR) AS begin_report_date,
            CAST(b.issuer_name AS VARCHAR) AS begin_issuer_name,
            b.fv AS begin_fair_value, b.cost_val AS begin_cost,
            b.pa AS begin_principal_amount, b.ir AS begin_interest_rate,
            b.bs AS begin_basis_spread, b.sh AS begin_shares_held,
            e.quarter AS end_quarter,
            CAST(e.report_date AS VARCHAR) AS end_report_date,
            CAST(e.issuer_name AS VARCHAR) AS end_issuer_name,
            e.fv AS end_fair_value, e.cost_val AS end_cost,
            e.pa AS end_principal_amount, e.ir AS end_interest_rate,
            e.bs AS end_basis_spread, e.sh AS end_shares_held,
            'C_normalized_name' AS match_method,
            CAST(b._norm_name AS VARCHAR) AS match_key,
            1.0 AS match_score,
            3 AS span_months,
            b._row_id AS _begin_row_id,
            e._row_id AS _end_row_id,
            {_fv_proximity_sql('b.fv', 'e.fv')} AS _fv_prox
        FROM remaining b
        JOIN remaining e
          ON b.cik = e.cik
         AND e.quarter = ({next_qtr})
         AND b._norm_name = e._norm_name
         AND b._norm_name != ''
         AND b.source = e.source
        WHERE b._norm_name NOT IN (
            SELECT _norm_name FROM high_mult_norm
            WHERE cik = b.cik AND quarter = b.quarter
        )
        AND e._norm_name NOT IN (
            SELECT _norm_name FROM high_mult_norm
            WHERE cik = e.cik AND quarter = e.quarter
        )
        AND b.fv > 0 AND e.fv > 0
        AND b.fv / e.fv BETWEEN (1.0 / {MAX_FV_RATIO_IDENTIFIER}) AND {MAX_FV_RATIO_IDENTIFIER}
    ),
    rn_begin AS (
        SELECT *,
            ROW_NUMBER() OVER (
                PARTITION BY _begin_row_id
                ORDER BY _fv_prox ASC, _end_row_id ASC
            ) AS rn_b
        FROM pairs
    ),
    rn_end AS (
        SELECT *,
            ROW_NUMBER() OVER (
                PARTITION BY _end_row_id
                ORDER BY _fv_prox ASC, _begin_row_id ASC
            ) AS rn_e
        FROM rn_begin WHERE rn_b = 1
    )
    SELECT cik, entity_name, source,
        begin_quarter, begin_report_date, begin_issuer_name,
        begin_fair_value, begin_cost, begin_principal_amount,
        begin_interest_rate, begin_basis_spread, begin_shares_held,
        end_quarter, end_report_date, end_issuer_name,
        end_fair_value, end_cost, end_principal_amount,
        end_interest_rate, end_basis_spread, end_shares_held,
        match_method, match_key, match_score, span_months,
        _begin_row_id, _end_row_id
    FROM rn_end WHERE rn_e = 1
    """
    con.execute(sql)
    return "tier_c"


# ---------------------------------------------------------------------------
# Tier D: Jaro-Winkler Fuzzy Match
# ---------------------------------------------------------------------------

def _match_fuzzy(con: duckdb.DuckDBPyConnection) -> str:
    """Tier D: Fuzzy matching with prefix-blocking and FV guard.

    Returns the name of the result table.
    """
    next_qtr = _next_quarter_sql("b.quarter")
    norm_sql = _normalize_name_sql("CAST(issuer_name AS VARCHAR)")

    sql = f"""
    CREATE OR REPLACE TEMP TABLE tier_d AS
    WITH
    all_used AS (
        SELECT _row_id FROM tier_a_unified_ids
        UNION
        SELECT _begin_row_id AS _row_id FROM tier_b
        UNION
        SELECT _end_row_id AS _row_id FROM tier_b
        UNION
        SELECT _begin_row_id AS _row_id FROM tier_c
        UNION
        SELECT _end_row_id AS _row_id FROM tier_c
    ),
    remaining AS (
        SELECT u.*,
            {norm_sql} AS _norm_name
        FROM unified_base u
        WHERE u._row_id NOT IN (SELECT _row_id FROM all_used)
    ),
    -- Normalized-name multiplicity cap for fuzzy matching
    d_norm_counts AS (
        SELECT cik, quarter, _norm_name, COUNT(*) AS n
        FROM (
            SELECT cik, quarter, {norm_sql} AS _norm_name
            FROM unified_base
            WHERE _row_id NOT IN (SELECT _row_id FROM all_used)
        )
        WHERE _norm_name IS NOT NULL AND _norm_name != ''
        GROUP BY cik, quarter, _norm_name
    ),
    d_high_mult_norm AS (
        SELECT cik, quarter, _norm_name
        FROM d_norm_counts
        WHERE n > {MAX_NAME_MULTIPLICITY}
    ),
    -- Prefix-blocking: only compare pairs sharing first 4 chars
    blocked AS (
        SELECT
            e.cik, e.entity_name, e.source,
            b.quarter AS b_quarter, b.report_date AS b_report_date,
            b.issuer_name AS b_issuer_name,
            b.fv AS b_fv, b.cost_val AS b_cost,
            b.pa AS b_pa, b.ir AS b_ir,
            b.bs AS b_bs, b.sh AS b_sh,
            e.quarter AS e_quarter, e.report_date AS e_report_date,
            e.issuer_name AS e_issuer_name,
            e.fv AS e_fv, e.cost_val AS e_cost,
            e.pa AS e_pa, e.ir AS e_ir,
            e.bs AS e_bs, e.sh AS e_sh,
            b._row_id AS _begin_row_id,
            e._row_id AS _end_row_id,
            b._norm_name AS b_norm,
            e._norm_name AS e_norm
        FROM remaining b
        JOIN remaining e
          ON b.cik = e.cik
         AND e.quarter = ({next_qtr})
         AND b.source = e.source
         AND b._norm_name != ''
         AND e._norm_name != ''
         AND LEFT(b._norm_name, 4) = LEFT(e._norm_name, 4)
        WHERE b._norm_name NOT IN (
            SELECT _norm_name FROM d_high_mult_norm
            WHERE cik = b.cik AND quarter = b.quarter
        )
        AND e._norm_name NOT IN (
            SELECT _norm_name FROM d_high_mult_norm
            WHERE cik = e.cik AND quarter = e.quarter
        )
    ),
    scored AS (
        SELECT *,
            jaro_winkler_similarity(b_norm, e_norm) AS jw,
            {_fv_proximity_sql('b_fv', 'e_fv')} AS _fv_prox
        FROM blocked
        WHERE jaro_winkler_similarity(b_norm, e_norm) >= {MIN_JW_SIMILARITY}
          AND b_fv > 0 AND e_fv > 0
          AND b_fv / e_fv BETWEEN (1.0 / {MAX_FV_RATIO}) AND {MAX_FV_RATIO}
    ),
    with_output AS (
        SELECT
            cik, entity_name, source,
            {_quarter_label_sql('b_report_date')} AS begin_quarter,
            CAST(b_report_date AS VARCHAR) AS begin_report_date,
            CAST(b_issuer_name AS VARCHAR) AS begin_issuer_name,
            b_fv AS begin_fair_value, b_cost AS begin_cost,
            b_pa AS begin_principal_amount, b_ir AS begin_interest_rate,
            b_bs AS begin_basis_spread, b_sh AS begin_shares_held,
            {_quarter_label_sql('e_report_date')} AS end_quarter,
            CAST(e_report_date AS VARCHAR) AS end_report_date,
            CAST(e_issuer_name AS VARCHAR) AS end_issuer_name,
            e_fv AS end_fair_value, e_cost AS end_cost,
            e_pa AS end_principal_amount, e_ir AS end_interest_rate,
            e_bs AS end_basis_spread, e_sh AS end_shares_held,
            'D_fuzzy' AS match_method,
            CAST(b_norm || ' ~ ' || e_norm AS VARCHAR) AS match_key,
            jw AS match_score,
            3 AS span_months,
            _begin_row_id,
            _end_row_id,
            _fv_prox
        FROM scored
    ),
    rn_begin AS (
        SELECT *,
            ROW_NUMBER() OVER (
                PARTITION BY _begin_row_id
                ORDER BY match_score DESC, _fv_prox ASC, _end_row_id ASC
            ) AS rn_b
        FROM with_output
    ),
    rn_end AS (
        SELECT *,
            ROW_NUMBER() OVER (
                PARTITION BY _end_row_id
                ORDER BY match_score DESC, _fv_prox ASC, _begin_row_id ASC
            ) AS rn_e
        FROM rn_begin WHERE rn_b = 1
    )
    SELECT cik, entity_name, source,
        begin_quarter, begin_report_date, begin_issuer_name,
        begin_fair_value, begin_cost, begin_principal_amount,
        begin_interest_rate, begin_basis_spread, begin_shares_held,
        end_quarter, end_report_date, end_issuer_name,
        end_fair_value, end_cost, end_principal_amount,
        end_interest_rate, end_basis_spread, end_shares_held,
        match_method, match_key, match_score, span_months,
        _begin_row_id, _end_row_id
    FROM rn_end WHERE rn_e = 1
    """
    con.execute(sql)
    return "tier_d"


# ---------------------------------------------------------------------------
# Tier E: Entity-Constrained Fingerprint Matching
# ---------------------------------------------------------------------------

def _match_entity_fingerprint(con: duckdb.DuckDBPyConnection) -> str:
    """Tier E: Entity-constrained fingerprint matching.

    Matches positions with same entity_id across consecutive quarters using
    index_classification + principal_amount_bucket as a composite key.
    Catches name changes and disambiguates multi-position entities.

    Returns the name of the result table.
    """
    next_qtr = _next_quarter_sql("b.quarter")

    sql = f"""
    CREATE OR REPLACE TEMP TABLE tier_e AS
    WITH
    all_used AS (
        SELECT _row_id FROM tier_a_unified_ids
        UNION
        SELECT _begin_row_id AS _row_id FROM tier_b
        UNION
        SELECT _end_row_id AS _row_id FROM tier_b
        UNION
        SELECT _begin_row_id AS _row_id FROM tier_c
        UNION
        SELECT _end_row_id AS _row_id FROM tier_c
        UNION
        SELECT _begin_row_id AS _row_id FROM tier_d
        UNION
        SELECT _end_row_id AS _row_id FROM tier_d
    ),
    remaining AS (
        SELECT u.*,
            CAST(entity_id AS VARCHAR) AS _entity_id,
            CAST(ROUND(COALESCE(pa, 0) / 500000.0, 0) AS INTEGER) AS _prin_bucket
        FROM unified_base u
        WHERE u._row_id NOT IN (SELECT _row_id FROM all_used)
          AND CAST(entity_id AS VARCHAR) IS NOT NULL
          AND CAST(entity_id AS VARCHAR) != ''
    ),
    -- Count positions per entity_id + CIK + quarter + classification
    -- Single-position entities don't need fingerprint disambiguation
    entity_counts AS (
        SELECT cik, source, quarter, _entity_id,
            CAST(index_classification AS VARCHAR) AS _ic,
            COUNT(*) AS n
        FROM remaining
        GROUP BY cik, source, quarter, _entity_id,
            CAST(index_classification AS VARCHAR)
    ),
    -- E1: Single-position entities -- no principal bucket needed
    pairs_single AS (
        SELECT
            e.cik, e.entity_name, e.source,
            b.quarter AS begin_quarter,
            CAST(b.report_date AS VARCHAR) AS begin_report_date,
            CAST(b.issuer_name AS VARCHAR) AS begin_issuer_name,
            b.fv AS begin_fair_value, b.cost_val AS begin_cost,
            b.pa AS begin_principal_amount, b.ir AS begin_interest_rate,
            b.bs AS begin_basis_spread, b.sh AS begin_shares_held,
            e.quarter AS end_quarter,
            CAST(e.report_date AS VARCHAR) AS end_report_date,
            CAST(e.issuer_name AS VARCHAR) AS end_issuer_name,
            e.fv AS end_fair_value, e.cost_val AS end_cost,
            e.pa AS end_principal_amount, e.ir AS end_interest_rate,
            e.bs AS end_basis_spread, e.sh AS end_shares_held,
            'E_entity_fingerprint' AS match_method,
            CAST(b._entity_id || '|' || COALESCE(CAST(b.index_classification AS VARCHAR), '')
                AS VARCHAR) AS match_key,
            1.0 AS match_score,
            3 AS span_months,
            b._row_id AS _begin_row_id,
            e._row_id AS _end_row_id,
            {_fv_proximity_sql('b.fv', 'e.fv')} AS _fv_prox,
            ABS(COALESCE(b.ir, 0) - COALESCE(e.ir, 0)) AS _rate_prox,
            {_fv_proximity_sql('COALESCE(b.pa, 1.0)', 'COALESCE(e.pa, 1.0)')}
                AS _pa_prox
        FROM remaining b
        JOIN remaining e
          ON b.cik = e.cik
         AND e.quarter = ({next_qtr})
         AND b.source = e.source
         AND b._entity_id = e._entity_id
         AND CAST(b.index_classification AS VARCHAR) = CAST(e.index_classification AS VARCHAR)
         AND b.fv > 0 AND e.fv > 0
         AND b.fv / e.fv BETWEEN (1.0 / {MAX_FV_RATIO}) AND {MAX_FV_RATIO}
        -- Both sides must be single-position for this entity+classification
        JOIN entity_counts bc
          ON b.cik = bc.cik AND b.source = bc.source
         AND b.quarter = bc.quarter AND b._entity_id = bc._entity_id
         AND CAST(b.index_classification AS VARCHAR) = bc._ic
         AND bc.n = 1
        JOIN entity_counts ec
          ON e.cik = ec.cik AND e.source = ec.source
         AND e.quarter = ec.quarter AND e._entity_id = ec._entity_id
         AND CAST(e.index_classification AS VARCHAR) = ec._ic
         AND ec.n = 1
    ),
    -- E2: Multi-position entities -- require principal bucket match
    pairs_multi AS (
        SELECT
            e.cik, e.entity_name, e.source,
            b.quarter AS begin_quarter,
            CAST(b.report_date AS VARCHAR) AS begin_report_date,
            CAST(b.issuer_name AS VARCHAR) AS begin_issuer_name,
            b.fv AS begin_fair_value, b.cost_val AS begin_cost,
            b.pa AS begin_principal_amount, b.ir AS begin_interest_rate,
            b.bs AS begin_basis_spread, b.sh AS begin_shares_held,
            e.quarter AS end_quarter,
            CAST(e.report_date AS VARCHAR) AS end_report_date,
            CAST(e.issuer_name AS VARCHAR) AS end_issuer_name,
            e.fv AS end_fair_value, e.cost_val AS end_cost,
            e.pa AS end_principal_amount, e.ir AS end_interest_rate,
            e.bs AS end_basis_spread, e.sh AS end_shares_held,
            'E_entity_fingerprint' AS match_method,
            CAST(b._entity_id || '|' || COALESCE(CAST(b.index_classification AS VARCHAR), '')
                || '|' || CAST(b._prin_bucket AS VARCHAR) AS VARCHAR) AS match_key,
            1.0 AS match_score,
            3 AS span_months,
            b._row_id AS _begin_row_id,
            e._row_id AS _end_row_id,
            {_fv_proximity_sql('b.fv', 'e.fv')} AS _fv_prox,
            ABS(COALESCE(b.ir, 0) - COALESCE(e.ir, 0)) AS _rate_prox,
            {_fv_proximity_sql('COALESCE(b.pa, 1.0)', 'COALESCE(e.pa, 1.0)')}
                AS _pa_prox
        FROM remaining b
        JOIN remaining e
          ON b.cik = e.cik
         AND e.quarter = ({next_qtr})
         AND b.source = e.source
         AND b._entity_id = e._entity_id
         AND CAST(b.index_classification AS VARCHAR) = CAST(e.index_classification AS VARCHAR)
         AND ABS(b._prin_bucket - e._prin_bucket) <= 1
         AND b.fv > 0 AND e.fv > 0
         AND b.fv / e.fv BETWEEN (1.0 / {MAX_FV_RATIO}) AND {MAX_FV_RATIO}
        -- At least one side is multi-position (not caught by E1)
        JOIN entity_counts bc
          ON b.cik = bc.cik AND b.source = bc.source
         AND b.quarter = bc.quarter AND b._entity_id = bc._entity_id
         AND CAST(b.index_classification AS VARCHAR) = bc._ic
        JOIN entity_counts ec
          ON e.cik = ec.cik AND e.source = ec.source
         AND e.quarter = ec.quarter AND e._entity_id = ec._entity_id
         AND CAST(e.index_classification AS VARCHAR) = ec._ic
        WHERE bc.n > 1 OR ec.n > 1
    ),
    -- Combine E1 + E2
    all_pairs AS (
        SELECT * FROM pairs_single
        UNION ALL
        SELECT * FROM pairs_multi
    ),
    rn_begin AS (
        SELECT *,
            ROW_NUMBER() OVER (
                PARTITION BY _begin_row_id
                ORDER BY _fv_prox ASC, _rate_prox ASC, _pa_prox ASC,
                    _end_row_id ASC
            ) AS rn_b
        FROM all_pairs
    ),
    rn_end AS (
        SELECT *,
            ROW_NUMBER() OVER (
                PARTITION BY _end_row_id
                ORDER BY _fv_prox ASC, _rate_prox ASC, _pa_prox ASC,
                    _begin_row_id ASC
            ) AS rn_e
        FROM rn_begin WHERE rn_b = 1
    )
    SELECT cik, entity_name, source,
        begin_quarter, begin_report_date, begin_issuer_name,
        begin_fair_value, begin_cost, begin_principal_amount,
        begin_interest_rate, begin_basis_spread, begin_shares_held,
        end_quarter, end_report_date, end_issuer_name,
        end_fair_value, end_cost, end_principal_amount,
        end_interest_rate, end_basis_spread, end_shares_held,
        match_method, match_key, match_score, span_months,
        _begin_row_id, _end_row_id
    FROM rn_end WHERE rn_e = 1
    """
    con.execute(sql)
    return "tier_e"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def match_positions(
    unified_df: Optional[pd.DataFrame] = None,
    bdc_raw_df: Optional[pd.DataFrame] = None,
    *,
    output_file: Optional[Path] = None,
) -> pd.DataFrame:
    """Match positions across consecutive quarters.

    Parameters
    ----------
    unified_df : DataFrame, optional
        Unified holdings (current-period only). Loaded from disk if None.
    bdc_raw_df : DataFrame, optional
        Raw BDC holdings with comparative periods. Loaded from disk if None.

    Returns
    -------
    DataFrame with matched position pairs and match metadata.
    """
    t0 = time.time()

    # Load from disk if not provided
    if unified_df is None:
        logger.info("Loading unified holdings from %s", UNIFIED_HOLDINGS_FILE.name)
        unified_df = pd.read_csv(UNIFIED_HOLDINGS_FILE, dtype=str)
        logger.info("  Loaded %d unified rows", len(unified_df))

    if bdc_raw_df is None:
        logger.info("Loading raw BDC holdings from %s", BDC_HOLDINGS_FILE.name)
        bdc_raw_df = pd.read_csv(BDC_HOLDINGS_FILE, dtype=str)
        logger.info("  Loaded %d raw BDC rows", len(bdc_raw_df))

    if unified_df.empty:
        logger.warning("Empty unified holdings -- nothing to match")
        return pd.DataFrame(columns=MATCH_COLUMNS)

    if "principal_amount_usd" not in unified_df.columns:
        unified_df = unified_df.copy()
        unified_df["principal_amount_usd"] = unified_df.get("principal_amount", "")

    unified_df = _sort_existing(unified_df, UNIFIED_SORT_COLUMNS)

    con = duckdb.connect()
    con.register("unified", unified_df)
    con.register("bdc_raw", bdc_raw_df)

    # --- Prepare unified base table with row IDs and typed columns ---
    sql = f"""
    CREATE OR REPLACE TEMP TABLE unified_base AS
    SELECT *,
        ROW_NUMBER() OVER (
            ORDER BY
                CAST(source AS VARCHAR),
                CAST(cik AS VARCHAR),
                CAST(report_date AS VARCHAR),
                CAST(filing_date AS VARCHAR),
                CAST(accession_number AS VARCHAR),
                CAST(bdc_investment_identifier AS VARCHAR),
                CAST(nport_holding_id AS VARCHAR),
                CAST(issuer_name AS VARCHAR),
                CAST(instrument_description AS VARCHAR),
                TRY_CAST(fair_value AS DOUBLE),
                TRY_CAST(cost AS DOUBLE),
                TRY_CAST(COALESCE(principal_amount_usd, principal_amount) AS DOUBLE),
                TRY_CAST(shares_held AS DOUBLE)
        ) AS _row_id,
        {_quarter_label_sql('report_date')} AS quarter,
        TRY_CAST(fair_value AS DOUBLE) AS fv,
        TRY_CAST(cost AS DOUBLE) AS cost_val,
        COALESCE(
            TRY_CAST(principal_amount_usd AS DOUBLE),
            TRY_CAST(principal_amount AS DOUBLE)
        ) AS pa,
        TRY_CAST(interest_rate AS DOUBLE) AS ir,
        TRY_CAST(basis_spread AS DOUBLE) AS bs,
        TRY_CAST(shares_held AS DOUBLE) AS sh,
        LOWER(TRIM(CAST(issuer_name AS VARCHAR))) AS _name_lower,
        CAST(cusip AS VARCHAR) AS _cusip,
        CAST(position_key AS VARCHAR) AS _position_key
    FROM unified
    WHERE TRY_CAST(fair_value AS DOUBLE) IS NOT NULL
      AND TRY_CAST(fair_value AS DOUBLE) != 0
    """
    con.execute(sql)

    # --- Tier A: BDC within-filing comparatives ---
    logger.info("Running Tier A: BDC within-filing comparatives...")
    _match_bdc_within_filing(con)
    tier_a_count = con.execute("SELECT COUNT(*) FROM tier_a").fetchone()[0]
    logger.info("  Tier A: %d pairs", tier_a_count)

    # Map Tier A END-side matches to unified row IDs for cascade exclusion.
    # Begin-side is released to B/C/D (deferred exclusion).
    _map_tier_a_end_side_ids(con)

    # --- Tier B: Exact name / CUSIP ---
    logger.info("Running Tier B: Exact name / CUSIP matching...")
    _match_exact_name(con)
    tier_b_counts = con.execute("""
        SELECT match_method, COUNT(*) AS n FROM tier_b GROUP BY match_method
    """).fetchdf()
    for _, row in tier_b_counts.iterrows():
        logger.info("  %s: %d pairs", row["match_method"], row["n"])

    # --- Tier C: Normalized name ---
    logger.info("Running Tier C: Normalized name matching...")
    _match_normalized_name(con)
    tier_c_count = con.execute("SELECT COUNT(*) FROM tier_c").fetchone()[0]
    logger.info("  Tier C: %d pairs", tier_c_count)

    # --- Tier D: Fuzzy ---
    logger.info("Running Tier D: Jaro-Winkler fuzzy matching...")
    _match_fuzzy(con)
    tier_d_count = con.execute("SELECT COUNT(*) FROM tier_d").fetchone()[0]
    logger.info("  Tier D: %d pairs", tier_d_count)

    # --- Tier E: Entity fingerprint ---
    logger.info("Running Tier E: Entity-constrained fingerprint matching...")
    _match_entity_fingerprint(con)
    tier_e_count = con.execute("SELECT COUNT(*) FROM tier_e").fetchone()[0]
    logger.info("  Tier E: %d pairs", tier_e_count)

    # --- Combine all tiers and annotate with classification ---
    # Two separate queries to avoid conditional JOIN anti-pattern:
    #   1. Tier A: join via bdc_investment_identifier (raw identifier)
    #   2. Tiers B/C/D: join via _row_id (fast integer lookup)
    logger.info("Assembling results and annotating classification...")

    def _select_cols(alias: str) -> str:
        return f"""{alias}.cik, {alias}.entity_name, {alias}.source,
        {alias}.begin_quarter, {alias}.begin_report_date, {alias}.begin_issuer_name,
        {alias}.begin_fair_value, {alias}.begin_cost, {alias}.begin_principal_amount,
        {alias}.begin_interest_rate, {alias}.begin_basis_spread, {alias}.begin_shares_held,
        {alias}.end_quarter, {alias}.end_report_date, {alias}.end_issuer_name,
        {alias}.end_fair_value, {alias}.end_cost, {alias}.end_principal_amount,
        {alias}.end_interest_rate, {alias}.end_basis_spread, {alias}.end_shares_held,
        {alias}.match_method, {alias}.match_key, {alias}.match_score, {alias}.span_months"""

    _class_cols = """CAST(u.index_classification AS VARCHAR) AS index_classification,
        CAST(u.asset_category AS VARCHAR) AS asset_category,
        CAST(u.issuer_category AS VARCHAR) AS issuer_category,
        CAST(u.maturity_date AS VARCHAR) AS maturity_date,
        CAST(u.coupon_type AS VARCHAR) AS coupon_type"""

    # Part 1: Tier A annotation via bdc_investment_identifier
    # Override begin/end_issuer_name with the cleaned issuer_name from
    # unified_base (Tier A stores raw investment_identifier in those cols).
    # Dedup: ROW_NUMBER picks the closest FV match when multiple unified rows
    # share the same (cik, report_date, bdc_investment_identifier).
    sql_a = f"""
    WITH tier_a_candidates AS (
        SELECT a.cik, a.entity_name, a.source,
            a.begin_quarter, a.begin_report_date, a.begin_issuer_name,
            a.begin_fair_value, a.begin_cost, a.begin_principal_amount,
            a.begin_interest_rate, a.begin_basis_spread, a.begin_shares_held,
            a.end_quarter, a.end_report_date, a.end_issuer_name,
            a.end_fair_value, a.end_cost, a.end_principal_amount,
            a.end_interest_rate, a.end_basis_spread, a.end_shares_held,
            a.match_method, a.match_key, a.match_score, a.span_months,
            CAST(u.issuer_name AS VARCHAR) AS _u_issuer_name,
            CAST(u.index_classification AS VARCHAR) AS _u_index_classification,
            CAST(u.asset_category AS VARCHAR) AS _u_asset_category,
            CAST(u.issuer_category AS VARCHAR) AS _u_issuer_category,
            CAST(u.maturity_date AS VARCHAR) AS _u_maturity_date,
            CAST(u.coupon_type AS VARCHAR) AS _u_coupon_type,
            u._row_id AS _u_row_id,
            ROW_NUMBER() OVER (
                PARTITION BY a.cik, a.end_report_date, a.end_issuer_name,
                             a.begin_report_date, a.begin_issuer_name
                ORDER BY ABS(COALESCE(TRY_CAST(a.end_fair_value AS DOUBLE), 0)
                             - COALESCE(u.fv, 0)) ASC,
                         COALESCE(u._row_id, 0) ASC
            ) AS _rn
        FROM tier_a a
        LEFT JOIN unified_base u
          ON a.cik = u.cik
         AND a.end_report_date = CAST(u.report_date AS VARCHAR)
         AND a.end_issuer_name = CAST(u.bdc_investment_identifier AS VARCHAR)
         AND u.source = 'bdc'
    )
    SELECT cik, entity_name, source,
        begin_quarter, begin_report_date,
        COALESCE(_u_issuer_name, begin_issuer_name) AS begin_issuer_name,
        begin_fair_value, begin_cost, begin_principal_amount,
        begin_interest_rate, begin_basis_spread, begin_shares_held,
        end_quarter, end_report_date,
        COALESCE(_u_issuer_name, end_issuer_name) AS end_issuer_name,
        end_fair_value, end_cost, end_principal_amount,
        end_interest_rate, end_basis_spread, end_shares_held,
        match_method, match_key, match_score, span_months,
        _u_index_classification AS index_classification,
        _u_asset_category AS asset_category,
        _u_issuer_category AS issuer_category,
        _u_maturity_date AS maturity_date,
        _u_coupon_type AS coupon_type
    FROM tier_a_candidates
    WHERE _rn = 1
    """

    # Part 2: Tiers B/C/D/E annotation via _row_id
    sql_bcd = f"""
    WITH bcd AS (
        SELECT * FROM tier_b
        UNION ALL
        SELECT * FROM tier_c
        UNION ALL
        SELECT * FROM tier_d
        UNION ALL
        SELECT * FROM tier_e
    )
    SELECT {_select_cols('m')},
        {_class_cols}
    FROM bcd m
    LEFT JOIN unified_base u
      ON m._end_row_id = u._row_id
    """

    result_a = con.execute(sql_a).fetchdf()
    result_bcd = con.execute(sql_bcd).fetchdf()
    result = pd.concat([result_a, result_bcd], ignore_index=True)
    con.close()

    # B3: Diagnostic logging for residual duplicates (safety net)
    if len(result) > 0:
        for side, date_col, name_col in [
            ("begin", "begin_report_date", "begin_issuer_name"),
            ("end", "end_report_date", "end_issuer_name"),
        ]:
            key_cols = ["cik", "source", date_col, name_col,
                        f"{side}_fair_value"]
            dup_count = result.duplicated(subset=key_cols, keep=False).sum()
            if dup_count > 0:
                logger.warning(
                    "  Residual %s-side duplicates: %d rows "
                    "(same cik/source/date/name/fv appear in multiple pairs)",
                    side, dup_count,
                )

    # Ensure column order
    for col in MATCH_COLUMNS:
        if col not in result.columns:
            result[col] = None
    result = result[MATCH_COLUMNS]
    result = _sort_existing(result, MATCH_SORT_COLUMNS)

    # Save
    _out_file = output_file or POSITION_MATCHES_FILE
    _out_file.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(_out_file, index=False)
    elapsed = time.time() - t0
    logger.info("Position matching complete: %d pairs in %.1f s", len(result), elapsed)
    if _out_file.exists():
        logger.info("Saved to %s (%.1f MB)",
                     _out_file.name,
                     _out_file.stat().st_size / (1024 * 1024))

    # Summary by method
    if len(result) > 0:
        method_summary = result.groupby("match_method").size()
        for method, count in method_summary.items():
            pct = 100 * count / len(result)
            logger.info("  %s: %d (%.1f%%)", method, count, pct)

    return result


# ---------------------------------------------------------------------------
# Position ID assignment -- stable tracking across quarters
# ---------------------------------------------------------------------------

def assign_position_ids(
    unified_df: pd.DataFrame,
    matches_df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Assign stable position_id values to unified holdings and match pairs.

    Maps each match-pair side to a unified row ID via DuckDB join, then
    computes connected components over (begin_uid, end_uid) edges using
    union-find.  Uses integer row IDs as UF nodes to avoid the name-based
    ambiguity that caused over-connection with the prior bridge-edge approach.

    Parameters
    ----------
    unified_df : DataFrame
        Unified holdings (with position_id column, initially blank).
    matches_df : DataFrame
        Output of match_positions().

    Returns
    -------
    (unified_df, matches_df) with position_id populated.
    """
    t0 = time.time()

    if matches_df.empty:
        # All singletons
        unified_df = _sort_existing(unified_df.copy(), UNIFIED_SORT_COLUMNS)
        unified_df["position_id"] = [
            f"POS-{i:08d}" for i in range(1, len(unified_df) + 1)
        ]
        _write_position_id_edges([])
        logger.info("No match pairs -- assigned %d singleton position IDs", len(unified_df))
        return unified_df, matches_df

    # ------------------------------------------------------------------
    # Step 1: Add stable integer row indices
    # ------------------------------------------------------------------
    unified_df = _sort_existing(unified_df.copy(), UNIFIED_SORT_COLUMNS)
    unified_df["_uid"] = range(len(unified_df))

    matches_df = _sort_existing(matches_df.copy(), MATCH_SORT_COLUMNS)
    matches_df["_midx"] = range(len(matches_df))

    # ------------------------------------------------------------------
    # Step 2: Map each match-pair side to a unified _uid via DuckDB
    # ------------------------------------------------------------------
    con = duckdb.connect()
    con.register("u", unified_df)
    con.register("m", matches_df)

    def _map_side_sql(side: str) -> str:
        """SQL to map one side (begin/end) of match pairs to unified _uid.

        Tier A matches join on bdc_investment_identifier (raw identifier);
        Tiers B/C/D join on issuer_name (cleaned).  Double ROW_NUMBER
        enforces 1:1 on *both* sides: each match picks at most one unified
        row (round 1), and each unified row is claimed by at most one match
        (round 2).  This prevents fan-out when multiple positions share
        the same issuer_name at the same CIK/date.
        """
        date_col = f"{side}_report_date"
        name_col = f"{side}_issuer_name"
        fv_col = f"{side}_fair_value"
        return f"""
        WITH
        tier_a_cand AS (
            SELECT
                m._midx,
                u._uid,
                ABS(COALESCE(TRY_CAST(m.{fv_col} AS DOUBLE), 0)
                    - COALESCE(TRY_CAST(u.fair_value AS DOUBLE), 0)) AS _fv_diff
            FROM m
            JOIN u
              ON CAST(m.cik AS VARCHAR) = CAST(u.cik AS VARCHAR)
             AND CAST(m.source AS VARCHAR) = CAST(u.source AS VARCHAR)
             AND CAST(m.{date_col} AS VARCHAR) = CAST(u.report_date AS VARCHAR)
             AND CAST(m.{name_col} AS VARCHAR) = CAST(u.bdc_investment_identifier AS VARCHAR)
            WHERE CAST(m.match_method AS VARCHAR) LIKE 'A%'
        ),
        poskey_cand AS (
            SELECT
                m._midx,
                u._uid,
                ABS(COALESCE(TRY_CAST(m.{fv_col} AS DOUBLE), 0)
                    - COALESCE(TRY_CAST(u.fair_value AS DOUBLE), 0)) AS _fv_diff
            FROM m
            JOIN u
              ON CAST(m.cik AS VARCHAR) = CAST(u.cik AS VARCHAR)
             AND CAST(m.source AS VARCHAR) = CAST(u.source AS VARCHAR)
             AND CAST(m.{date_col} AS VARCHAR) = CAST(u.report_date AS VARCHAR)
             AND CAST(m.match_key AS VARCHAR) = CAST(u.position_key AS VARCHAR)
            WHERE CAST(m.match_method AS VARCHAR) = 'B1b_position_key'
              AND ({_strong_position_key_sql('m.match_key')})
              AND ({_strong_position_key_sql('u.position_key')})
        ),
        other_cand AS (
            SELECT
                m._midx,
                u._uid,
                ABS(COALESCE(TRY_CAST(m.{fv_col} AS DOUBLE), 0)
                    - COALESCE(TRY_CAST(u.fair_value AS DOUBLE), 0)) AS _fv_diff
            FROM m
            JOIN u
              ON CAST(m.cik AS VARCHAR) = CAST(u.cik AS VARCHAR)
             AND CAST(m.source AS VARCHAR) = CAST(u.source AS VARCHAR)
             AND CAST(m.{date_col} AS VARCHAR) = CAST(u.report_date AS VARCHAR)
             AND CAST(m.{name_col} AS VARCHAR) = CAST(u.issuer_name AS VARCHAR)
            WHERE CAST(m.match_method AS VARCHAR) NOT LIKE 'A%'
              AND CAST(m.match_method AS VARCHAR) != 'B1b_position_key'
        ),
        all_cand AS (
            SELECT * FROM tier_a_cand
            UNION ALL
            SELECT * FROM poskey_cand
            UNION ALL
            SELECT * FROM other_cand
        ),
        -- Round 1: each match picks closest unified row
        ranked_match AS (
            SELECT *,
                ROW_NUMBER() OVER (
                    PARTITION BY _midx ORDER BY _fv_diff ASC, _uid ASC
                ) AS _rn_m
            FROM all_cand
        ),
        -- Round 2: each unified row keeps closest match
        ranked_uid AS (
            SELECT *,
                ROW_NUMBER() OVER (
                    PARTITION BY _uid ORDER BY _fv_diff ASC, _midx ASC
                ) AS _rn_u
            FROM ranked_match WHERE _rn_m = 1
        )
        SELECT _midx, _uid FROM ranked_uid WHERE _rn_u = 1
        """

    begin_map = con.execute(_map_side_sql("begin")).fetchdf()
    end_map = con.execute(_map_side_sql("end")).fetchdf()
    con.close()

    # Lookup: match_idx -> unified row id
    begin_uid = dict(zip(
        begin_map["_midx"].astype(int), begin_map["_uid"].astype(int),
    ))
    end_uid = dict(zip(
        end_map["_midx"].astype(int), end_map["_uid"].astype(int),
    ))

    n_begin = len(begin_uid)
    n_end = len(end_uid)
    n_match = len(matches_df)
    logger.info("  Match->unified mapping: begin %d/%d (%.1f%%), end %d/%d (%.1f%%)",
                n_begin, n_match, 100 * n_begin / max(n_match, 1),
                n_end, n_match, 100 * n_end / max(n_match, 1))

    # ------------------------------------------------------------------
    # Step 3: Build union-find on unified row IDs
    # Only use short-span (<=4 month) match pairs for chain formation.
    # Longer spans (6/9/12 month) are retained in the match file for
    # return computation but cause oversubscription when used for
    # chaining: multiple filings' comparatives all reference the same
    # prior year-end, competing for one unified row.
    # ------------------------------------------------------------------
    uf = UnionFind()
    row_date_keys = [
        (
            str(unified_df.at[i, "cik"]),
            str(unified_df.at[i, "source"]),
            str(unified_df.at[i, "report_date"]),
        )
        for i in range(len(unified_df))
    ]
    component_date_keys: dict[int, set[tuple[str, str, str]]] = {}

    def _register_component(uid: int) -> int:
        root = uf.find(uid)
        component_date_keys.setdefault(root, {row_date_keys[uid]})
        return root

    def _guarded_union(a: int, b: int) -> bool:
        """Union two rows only if the component remains date-unique."""
        root_a = _register_component(a)
        root_b = _register_component(b)
        if root_a == root_b:
            return True

        keys_a = component_date_keys[root_a]
        keys_b = component_date_keys[root_b]
        if not keys_a.isdisjoint(keys_b):
            return False

        merged = keys_a | keys_b
        uf.union(a, b)
        new_root = uf.find(a)
        component_date_keys.pop(root_a, None)
        component_date_keys.pop(root_b, None)
        component_date_keys[new_root] = merged
        return True

    n_edges = 0
    n_skipped_date_collision = 0
    used_match_midx: set[int] = set()
    used_supp_edges: set[tuple[int, int]] = set()
    spans = pd.to_numeric(matches_df["span_months"], errors="coerce").fillna(99)
    for midx in range(n_match):
        if spans.iloc[midx] > 4:
            continue
        b = begin_uid.get(midx)
        e = end_uid.get(midx)
        if b is not None and e is not None:
            if _guarded_union(b, e):
                n_edges += 1
                used_match_midx.add(midx)
            else:
                n_skipped_date_collision += 1
        elif b is not None:
            _register_component(b)  # register isolated node
        elif e is not None:
            _register_component(e)

    logger.info("  UF edges from match pairs (span<=4mo): %d (of %d total pairs)",
                n_edges, n_match)
    if n_skipped_date_collision:
        logger.warning(
            "  Skipped %d match edges that would merge duplicate report-date rows",
            n_skipped_date_collision,
        )

    # ------------------------------------------------------------------
    # Step 3b: Supplementary consecutive-quarter matching
    # Tier A cascade exclusion prevents B2 from matching positions that
    # Tier A claimed.  When those Tier A edges fail to form (begin-side
    # mapping failure), the positions are stranded as singletons despite
    # having identical issuer_names in adjacent quarters.
    # Fix: run B2-style issuer_name matching directly on unified holdings
    # with double 1:1 enforcement, and add new edges to the UF.
    # ------------------------------------------------------------------
    next_qtr = _next_quarter_sql("a.qtr")
    con2 = duckdb.connect()
    con2.register("u", unified_df)

    supp_sql = f"""
    WITH base AS (
        SELECT _uid,
            CAST(cik AS VARCHAR) AS cik,
            CAST(source AS VARCHAR) AS source,
            {_quarter_label_sql('report_date')} AS qtr,
            LOWER(TRIM(CAST(issuer_name AS VARCHAR))) AS _name,
            TRY_CAST(fair_value AS DOUBLE) AS fv
        FROM u
        WHERE TRY_CAST(fair_value AS DOUBLE) IS NOT NULL
          AND TRY_CAST(fair_value AS DOUBLE) != 0
          AND TRIM(CAST(issuer_name AS VARCHAR)) != ''
    ),
    -- Only use names that appear exactly once per CIK/quarter.
    -- Multi-tranche positions (same name, different bonds) would
    -- merge into mega-chains without a stable sub-identifier.
    name_counts AS (
        SELECT cik, source, qtr, _name, COUNT(*) AS n
        FROM base GROUP BY cik, source, qtr, _name
    ),
    unique_base AS (
        SELECT b.* FROM base b
        JOIN name_counts nc
          ON b.cik = nc.cik AND b.source = nc.source
         AND b.qtr = nc.qtr AND b._name = nc._name
        WHERE nc.n = 1
    ),
    pairs AS (
        SELECT a._uid AS uid_a, b._uid AS uid_b,
            ABS(LN(GREATEST(ABS(a.fv), 1.0) / GREATEST(ABS(b.fv), 1.0))) AS fv_prox
        FROM unique_base a
        JOIN unique_base b
          ON a.cik = b.cik AND a.source = b.source
         AND b.qtr = ({next_qtr})
         AND a._name = b._name
         AND ABS(a.fv) / GREATEST(ABS(b.fv), 1.0) BETWEEN (1.0 / {MAX_FV_RATIO}) AND {MAX_FV_RATIO}
         AND ABS(b.fv) / GREATEST(ABS(a.fv), 1.0) BETWEEN (1.0 / {MAX_FV_RATIO}) AND {MAX_FV_RATIO}
    ),
    rn_a AS (
        SELECT *,
            ROW_NUMBER() OVER (
                PARTITION BY uid_a ORDER BY fv_prox ASC, uid_b ASC
            ) AS rn1
        FROM pairs
    ),
    rn_b AS (
        SELECT *,
            ROW_NUMBER() OVER (
                PARTITION BY uid_b ORDER BY fv_prox ASC, uid_a ASC
            ) AS rn2
        FROM rn_a WHERE rn1 = 1
    )
    SELECT uid_a, uid_b FROM rn_b WHERE rn2 = 1
    """
    supp_pairs = con2.execute(supp_sql).fetchdf()
    con2.close()

    n_supp = 0
    n_supp_skipped_date_collision = 0
    if not supp_pairs.empty:
        uid_a_arr = supp_pairs["uid_a"].astype(int).values
        uid_b_arr = supp_pairs["uid_b"].astype(int).values
        for a, b in zip(uid_a_arr, uid_b_arr):
            root_a = _register_component(a)
            root_b = _register_component(b)
            if root_a == root_b:
                continue
            if not _guarded_union(a, b):
                n_supp_skipped_date_collision += 1
                continue
            used_supp_edges.add((a, b))
            if root_a != root_b:
                n_supp += 1

    logger.info("  Supplementary B2 edges: %d new connections (of %d pairs)",
                n_supp, len(supp_pairs))
    if n_supp_skipped_date_collision:
        logger.warning(
            "  Skipped %d supplementary edges that would merge duplicate report-date rows",
            n_supp_skipped_date_collision,
        )

    # ------------------------------------------------------------------
    # Step 4: Assign component IDs (sorted for determinism)
    # ------------------------------------------------------------------
    components = uf.components()
    uid_to_pid: dict[int, str] = {}
    ordered_components = sorted(
        (sorted(members) for members in components.values()),
        key=lambda members: members[0],
    )
    for i, members in enumerate(ordered_components, 1):
        pid = f"POS-{i:08d}"
        for uid in members:
            uid_to_pid[uid] = pid

    n_components = len(ordered_components)

    # Singletons: unified rows not in any component
    next_id = n_components + 1
    n_singletons = 0
    for uid in range(len(unified_df)):
        if uid not in uid_to_pid:
            uid_to_pid[uid] = f"POS-{next_id:08d}"
            next_id += 1
            n_singletons += 1

    # Write position_id directly by row index (no join = no fan-out)
    unified_df["position_id"] = [uid_to_pid[i] for i in range(len(unified_df))]
    _validate_unique_position_ids(unified_df)

    # ------------------------------------------------------------------
    # Step 5: Tag matches (prefer end_uid which is always current-period)
    # ------------------------------------------------------------------
    match_pids = []
    n_unlinked = 0
    for midx in range(n_match):
        e = end_uid.get(midx)
        b = begin_uid.get(midx)
        if e is not None:
            match_pids.append(uid_to_pid[e])
        elif b is not None:
            match_pids.append(uid_to_pid[b])
        else:
            match_pids.append("")
            n_unlinked += 1
    matches_df["position_id"] = match_pids
    matches_df.drop(columns=["_midx"], inplace=True)

    if n_unlinked:
        logger.warning(
            "  %d match pairs could not be linked to any unified row; "
            "dropping them from assigned match output",
            n_unlinked,
        )

    # ------------------------------------------------------------------
    # Step 5b: Persist auditable chain-forming edges
    # ------------------------------------------------------------------
    uid_lookup = unified_df.set_index("_uid", drop=False)
    edge_rows: list[dict] = []
    for midx in range(n_match):
        if midx not in used_match_midx:
            continue
        b = begin_uid.get(midx)
        e = end_uid.get(midx)
        if b is None or e is None or spans.iloc[midx] > 4:
            continue
        row = matches_df.iloc[midx]
        edge_rows.append({
            "edge_type": "match_pair",
            "position_id": uid_to_pid[e],
            "cik": row.get("cik", ""),
            "source": row.get("source", ""),
            "begin_report_date": row.get("begin_report_date", ""),
            "begin_quarter": row.get("begin_quarter", ""),
            "begin_issuer_name": row.get("begin_issuer_name", ""),
            "begin_fair_value": row.get("begin_fair_value", ""),
            "end_report_date": row.get("end_report_date", ""),
            "end_quarter": row.get("end_quarter", ""),
            "end_issuer_name": row.get("end_issuer_name", ""),
            "end_fair_value": row.get("end_fair_value", ""),
            "match_method": row.get("match_method", ""),
            "match_key": row.get("match_key", ""),
            "match_score": row.get("match_score", ""),
            "span_months": row.get("span_months", ""),
        })
    for item in supp_pairs.itertuples(index=False):
        a = int(item.uid_a)
        b = int(item.uid_b)
        if (a, b) not in used_supp_edges:
            continue
        begin = uid_lookup.loc[a]
        end = uid_lookup.loc[b]
        edge_rows.append({
            "edge_type": "supplementary_b2",
            "position_id": uid_to_pid[b],
            "cik": end.get("cik", ""),
            "source": end.get("source", ""),
            "begin_report_date": begin.get("report_date", ""),
            "begin_quarter": _quarter_from_date(begin.get("report_date", "")),
            "begin_issuer_name": begin.get("issuer_name", ""),
            "begin_fair_value": begin.get("fair_value", ""),
            "end_report_date": end.get("report_date", ""),
            "end_quarter": _quarter_from_date(end.get("report_date", "")),
            "end_issuer_name": end.get("issuer_name", ""),
            "end_fair_value": end.get("fair_value", ""),
            "match_method": "SUPP_B2_unique_exact_name",
            "match_key": str(end.get("issuer_name", "")).strip().lower(),
            "match_score": "1.0",
            "span_months": "3",
        })
    _write_position_id_edges(edge_rows)
    logger.info("  Position ID edge artifact: %d edges", len(edge_rows))

    if n_unlinked:
        matches_df = matches_df[
            matches_df["position_id"].astype(str).str.strip() != ""
        ].copy()

    # Ensure column order matches UNIFIED_COLUMNS
    from pipeline.unified_holdings import UNIFIED_COLUMNS
    unified_df = unified_df[[c for c in UNIFIED_COLUMNS if c in unified_df.columns]]
    for col in UNIFIED_COLUMNS:
        if col not in unified_df.columns:
            unified_df[col] = ""
    unified_df = unified_df[UNIFIED_COLUMNS]
    unified_df = _sort_existing(unified_df, UNIFIED_SORT_COLUMNS)
    matches_df = _sort_existing(matches_df, MATCH_SORT_COLUMNS)

    elapsed = time.time() - t0
    logger.info("Position IDs assigned in %.1f s", elapsed)
    logger.info("  Components (chained): %d", n_components)
    logger.info("  Singletons: %d", n_singletons)
    logger.info("  Total unique position_ids: %d", n_components + n_singletons)

    return unified_df, matches_df
