"""Deterministic two-tier re-verification of provenance-annotated holdings.

Cheap tier (this half): re-derive each published value from its declared raw
(src_facts) + declared transform events (src_facts.x + src_transforms) with no
filing access -- runnable on every rebuild. Full tier (full_tier): re-read the
cached iXBRL instance at (accession, src_context_id, concept). Consumes the
provenance columns; never writes to the holdings artifact (verification STATE
lives in the ledger only -- scoping doc section 2). ASCII-only. Cache-only.
"""
from __future__ import annotations

import logging
from pathlib import Path

import duckdb
import pandas as pd

logger = logging.getLogger(__name__)

# field -> (pathway enum column, empty-pathway-means-xbrl?)
# cost/shares: '' = as-extracted xbrl pathway (trivial pass if no event).
CHEAP_FIELDS: dict[str, tuple[str, bool]] = {
    "interest_rate": ("interest_rate_source", False),
    "basis_spread": ("basis_spread_source", False),
    "pik_rate": ("pik_rate_source", False),
    "pct_of_net_assets": ("pct_of_net_assets_source", False),
    "fair_value": ("fair_value_source", False),
    "cost": ("cost_source", True),
    "principal_amount": ("principal_amount_source", False),
    "shares_held": ("shares_held_source", True),
}
_RATE_FIELDS = ("interest_rate", "basis_spread", "pik_rate", "pct_of_net_assets")

# src_facts is included so Task 8 can use it without a join back to the
# original holdings frame.
_ID_COLS = "row_id, cik, accession_number, report_date, src_context_id, src_facts"


def _field_sql(field: str, source_col: str, empty_is_xbrl: bool) -> str:  # noqa: ARG001
    """One SELECT producing the cheap-tier verdict for *field* (long format).

    src_facts.x is stored as a JSON array (e.g. '["decimals_rescale:10^-3"]').
    json_extract_string on a VARCHAR column in DuckDB returns the JSON-encoded
    value for arrays (including the surrounding brackets), so we use LIKE
    matching against the raw json_extract string for both .x and .r fields.
    """
    is_rate = field in _RATE_FIELDS

    pathway = f"COALESCE(CAST({source_col} AS VARCHAR), '')"

    # Declared raw value: extract r from src_facts JSON.
    # json_extract_string returns NULL when key absent or src_facts is empty.
    raw = (
        f"TRY_CAST("
        f"  json_extract_string(NULLIF(CAST(src_facts AS VARCHAR), ''), '$.{field}.r')"
        f"  AS DOUBLE"
        f")"
    )

    # src_facts.x is a JSON array; json_extract returns the array as a JSON
    # string like '["decimals_rescale:10^-3","cik_scale_fix:x1000"]'.
    # We capture the raw x string once and LIKE-match against it.
    x_str = (
        f"json_extract_string("
        f"  NULLIF(CAST(src_facts AS VARCHAR), ''), '$.{field}.x'"
        f")"
    )

    # decimals_rescale multiplier: parse exponent from the x array string.
    # e.g. 'decimals_rescale:10^-3' -> POWER(10, -3) = 0.001
    dec = (
        f"CASE"
        f"  WHEN {x_str} LIKE '%decimals_rescale:10^%'"
        f"  THEN POWER(10.0, TRY_CAST("
        f"    regexp_extract({x_str}, 'decimals_rescale:10\\^(-?\\d+)', 1)"
        f"    AS INTEGER))"
        f"  ELSE 1.0"
        f"END"
    )

    # cik_scale_fix multiplier
    cik_fix = (
        f"CASE WHEN {x_str} LIKE '%cik_scale_fix:x1000%' THEN 1000.0"
        f"     ELSE 1.0 END"
    )

    # Staging events from src_transforms (flat 'field:code;...' string)
    ev = "COALESCE(CAST(src_transforms AS VARCHAR), '')"
    stag = (
        f"CASE"
        f"  WHEN {ev} LIKE '%{field}:rate_x100%' THEN 100.0"
        f"  WHEN {ev} LIKE '%{field}:rate_div100%' THEN 0.01"
        f"  WHEN {ev} LIKE '%{field}:pik_boundary_div100%' THEN 0.01"
        f"  ELSE 1.0"
        f"END"
    )

    neg_null = f"({ev} LIKE '%{field}:neg_null%')"

    # has_event: either src_transforms mentions this field, or src_facts.x is present
    has_event = (
        f"("
        f"  {ev} LIKE '%{field}:%'"
        f"  OR {x_str} IS NOT NULL"
        f")"
    )

    published = f"TRY_CAST({field} AS DOUBLE)"
    expected = f"({raw} * {dec} * {cik_fix} * {stag})"

    # marker: match field name in comma-joined or semicolon-joined list columns
    def marker(col: str) -> str:
        return (
            f"((',' || COALESCE(CAST({col} AS VARCHAR), '') || ',') LIKE '%,{field},%'"
            f" OR (';' || COALESCE(CAST({col} AS VARCHAR), '') || ';') LIKE '%;{field};%')"
        )

    # Rate fields: when pathway='' and published IS NULL, the field is simply
    # absent from this row -- trivial pass, not a declaration failure.
    # This branch must come ABOVE the raw IS NULL -> fail branch.
    rate_absent_trivial = (
        f"WHEN {pathway} = '' AND {published} IS NULL THEN 'pass_trivial'"
        if is_rate else ""
    )

    # When raw is NULL and there is no event, the result depends on field type:
    # - rate fields: declaration incomplete -> fail
    # - monetary fields: raw=stored-value by construction -> pass_trivial
    raw_null_no_event_status = "'fail'" if is_rate else "'pass_trivial'"

    return f"""
    SELECT {_ID_COLS},
           '{field}' AS field,
           {pathway} AS pathway,
           {raw} AS declared_raw,
           {ev} AS declared_events,
           {published} AS published,
           {expected} AS expected,
           CASE
             WHEN {marker('corrected_fields')}    THEN 'corrected'
             WHEN {pathway} = 'derived_proxy'     THEN 'derived'
             WHEN {pathway} = 'identifier_text'   THEN 'text_pathway'
             WHEN {marker('src_filled_fields')}   THEN 'filled_field'
             WHEN {marker('src_conflict_fields')} THEN 'merged_conflict'
             WHEN COALESCE(CAST(src_context_id AS VARCHAR), '') = ''
               THEN 'no_provenance'
             WHEN {published} IS NULL AND {raw} IS NULL AND NOT {has_event}
               THEN 'pass_trivial'
             WHEN {neg_null}
               THEN CASE WHEN {published} IS NULL THEN 'pass' ELSE 'fail' END
             WHEN {raw} IS NULL AND {has_event}
               THEN 'missing_raw_with_transform'
             {rate_absent_trivial}
             WHEN {raw} IS NULL
               THEN {raw_null_no_event_status}
             WHEN ABS({expected} - {published})
                  <= 1e-6 * GREATEST(ABS({expected}), ABS({published}), 1e-12)
               THEN 'pass'
             ELSE 'fail'
           END AS cheap_status
    FROM h
    WHERE lower(COALESCE(CAST(source AS VARCHAR), '')) = 'bdc'
    """


