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
    POSITION_ID_REGISTRY_FILE,
    POSITION_ID_RETIREMENTS_FILE,
    POSITION_MATCHES_FILE,
    UNIFIED_HOLDINGS_FILE,
)
from pipeline.utils import UnionFind, hungarian_assignment

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

# Maximum maturity date gap (days) for C/D/E tier matches
MAX_MATURITY_GAP_DAYS = 365

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


def _write_position_id_edges(edges: list[dict], output_file=None) -> None:
    """Persist auditable edges used to form position_id chains."""
    edges_df = pd.DataFrame(edges, columns=POSITION_ID_EDGE_COLUMNS)
    edges_df = _sort_existing(edges_df, POSITION_ID_EDGE_COLUMNS)
    output_file = Path(output_file or POSITION_ID_EDGES_FILE)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    edges_df.to_csv(output_file, index=False)
    from pipeline.utils import write_parquet_companion
    write_parquet_companion(output_file)


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
# Contested-group assignment helpers (mg3 replay, 2026-09-06)
#
# When several concurrent tranches of one borrower share an issuer_name, the
# identity tiers used to resolve the 1:1 contest by fair-value proximity.
# Replaying the mg3 gold set showed that principal continuity picks the
# adjudicated twin on 44 of 69 wrong edges, and that filer-side trailing
# ordinals ("First lien senior secured loan 2") are renumbered between
# quarters.  These helpers are only active when ``contested_assignment`` is
# passed; the default matcher behaviour is unchanged.
# ---------------------------------------------------------------------------

def _name_key_sql(col: str) -> str:
    """Lower-cased issuer_name with commas, an "(fka ...)" / "(f/k/a ...)" /
    "(formerly ...)" parenthetical and a trailing ordinal (" 2", " (3)")
    removed, whitespace collapsed.  Commas and the fka parenthetical are
    filer-side formatting noise (mg3: "Inc., First Lien 1" vs "Inc. First
    Lien 1"; "Corp (fka 1272775 B.C. LTD.)" vs "Corp") that kept adjudicated
    same-position rows apart."""
    s = f"LOWER(CAST({col} AS VARCHAR))"
    s = f"regexp_replace({s}, '\\s*\\((?:f/?k/?a|formerly)\\s[^)]*\\)', '', 'g')"
    s = f"regexp_replace({s}, ',', '', 'g')"
    s = f"regexp_replace({s}, '\\s*\\(\\d+\\)\\s*$', '')"
    s = f"regexp_replace({s}, '\\s+\\d{{1,2}}\\s*$', '')"
    return f"TRIM(regexp_replace({s}, '\\s+', ' ', 'g'))"


def _slot_availability_ctes(prior_tiers: tuple[str, ...]) -> str:
    """CTE text ``used_begin AS (...), used_end AS (...)`` for cascade exclusion.

    A row has independent incoming (end) and outgoing (begin) continuity
    slots. A tier may claim a row's END slot without removing its BEGIN slot
    and vice versa. Tier A contributes only its mapped current-period END
    slot (see ``_map_tier_a_end_side_ids``). Introduced for Tier E in the
    V12 repair; extended to B2-leftover, C, D and F after the Resideo review
    (docs/investigations/position_matching.md, 2026-09-17).
    """
    begins = " UNION ".join(f"SELECT _begin_row_id AS _row_id FROM {t}" for t in prior_tiers)
    ends = " UNION ".join(["SELECT _row_id FROM tier_a_unified_ids"] +
                          [f"SELECT _end_row_id AS _row_id FROM {t}" for t in prior_tiers])
    if not begins:
        begins = "SELECT CAST(NULL AS BIGINT) AS _row_id WHERE FALSE"
    return f"used_begin AS ({begins}), used_end AS ({ends})"


def _maturity_gap_sql(b: str, e: str) -> str:
    from pipeline.matching_contract import interval_gap_sql
    return interval_gap_sql(b+'._mat_low',b+'._mat_high',e+'._mat_low',e+'._mat_high')


def _maturity_rank_sql(begin_alias: str, end_alias: str) -> str:
    """0 = intervals overlap, 1 = either unknown, 2 = disjoint."""
    from pipeline.matching_contract import interval_rank_sql
    return interval_rank_sql(begin_alias+'._mat_low',begin_alias+'._mat_high',
        end_alias+'._mat_low',end_alias+'._mat_high')


def _principal_prox_sql(begin_pa: str, end_pa: str) -> str:
    """|ln(pa_b / pa_e)| when both principals are known and positive, else NULL
    (sorted NULLS LAST so unknown principal never outranks a known match)."""
    return (
        f"CASE WHEN {begin_pa} > 0 AND {end_pa} > 0 "
        f"THEN ABS(LN({begin_pa} / {end_pa})) END"
    )


# Principal log-band: pairs whose principal ratio falls in the same band are
# treated as tied on principal and fall through to maturity, rate, the raw
# name (ordinal) and cost.  Revolver / DDTL rows use a wide band because a
# draw legitimately moves principal several-fold (mg3: Ideal Image 33K ->
# 765K, Help/Systems 6.7M -> 1.7M were CONFIRMED and lost to principal-first).
CONTESTED_PA_BAND = 1.05
CONTESTED_PA_BAND_REVOLVER = 4.0
# Leftover rounds: after the greedy 1:1 pass, re-run the contest on the rows
# it left unmatched so a sibling taking the nearest partner does not orphan
# the other tranche.  Bounded; each round only touches still-unmatched rows.
# OFF by default since the mg4_contested gold gate (2026-09-07): the leftover
# tiers scored 0.56 (B2_leftover_round, n=39) and 0.71
# (SUPP_B2_contested_leftover, n=41) against 0.98 for the first-round name-key
# contest (n=499).  Their wrong edges pair principals that differ by orders of
# magnitude (source scale defects) or spreads that differ, which the
# equal-maturity guard does not catch.  The mechanism is kept behind
# ``contested_leftover_rounds`` so a future stratum can re-test it.
CONTESTED_LEFTOVER_ROUNDS = 0
CONTESTED_MAX_ROUNDS = 1 + CONTESTED_LEFTOVER_ROUNDS
# Production switch for the contested contest.  Promoted 2026-09-07 on the
# mg4_contested gold batch: SUPP_B2_contested_name_key 0.98 on 499 random
# edges (mg3 production baseline for the unique-name pass: 0.95), flag-on
# tier_random precision 0.960 excluding leftover tiers vs 0.919 production.
# See docs/investigations/agent_campaigns.md ("Match-gold batch mg4_contested").
CONTESTED_ASSIGNMENT_DEFAULT = True
# Maturity veto with amendment escape (experiment E5,
# docs/investigations/position_matching.md).  On the mg3 gold set a strict
# maturity veto loses 2.6% of confirmed edges to extensions / amendments in
# which the lot's principal and spread are unchanged; the escape keeps 11 of
# those 16 while still rejecting 92% of wrong-borrower and 21% of
# wrong-tranche edges.  Contested contest only.
CONTESTED_AMENDMENT_PA_TOLERANCE = 1.02
CONTESTED_AMENDMENT_SPREAD_TOLERANCE = 0.01
# Widest principal move the spread-only amendment escape will tolerate.  Set from
# the CONFIRMED gold pairs the strict AND escape rejected: Comar 0.66 and IXS 1.40
# must pass, a 5.0M -> 3.0M (1.67) tranche hop must not.
CONTESTED_AMENDMENT_SPREAD_PA_BAND = 1.5


def _maturity_veto_sql(mat_b: str, mat_e: str, pa_b: str, pa_e: str,
                       spr_b: str, spr_e: str, *, overlap: str | None = None) -> str:
    """TRUE when the pair passes the maturity veto: either maturity unknown,
    maturities equal, or the change is an amendment on the same lot.

    Two escapes, either of which is enough:

    * principal within ``CONTESTED_AMENDMENT_PA_TOLERANCE`` -- a repricing that
      cuts or lifts the spread and extends the maturity while the lot itself is
      untouched.  The old rule also demanded a stable spread here, which is what
      lost Columbia Helicopters (principal within 2%, spread 10.51 -> 11.51,
      maturity +380d) and Nouryon Finance (principal identical, spread
      4.00 -> 3.50, maturity +912d), both CONFIRMED gold pairs (E15, 2026-09-08).
    * spread within ``CONTESTED_AMENDMENT_SPREAD_TOLERANCE`` and the principal
      not actively contradicting -- unknown on a side, or within
      ``CONTESTED_AMENDMENT_SPREAD_PA_BAND``.  Spread stability alone is a weak
      signal because a portfolio's loans routinely share a spread, so it only
      escapes when the principal is plausible: that admits Heritage
      Environmental (principal unknown), Comar (0.66) and IXS (1.40) while still
      vetoing a 5.0M -> 3.0M tranche hop.
    """
    pa_same = (
        f"(CASE WHEN {pa_b} > 0 AND {pa_e} > 0 "
        f"THEN ABS(LN({pa_b} / {pa_e})) <= LN({CONTESTED_AMENDMENT_PA_TOLERANCE}) "
        f"ELSE FALSE END)"
    )
    pa_not_contradicting = (
        f"(CASE WHEN {pa_b} > 0 AND {pa_e} > 0 "
        f"THEN ABS(LN({pa_b} / {pa_e})) <= LN({CONTESTED_AMENDMENT_SPREAD_PA_BAND}) "
        f"ELSE TRUE END)"
    )
    spread_same = (
        f"({spr_b} IS NOT NULL AND {spr_e} IS NOT NULL "
        f"AND ABS({spr_b} - {spr_e}) <= {CONTESTED_AMENDMENT_SPREAD_TOLERANCE} "
        f"AND {pa_not_contradicting})"
    )
    same_lot = f"({pa_same} OR {spread_same})"
    return (
        f"({mat_b} IS NULL OR {mat_e} IS NULL OR {overlap or (mat_b + ' = ' + mat_e)} OR {same_lot})"
    )


def _pa_band_sql(b: str, e: str) -> str:
    """Integer principal band for the pair (b, e); NULL when either principal
    is unknown (sorted NULLS LAST)."""
    # The sub-type that drives the vetoes is parsed from instrument_description.
    # Several filers put the instrument text in issuer_name instead and leave the
    # description empty, so their revolvers looked like NULL sub-type and were
    # assigned on the narrow band -- which is how "Help/Systems Holdings, Inc.,
    # First lien senior secured revolving loan 1" (principal ratio 3.94) and
    # "Ideal Image Development, LLC, ... revolving loan 1" (0.04) were lost
    # despite CONTESTED_PA_BAND_REVOLVER existing for exactly that case (E15,
    # 2026-09-08).  ``_inst_subtype_name`` is the same parse over issuer_name and
    # is used ONLY to widen this band; the vetoes still key on the description so
    # broadening detection cannot reject a pair that is accepted today.
    def _sub(alias: str) -> str:
        return f"COALESCE({alias}._inst_subtype, {alias}._inst_subtype_name)"

    wide = (
        f"({_sub(b)} IN ('REVOLVER', 'DDTL') "
        f"OR {_sub(e)} IN ('REVOLVER', 'DDTL'))"
    )
    return (
        f"CASE WHEN {b}.pa > 0 AND {e}.pa > 0 THEN FLOOR(ABS(LN({b}.pa / {e}.pa)) / "
        f"LN(CASE WHEN {wide} THEN {CONTESTED_PA_BAND_REVOLVER} "
        f"ELSE {CONTESTED_PA_BAND} END)) END"
    )


# Principal agreement that substitutes for the fair-value scale guard.  A
# delayed-draw or revolving commitment reports a constant principal while its
# fair value moves from zero (or a small negative mark) to fully funded, so the
# signed FV ratio is the wrong instrument for those rows.
_FV_SCALE_PA_TOLERANCE = 1.02


