"""Disposition-trace diagnosis for source-only blocking rows.

For every blocking source-only row in the source reconciliation (source facts
present in cached XBRL, no matching row in private_markets_holdings.csv), trace
WHERE production lost it:

  Stage A (joins, no XML):
    A_in_unified_recon_match_gap  -- row IS in unified output; the reconciliation
                                     matcher failed to pair it (false blocker
                                     candidate, fix the matcher not the parser)
    B_raw_no_fair_value           -- production extracted the context but with no
                                     fair value fact
    C_dropped_aggregate_filter    -- extracted into bdc_holdings, then killed by
                                     the global aggregate-identifier predicate
    D_dropped_comparative         -- extracted, period != report_date (comparative
                                     filter took it)
    E_dropped_raw_to_unified_other-- extracted into bdc_holdings with FV, absent
                                     from unified, no cheap predicate explains it
    F_raw_context_collapsed       -- identifier present in raw for the accession
                                     but under different dimensions (production
                                     within-filing dedupe collapsed contexts)
    G_not_in_raw                  -- production extraction emitted nothing for
                                     this context at all -> Stage B replay

  Stage B (replay, XML): for G rows only, re-parse the cached instance with the
  PRODUCTION functions (_parse_xbrl_contexts / _extract_investment_facts) and
  report the first predicate that killed the context:
    context_absent_in_file / context_not_selected / no_mapped_facts_for_context /
    emitted_then_dropped_postparse / xml_missing / xml_parse_error

Read-only over production artifacts; writes two NEW artifacts:
  data/output/parser_mismatch_diagnosis.csv   (one row per blocking source row)
  data/output/parser_mismatch_diagnosis.md    (mechanism x trace clusters)

Usage: python scripts/diagnose_parser_mismatch.py [--skip-replay] [--max-replay N]
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import duckdb  # noqa: E402
import pandas as pd  # noqa: E402
from lxml import etree  # noqa: E402

from pipeline.bdc_filings import (  # noqa: E402
    _extract_investment_facts,
    _parse_xbrl_contexts,
)
from pipeline.bdc_identifier import _sql_is_bdc_aggregate  # noqa: E402
from pipeline.config import (  # noqa: E402
    BDC_FILINGS_INDEX_FILE,
    OUTPUT_DIR,
    SOURCE_RECONCILIATION_DETAIL_BY_CIK_DIR,
    SOURCE_RECONCILIATION_SOURCE_ONLY_DETAIL_FILE,
)

BDC_HOLDINGS_PARQUET = OUTPUT_DIR / "bdc_holdings.parquet"
UNIFIED_CSV = OUTPUT_DIR / "private_markets_holdings.csv"
OUT_CSV = OUTPUT_DIR / "parser_mismatch_diagnosis.csv"
OUT_MD = OUTPUT_DIR / "parser_mismatch_diagnosis.md"

NORM_MACRO = (
    "CREATE OR REPLACE MACRO norm_id(s) AS "
    "trim(regexp_replace(regexp_replace(lower(COALESCE(s, '')), "
    "'[^a-z0-9]+', ' ', 'g'), ' +', ' ', 'g'))"
)


def build_stage_a(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    t0 = time.time()
    detail_glob = str(SOURCE_RECONCILIATION_DETAIL_BY_CIK_DIR / "*.parquet").replace("'", "''")
    con.execute(NORM_MACRO)

    con.execute(f"""
        CREATE TEMP TABLE blocking AS
        SELECT
            lpad(CAST(cik AS VARCHAR), 10, '0') AS cik,
            CAST(entity_name AS VARCHAR) AS entity_name,
            CAST(report_date AS VARCHAR) AS report_date,
            CAST(period AS VARCHAR) AS period,
            CAST(accession_number AS VARCHAR) AS accession_number,
            CAST(context_id AS VARCHAR) AS context_id,
            CAST(source_row_id AS VARCHAR) AS source_row_id,
            CAST(raw_investment_identifier AS VARCHAR) AS raw_investment_identifier,
            CAST(dimensions_raw AS VARCHAR) AS dimensions_raw,
            CAST(concept_names AS VARCHAR) AS concept_names,
            CAST(source_wrapper_disposition AS VARCHAR) AS source_wrapper_disposition,
            CAST(wrapper_leaf_staging_excluded AS VARCHAR) AS wrapper_leaf_staging_excluded,
            CAST(residual_class AS VARCHAR) AS residual_class,
            TRY_CAST(source_fair_value AS DOUBLE) AS source_fair_value
        FROM read_parquet('{detail_glob}')
        WHERE CAST(status AS VARCHAR) = 'missing_from_pipeline'
          AND lower(CAST(blocking_issue AS VARCHAR)) IN ('true', '1', 'yes')
    """)
    n_blocking = con.execute("SELECT count(*) FROM blocking").fetchone()[0]
    print(f"[stage A] blocking missing_from_pipeline rows: {n_blocking}")

    so_path = str(SOURCE_RECONCILIATION_SOURCE_ONLY_DETAIL_FILE).replace("'", "''")
    con.execute(f"""
        CREATE TEMP TABLE mech AS
        SELECT
            lpad(CAST(cik AS VARCHAR), 10, '0') AS cik,
            CAST(accession_number AS VARCHAR) AS accession_number,
            CAST(source_row_id AS VARCHAR) AS source_row_id,
            CAST(mechanism AS VARCHAR) AS mechanism
        FROM read_csv('{so_path}', all_varchar=true, header=true)
    """)

    con.execute("""
        CREATE TEMP TABLE raw AS
        SELECT
            lpad(CAST(cik AS VARCHAR), 10, '0') AS cik,
            CAST(accession_number AS VARCHAR) AS accession_number,
            CAST(period AS VARCHAR) AS period,
            CAST(investment_identifier AS VARCHAR) AS investment_identifier,
            CAST(dimensions_raw AS VARCHAR) AS dimensions_raw,
            TRY_CAST(fair_value AS DOUBLE) AS fair_value
        FROM read_parquet(?)
        WHERE lpad(CAST(cik AS VARCHAR), 10, '0') IN (SELECT DISTINCT cik FROM blocking)
    """, [str(BDC_HOLDINGS_PARQUET)])
    n_raw = con.execute("SELECT count(*) FROM raw").fetchone()[0]
    print(f"[stage A] raw bdc_holdings rows for blocking CIKs: {n_raw}")

    uni_path = str(UNIFIED_CSV).replace("'", "''")
    con.execute(f"""
        CREATE TEMP TABLE uni AS
        SELECT
            CAST(cik AS VARCHAR) AS cik,
            CAST(accession_number AS VARCHAR) AS accession_number,
            CAST(report_date AS VARCHAR) AS report_date,
            CAST(bdc_investment_identifier AS VARCHAR) AS bdc_investment_identifier,
            CAST(bdc_dimensions_raw AS VARCHAR) AS bdc_dimensions_raw
        FROM read_csv('{uni_path}', all_varchar=true, header=true)
        WHERE lower(CAST(source AS VARCHAR)) = 'bdc'
          AND CAST(cik AS VARCHAR) IN (SELECT DISTINCT cik FROM blocking)
    """)
    n_uni = con.execute("SELECT count(*) FROM uni").fetchone()[0]
    print(f"[stage A] unified BDC rows for blocking CIKs: {n_uni}")

    agg_expr = (
        _sql_is_bdc_aggregate()
        .replace("_lower_id", "lower(COALESCE(t.raw_investment_identifier, ''))")
        .replace("_raw_id", "t.raw_investment_identifier")
    )

    con.execute(f"""
        CREATE TEMP TABLE traced AS
        SELECT
            t.*,
            COALESCE(m.mechanism, 'mechanism_unjoined') AS mechanism,
            EXISTS (SELECT 1 FROM raw r
                    WHERE r.cik = t.cik AND r.accession_number = t.accession_number
                      AND r.dimensions_raw = t.dimensions_raw) AS in_raw_dims,
            EXISTS (SELECT 1 FROM raw r
                    WHERE r.cik = t.cik AND r.accession_number = t.accession_number
                      AND norm_id(r.investment_identifier) = norm_id(t.raw_investment_identifier)
                      AND COALESCE(r.period, '') = COALESCE(t.period, '')) AS in_raw_ident,
            COALESCE((SELECT max(CASE WHEN r.fair_value IS NOT NULL THEN 1 ELSE 0 END)
                      FROM raw r
                      WHERE r.cik = t.cik AND r.accession_number = t.accession_number
                        AND r.dimensions_raw = t.dimensions_raw), 0) = 1 AS raw_has_fv,
            EXISTS (SELECT 1 FROM uni u
                    WHERE u.cik = t.cik AND u.accession_number = t.accession_number
                      AND u.bdc_dimensions_raw = t.dimensions_raw) AS in_uni_dims,
            EXISTS (SELECT 1 FROM uni u
                    WHERE u.cik = t.cik AND u.report_date = t.report_date
                      AND norm_id(u.bdc_investment_identifier) = norm_id(t.raw_investment_identifier)) AS in_uni_ident,
            ({agg_expr}) AS is_aggregate_identifier
        FROM (SELECT b.*, lower(COALESCE(b.raw_investment_identifier, '')) AS lower_id
              FROM blocking b) t
        LEFT JOIN mech m
          ON m.cik = t.cik AND m.accession_number = t.accession_number
         AND m.source_row_id = t.source_row_id
    """)
    # Scope to the residual-classification blocking pool: rows whose final
    # source-only mechanism is blocking_*. The parquet blocking_issue flag is
    # broader (it also covers rows the source-only classifier later documents).
    n_all = con.execute("SELECT count(*) FROM traced").fetchone()[0]
    con.execute("DELETE FROM traced WHERE mechanism NOT LIKE 'blocking%'")
    n_blk = con.execute("SELECT count(*) FROM traced").fetchone()[0]
    print(f"[stage A] scoped to blocking_* mechanisms: {n_blk} of {n_all} rows")

    # Promoted Layer-C exclusion / Layer-B comparative-filter CIKs from the
    # per-rebuild application audit -- candidate cause for raw->unified drops.
    audit_path = OUTPUT_DIR / "agent_fix_application_audit.csv"
    if audit_path.exists():
        ap_str = str(audit_path).replace("'", "''")
        con.execute(f"""
            CREATE TEMP TABLE promoted_excl AS
            SELECT DISTINCT lpad(CAST(cik AS VARCHAR), 10, '0') AS cik
            FROM read_csv('{ap_str}', all_varchar=true, header=true)
            WHERE TRY_CAST(rows_changed AS INTEGER) > 0
              AND CAST(rule_type AS VARCHAR) IN
                  ('row_exclusion', 'dedup', 'comparative_period_filter')
        """)
    else:
        con.execute("CREATE TEMP TABLE promoted_excl (cik VARCHAR)")
    n_excl = con.execute("SELECT count(*) FROM promoted_excl").fetchone()[0]
    print(f"[stage A] CIKs with promoted row-removal rules applied: {n_excl}")

    con.execute("""
        CREATE TEMP TABLE diagnosed AS
        SELECT *,
            CASE
                WHEN in_uni_dims OR in_uni_ident THEN 'A_in_unified_recon_match_gap'
                WHEN in_raw_dims AND NOT raw_has_fv THEN 'B_raw_no_fair_value'
                WHEN in_raw_dims AND is_aggregate_identifier THEN 'C_dropped_aggregate_filter'
                WHEN in_raw_dims AND COALESCE(period, '') <> COALESCE(report_date, '')
                    THEN 'D_dropped_comparative'
                WHEN in_raw_dims AND lower(COALESCE(wrapper_leaf_staging_excluded, ''))
                    IN ('true', '1') THEN 'E0_wrapper_leaf_staging_excluded'
                WHEN in_raw_dims AND cik IN (SELECT cik FROM promoted_excl)
                    THEN 'E1_promoted_rule_exclusion_candidate'
                WHEN in_raw_dims THEN 'E2_dropped_raw_to_unified_unattributed'
                WHEN in_raw_ident THEN 'F_raw_context_collapsed'
                ELSE 'G_not_in_raw'
            END AS trace
        FROM traced
    """)

    df = con.execute("SELECT * FROM diagnosed").fetchdf()
    print(f"[stage A] done in {time.time() - t0:.1f}s")
    return df


def run_stage_b(df: pd.DataFrame, max_replay: int) -> pd.DataFrame:
    """Replay production parsing for G_not_in_raw rows, grouped per accession."""
    g = df[df["trace"] == "G_not_in_raw"]
    df["replay_outcome"] = ""
    if g.empty:
        print("[stage B] no G_not_in_raw rows; replay skipped")
        return df

    idx = pd.read_csv(BDC_FILINGS_INDEX_FILE, dtype=str)
    idx["cik"] = idx["cik"].str.zfill(10)
    path_by_acc: dict[tuple[str, str], str] = {}
    for _, r in idx.iterrows():
        path_by_acc[(r["cik"], str(r.get("accession_number", "")))] = str(
            r.get("xbrl_local_path", "") or ""
        )

    groups = list(g.groupby(["cik", "accession_number"]))
    if len(groups) > max_replay:
        print(f"[stage B] WARNING: {len(groups)} accessions need replay; "
              f"capping at {max_replay} (use --max-replay to raise). "
              f"Uncapped rows get replay_outcome=replay_skipped_cap.")
    outcomes: dict[int, str] = {}
    done = 0
    t0 = time.time()
    for (cik, acc), rows in groups:
        if done >= max_replay:
            for i in rows.index:
                outcomes[i] = "replay_skipped_cap"
            continue
        done += 1
        xml_path = path_by_acc.get((cik, acc), "")
        if not xml_path or not Path(xml_path).exists():
            for i in rows.index:
                outcomes[i] = "xml_missing"
            continue
        try:
            tree = etree.parse(xml_path)
        except Exception:
            for i in rows.index:
                outcomes[i] = "xml_parse_error"
            continue
        contexts = _parse_xbrl_contexts(tree)
        emitted_ctx = {rec["_context_id"] for rec in _extract_investment_facts(tree, contexts)}
        for i, row in rows.iterrows():
            ctx_id = str(row["context_id"] or "")
            info = contexts.get(ctx_id)
            if info is None:
                outcomes[i] = "context_absent_in_file"
            elif not info.get("is_investment"):
                outcomes[i] = "context_not_selected"
            elif ctx_id in emitted_ctx:
                outcomes[i] = "emitted_then_dropped_postparse"
            else:
                outcomes[i] = "no_mapped_facts_for_context"
        if done % 10 == 0:
            print(f"[stage B] replayed {done}/{min(len(groups), max_replay)} accessions "
                  f"({time.time() - t0:.0f}s)")

    df.loc[list(outcomes.keys()), "replay_outcome"] = pd.Series(outcomes)
    print(f"[stage B] replayed {done} accessions in {time.time() - t0:.1f}s")
    return df


def write_outputs(df: pd.DataFrame) -> None:
    out_cols = [
        "cik", "entity_name", "report_date", "period", "accession_number",
        "context_id", "source_row_id", "raw_investment_identifier",
        "dimensions_raw", "concept_names", "source_wrapper_disposition",
        "wrapper_leaf_staging_excluded",
        "mechanism", "residual_class", "source_fair_value",
        "in_raw_dims", "in_raw_ident", "raw_has_fv", "in_uni_dims",
        "in_uni_ident", "is_aggregate_identifier", "trace", "replay_outcome",
    ]
    df[out_cols].to_csv(OUT_CSV, index=False)

    def fv(sub: pd.DataFrame) -> float:
        return float(sub["source_fair_value"].fillna(0).sum())

    lines = ["# Parser Mismatch Disposition-Trace Diagnosis", ""]
    lines.append(f"Blocking source-only rows traced: {len(df)}")
    lines.append("")
    lines.append("## Trace outcomes")
    lines.append("")
    lines.append("| Trace | Rows | CIKs | Source FV |")
    lines.append("| --- | ---: | ---: | ---: |")
    for trace, sub in df.groupby("trace"):
        lines.append(f"| {trace} | {len(sub)} | {sub['cik'].nunique()} | {fv(sub):,.0f} |")
    lines.append("")
    lines.append("## Mechanism x trace")
    lines.append("")
    lines.append("| Mechanism | Trace | Rows | Source FV |")
    lines.append("| --- | --- | ---: | ---: |")
    for (mech, trace), sub in df.groupby(["mechanism", "trace"]):
        lines.append(f"| {mech} | {trace} | {len(sub)} | {fv(sub):,.0f} |")
    lines.append("")
    lines.append("## Replay outcomes (G_not_in_raw only)")
    lines.append("")
    lines.append("| Replay outcome | Rows | CIKs | Source FV |")
    lines.append("| --- | ---: | ---: | ---: |")
    gdf = df[df["trace"] == "G_not_in_raw"]
    if gdf.empty:
        lines.append("| (none) | 0 | 0 | 0 |")
    else:
        for out, sub in gdf.groupby("replay_outcome"):
            lines.append(f"| {out or '(not replayed)'} | {len(sub)} | {sub['cik'].nunique()} | {fv(sub):,.0f} |")
    lines.append("")
    lines.append("## Per-CIK trace profile (top 25 by blocking rows)")
    lines.append("")
    lines.append("| CIK | Entity | Rows | Dominant trace | Dominant replay | Source FV |")
    lines.append("| --- | --- | ---: | --- | --- | ---: |")
    per_cik = df.groupby(["cik", "entity_name"])
    ranked = sorted(per_cik, key=lambda kv: len(kv[1]), reverse=True)[:25]
    for (cik, name), sub in ranked:
        dom_trace = sub["trace"].mode().iloc[0]
        rp = sub.loc[sub["replay_outcome"] != "", "replay_outcome"]
        dom_replay = rp.mode().iloc[0] if not rp.empty else ""
        lines.append(f"| {cik} | {name} | {len(sub)} | {dom_trace} | {dom_replay} | {fv(sub):,.0f} |")
    lines.append("")
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"[out] wrote {OUT_CSV}")
    print(f"[out] wrote {OUT_MD}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--skip-replay", action="store_true",
                    help="Stage A joins only; skip XML replay")
    ap.add_argument("--max-replay", type=int, default=400,
                    help="Max accessions to re-parse in stage B (default 400)")
    args = ap.parse_args()

    con = duckdb.connect()
    df = build_stage_a(con)
    con.close()
    if df.empty:
        print("No blocking rows found; nothing to diagnose.")
        return 0
    if args.skip_replay:
        df["replay_outcome"] = ""
    else:
        df = run_stage_b(df, args.max_replay)
    write_outputs(df)

    print("")
    print("Trace distribution:")
    print(df.groupby("trace").size().to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