def cheap_tier(
    holdings_df: pd.DataFrame | None = None,
    holdings_path: Path | None = None,
    ciks: list[str] | None = None,
) -> pd.DataFrame:
    """Cheap-tier verdicts for every (bdc row, checkable field).

    Parameters
    ----------
    holdings_df:
        In-memory DataFrame (used in tests; overrides holdings_path).
    holdings_path:
        Path to unified holdings parquet or CSV. Defaults to
        config.UNIFIED_HOLDINGS_PARQUET_FILE when neither arg is given.
    ciks:
        Optional list of CIK strings to filter to (strips leading zeros for
        comparison, so '0001287750' and '1287750' match the same entity).

    Returns
    -------
    pd.DataFrame
        Long format, one row per (row_id, field). Columns:
        row_id, cik, accession_number, report_date, src_context_id,
        src_facts, field, pathway, declared_raw, declared_events,
        published, expected, cheap_status.
    """
    con = duckdb.connect()
    try:
        if holdings_df is not None:
            con.register("h_src", holdings_df)
            con.execute("CREATE VIEW h AS SELECT * FROM h_src")
        else:
            if holdings_path is None:
                from pipeline import config  # noqa: PLC0415
                holdings_path = config.UNIFIED_HOLDINGS_PARQUET_FILE
            src = str(holdings_path).replace("'", "''")
            reader = (
                "read_parquet"
                if str(holdings_path).endswith(".parquet")
                else "read_csv_auto"
            )
            con.execute(f"CREATE VIEW h AS SELECT * FROM {reader}('{src}')")

        if ciks:
            wanted = ",".join(
                f"'{str(c).lstrip('0') or '0'}'"
                for c in sorted(set(ciks))
            )
            con.execute(
                "CREATE OR REPLACE VIEW h AS SELECT * FROM h WHERE "
                "ltrim(regexp_replace(CAST(cik AS VARCHAR), '[^0-9]', '', 'g'), '0') "
                f"IN ({wanted})"
            )

        parts = [_field_sql(f, sc, e) for f, (sc, e) in CHEAP_FIELDS.items()]
        sql = " UNION ALL ".join(parts)
        out: pd.DataFrame = con.execute(sql).fetchdf()
    finally:
        con.close()

    return out