def _fv_scale_ok_sql(b_fv: str, e_fv: str, b_pa: str, e_pa: str, cap: float) -> str:
    """Fair-value scale guard that survives zero, negative and sign-flipped marks.

    The guard exists to catch unit-scale mismatches (a filer reporting
    thousands one quarter and units the next), not to judge economics.  The
    original form ``b.fv / e.fv BETWEEN 1/cap AND cap`` rejected every pair in
    which either side was zero (NULL from the division) or the sign flipped,
    which silently made ~6.6% of cohort rows unmatchable -- 44% of all
    singletons (E15, docs/investigations/position_matching.md).

    A pair passes when the fair-value MAGNITUDES are within ``cap``, or when
    both principal amounts are known, positive and within
    ``_FV_SCALE_PA_TOLERANCE`` -- in which case the principal already supplies
    the scale check the guard was there to perform.
    """
    mag = (
        f"(ABS({b_fv}) > 0 AND ABS({e_fv}) > 0 "
        f"AND ABS({b_fv}) / ABS({e_fv}) BETWEEN (1.0 / {cap}) AND {cap})"
    )
    pa_ok = (
        f"(CASE WHEN {b_pa} > 0 AND {e_pa} > 0 "
        f"THEN ABS(LN({b_pa} / {e_pa})) <= LN({_FV_SCALE_PA_TOLERANCE}) "
        f"ELSE FALSE END)"
    )
    return f"({b_fv} IS NOT NULL AND {e_fv} IS NOT NULL AND ({mag} OR {pa_ok}))"


def _cost_prox_sql(begin_cost: str, end_cost: str) -> str:
    """|ln(cost_b / cost_e)| when both costs are known and positive, else NULL."""
    return (
        f"CASE WHEN {begin_cost} > 0 AND {end_cost} > 0 "
        f"THEN ABS(LN({begin_cost} / {end_cost})) END"
    )


def _name_exact_sql(b: str, e: str) -> str:
    """1 when the raw lower-cased names (ordinal included) agree, else 0."""
    return f"CASE WHEN {b}._name_lower = {e}._name_lower THEN 1 ELSE 0 END"


def _inst_subtype_sql(col: str) -> str:
    """Instrument sub-type from a description column (same rules as
    ``unified_base._inst_subtype``; RE2: no \\b, use (^|\\W)..(\\W|$))."""
    c = f"CAST({col} AS VARCHAR)"
    return (
        "CASE "
        f"WHEN regexp_matches({c}, '(?i)(^|\\W)(?:revolv(?:er|ing)|rcf|revolving credit)(\\W|$)') THEN 'REVOLVER' "
        f"WHEN regexp_matches({c}, '(?i)(^|\\W)(?:ddtl|delayed draw)(\\W|$)') THEN 'DDTL' "
        f"WHEN regexp_matches({c}, '(?i)(^|\\W)(?:term loan|tl[a-d]?)(\\W|$)') THEN 'TERM_LOAN' "
        f"WHEN regexp_matches({c}, '(?i)(^|\\W)warrants?(\\W|$)') THEN 'WARRANT' "
        f"WHEN regexp_matches({c}, '(?i)(^|\\W)(?:common (?:stock|equity|units?)|preferred (?:stock|equity|units?)|membership interest|llc interest|equity interest|class [a-c](\\W|$)|ordinary shares)(\\W|$)') THEN 'EQUITY' "
        "ELSE NULL END"
    )


# Maximum principal drift for a row to count as the begin row's "twin".
COEXISTENCE_TWIN_PA_TOLERANCE = 1.02


def _coexistence_vetoed(
    unified_df: pd.DataFrame,
    edges: list[tuple[int, int]],
) -> set[tuple[int, int]]:
    """Return the edges (begin_uid, end_uid) that must not form a chain because
    a better twin of the begin row exists in the end quarter.

    Twin = same cik/source/name_key, same report_date as the chosen end row,
    equal maturity (both known), principal within COEXISTENCE_TWIN_PA_TOLERANCE,
    and not the chosen end row.  The edge is vetoed only when the chosen end
    row's principal is NOT within that tolerance -- two identical tranches stay
    ambiguous and untouched.  On mg3 this rule fired on 27 of 69 WRONG edges
    and 1 of 637 CONFIRMED edges.
    """
    if not edges or "_uid" not in unified_df.columns:
        return set()
    con = duckdb.connect()
    con.register("u", unified_df)
    con.register("edges", pd.DataFrame(edges, columns=["a", "b"]))
    pa_expr = (
        "COALESCE(TRY_CAST(principal_amount_usd AS DOUBLE), "
        "TRY_CAST(principal_amount AS DOUBLE))"
        if "principal_amount_usd" in unified_df.columns
        else "TRY_CAST(principal_amount AS DOUBLE)"
    )
    con.execute(f"""
    CREATE OR REPLACE TEMP TABLE r AS
    SELECT _uid,
        CAST(cik AS VARCHAR) AS cik,
        CAST(source AS VARCHAR) AS source,
        CAST(report_date AS VARCHAR) AS rd,
        {_name_key_sql('issuer_name')} AS nk,
        TRY_CAST(fair_value AS DOUBLE) AS fv,
        {pa_expr} AS pa,
        TRY_CAST(maturity_date AS DATE) AS mat
    FROM u
    """)
    tol = COEXISTENCE_TWIN_PA_TOLERANCE
    df = con.execute(f"""
    SELECT e.a, e.b
    FROM edges e
    JOIN r a ON a._uid = e.a
    JOIN r b ON b._uid = e.b
    WHERE a.mat IS NOT NULL AND a.pa > 0
      AND (b.pa IS NULL OR b.pa <= 0
           OR GREATEST(a.pa, b.pa) / LEAST(a.pa, b.pa) > {tol})
      AND EXISTS (
          SELECT 1 FROM r t
          WHERE t.cik = a.cik AND t.source = a.source AND t.rd = b.rd
            AND t._uid != b._uid AND t.nk = a.nk
            AND t.fv IS NOT NULL AND t.fv != 0
            AND t.mat = a.mat AND t.pa > 0
            AND GREATEST(a.pa, t.pa) / LEAST(a.pa, t.pa) <= {tol}
      )
    """).fetchdf()
    con.close()
    return {(int(x), int(y)) for x, y in zip(df["a"], df["b"])}


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

