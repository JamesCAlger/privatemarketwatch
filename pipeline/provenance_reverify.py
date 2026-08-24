"""Deterministic two-tier re-verification of provenance-annotated holdings.

Cheap tier (this half): re-derive each published value from its declared raw
(src_facts) + declared transform events (src_facts.x + src_transforms) with no
filing access -- runnable on every rebuild. Full tier (full_tier): re-read the
cached iXBRL instance at (accession, src_context_id, concept). Consumes the
provenance columns; never writes to the holdings artifact (verification STATE
lives in the ledger only -- scoping doc section 2). ASCII-only. Cache-only.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import duckdb
import pandas as pd

logger = logging.getLogger(__name__)

# field -> pathway enum column.
# cost/shares '' pathway = as-extracted xbrl (trivial pass when no event).
# Monetary fields (cost, shares_held) reach pass_trivial via raw IS NULL /
# no event branch; no separate flag is needed.
CHEAP_FIELDS: dict[str, str] = {
    "interest_rate": "interest_rate_source",
    "basis_spread": "basis_spread_source",
    "pik_rate": "pik_rate_source",
    "pct_of_net_assets": "pct_of_net_assets_source",
    "fair_value": "fair_value_source",
    "cost": "cost_source",
    "principal_amount": "principal_amount_source",
    "shares_held": "shares_held_source",
}
_RATE_FIELDS = ("interest_rate", "basis_spread", "pik_rate", "pct_of_net_assets")

# src_facts is included so Task 8 can use it without a join back to the
# original holdings frame.
_ID_COLS = "row_id, cik, accession_number, report_date, src_context_id, src_facts"


def _field_sql(field: str, source_col: str) -> str:
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
             WHEN COALESCE(NULLIF(CAST(src_facts AS VARCHAR), ''), '') = ''
               AND {ev} LIKE '%{field}:%'
               THEN 'undeclared'
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
            con.execute("CREATE VIEW h_base AS SELECT * FROM h_src")
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
            con.execute(f"CREATE VIEW h_base AS SELECT * FROM {reader}('{src}')")

        if ciks:
            wanted = ",".join(
                f"'{str(c).lstrip('0') or '0'}'"
                for c in sorted(set(ciks))
            )
            con.execute(
                "CREATE VIEW h AS SELECT * FROM h_base WHERE "
                "ltrim(regexp_replace(CAST(cik AS VARCHAR), '[^0-9]', '', 'g'), '0') "
                f"IN ({wanted})"
            )
        else:
            con.execute("CREATE VIEW h AS SELECT * FROM h_base")

        parts = [_field_sql(f, sc) for f, sc in CHEAP_FIELDS.items()]
        sql = " UNION ALL ".join(parts)
        out: pd.DataFrame = con.execute(sql).fetchdf()
    finally:
        con.close()

    return out


# ---------------------------------------------------------------------------
# Full tier
# ---------------------------------------------------------------------------

# cheap_status values that short-circuit full-tier (no filing access needed).
_SHORT_CIRCUIT = frozenset({"corrected", "derived", "text_pathway",
                             "filled_field", "merged_conflict", "no_provenance",
                             "undeclared"})


def _staging_multiplier(field: str, events: str) -> float:
    """Staging transform multiplier for *field* from declared_events string."""
    if f"{field}:rate_x100" in events:
        return 100.0
    if f"{field}:rate_div100" in events or f"{field}:pik_boundary_div100" in events:
        return 0.01
    return 1.0


def _extractor_multiplier(x_events: list) -> float:
    """Product of extractor-side scale events (decimals_rescale, cik_scale_fix)."""
    mult = 1.0
    for code in x_events or []:
        if code.startswith("decimals_rescale:10^"):
            mult *= 10.0 ** int(code.split("^", 1)[1])
        elif code.startswith("cik_scale_fix:x"):
            # Split on ':x' (not bare 'x') so the 'x' inside 'fix' is not the split point.
            # 'cik_scale_fix:x1000'.split(':x', 1)[1] == '1000', not ':x1000'.
            mult *= float(code.split(":x", 1)[1])
    return mult


def _numbers_close(a: float, b: float) -> bool:
    return abs(a - b) <= 1e-6 * max(abs(a), abs(b), 1e-12)


def _default_xml_loader(filings_index: pd.DataFrame):
    """Build production loader from the filings index CSV."""
    paths = dict(zip(filings_index["accession_number"].astype(str),
                     filings_index["xbrl_local_path"].astype(str)))

    def _load(cik: str, accession: str):
        from lxml import etree
        p = paths.get(str(accession), "")
        if not p or not Path(p).exists():
            return None
        try:
            return etree.parse(p)
        except Exception:
            return None
    return _load


def full_tier(cheap_df: pd.DataFrame, xml_loader=None,
              filings_index: pd.DataFrame | None = None) -> pd.DataFrame:
    """Re-read each anchored fact from the cached instance document.

    Iterates over accessions (filing count), not holdings rows -- one XML parse
    per accession.  Appends ``instance_raw`` (float|None) and ``full_status``
    to the cheap-tier frame.

    full_status enum: raw_match | raw_stale | published_mismatch |
    anchor_missing | context_missing | source_unavailable | not_checked.
    """
    from pipeline.bdc_filings import _local_name, _match_concept, _parse_fact_value

    if xml_loader is None:
        if filings_index is None:
            from pipeline.config import BDC_FILINGS_INDEX_FILE
            filings_index = pd.read_csv(BDC_FILINGS_INDEX_FILE, dtype=str)
        xml_loader = _default_xml_loader(filings_index)

    out = cheap_df.copy()
    out["instance_raw"] = None
    out["full_status"] = "not_checked"

    # pass_trivial rows with no published value have nothing to look up.
    checkable = (~out["cheap_status"].isin(_SHORT_CIRCUIT)
                 & ~((out["cheap_status"] == "pass_trivial")
                     & out["published"].isna()))

    for (cik, accession), grp in out.loc[checkable].groupby(
            ["cik", "accession_number"], sort=False):
        tree = xml_loader(str(cik), str(accession))
        if tree is None:
            out.loc[grp.index, "full_status"] = "source_unavailable"
            continue

        # Single pass over the tree for all wanted contexts in this accession.
        wanted_ctx = set(grp["src_context_id"].astype(str))
        # facts[ctx][col] = (local_name, raw_text)  first-wins per col
        facts: dict[str, dict[str, tuple[str, str]]] = {}
        seen_ctx: set[str] = set()

        for elem in tree.getroot().iter():
            ctx = elem.get("contextRef")
            if ctx is None or ctx not in wanted_ctx:
                continue
            seen_ctx.add(ctx)
            local = _local_name(elem.tag).lower()
            raw_text = (elem.text or "").strip()
            if not raw_text:
                continue
            col = _match_concept(local)
            if col is None:
                continue
            ctx_facts = facts.setdefault(ctx, {})
            # first-wins by column name (extractor rule)
            ctx_facts.setdefault(col, (local, raw_text))
            # also index by exact localname so declared-c lookups work
            ctx_facts.setdefault(f"__local__{local}", (local, raw_text))

        for i, r in grp.iterrows():
            ctx = str(r["src_context_id"])
            if ctx not in seen_ctx:
                out.at[i, "full_status"] = "context_missing"
                continue

            try:
                field = str(r["field"])

                # Resolve declared concept + x events from src_facts JSON.
                declared_c = ""
                x_events: list = []
                try:
                    sf = json.loads(str(r.get("src_facts") or "") or "{}")
                    field_sf = sf.get(field) or {}
                    declared_c = str(field_sf.get("c") or "").lower()
                    x_events = list(field_sf.get("x") or [])
                except (json.JSONDecodeError, AttributeError, TypeError):
                    pass

                ctx_facts = facts.get(ctx, {})
                if declared_c:
                    hit = ctx_facts.get(f"__local__{declared_c}")
                else:
                    hit = ctx_facts.get(field)

                if hit is None:
                    out.at[i, "full_status"] = "anchor_missing"
                    continue

                _local, raw_text = hit
                instance_raw = _parse_fact_value(field, raw_text)
                out.at[i, "instance_raw"] = instance_raw

                if not isinstance(instance_raw, (int, float)):
                    out.at[i, "full_status"] = "anchor_missing"
                    continue

                mult = (_extractor_multiplier(x_events)
                        * _staging_multiplier(field, str(r.get("declared_events") or "")))
                neg_null = f"{field}:neg_null" in str(r.get("declared_events") or "")
                published = r["published"]

                if neg_null:
                    pub_ok = pd.isna(published) and instance_raw < 0
                else:
                    pub_ok = (not pd.isna(published)
                              and _numbers_close(instance_raw * mult, float(published)))

                if not pub_ok:
                    out.at[i, "full_status"] = "published_mismatch"
                    continue

                declared_raw = r.get("declared_raw")
                if pd.isna(declared_raw) or _numbers_close(float(declared_raw),
                                                            float(instance_raw)):
                    out.at[i, "full_status"] = "raw_match"
                else:
                    out.at[i, "full_status"] = "raw_stale"

            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "full_tier: unexpected error on row %s field %s -- set source_unavailable: %s",
                    i, r.get("field", "?"), str(exc)
                )
                out.at[i, "full_status"] = "source_unavailable"

    return out


# ---------------------------------------------------------------------------
# Reason triage (scoping doc 8.2)
# ---------------------------------------------------------------------------

_CHEAP_REASON: dict[str, str] = {
    "corrected":       "corrected",
    "derived":         "derived",
    "text_pathway":    "text_pathway",
    "filled_field":    "merged_context_excluded",
    "merged_conflict": "merged_context_excluded",
    "no_provenance":   "no_provenance",
    "undeclared":      "no_provenance",
}

_FULL_REASON: dict[str, str] = {
    "source_unavailable": "source_unavailable",
    "context_missing":    "provenance_wrong",
    "anchor_missing":     "anchor_missing",
    "published_mismatch": "filing_mismatch",
    "raw_stale":          "anchor_stale",
}


def classify_reason(cheap_status: str, full_status: str) -> str:
    """Pure deterministic triage from the scoping doc 8.2 table.

    Reason enum: verified | anchor_stale | transform_drift | filing_mismatch |
    anchor_missing | provenance_wrong | source_unavailable | corrected |
    derived | text_pathway | merged_context_excluded | no_provenance |
    unchecked_trivial.
    """
    if cheap_status in _CHEAP_REASON:
        return _CHEAP_REASON[cheap_status]
    if full_status in _FULL_REASON:
        return _FULL_REASON[full_status]
    if full_status == "raw_match":
        return ("transform_drift"
                if cheap_status in ("fail", "missing_raw_with_transform")
                else "verified")
    return "unchecked_trivial"


# ---------------------------------------------------------------------------
# Ledger artifact (scoping doc 8.1)
# ---------------------------------------------------------------------------

def build_ledger(
    tier_df: pd.DataFrame,
    out_dir: Path,
    holdings_mtime: str = "",
) -> tuple[Path, Path]:
    """Write provenance_ledger.csv and provenance_ledger_summary.csv.

    Parameters
    ----------
    tier_df:
        Combined cheap + full tier DataFrame (output of full_tier or cheap
        with full_status='not_checked' appended).
    out_dir:
        Directory to write output files into (created if absent).
    holdings_mtime:
        ISO-format mtime of the holdings artifact this run was computed
        against; recorded verbatim in every ledger row.

    Returns
    -------
    tuple[Path, Path]
        (ledger_path, summary_path)
    """
    ledger = tier_df.copy()
    ledger["reason_code"] = [
        classify_reason(str(c), str(f))
        for c, f in zip(ledger["cheap_status"], ledger["full_status"])
    ]
    ledger["holdings_artifact_mtime"] = holdings_mtime

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    ledger_path = out_dir / "provenance_ledger.csv"
    ledger.to_csv(ledger_path, index=False)

    # Summary: aggregate over fair_value rows only for FV buckets.
    fv = ledger[ledger["field"] == "fair_value"].copy()
    fv["published"] = pd.to_numeric(fv["published"], errors="coerce").fillna(0.0)

    if fv.empty:
        summary = pd.DataFrame(columns=[
            "cik", "report_date", "n_fields", "n_verified",
            "verified_fv", "derived_fv", "corrected_fv", "total_fv",
            "verified_fv_share",
        ])
    else:
        grp = fv.groupby(["cik", "report_date"], dropna=False)
        summary = grp.apply(
            lambda g: pd.Series({
                "n_fields": len(g),
                "n_verified": int((g["reason_code"] == "verified").sum()),
                "verified_fv": g.loc[
                    g["reason_code"] == "verified", "published"].sum(),
                "derived_fv": g.loc[
                    g["reason_code"] == "derived", "published"].sum(),
                "corrected_fv": g.loc[
                    g["reason_code"] == "corrected", "published"].sum(),
                "total_fv": g["published"].sum(),
            }),
            include_groups=False,
        ).reset_index()

        summary["verified_fv_share"] = (
            summary["verified_fv"]
            / summary["total_fv"].replace(0, pd.NA)
        )

    # Wide reason-code counts across ALL fields (not just fair_value).
    counts = (
        ledger.groupby(["cik", "report_date", "reason_code"])
        .size()
        .unstack(fill_value=0)
        .reset_index()
    )
    summary = summary.merge(counts, on=["cik", "report_date"], how="right")

    # Zero-fill FV buckets for cik-quarters with no fair_value rows
    summary[["n_fields", "n_verified", "verified_fv", "derived_fv",
             "corrected_fv", "total_fv"]] = summary[[
        "n_fields", "n_verified", "verified_fv", "derived_fv",
        "corrected_fv", "total_fv"]].fillna(0)

    summary_path = out_dir / "provenance_ledger_summary.csv"
    summary.to_csv(summary_path, index=False)

    return ledger_path, summary_path


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(argv: list | None = None) -> int:
    """CLI: python -m pipeline.provenance_reverify --cohort [--cheap-only] ..."""
    import argparse

    ap = argparse.ArgumentParser(
        description="Deterministic provenance re-verification -> ledger.")
    ap.add_argument("--ciks", nargs="*", default=None)
    ap.add_argument("--cohort", action="store_true")
    ap.add_argument("--all-rows", action="store_true",
                    help="Run universe-wide (required when neither --cohort nor --ciks given).")
    ap.add_argument("--cheap-only", action="store_true")
    ap.add_argument("--out", default=None,
                    help="output dir (default: data/output)")
    args = ap.parse_args(argv)

    if not args.cohort and not args.ciks and not args.all_rows:
        print(
            "ERROR: scope required. Pass --cohort, --ciks <cik...>, or --all-rows.\n"
            "Running without a scope filter would classify out-of-cohort BDC rows\n"
            "that have src_transforms events but empty src_facts as 'undeclared',\n"
            "which correctly avoids misclassifying them as missing_raw_with_transform.\n"
            "However, an unscoped run is expensive and usually unintended.\n"
            "Pass --all-rows explicitly to confirm a universe-wide run."
        )
        return 2

    from pipeline import config  # noqa: PLC0415

    ciks = args.ciks
    if args.cohort:
        from pipeline.cohort_guard import load_cohort_ciks  # noqa: PLC0415
        ciks = sorted(load_cohort_ciks())

    holdings = config.UNIFIED_HOLDINGS_PARQUET_FILE
    logger.info("Cheap tier over %s (ciks=%s)", holdings.name,
                len(ciks) if ciks else "all")

    cheap = cheap_tier(holdings_path=holdings, ciks=ciks)

    if args.cheap_only:
        tiers = cheap.assign(instance_raw=None, full_status="not_checked")
    else:
        tiers = full_tier(cheap)

    import datetime as _dt  # noqa: PLC0415
    mtime = _dt.datetime.fromtimestamp(holdings.stat().st_mtime).isoformat()

    out_dir = Path(args.out) if args.out else config.OUTPUT_DIR
    lp, sp = build_ledger(tiers, out_dir=out_dir, holdings_mtime=mtime)
    logger.info("Ledger: %s; summary: %s", lp, sp)
    return 0


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)-8s %(message)s")
    sys.exit(main())