def _match_exact_name(
    con: duckdb.DuckDBPyConnection,
    *,
    contested: bool = False,
) -> str:
    """Tier B: Exact CUSIP (B1) and exact issuer_name (B2) matching.

    ``contested=True`` switches the B1b/B2 1:1 contest to principal-led
    ordering (principal, maturity equality, then the legacy keys) and keys B2
    on the ordinal-stripped ``_name_key`` instead of the raw lower-cased name.

    Returns the name of the result table.
    """
    next_qtr = _next_quarter_sql("b.quarter")
    name_col = "_name_key" if contested else "_name_lower"
    # Maturity veto with amendment escape on the B2 name contest (contested only).
    name_mat_veto = (
        "AND " + _maturity_veto_sql(
            "b._mat_low", "e._mat_low",
            "b.pa", "e.pa", "b.bs", "e.bs", overlap=_maturity_rank_sql("b","e")+"=0",
        )
        if contested else ""
    )
    if contested:
        # Banded principal -> maturity -> rate -> raw name (ordinal) -> cost
        # -> FV -> continuous principal.  Cost sits before FV because cost is
        # the stickier of the two for a lot (mg3 Kaseya: equal par, FV 4x apart
        # quarter to quarter, cost constant).
        poskey_order_end = (
            "_pa_band ASC NULLS LAST, _mat_rank ASC, _rate_prox ASC, "
            "_name_exact DESC, _cost_prox ASC NULLS LAST, _fv_prox ASC, "
            "_pa_prox_c ASC NULLS LAST, _end_row_id ASC"
        )
        poskey_order_begin = (
            "_pa_band ASC NULLS LAST, _mat_rank ASC, _rate_prox ASC, "
            "_name_exact DESC, _cost_prox ASC NULLS LAST, _fv_prox ASC, "
            "_pa_prox_c ASC NULLS LAST, _begin_row_id ASC"
        )
        name_order_end = (
            "_pa_band ASC NULLS LAST, _mat_rank ASC, _attr_penalty ASC, "
            "_rate_prox ASC, _name_exact DESC, _suffix_match DESC, "
            "_cost_prox ASC NULLS LAST, _fv_prox ASC, _pa_prox_c ASC NULLS LAST, "
            "_end_row_id ASC"
        )
        name_order_begin = (
            "_pa_band ASC NULLS LAST, _mat_rank ASC, _attr_penalty ASC, "
            "_rate_prox ASC, _name_exact DESC, _suffix_match DESC, "
            "_cost_prox ASC NULLS LAST, _fv_prox ASC, _pa_prox_c ASC NULLS LAST, "
            "_begin_row_id ASC"
        )
    else:
        poskey_order_end = "_fv_prox ASC, _rate_prox ASC, _pa_prox ASC, _end_row_id ASC"
        poskey_order_begin = "_fv_prox ASC, _rate_prox ASC, _pa_prox ASC, _begin_row_id ASC"
        name_order_end = (
            "_suffix_match DESC, _attr_penalty ASC, _fv_prox ASC, "
            "_rate_prox ASC, _maturity_prox ASC, _pa_prox ASC, _end_row_id ASC"
        )
        name_order_begin = (
            "_suffix_match DESC, _attr_penalty ASC, _fv_prox ASC, "
            "_rate_prox ASC, _maturity_prox ASC, _pa_prox ASC, _begin_row_id ASC"
        )

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
          ON b.cik = e.cik AND b._accounting_scope=e._accounting_scope
         AND e.quarter = ({next_qtr})
         AND b.clean_cusip IS NOT NULL
         AND b.clean_cusip = e.clean_cusip
         AND b.source = e.source
        WHERE {_fv_scale_ok_sql('b.fv', 'e.fv', 'b.pa', 'e.pa', MAX_FV_RATIO_IDENTIFIER)}
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
                AS _pa_prox,
            {_principal_prox_sql('b.pa', 'e.pa')} AS _pa_prox_c,
            {_maturity_rank_sql('b', 'e')} AS _mat_rank,
            {_pa_band_sql('b', 'e')} AS _pa_band,
            {_cost_prox_sql('b.cost_val', 'e.cost_val')} AS _cost_prox,
            {_name_exact_sql('b', 'e')} AS _name_exact
        FROM poskey_remaining b
        JOIN poskey_remaining e
          ON b.cik = e.cik AND b._accounting_scope=e._accounting_scope
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
        AND {_fv_scale_ok_sql('b.fv', 'e.fv', 'b.pa', 'e.pa', MAX_FV_RATIO_IDENTIFIER)}
        -- Instrument sub-type continuity
        AND (b._inst_subtype IS NULL OR e._inst_subtype IS NULL
             OR b._inst_subtype = e._inst_subtype)
    ),
    -- B1b: 1:1 enforcement (composite tiebreaker: FV + rate + principal,
    -- or principal-led when contested_assignment is on)
    poskey_rn_begin AS (
        SELECT *,
            ROW_NUMBER() OVER (
                PARTITION BY _begin_row_id
                ORDER BY {poskey_order_end}
            ) AS rn_b
        FROM pairs_poskey
    ),
    poskey_rn_end AS (
        SELECT *,
            ROW_NUMBER() OVER (
                PARTITION BY _end_row_id
                ORDER BY {poskey_order_begin}
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
        SELECT cik, quarter, {name_col} AS _name_lower, COUNT(*) AS n
        FROM name_remaining
        WHERE {name_col} IS NOT NULL AND {name_col} != ''
        GROUP BY cik, quarter, {name_col}
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
                AS _pa_prox,
            -- Attribute penalty: count of categorical mismatches (0=perfect)
            (CASE WHEN COALESCE(CAST(b.lien_position AS VARCHAR), '') != ''
                      AND COALESCE(CAST(e.lien_position AS VARCHAR), '') != ''
                      AND CAST(b.lien_position AS VARCHAR) != CAST(e.lien_position AS VARCHAR)
                  THEN 1 ELSE 0 END)
            + (CASE WHEN COALESCE(CAST(b.index_classification AS VARCHAR), '') != ''
                        AND COALESCE(CAST(e.index_classification AS VARCHAR), '') != ''
                        AND CAST(b.index_classification AS VARCHAR) != CAST(e.index_classification AS VARCHAR)
                    THEN 1 ELSE 0 END)
            + (CASE WHEN COALESCE(CAST(b.coupon_type AS VARCHAR), '') != ''
                        AND COALESCE(CAST(e.coupon_type AS VARCHAR), '') != ''
                        AND CAST(b.coupon_type AS VARCHAR) != CAST(e.coupon_type AS VARCHAR)
                    THEN 1 ELSE 0 END)
            AS _attr_penalty,
            COALESCE({_maturity_gap_sql('b','e')},999999) AS _maturity_prox,
            {_principal_prox_sql('b.pa', 'e.pa')} AS _pa_prox_c,
            {_maturity_rank_sql('b', 'e')} AS _mat_rank,
            {_pa_band_sql('b', 'e')} AS _pa_band,
            {_cost_prox_sql('b.cost_val', 'e.cost_val')} AS _cost_prox,
            {_name_exact_sql('b', 'e')} AS _name_exact,
            -- Suffix coexistence: prefer matching trailing numbers
            CASE WHEN b._trailing_num IS NOT NULL
                      AND e._trailing_num IS NOT NULL
                      AND b._trailing_num = e._trailing_num
                 THEN 1 ELSE 0 END AS _suffix_match
        FROM name_remaining b
        JOIN name_remaining e
          ON b.cik = e.cik AND b._accounting_scope=e._accounting_scope
         AND e.quarter = ({next_qtr})
         AND b.{name_col} = e.{name_col}
         AND b.{name_col} != ''
         AND b.source = e.source
        WHERE b.{name_col} NOT IN (
            SELECT _name_lower FROM high_mult_names
            WHERE cik = b.cik AND quarter = b.quarter
        )
        AND e.{name_col} NOT IN (
            SELECT _name_lower FROM high_mult_names
            WHERE cik = e.cik AND quarter = e.quarter
        )
        AND {_fv_scale_ok_sql('b.fv', 'e.fv', 'b.pa', 'e.pa', MAX_FV_RATIO_IDENTIFIER)}
        -- Classification flip veto: reject if both sides have a classification and they differ
        AND (COALESCE(CAST(b.index_classification AS VARCHAR), '') = ''
             OR COALESCE(CAST(e.index_classification AS VARCHAR), '') = ''
             OR CAST(b.index_classification AS VARCHAR) = CAST(e.index_classification AS VARCHAR))
        -- Instrument sub-type continuity
        AND (b._inst_subtype IS NULL OR e._inst_subtype IS NULL
             OR b._inst_subtype = e._inst_subtype)
        {name_mat_veto}
    ),
    -- B2: 1:1 enforcement (attribute penalty + FV + rate + maturity + principal,
    -- or principal-led when contested_assignment is on)
    name_rn_begin AS (
        SELECT *,
            ROW_NUMBER() OVER (
                PARTITION BY _begin_row_id
                ORDER BY {name_order_end}
            ) AS rn_b
        FROM pairs_name
    ),
    name_rn_end AS (
        SELECT *,
            ROW_NUMBER() OVER (
                PARTITION BY _end_row_id
                ORDER BY {name_order_begin}
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

_TIER_B_COLUMNS = (
    "cik, entity_name, source, "
    "begin_quarter, begin_report_date, begin_issuer_name, "
    "begin_fair_value, begin_cost, begin_principal_amount, "
    "begin_interest_rate, begin_basis_spread, begin_shares_held, "
    "end_quarter, end_report_date, end_issuer_name, "
    "end_fair_value, end_cost, end_principal_amount, "
    "end_interest_rate, end_basis_spread, end_shares_held, "
    "match_method, match_key, match_score, span_months, "
    "_begin_row_id, _end_row_id"
)


def _match_exact_name_leftover_rounds(
    con: duckdb.DuckDBPyConnection,
    max_rounds: int = CONTESTED_LEFTOVER_ROUNDS,
) -> int:
    """Contested-assignment only: re-run the B2 name-key contest on the rows
    the greedy 1:1 pass left unmatched, up to ``max_rounds`` times.

    Greedy double ROW_NUMBER lets a sibling tranche take the nearest partner
    and leaves the other tranche (typically a revolver draw whose principal
    moved several-fold) with no edge at all, although its only remaining
    same-name candidate is unclaimed.  Each round considers only rows not yet
    used by tier A or tier B and appends the new pairs to ``tier_b`` with
    match_method ``B2_leftover_round`` so they stay auditable as a tier.
    Returns the number of pairs added.
    """
    next_qtr = _next_quarter_sql("b.quarter")
    order_end = (
        "_pa_band ASC NULLS LAST, _mat_rank ASC, _rate_prox ASC, "
        "_name_exact DESC, _cost_prox ASC NULLS LAST, _fv_prox ASC, "
        "_pa_prox_c ASC NULLS LAST, _end_row_id ASC"
    )
    order_begin = order_end.replace("_end_row_id", "_begin_row_id")
    sql = f"""
    CREATE OR REPLACE TEMP TABLE b2_leftover AS
    WITH
    {_slot_availability_ctes(('tier_b',))},
    remaining AS (
        SELECT *,
            _row_id NOT IN (SELECT _row_id FROM used_begin) AS _begin_available,
            _row_id NOT IN (SELECT _row_id FROM used_end) AS _end_available
        FROM unified_base
        WHERE _name_key IS NOT NULL AND _name_key != ''
    ),
    name_counts AS (
        SELECT cik, source, quarter, _name_key,
            COUNT(*) FILTER (WHERE _begin_available) AS n_begin,
            COUNT(*) FILTER (WHERE _end_available) AS n_end
        FROM remaining GROUP BY cik, source, quarter, _name_key
    ),
    eligible_begin AS (
        SELECT r.* FROM remaining r
        JOIN name_counts nc
          ON r.cik = nc.cik AND r.source = nc.source
         AND r.quarter = nc.quarter AND r._name_key = nc._name_key
        WHERE r._begin_available AND nc.n_begin <= {MAX_NAME_MULTIPLICITY}
    ),
    eligible_end AS (
        SELECT r.* FROM remaining r
        JOIN name_counts nc
          ON r.cik = nc.cik AND r.source = nc.source
         AND r.quarter = nc.quarter AND r._name_key = nc._name_key
        WHERE r._end_available AND nc.n_end <= {MAX_NAME_MULTIPLICITY}
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
            'B2_leftover_round' AS match_method,
            CAST(b._name_key AS VARCHAR) AS match_key,
            1.0 AS match_score,
            3 AS span_months,
            b._row_id AS _begin_row_id,
            e._row_id AS _end_row_id,
            {_fv_proximity_sql('b.fv', 'e.fv')} AS _fv_prox,
            ABS(COALESCE(b.ir, 0) - COALESCE(e.ir, 0)) AS _rate_prox,
            {_principal_prox_sql('b.pa', 'e.pa')} AS _pa_prox_c,
            {_maturity_rank_sql('b', 'e')} AS _mat_rank,
            {_pa_band_sql('b', 'e')} AS _pa_band,
            {_cost_prox_sql('b.cost_val', 'e.cost_val')} AS _cost_prox,
            {_name_exact_sql('b', 'e')} AS _name_exact
        FROM eligible_begin b
        JOIN eligible_end e
          ON b.cik = e.cik AND b._accounting_scope=e._accounting_scope AND b.source = e.source
         AND e.quarter = ({next_qtr})
         AND b._name_key = e._name_key
        WHERE {_fv_scale_ok_sql('b.fv', 'e.fv', 'b.pa', 'e.pa', MAX_FV_RATIO_IDENTIFIER)}
          AND (COALESCE(CAST(b.index_classification AS VARCHAR), '') = ''
               OR COALESCE(CAST(e.index_classification AS VARCHAR), '') = ''
               OR CAST(b.index_classification AS VARCHAR) = CAST(e.index_classification AS VARCHAR))
          AND (b._inst_subtype IS NULL OR e._inst_subtype IS NULL
               OR b._inst_subtype = e._inst_subtype)
          -- A draw on an existing facility keeps its maturity: leftover pairs
          -- need equal, known maturities (flag-on profile 2026-09-07 showed
          -- 20-25% maturity disagreement in leftover edges without this).
          AND {_maturity_rank_sql('b', 'e')} = 0
    ),
    rn_begin AS (
        SELECT *, ROW_NUMBER() OVER (PARTITION BY _begin_row_id ORDER BY {order_end}) AS rn_b
        FROM pairs
    ),
    rn_end AS (
        SELECT *, ROW_NUMBER() OVER (PARTITION BY _end_row_id ORDER BY {order_begin}) AS rn_e
        FROM rn_begin WHERE rn_b = 1
    )
    SELECT {_TIER_B_COLUMNS} FROM rn_end WHERE rn_e = 1
    """
    total = 0
    for _round in range(max_rounds):
        con.execute(sql)
        n = con.execute("SELECT COUNT(*) FROM b2_leftover").fetchone()[0]
        if n == 0:
            break
        con.execute(f"INSERT INTO tier_b SELECT {_TIER_B_COLUMNS} FROM b2_leftover")
        total += n
    logger.info("  Tier B leftover rounds (contested): %d pairs added", total)
    return total


def _match_normalized_name(con: duckdb.DuckDBPyConnection) -> str:
    """Tier C: Match after aggressive name normalization.

    Catches pipe suffix additions, parenthetical changes, trailing ordinals,
    and punctuation differences.

    Returns the name of the result table.
    """
    next_qtr = _next_quarter_sql("b.quarter")
    norm_sql = _normalize_name_sql("CAST(issuer_name AS VARCHAR)")

    # Statement 1: save all candidate pairs (before greedy dedup)
    sql_candidates = f"""
    CREATE OR REPLACE TEMP TABLE tier_c_candidates AS
    WITH
    {_slot_availability_ctes(('tier_b',))},
    remaining AS (
        SELECT u.*,
            {norm_sql} AS _norm_name,
            u._row_id NOT IN (SELECT _row_id FROM used_begin) AS _begin_available,
            u._row_id NOT IN (SELECT _row_id FROM used_end) AS _end_available
        FROM unified_base u
    ),
    -- Normalized-name multiplicity cap, counted per direction so a row whose
    -- opposite slot is already claimed does not change this side's ambiguity.
    norm_name_counts AS (
        SELECT cik, quarter, _norm_name,
            COUNT(*) FILTER (WHERE _begin_available) AS n_begin,
            COUNT(*) FILTER (WHERE _end_available) AS n_end
        FROM remaining
        WHERE _norm_name IS NOT NULL AND _norm_name != ''
        GROUP BY cik, quarter, _norm_name
    ),
    high_mult_begin AS (
        SELECT cik, quarter, _norm_name
        FROM norm_name_counts
        WHERE n_begin > {MAX_NAME_MULTIPLICITY}
    ),
    high_mult_end AS (
        SELECT cik, quarter, _norm_name
        FROM norm_name_counts
        WHERE n_end > {MAX_NAME_MULTIPLICITY}
    )
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
        {_fv_proximity_sql('b.fv', 'e.fv')} AS _fv_prox,
        -- Attribute penalty: count of categorical mismatches (0=perfect)
        (CASE WHEN COALESCE(CAST(b.lien_position AS VARCHAR), '') != ''
                  AND COALESCE(CAST(e.lien_position AS VARCHAR), '') != ''
                  AND CAST(b.lien_position AS VARCHAR) != CAST(e.lien_position AS VARCHAR)
              THEN 1 ELSE 0 END)
        + (CASE WHEN COALESCE(CAST(b.index_classification AS VARCHAR), '') != ''
                    AND COALESCE(CAST(e.index_classification AS VARCHAR), '') != ''
                    AND CAST(b.index_classification AS VARCHAR) != CAST(e.index_classification AS VARCHAR)
                THEN 1 ELSE 0 END)
        + (CASE WHEN COALESCE(CAST(b.coupon_type AS VARCHAR), '') != ''
                    AND COALESCE(CAST(e.coupon_type AS VARCHAR), '') != ''
                    AND CAST(b.coupon_type AS VARCHAR) != CAST(e.coupon_type AS VARCHAR)
                THEN 1 ELSE 0 END)
        AS _attr_penalty,
        COALESCE({_maturity_gap_sql('b','e')},999999) AS _maturity_prox,
        -- Suffix coexistence: prefer matching trailing numbers
        CASE WHEN b._trailing_num IS NOT NULL
                  AND e._trailing_num IS NOT NULL
                  AND b._trailing_num = e._trailing_num
             THEN 1 ELSE 0 END AS _suffix_match
    FROM remaining b
    JOIN remaining e
      ON b.cik = e.cik AND b._accounting_scope=e._accounting_scope
     AND b._begin_available AND e._end_available
     AND e.quarter = ({next_qtr})
     AND b._norm_name = e._norm_name
     AND b._norm_name != ''
     AND b.source = e.source
    WHERE b._norm_name NOT IN (
        SELECT _norm_name FROM high_mult_begin
        WHERE cik = b.cik AND quarter = b.quarter
    )
    AND e._norm_name NOT IN (
        SELECT _norm_name FROM high_mult_end
        WHERE cik = e.cik AND quarter = e.quarter
    )
    AND {_fv_scale_ok_sql('b.fv', 'e.fv', 'b.pa', 'e.pa', MAX_FV_RATIO_IDENTIFIER)}
    -- Classification flip veto
    AND (COALESCE(CAST(b.index_classification AS VARCHAR), '') = ''
         OR COALESCE(CAST(e.index_classification AS VARCHAR), '') = ''
         OR CAST(b.index_classification AS VARCHAR) = CAST(e.index_classification AS VARCHAR))
    -- Instrument sub-type continuity
    AND (b._inst_subtype IS NULL OR e._inst_subtype IS NULL
         OR b._inst_subtype = e._inst_subtype)
    -- Maturity mismatch veto (C/D/E only)
    AND (b._mat_low IS NULL OR e._mat_low IS NULL OR {_maturity_gap_sql('b','e')} <= {MAX_MATURITY_GAP_DAYS})
    """
    con.execute(sql_candidates)

    # Statement 2: greedy dedup from candidates
    sql_dedup = """
    CREATE OR REPLACE TEMP TABLE tier_c AS
    WITH rn_begin AS (
        SELECT *,
            ROW_NUMBER() OVER (
                PARTITION BY _begin_row_id
                ORDER BY _suffix_match DESC, _attr_penalty ASC, _fv_prox ASC,
                    _maturity_prox ASC, _end_row_id ASC
            ) AS rn_b
        FROM tier_c_candidates
    ),
    rn_end AS (
        SELECT *,
            ROW_NUMBER() OVER (
                PARTITION BY _end_row_id
                ORDER BY _suffix_match DESC, _attr_penalty ASC, _fv_prox ASC,
                    _maturity_prox ASC, _begin_row_id ASC
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
    con.execute(sql_dedup)
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

    # Statement 1: save all candidate pairs (before greedy dedup)
    sql_candidates = f"""
    CREATE OR REPLACE TEMP TABLE tier_d_candidates AS
    WITH
    {_slot_availability_ctes(('tier_b','tier_c'))},
    remaining AS (
        SELECT u.*,
            {norm_sql} AS _norm_name,
            u._row_id NOT IN (SELECT _row_id FROM used_begin) AS _begin_available,
            u._row_id NOT IN (SELECT _row_id FROM used_end) AS _end_available
        FROM unified_base u
    ),
    -- Directional multiplicity cap for fuzzy matching.
    d_norm_counts AS (
        SELECT cik, quarter, _norm_name,
            COUNT(*) FILTER (WHERE _begin_available) AS n_begin,
            COUNT(*) FILTER (WHERE _end_available) AS n_end
        FROM remaining
        WHERE _norm_name IS NOT NULL AND _norm_name != ''
        GROUP BY cik, quarter, _norm_name
    ),
    d_high_mult_begin AS (
        SELECT cik, quarter, _norm_name
        FROM d_norm_counts
        WHERE n_begin > {MAX_NAME_MULTIPLICITY}
    ),
    d_high_mult_end AS (
        SELECT cik, quarter, _norm_name
        FROM d_norm_counts
        WHERE n_end > {MAX_NAME_MULTIPLICITY}
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
            e._norm_name AS e_norm,
            -- Attribute penalty columns
            (CASE WHEN COALESCE(CAST(b.lien_position AS VARCHAR), '') != ''
                      AND COALESCE(CAST(e.lien_position AS VARCHAR), '') != ''
                      AND CAST(b.lien_position AS VARCHAR) != CAST(e.lien_position AS VARCHAR)
                  THEN 1 ELSE 0 END)
            + (CASE WHEN COALESCE(CAST(b.index_classification AS VARCHAR), '') != ''
                        AND COALESCE(CAST(e.index_classification AS VARCHAR), '') != ''
                        AND CAST(b.index_classification AS VARCHAR) != CAST(e.index_classification AS VARCHAR)
                    THEN 1 ELSE 0 END)
            + (CASE WHEN COALESCE(CAST(b.coupon_type AS VARCHAR), '') != ''
                        AND COALESCE(CAST(e.coupon_type AS VARCHAR), '') != ''
                        AND CAST(b.coupon_type AS VARCHAR) != CAST(e.coupon_type AS VARCHAR)
                    THEN 1 ELSE 0 END)
            AS _attr_penalty,
            COALESCE({_maturity_gap_sql('b','e')},999999) AS _maturity_prox,
            COALESCE(CAST(b.index_classification AS VARCHAR), '') AS b_index_classification,
            COALESCE(CAST(e.index_classification AS VARCHAR), '') AS e_index_classification,
            b._mat_low AS b_maturity_dt, e._mat_low AS e_maturity_dt,
            b._inst_subtype AS b_inst_subtype,
            e._inst_subtype AS e_inst_subtype,
            b._trailing_num AS b_trailing_num,
            e._trailing_num AS e_trailing_num
        FROM remaining b
        JOIN remaining e
          ON b.cik = e.cik AND b._accounting_scope=e._accounting_scope
         AND b._begin_available AND e._end_available
         AND e.quarter = ({next_qtr})
         AND b.source = e.source
         AND b._norm_name != ''
         AND e._norm_name != ''
         AND LEFT(b._norm_name, 4) = LEFT(e._norm_name, 4)
        WHERE b._norm_name NOT IN (
            SELECT _norm_name FROM d_high_mult_begin
            WHERE cik = b.cik AND quarter = b.quarter
        )
        AND e._norm_name NOT IN (
            SELECT _norm_name FROM d_high_mult_end
            WHERE cik = e.cik AND quarter = e.quarter
        )
    ),
    scored AS (
        SELECT *,
            jaro_winkler_similarity(b_norm, e_norm) AS jw,
            {_fv_proximity_sql('b_fv', 'e_fv')} AS _fv_prox
        FROM blocked
        WHERE jaro_winkler_similarity(b_norm, e_norm) >= {MIN_JW_SIMILARITY}
          AND {_fv_scale_ok_sql('b_fv', 'e_fv', 'b_pa', 'e_pa', MAX_FV_RATIO)}
          -- Classification flip veto
          AND (b_index_classification = ''
               OR e_index_classification = ''
               OR b_index_classification = e_index_classification)
          -- Instrument sub-type continuity
          AND (b_inst_subtype IS NULL OR e_inst_subtype IS NULL
               OR b_inst_subtype = e_inst_subtype)
          -- Maturity mismatch veto
          AND (b_maturity_dt IS NULL OR e_maturity_dt IS NULL
               OR _maturity_prox <= {MAX_MATURITY_GAP_DAYS})
    )
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
        _fv_prox,
        _attr_penalty,
        _maturity_prox,
        -- Suffix coexistence: prefer matching trailing numbers
        CASE WHEN b_trailing_num IS NOT NULL
                  AND e_trailing_num IS NOT NULL
                  AND b_trailing_num = e_trailing_num
             THEN 1 ELSE 0 END AS _suffix_match
    FROM scored
    """
    con.execute(sql_candidates)

    # Statement 2: greedy dedup from candidates
    sql_dedup = """
    CREATE OR REPLACE TEMP TABLE tier_d AS
    WITH rn_begin AS (
        SELECT *,
            ROW_NUMBER() OVER (
                PARTITION BY _begin_row_id
                ORDER BY match_score DESC, _suffix_match DESC, _attr_penalty ASC,
                    _fv_prox ASC, _maturity_prox ASC, _end_row_id ASC
            ) AS rn_b
        FROM tier_d_candidates
    ),
    rn_end AS (
        SELECT *,
            ROW_NUMBER() OVER (
                PARTITION BY _end_row_id
                ORDER BY match_score DESC, _suffix_match DESC, _attr_penalty ASC,
                    _fv_prox ASC, _maturity_prox ASC, _begin_row_id ASC
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
    con.execute(sql_dedup)
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

    # A row has independent incoming and outgoing continuity slots. A
    # later-quarter match must not remove its ability to link to an earlier
    # quarter. Tier A contributes only its mapped current-period end slot.
    # Count available positions by direction so a claimed slot does not alter
    # the opposite side's single/multiple-position classification.
    # Statement 1: save all candidate pairs (before greedy dedup)
    sql_candidates = f"""
    CREATE OR REPLACE TEMP TABLE tier_e_candidates AS
    WITH
    {_slot_availability_ctes(('tier_b','tier_c','tier_d'))},
    remaining AS (
        SELECT u.*,
            u._row_id NOT IN (SELECT _row_id FROM used_begin) AS _begin_available,
            u._row_id NOT IN (SELECT _row_id FROM used_end) AS _end_available,
            CAST(entity_id AS VARCHAR) AS _entity_id,
            CAST(ROUND(COALESCE(pa, 0) / 500000.0, 0) AS INTEGER) AS _prin_bucket
        FROM unified_base u
        WHERE CAST(entity_id AS VARCHAR) IS NOT NULL
          AND CAST(entity_id AS VARCHAR) != ''
    ),
    -- Count positions per entity_id + CIK + quarter + classification
    entity_counts AS (
        SELECT cik, source, quarter, _entity_id, _accounting_scope,
            CAST(index_classification AS VARCHAR) AS _ic,
            COUNT(*) FILTER (WHERE _begin_available) AS n_begin,
            COUNT(*) FILTER (WHERE _end_available) AS n_end
        FROM remaining
        GROUP BY cik, source, quarter, _entity_id, _accounting_scope,
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
          ON b.cik = e.cik AND b._accounting_scope=e._accounting_scope
         AND b._begin_available AND e._end_available
         AND e.quarter = ({next_qtr})
         AND b.source = e.source
         AND b._entity_id = e._entity_id
         AND CAST(b.index_classification AS VARCHAR) = CAST(e.index_classification AS VARCHAR)
         AND {_fv_scale_ok_sql('b.fv', 'e.fv', 'b.pa', 'e.pa', MAX_FV_RATIO)}
         -- Instrument sub-type continuity
         AND (b._inst_subtype IS NULL OR e._inst_subtype IS NULL
              OR b._inst_subtype = e._inst_subtype)
         -- Maturity mismatch veto
         AND (b._mat_low IS NULL OR e._mat_low IS NULL OR {_maturity_gap_sql('b','e')} <= {MAX_MATURITY_GAP_DAYS})
        -- Both sides must be single-position for this entity+classification
        JOIN entity_counts bc
          ON b.cik = bc.cik AND b.source = bc.source
         AND b._accounting_scope = bc._accounting_scope
         AND b.quarter = bc.quarter AND b._entity_id = bc._entity_id
         AND CAST(b.index_classification AS VARCHAR) = bc._ic
         AND bc.n_begin = 1
        JOIN entity_counts ec
          ON e.cik = ec.cik AND e.source = ec.source
         AND e._accounting_scope = ec._accounting_scope
         AND e.quarter = ec.quarter AND e._entity_id = ec._entity_id
         AND CAST(e.index_classification AS VARCHAR) = ec._ic
         AND ec.n_end = 1
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
          ON b.cik = e.cik AND b._accounting_scope=e._accounting_scope
         AND b._begin_available AND e._end_available
         AND e.quarter = ({next_qtr})
         AND b.source = e.source
         AND b._entity_id = e._entity_id
         AND CAST(b.index_classification AS VARCHAR) = CAST(e.index_classification AS VARCHAR)
         AND ABS(b._prin_bucket - e._prin_bucket) <= 1
         AND {_fv_scale_ok_sql('b.fv', 'e.fv', 'b.pa', 'e.pa', MAX_FV_RATIO)}
         -- Instrument sub-type continuity
         AND (b._inst_subtype IS NULL OR e._inst_subtype IS NULL
              OR b._inst_subtype = e._inst_subtype)
         -- Maturity mismatch veto
         AND (b._mat_low IS NULL OR e._mat_low IS NULL OR {_maturity_gap_sql('b','e')} <= {MAX_MATURITY_GAP_DAYS})
        -- At least one side is multi-position (not caught by E1)
        JOIN entity_counts bc
          ON b.cik = bc.cik AND b.source = bc.source
         AND b._accounting_scope = bc._accounting_scope
         AND b.quarter = bc.quarter AND b._entity_id = bc._entity_id
         AND CAST(b.index_classification AS VARCHAR) = bc._ic
        JOIN entity_counts ec
          ON e.cik = ec.cik AND e.source = ec.source
         AND e._accounting_scope = ec._accounting_scope
         AND e.quarter = ec.quarter AND e._entity_id = ec._entity_id
         AND CAST(e.index_classification AS VARCHAR) = ec._ic
        WHERE bc.n_begin > 1 OR ec.n_end > 1
    )
    SELECT * FROM pairs_single
    UNION ALL
    SELECT * FROM pairs_multi
    """
    con.execute(sql_candidates)

    # Statement 2: greedy dedup from candidates
    sql_dedup = """
    CREATE OR REPLACE TEMP TABLE tier_e AS
    WITH rn_begin AS (
        SELECT *,
            ROW_NUMBER() OVER (
                PARTITION BY _begin_row_id
                ORDER BY _fv_prox ASC, _rate_prox ASC, _pa_prox ASC,
                    _end_row_id ASC
            ) AS rn_b
        FROM tier_e_candidates
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
    con.execute(sql_dedup)
    return "tier_e"


# ---------------------------------------------------------------------------
# Tier F: Gap-quarter (span-2) links
# ---------------------------------------------------------------------------

# Off by default.  E13 sizes the strict population at 496 pairs / $4.7B across
# 44 CIKs, and no adjudicated batch has scored a span-2 link yet, so the tier
# ships dark until the joint continuation metric (step 1 of
# docs/superpowers/plans/2026-09-08-chain-completeness.md) can score it.
GAP_QUARTER_TIER_DEFAULT = False


def _quarter_plus_two_sql(qtr_col: str) -> str:
    """Quarter label two calendar quarters after ``qtr_col``."""
    return _next_quarter_sql(_next_quarter_sql(qtr_col))


def _match_gap_quarter(con: duckdb.DuckDBPyConnection, *, enabled: bool) -> str:
    """Tier F: link a position across one missing filing.

    Every other tier requires strictly adjacent quarters, so a position that
    disappears from one filing and returns in the next starts a fresh chain.
    Two shapes qualify, and both demand an exact issuer name that is unique in
    each of the two quarters, so this can never merge tranches:

    ``F_gap_no_filing``    the CIK has no rows at all in the intervening
                           quarter -- the position could not have been
                           reported, so absence carries no information.
    ``F_gap_name_absent``  the CIK filed, and that issuer name is absent from
                           the filing.  Weaker: a genuine exit and re-entry
                           looks identical, which is why the tier is gated.

    Both carry the maturity veto and the fair-value scale guard.  Creating the
    table even when disabled keeps the downstream union unconditional.
    """
    if not enabled:
        con.execute("""
        CREATE OR REPLACE TEMP TABLE tier_f AS
        SELECT * FROM tier_e WHERE FALSE
        """)
        return "tier_f"

    mat_veto = _maturity_veto_sql(
        "b._mat_low", "e._mat_low",
        "b.pa", "e.pa", "b.bs", "e.bs", overlap=_maturity_rank_sql("b","e")+"=0")
    con.execute(f"""
    CREATE OR REPLACE TEMP TABLE tier_f_candidates AS
    WITH {_slot_availability_ctes(('tier_b','tier_c','tier_d','tier_e'))},
    name_counts AS (
        SELECT cik, source, quarter, _name_lower, COUNT(*) AS n
        FROM unified_base GROUP BY cik, source, quarter, _name_lower
    ),
    filed AS (SELECT DISTINCT cik, source, quarter FROM unified_base),
    remaining AS (
        SELECT u.*,
            u._row_id NOT IN (SELECT _row_id FROM used_begin) AS _begin_available,
            u._row_id NOT IN (SELECT _row_id FROM used_end) AS _end_available
        FROM unified_base u
        WHERE COALESCE(u._name_lower, '') != ''
    )
    SELECT
        b.cik, b.entity_name, b.source,
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
        CASE WHEN f.quarter IS NULL THEN 'F_gap_no_filing'
             ELSE 'F_gap_name_absent' END AS match_method,
        CAST(b._name_lower AS VARCHAR) AS match_key,
        0.55 AS match_score,
        6 AS span_months,
        b._row_id AS _begin_row_id,
        e._row_id AS _end_row_id,
        {_fv_proximity_sql('b.fv', 'e.fv')} AS _fv_prox,
        {_principal_prox_sql('b.pa', 'e.pa')} AS _pa_prox
    FROM remaining b
    JOIN remaining e
      ON e.cik = b.cik AND e.source = b.source
     AND b._begin_available AND e._end_available
     AND e.quarter = ({_quarter_plus_two_sql('b.quarter')})
     AND e._name_lower = b._name_lower
    JOIN name_counts nb
      ON nb.cik = b.cik AND nb.source = b.source AND nb.quarter = b.quarter
     AND nb._name_lower = b._name_lower AND nb.n = 1
    JOIN name_counts ne
      ON ne.cik = e.cik AND ne.source = e.source AND ne.quarter = e.quarter
     AND ne._name_lower = e._name_lower AND ne.n = 1
    LEFT JOIN filed f
      ON f.cik = b.cik AND f.source = b.source
     AND f.quarter = ({_next_quarter_sql('b.quarter')})
    WHERE {_fv_scale_ok_sql('b.fv', 'e.fv', 'b.pa', 'e.pa', MAX_FV_RATIO_IDENTIFIER)}
      AND {mat_veto}
      AND (COALESCE(CAST(b.index_classification AS VARCHAR), '') = ''
           OR COALESCE(CAST(e.index_classification AS VARCHAR), '') = ''
           OR CAST(b.index_classification AS VARCHAR)
              = CAST(e.index_classification AS VARCHAR))
      AND (b._inst_subtype IS NULL OR e._inst_subtype IS NULL
           OR b._inst_subtype = e._inst_subtype)
      -- The position must be genuinely absent from the intervening filing.
      AND NOT EXISTS (
          SELECT 1 FROM unified_base m
          WHERE m.cik = b.cik AND m.source = b.source
            AND m.quarter = ({_next_quarter_sql('b.quarter')})
            AND m._name_lower = b._name_lower
      )
    """)
    con.execute("""
    CREATE OR REPLACE TEMP TABLE tier_f AS
    WITH rn_begin AS (
        SELECT *, ROW_NUMBER() OVER (
            PARTITION BY _begin_row_id
            ORDER BY _fv_prox ASC, _pa_prox ASC NULLS LAST, _end_row_id ASC
        ) AS rn_b
        FROM tier_f_candidates
    ),
    rn_end AS (
        SELECT *, ROW_NUMBER() OVER (
            PARTITION BY _end_row_id
            ORDER BY _fv_prox ASC, _pa_prox ASC NULLS LAST, _begin_row_id ASC
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
    """)
    return "tier_f"


# ---------------------------------------------------------------------------
# Bipartite (Hungarian) dedup for C/D/E tiers
# ---------------------------------------------------------------------------

# Cost function weights per tier.
# Converts the ORDER BY tiebreaker columns into a scalar cost for the
# Hungarian algorithm.  Lower cost = better match.
COST_CONFIG_C = {
    "suffix_match_weight": 100.0,
    "attr_penalty_weight": 10.0,
    "fv_prox_weight": 1.0,
    "maturity_prox_weight": 0.001,
    "cost_cols": ["_suffix_match", "_attr_penalty", "_fv_prox", "_maturity_prox"],
}
COST_CONFIG_D = {
    "match_score_weight": 1000.0,
    "suffix_match_weight": 100.0,
    "attr_penalty_weight": 10.0,
    "fv_prox_weight": 1.0,
    "maturity_prox_weight": 0.001,
    "cost_cols": ["match_score", "_suffix_match", "_attr_penalty", "_fv_prox",
                  "_maturity_prox"],
}
COST_CONFIG_E = {
    "fv_prox_weight": 1.0,
    "rate_prox_weight": 0.3,
    "pa_prox_weight": 0.1,
    "cost_cols": ["_fv_prox", "_rate_prox", "_pa_prox"],
}


def _compute_pair_cost(row: dict, tier_name: str) -> float:
    """Compute scalar cost for a candidate pair row."""
    if tier_name == "tier_c":
        cfg = COST_CONFIG_C
        return (
            cfg["suffix_match_weight"] * (1 - float(row.get("_suffix_match", 0)))
            + cfg["attr_penalty_weight"] * float(row.get("_attr_penalty", 0))
            + cfg["fv_prox_weight"] * float(row.get("_fv_prox", 0))
            + cfg["maturity_prox_weight"]
            * min(float(row.get("_maturity_prox", 999999)) / 365.0, 1.0)
        )
    elif tier_name == "tier_d":
        cfg = COST_CONFIG_D
        return (
            cfg["match_score_weight"] * (1 - float(row.get("match_score", 0)))
            + cfg["suffix_match_weight"] * (1 - float(row.get("_suffix_match", 0)))
            + cfg["attr_penalty_weight"] * float(row.get("_attr_penalty", 0))
            + cfg["fv_prox_weight"] * float(row.get("_fv_prox", 0))
            + cfg["maturity_prox_weight"]
            * min(float(row.get("_maturity_prox", 999999)) / 365.0, 1.0)
        )
    else:  # tier_e
        cfg = COST_CONFIG_E
        return (
            cfg["fv_prox_weight"] * float(row.get("_fv_prox", 0))
            + cfg["rate_prox_weight"] * float(row.get("_rate_prox", 0))
            + cfg["pa_prox_weight"] * float(row.get("_pa_prox", 0))
        )


def _bipartite_dedup(
    con: duckdb.DuckDBPyConnection,
    tier_name: str,
) -> int:
    """Replace greedy ROW_NUMBER dedup with Hungarian bipartite matching.

    Reads candidates from ``{tier_name}_candidates``, groups into connected
    components via UnionFind, runs the Hungarian algorithm on each
    multi-position component, and replaces the ``{tier_name}`` temp table.

    Returns the number of pairs that changed assignment vs greedy.
    """
    t0 = time.time()
    cand_table = f"{tier_name}_candidates"

    # Fetch candidates
    cand_df = con.execute(f"SELECT * FROM {cand_table}").fetchdf()
    if cand_df.empty:
        return 0

    # Fetch greedy result for comparison
    greedy_pairs = set()
    greedy_df = con.execute(f"SELECT _begin_row_id, _end_row_id FROM {tier_name}").fetchdf()
    for _, r in greedy_df.iterrows():
        greedy_pairs.add((int(r["_begin_row_id"]), int(r["_end_row_id"])))

    # Build connected components via UnionFind.
    # Nodes are tagged as ('b', row_id) or ('e', row_id) to keep begin/end
    # sides separate.
    uf = UnionFind()
    for _, row in cand_df.iterrows():
        b_key = ("b", int(row["_begin_row_id"]))
        e_key = ("e", int(row["_end_row_id"]))
        uf.find(b_key)
        uf.find(e_key)
        uf.union(b_key, e_key)

    components = uf.components()

    # Build index: for each component, collect its candidate rows
    # Map each node to its component root
    node_to_root = {}
    for root, members in components.items():
        for m in members:
            node_to_root[m] = root

    # Group candidate rows by component
    comp_rows = {}
    for idx, row in cand_df.iterrows():
        b_key = ("b", int(row["_begin_row_id"]))
        root = node_to_root[b_key]
        if root not in comp_rows:
            comp_rows[root] = []
        comp_rows[root].append(idx)

    optimal_indices = []
    reassigned = 0

    for root, row_indices in comp_rows.items():
        members = components[root]
        begin_ids = sorted({m[1] for m in members if m[0] == "b"})
        end_ids = sorted({m[1] for m in members if m[0] == "e"})

        n_begin = len(begin_ids)
        n_end = len(end_ids)

        if n_begin <= 1 or n_end <= 1:
            # Trivial component: pick best candidate per side by cost
            sub_df = cand_df.loc[row_indices]
            best_per_begin = {}
            for idx in row_indices:
                row = cand_df.loc[idx]
                bid = int(row["_begin_row_id"])
                cost = _compute_pair_cost(row, tier_name)
                if bid not in best_per_begin or cost < best_per_begin[bid][0]:
                    best_per_begin[bid] = (cost, idx)
            # For single-end, also enforce 1:1 on end side
            used_ends = set()
            for bid in sorted(best_per_begin.keys()):
                _, idx = best_per_begin[bid]
                eid = int(cand_df.loc[idx, "_end_row_id"])
                if eid not in used_ends:
                    optimal_indices.append(idx)
                    used_ends.add(eid)
            continue

        # Multi-position component: build cost matrix and run Hungarian
        begin_id_to_idx = {bid: i for i, bid in enumerate(begin_ids)}
        end_id_to_idx = {eid: j for j, eid in enumerate(end_ids)}

        SENTINEL = 1e15
        cost_matrix = [[SENTINEL] * n_end for _ in range(n_begin)]
        # Also store which candidate row corresponds to each cell
        cell_to_cand_idx = {}

        for idx in row_indices:
            row = cand_df.loc[idx]
            bid = int(row["_begin_row_id"])
            eid = int(row["_end_row_id"])
            i = begin_id_to_idx[bid]
            j = end_id_to_idx[eid]
            cost = _compute_pair_cost(row, tier_name)
            # Keep the best (lowest cost) candidate for each (i, j) cell
            if cost < cost_matrix[i][j]:
                cost_matrix[i][j] = cost
                cell_to_cand_idx[(i, j)] = idx

        row_ind, col_ind = hungarian_assignment(cost_matrix)

        for i, j in zip(row_ind, col_ind):
            if cost_matrix[i][j] < SENTINEL and (i, j) in cell_to_cand_idx:
                cand_idx = cell_to_cand_idx[(i, j)]
                optimal_indices.append(cand_idx)
                pair = (begin_ids[i], end_ids[j])
                if pair not in greedy_pairs:
                    reassigned += 1

    # Build result DataFrame from optimal indices
    if optimal_indices:
        result_df = cand_df.loc[optimal_indices].copy()
    else:
        result_df = cand_df.iloc[:0].copy()

    # Get the output columns from the current tier table
    tier_cols = [desc[0] for desc in con.execute(
        f"SELECT * FROM {tier_name} LIMIT 0"
    ).description]

    # Select only columns that exist in the tier table
    out_cols = [c for c in tier_cols if c in result_df.columns]
    result_df = result_df[out_cols].reset_index(drop=True)

    # Replace the tier table
    con.register(f"_bipartite_{tier_name}", result_df)
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE {tier_name} AS
        SELECT * FROM _bipartite_{tier_name}
    """)
    con.unregister(f"_bipartite_{tier_name}")

    elapsed = time.time() - t0
    n_components = len(comp_rows)
    n_multi = sum(
        1 for root in comp_rows
        if len({m[1] for m in components[root] if m[0] == "b"}) >= 2
        and len({m[1] for m in components[root] if m[0] == "e"}) >= 2
    )
    logger.info(
        "  %s bipartite: %d components (%d multi-position), "
        "%d pairs reassigned, %.2fs",
        tier_name, n_components, n_multi, reassigned, elapsed,
    )
    return reassigned


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def match_positions(
    unified_df: Optional[pd.DataFrame] = None,
    bdc_raw_df: Optional[pd.DataFrame] = None,
    *,
    output_file: Optional[Path] = None,
    use_bipartite: bool = True,
    contested_assignment: bool = False,
    contested_leftover_rounds: int = CONTESTED_LEFTOVER_ROUNDS,
    gap_quarter_tier: bool = GAP_QUARTER_TIER_DEFAULT,
) -> pd.DataFrame:
    """Match positions across consecutive quarters.

    Parameters
    ----------
    unified_df : DataFrame, optional
        Unified holdings (current-period only). Loaded from disk if None.
    bdc_raw_df : DataFrame, optional
        Raw BDC holdings with comparative periods. Loaded from disk if None.
    contested_assignment : bool
        Experimental (mg3 replay): principal-led 1:1 ordering in the identity
        tiers and ordinal-stripped exact-name keys. Default off.

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

    from pipeline.matching_contract import bounds_sql,scope_sql
    mat_low,mat_high=bounds_sql(unified_df.columns)
    reported_cost='cost_reported' if 'cost_reported' in unified_df.columns else 'cost'
    accounting_scope=scope_sql(unified_df.columns,row_id='row_id' if 'row_id' in unified_df.columns else '_row_id')
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
                TRY_CAST({reported_cost} AS DOUBLE),
                COALESCE(TRY_CAST(principal_amount_usd AS DOUBLE), TRY_CAST(principal_amount AS DOUBLE)),
                TRY_CAST(shares_held AS DOUBLE)
        ) AS _row_id,
        {_quarter_label_sql('report_date')} AS quarter,
        TRY_CAST(fair_value AS DOUBLE) AS fv,
        TRY_CAST({reported_cost} AS DOUBLE) AS cost_val,
        COALESCE(
            TRY_CAST(principal_amount_usd AS DOUBLE),
            TRY_CAST(principal_amount AS DOUBLE)
        ) AS pa,
        {mat_low} AS _mat_low,{mat_high} AS _mat_high,{accounting_scope} AS _accounting_scope,
        TRY_CAST(interest_rate AS DOUBLE) AS ir,
        TRY_CAST(basis_spread AS DOUBLE) AS bs,
        TRY_CAST(shares_held AS DOUBLE) AS sh,
        LOWER(TRIM(CAST(issuer_name AS VARCHAR))) AS _name_lower,
        {_name_key_sql('issuer_name')} AS _name_key,
        CAST(cusip AS VARCHAR) AS _cusip,
        CAST(position_key AS VARCHAR) AS _position_key,
        -- Instrument sub-type parsed from description (RE2: no \\b, use (^|\\W)..(\\W|$))
        CASE
          WHEN regexp_matches(CAST(instrument_description AS VARCHAR),
               '(?i)(^|\\W)(?:revolv(?:er|ing)|rcf|revolving credit)(\\W|$)') THEN 'REVOLVER'
          WHEN regexp_matches(CAST(instrument_description AS VARCHAR),
               '(?i)(^|\\W)(?:ddtl|delayed draw)(\\W|$)') THEN 'DDTL'
          WHEN regexp_matches(CAST(instrument_description AS VARCHAR),
               '(?i)(^|\\W)(?:term loan|tl[a-d]?)(\\W|$)') THEN 'TERM_LOAN'
          WHEN regexp_matches(CAST(instrument_description AS VARCHAR),
               '(?i)(^|\\W)warrants?(\\W|$)') THEN 'WARRANT'
          WHEN regexp_matches(CAST(instrument_description AS VARCHAR),
               '(?i)(^|\\W)(?:common (?:stock|equity|units?)|preferred (?:stock|equity|units?)|membership interest|llc interest|equity interest|class [a-c](\\W|$)|ordinary shares)(\\W|$)') THEN 'EQUITY'
          ELSE NULL
        END AS _inst_subtype,
        -- Same parse over issuer_name, for filers that carry the instrument text
        -- there and leave instrument_description empty.  Used ONLY to widen the
        -- contested principal band (see _pa_band_sql); never as a veto.
        {_inst_subtype_sql('issuer_name')} AS _inst_subtype_name,
        -- Trailing number from issuer_name for suffix coexistence tiebreaker
        TRY_CAST(
          regexp_extract(CAST(issuer_name AS VARCHAR), '(\\d+)\\s*$', 1)
          AS INTEGER
        ) AS _trailing_num
    FROM unified
    WHERE TRY_CAST(fair_value AS DOUBLE) IS NOT NULL
      -- A zero fair value used to be excluded here.  That made 17,655 cohort
      -- rows (6.6%) unmatchable by construction and accounted for 44% of all
      -- singleton rows, even where the same position appears fully funded in
      -- the next quarter under the same issuer name (E15, 2026-09-08).  Those
      -- rows are undrawn revolvers and delayed-draw commitments, not noise.
      -- Chaining them does not touch the indices: index_returns.py filters
      -- `begin_fair_value != 0` independently before computing any return, so
      -- a pair with a zero-FV leg contributes nothing there either way.
      -- Cash and derivatives are analytics-only, never index constituents.
      -- Excluding them here (before the ROW_NUMBER _row_id assignment) keeps
      -- the matched-position universe -- and therefore index_returns and the
      -- return/value columns of position_returns for every real index class --
      -- identical to before these buckets were retained. (Verified by isolation
      -- test: only the synthetic position_id label re-sequences.)
      AND COALESCE(CAST(asset_class AS VARCHAR), '') NOT IN ('CASH', 'DERIVATIVE')
      AND COALESCE(CAST(index_classification AS VARCHAR), '') != 'CASH'
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
    _match_exact_name(con, contested=contested_assignment)
    if contested_assignment and contested_leftover_rounds > 0:
        _match_exact_name_leftover_rounds(con, max_rounds=contested_leftover_rounds)
    tier_b_counts = con.execute("""
        SELECT match_method, COUNT(*) AS n FROM tier_b GROUP BY match_method
    """).fetchdf()
    for _, row in tier_b_counts.iterrows():
        logger.info("  %s: %d pairs", row["match_method"], row["n"])

    # --- Tier C: Normalized name ---
    logger.info("Running Tier C: Normalized name matching...")
    _match_normalized_name(con)
    tier_c_count = con.execute("SELECT COUNT(*) FROM tier_c").fetchone()[0]
    logger.info("  Tier C: %d pairs (greedy)", tier_c_count)
    if use_bipartite:
        _bipartite_dedup(con, "tier_c")
        tier_c_count = con.execute("SELECT COUNT(*) FROM tier_c").fetchone()[0]
        logger.info("  Tier C: %d pairs (after bipartite)", tier_c_count)

    # --- Tier D: Fuzzy ---
    logger.info("Running Tier D: Jaro-Winkler fuzzy matching...")
    _match_fuzzy(con)
    tier_d_count = con.execute("SELECT COUNT(*) FROM tier_d").fetchone()[0]
    logger.info("  Tier D: %d pairs (greedy)", tier_d_count)
    if use_bipartite:
        _bipartite_dedup(con, "tier_d")
        tier_d_count = con.execute("SELECT COUNT(*) FROM tier_d").fetchone()[0]
        logger.info("  Tier D: %d pairs (after bipartite)", tier_d_count)

    # --- Tier E: Entity fingerprint ---
    logger.info("Running Tier E: Entity-constrained fingerprint matching...")
    _match_entity_fingerprint(con)
    tier_e_count = con.execute("SELECT COUNT(*) FROM tier_e").fetchone()[0]
    logger.info("  Tier E: %d pairs (greedy)", tier_e_count)
    # Bipartite disabled for Tier E: entity fingerprint matching operates on
    # fuzzy identity signals where globally-optimal reassignment produces
    # lateral churn (6,800+ swaps in assessment) without measurable accuracy
    # improvement.  Tier E's high base error rate is better addressed by
    # tightening candidate filters than by reassigning within noisy clusters.

    # --- Tier F: gap-quarter (span-2) links ---
    _match_gap_quarter(con, enabled=gap_quarter_tier)
    if gap_quarter_tier:
        tier_f_mix = con.execute(
            "SELECT match_method, COUNT(*) FROM tier_f GROUP BY 1 ORDER BY 2 DESC"
        ).fetchall()
        logger.info("  Tier F: %d pairs %s",
                    sum(n for _, n in tier_f_mix), dict(tier_f_mix))

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
        UNION ALL
        SELECT * FROM tier_f
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

    # Apply position match overrides (reject / force_pair)
    from pipeline.position_match_overrides import (
        apply_match_overrides,
        load_position_match_overrides,
    )
    overrides_df = load_position_match_overrides()
    if not overrides_df.empty:
        result, n_rejected, n_forced = apply_match_overrides(result, overrides_df)
        if n_rejected or n_forced:
            logger.info(
                "  Match overrides applied: %d rejected, %d forced",
                n_rejected, n_forced,
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
    from pipeline.utils import write_parquet_companion
    write_parquet_companion(_out_file)
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

def _assign_via_registry(unified_df, components_dict, registry_path,
                         retirements_path):
    """Resolve uid->position_id through the persisted registry layer.

    Returns (uid_to_pid, ResolveResult).  Writes the refreshed registry and
    retirement artifacts only when paths are provided.  Component formation is
    unchanged -- this only names the components.
    """
    from pipeline.position_id_registry import (
        compute_natural_keys, resolve_position_ids, load_registry,
    )
    natural_keys = compute_natural_keys(unified_df)
    comp_lists = [list(members) for members in components_dict.values()]
    prior = load_registry(registry_path) if registry_path else None
    res = resolve_position_ids(comp_lists, unified_df, natural_keys, prior)
    if registry_path is not None:
        from pathlib import Path as _P
        _P(registry_path).parent.mkdir(parents=True, exist_ok=True)
        res.registry_df.to_csv(registry_path, index=False)
    if retirements_path is not None:
        res.retirements_df.to_csv(retirements_path, index=False)
    logger.info(
        "  Registry: %d inherited, %d minted, %d merged, %d split-reassigned",
        res.n_inherited, res.n_minted, res.n_merged, res.n_split_reassigned,
    )
    return res.uid_to_pid, res


def _supplementary_position_key_pairs(unified_df: pd.DataFrame) -> list[tuple[int, int]]:
    """Adjacent-quarter pairs whose strong ``position_key`` is identical and
    unique per cik/source/quarter on both sides (FV ratio within MAX_FV_RATIO).

    Flag-independent.  Multi-tranche filers whose issuer_name used to be the
    whole raw identifier (Trinity, Silver Point, BlackRock DLC) got their
    chains from the supplementary *name* pass because every tranche's "name"
    was unique.  Once the wrappers extract the real company name, that pass
    refuses the company (n != 1) and the tranche identity survives only in
    position_key.  Uniqueness on both sides means no 1:1 contest is needed.
    """
    if "position_key" not in unified_df.columns or "_uid" not in unified_df.columns:
        return []
    con = duckdb.connect()
    con.register("u", unified_df)
    next_qtr = _next_quarter_sql("a.qtr")
    df = con.execute(f"""
    WITH base AS (
        SELECT _uid,
            CAST(cik AS VARCHAR) AS cik,
            CAST(source AS VARCHAR) AS source,
            {_quarter_label_sql('report_date')} AS qtr,
            CAST(position_key AS VARCHAR) AS pk,
            TRY_CAST(fair_value AS DOUBLE) AS fv
        FROM u
        WHERE TRY_CAST(fair_value AS DOUBLE) IS NOT NULL
          AND TRY_CAST(fair_value AS DOUBLE) != 0
          AND COALESCE(TRIM(CAST(position_key AS VARCHAR)), '') != ''
          AND ({_strong_position_key_sql('position_key')})
    ),
    key_counts AS (
        SELECT cik, source, qtr, pk, COUNT(*) AS n
        FROM base GROUP BY cik, source, qtr, pk
    ),
    unique_base AS (
        SELECT b.* FROM base b
        JOIN key_counts kc
          ON b.cik = kc.cik AND b.source = kc.source
         AND b.qtr = kc.qtr AND b.pk = kc.pk
        WHERE kc.n = 1
    )
    SELECT a._uid AS uid_a, b._uid AS uid_b
    FROM unique_base a
    JOIN unique_base b
      ON a.cik = b.cik AND a.source = b.source
     AND b.qtr = ({next_qtr})
     AND a.pk = b.pk
     AND ABS(a.fv) / GREATEST(ABS(b.fv), 1.0) BETWEEN (1.0 / {MAX_FV_RATIO}) AND {MAX_FV_RATIO}
     AND ABS(b.fv) / GREATEST(ABS(a.fv), 1.0) BETWEEN (1.0 / {MAX_FV_RATIO}) AND {MAX_FV_RATIO}
    ORDER BY uid_a, uid_b
    """).fetchdf()
    con.close()
    return [(int(a), int(b)) for a, b in zip(df["uid_a"], df["uid_b"])]


def assign_position_ids(
    unified_df: pd.DataFrame,
    matches_df: pd.DataFrame,
    *,
    use_registry: bool = False,
    registry_path=None,
    retirements_path=None,
    edges_file=None,
    contested_assignment: bool = False,
    contested_leftover_rounds: int = CONTESTED_LEFTOVER_ROUNDS,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Assign stable position_id values to unified holdings and match pairs.

    ``contested_assignment=True`` (experimental, mg3 replay) applies the
    coexistence veto to every chain-forming edge and lets the supplementary
    exact-name pass resolve contested name groups by principal instead of
    refusing them.

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

    if use_registry and registry_path is None:
        registry_path = POSITION_ID_REGISTRY_FILE
        if retirements_path is None:
            retirements_path = POSITION_ID_RETIREMENTS_FILE

    if matches_df.empty:
        # All singletons
        unified_df = _sort_existing(unified_df.copy(), UNIFIED_SORT_COLUMNS)
        if use_registry:
            uid_to_pid, _ = _assign_via_registry(
                unified_df, {}, registry_path, retirements_path,
            )
            unified_df["position_id"] = [
                uid_to_pid[i] for i in range(len(unified_df))
            ]
        else:
            unified_df["position_id"] = [
                f"POS-{i:08d}" for i in range(1, len(unified_df) + 1)
            ]
        _write_position_id_edges([], edges_file)
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
    from pipeline.matching_contract import scope_sql,bounds_sql,interval_rank_sql
    scope_expression=scope_sql(unified_df.columns,row_id='row_id' if 'row_id' in unified_df.columns else '_uid')
    row_scopes=con.execute('SELECT '+scope_expression+' AS scope FROM u ORDER BY _uid').fetchnumpy()['scope']
    supp_mat_low,supp_mat_high=bounds_sql(unified_df.columns)
    reported_cost='cost_reported' if 'cost_reported' in unified_df.columns else 'cost'

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
        if row_scopes[a]!=row_scopes[b]:
            return False
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
    n_vetoed = 0
    used_match_midx: set[int] = set()
    used_supp_edges: set[tuple[int, int]] = set()
    spans = pd.to_numeric(matches_df["span_months"], errors="coerce").fillna(99)
    # The span cap keeps Tier A's 6/9/12-month comparatives out of the chain,
    # since those restate a position the adjacent-quarter tiers already link.
    # Tier F is the deliberate exception: it exists to cross one missing filing,
    # so its span is 6 by construction and must be admitted.
    is_gap = (matches_df["match_method"].astype(str)
              .str.startswith("F_gap_").to_numpy())
    long_span = (spans.to_numpy() > 4) & ~is_gap
    vetoed: set[tuple[int, int]] = set()
    if contested_assignment:
        cand_edges = [
            (begin_uid[m], end_uid[m]) for m in range(n_match)
            if not long_span[m] and m in begin_uid and m in end_uid
        ]
        vetoed = _coexistence_vetoed(unified_df, cand_edges)
    for midx in range(n_match):
        if long_span[midx]:
            continue
        b = begin_uid.get(midx)
        e = end_uid.get(midx)
        if b is not None and e is not None:
            if (b, e) in vetoed:
                n_vetoed += 1
                _register_component(b)
                _register_component(e)
            elif _guarded_union(b, e):
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
    if n_vetoed:
        logger.info("  Coexistence veto dropped %d match edges (twin present)",
                    n_vetoed)
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

    if contested_assignment:
        # Contested variant: comma / fka / ordinal-insensitive key, names
        # allowed up to the generic-header multiplicity cap, 1:1 contest led
        # by banded principal -> maturity -> raw name -> cost -> FV, instrument
        # sub-type continuity, and leftover rounds (see
        # _match_exact_name_leftover_rounds for the rationale).
        supp_name_sql = _name_key_sql("issuer_name")
        supp_mult_cond = f"nc.n <= {MAX_NAME_MULTIPLICITY}"
        supp_order_b = (
            "pa_band ASC NULLS LAST, mat_rank ASC, name_exact DESC, "
            "cost_prox ASC NULLS LAST, fv_prox ASC, pa_prox ASC NULLS LAST, uid_b ASC"
        )
        supp_order_a = supp_order_b.replace("uid_b ASC", "uid_a ASC")
        supp_extra_base = (
            ", LOWER(TRIM(CAST(issuer_name AS VARCHAR))) AS _raw"
            f", TRY_CAST({reported_cost} AS DOUBLE) AS cost"
            ", TRY_CAST(basis_spread AS DOUBLE) AS bs"
            f", {_inst_subtype_sql('instrument_description')} AS _inst_subtype"
            f", {_inst_subtype_sql('issuer_name')} AS _inst_subtype_name"
        )
        supp_extra_pairs = (
            f", {_pa_band_sql('a', 'b')} AS pa_band"
            f", {_cost_prox_sql('a.cost', 'b.cost')} AS cost_prox"
            ", CASE WHEN a._raw = b._raw THEN 1 ELSE 0 END AS name_exact"
        )
        supp_subtype_cond = (
            "AND (a._inst_subtype IS NULL OR b._inst_subtype IS NULL "
            "OR a._inst_subtype = b._inst_subtype) "
            # Maturity veto with amendment escape (E5), as in the B2 contest.
            "AND " + _maturity_veto_sql("a._mat_low", "b._mat_low", "a.pa", "b.pa", "a.bs", "b.bs", overlap=_maturity_rank_sql("a","b")+"=0")
        )
    else:
        # Only use names that appear exactly once per CIK/quarter.
        # Multi-tranche positions (same name, different bonds) would
        # merge into mega-chains without a stable sub-identifier.
        supp_name_sql = "LOWER(TRIM(CAST(issuer_name AS VARCHAR)))"
        supp_mult_cond = "nc.n = 1"
        supp_order_b = "fv_prox ASC, uid_b ASC"
        supp_order_a = "fv_prox ASC, uid_a ASC"
        supp_extra_base = ""
        supp_extra_pairs = ""
        supp_subtype_cond = ""
    supp_pa_expr = (
        "COALESCE(TRY_CAST(principal_amount_usd AS DOUBLE), "
        "TRY_CAST(principal_amount AS DOUBLE))"
        if "principal_amount_usd" in unified_df.columns
        else "TRY_CAST(principal_amount AS DOUBLE)"
    )

    supp_pairs_cte = f"""
    WITH base AS (
        SELECT _uid,
            CAST(cik AS VARCHAR) AS cik,
            CAST(source AS VARCHAR) AS source,
            {_quarter_label_sql('report_date')} AS qtr,
            {supp_name_sql} AS _name,
            TRY_CAST(fair_value AS DOUBLE) AS fv,
            {supp_pa_expr} AS pa,
            TRY_CAST(maturity_date AS DATE) AS mat,
            {supp_mat_low} AS _mat_low,{supp_mat_high} AS _mat_high,{scope_expression} AS _accounting_scope
            {supp_extra_base}
        FROM u
        WHERE TRY_CAST(fair_value AS DOUBLE) IS NOT NULL
          AND TRY_CAST(fair_value AS DOUBLE) != 0
          AND TRIM(CAST(issuer_name AS VARCHAR)) != ''
    ),
    name_counts AS (
        SELECT cik, source, qtr, _name, COUNT(*) AS n
        FROM base GROUP BY cik, source, qtr, _name
    ),
    unique_base AS (
        SELECT b.* FROM base b
        JOIN name_counts nc
          ON b.cik = nc.cik AND b.source = nc.source
         AND b.qtr = nc.qtr AND b._name = nc._name
        WHERE {supp_mult_cond}
    ),
    pairs AS (
        SELECT a._uid AS uid_a, b._uid AS uid_b,
            ABS(LN(GREATEST(ABS(a.fv), 1.0) / GREATEST(ABS(b.fv), 1.0))) AS fv_prox,
            CASE WHEN a.pa > 0 AND b.pa > 0 THEN ABS(LN(a.pa / b.pa)) END AS pa_prox,
            {_maturity_rank_sql('a','b')} AS mat_rank
            {supp_extra_pairs}
        FROM unique_base a
        JOIN unique_base b
          ON a.cik = b.cik AND a.source = b.source AND a._accounting_scope=b._accounting_scope
         AND b.qtr = ({next_qtr})
         AND a._name = b._name
         AND ABS(a.fv) / GREATEST(ABS(b.fv), 1.0) BETWEEN (1.0 / {MAX_FV_RATIO}) AND {MAX_FV_RATIO}
         AND ABS(b.fv) / GREATEST(ABS(a.fv), 1.0) BETWEEN (1.0 / {MAX_FV_RATIO}) AND {MAX_FV_RATIO}
         {supp_subtype_cond}
    )
    """
    supp_select = f"""
    rn_a AS (
        SELECT *,
            ROW_NUMBER() OVER (
                PARTITION BY uid_a ORDER BY {supp_order_b}
            ) AS rn1
        FROM cand
    ),
    rn_b AS (
        SELECT *,
            ROW_NUMBER() OVER (
                PARTITION BY uid_b ORDER BY {supp_order_a}
            ) AS rn2
        FROM rn_a WHERE rn1 = 1
    )
    SELECT uid_a, uid_b FROM rn_b WHERE rn2 = 1
    """
    if not contested_assignment:
        supp_pairs = con2.execute(
            supp_pairs_cte + ", cand AS (SELECT * FROM pairs), " + supp_select
        ).fetchdf()
    else:
        con2.execute("CREATE OR REPLACE TEMP TABLE supp_all AS "
                     + supp_pairs_cte + " SELECT * FROM pairs")
        con2.execute("CREATE OR REPLACE TEMP TABLE supp_chosen (uid_a BIGINT, uid_b BIGINT)")
        rounds: list[pd.DataFrame] = []
        for _round in range(1 + contested_leftover_rounds):
            round_df = con2.execute(
                "WITH cand AS ("
                "  SELECT * FROM supp_all"
                "  WHERE uid_a NOT IN (SELECT uid_a FROM supp_chosen)"
                "    AND uid_b NOT IN (SELECT uid_b FROM supp_chosen)"
                # leftover rounds: equal, known maturity only (see
                # _match_exact_name_leftover_rounds)
                + ("    AND mat_rank = 0" if _round > 0 else "")
                + "), " + supp_select
            ).fetchdf()
            if round_df.empty:
                break
            # Round 1 is the ordinary greedy contest; later rounds pair the
            # leftovers and are labelled separately in the edge ledger so a
            # gold stratum can score them on their own.
            round_df["supp_round"] = _round + 1
            con2.register("round_df", round_df)
            con2.execute("INSERT INTO supp_chosen SELECT uid_a, uid_b FROM round_df")
            con2.unregister("round_df")
            rounds.append(round_df)
        supp_pairs = (pd.concat(rounds, ignore_index=True) if rounds
                      else pd.DataFrame(columns=["uid_a", "uid_b"]))
        logger.info("  Supplementary contested rounds: %d (%d pairs)",
                    len(rounds), len(supp_pairs))
    con2.close()
    if contested_assignment and not supp_pairs.empty:
        supp_vetoed = _coexistence_vetoed(
            unified_df,
            [(int(a), int(b)) for a, b in zip(supp_pairs["uid_a"], supp_pairs["uid_b"])],
        )
        if supp_vetoed:
            keep = [(int(a), int(b)) not in supp_vetoed
                    for a, b in zip(supp_pairs["uid_a"], supp_pairs["uid_b"])]
            supp_pairs = supp_pairs[keep].reset_index(drop=True)
            logger.info("  Coexistence veto dropped %d supplementary edges",
                        len(supp_vetoed))

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
    # Step 3c: Supplementary position_key pass (flag-independent)
    # ------------------------------------------------------------------
    # Rows whose strong position_key is identical in adjacent quarters and
    # unique per quarter on both sides.  Runs after the name pass and only
    # fills what is still unlinked (union is a no-op inside a component; the
    # report-date guard blocks merging two live tranches).
    key_pairs = _supplementary_position_key_pairs(unified_df)
    n_key = 0
    n_key_skipped_date_collision = 0
    used_key_edges: set[tuple[int, int]] = set()
    for a, b in key_pairs:
        root_a = _register_component(a)
        root_b = _register_component(b)
        if root_a == root_b:
            continue
        if not _guarded_union(a, b):
            n_key_skipped_date_collision += 1
            continue
        used_key_edges.add((a, b))
        n_key += 1
    logger.info("  Supplementary position_key edges: %d new connections (of %d pairs)",
                n_key, len(key_pairs))
    if n_key_skipped_date_collision:
        logger.warning(
            "  Skipped %d position_key edges that would merge duplicate report-date rows",
            n_key_skipped_date_collision,
        )

    # ------------------------------------------------------------------
    # Step 4: Assign component IDs (sorted for determinism)
    # ------------------------------------------------------------------
    components = uf.components()
    n_components = len(components)
    n_chained_rows = sum(len(m) for m in components.values())
    n_singletons = len(unified_df) - n_chained_rows

    if use_registry:
        # Stable identifier layer: names components via the persisted registry
        # instead of a sort-rank ordinal.  Component membership is unchanged.
        uid_to_pid, _ = _assign_via_registry(
            unified_df, components, registry_path, retirements_path,
        )
    else:
        uid_to_pid = {}
        ordered_components = sorted(
            (sorted(members) for members in components.values()),
            key=lambda members: members[0],
        )
        for i, members in enumerate(ordered_components, 1):
            pid = f"POS-{i:08d}"
            for uid in members:
                uid_to_pid[uid] = pid

        # Singletons: unified rows not in any component
        next_id = n_components + 1
        for uid in range(len(unified_df)):
            if uid not in uid_to_pid:
                uid_to_pid[uid] = f"POS-{next_id:08d}"
                next_id += 1

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
        if b is not None and e is not None and row_scopes[b]!=row_scopes[e]:
            match_pids.append("")
            n_unlinked+=1
        elif e is not None:
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
            "match_method": (
                ("SUPP_B2_contested_leftover"
                 if int(getattr(item, "supp_round", 1) or 1) > 1
                 else "SUPP_B2_contested_name_key")
                if contested_assignment else "SUPP_B2_unique_exact_name"
            ),
            "match_key": str(end.get("issuer_name", "")).strip().lower(),
            "match_score": "1.0",
            "span_months": "3",
        })
    for a, b in sorted(used_key_edges):
        begin = uid_lookup.loc[a]
        end = uid_lookup.loc[b]
        edge_rows.append({
            "edge_type": "supplementary_position_key",
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
            "match_method": "SUPP_B1b_unique_position_key",
            "match_key": str(end.get("position_key", "")).strip().lower(),
            "match_score": "1.0",
            "span_months": "3",
        })
    _write_position_id_edges(edge_rows, edges_file)
    logger.info("  Position ID edge artifact: %d edges", len(edge_rows))

    if n_unlinked:
        matches_df = matches_df[
            matches_df["position_id"].astype(str).str.strip() != ""
        ].copy()

    # Ensure column order matches UNIFIED_COLUMNS, but preserve appended
    # provenance columns (row_id, row_id_basis) that _assign_row_ids appends
    # AFTER building UNIFIED_COLUMNS -- they are intentionally not in that list.
    from pipeline.unified_holdings import UNIFIED_COLUMNS
    _appended = [c for c in ("row_id", "row_id_basis") if c in unified_df.columns]
    unified_df = unified_df[[c for c in UNIFIED_COLUMNS if c in unified_df.columns] + _appended]
    for col in UNIFIED_COLUMNS:
        if col not in unified_df.columns:
            unified_df[col] = ""
    unified_df = unified_df[UNIFIED_COLUMNS + _appended]
    unified_df = _sort_existing(unified_df, UNIFIED_SORT_COLUMNS)
    matches_df = _sort_existing(matches_df, MATCH_SORT_COLUMNS)

    elapsed = time.time() - t0
    logger.info("Position IDs assigned in %.1f s", elapsed)
    logger.info("  Components (chained): %d", n_components)
    logger.info("  Singletons: %d", n_singletons)
    logger.info("  Total unique position_ids: %d", n_components + n_singletons)

    return unified_df, matches_df
