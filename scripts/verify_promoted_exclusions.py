"""Row-level verification of promoted-rule exclusions against source-only blockers.

Phase-1 check for the E1 bucket of parser_mismatch_diagnosis.csv: for each of the
E1 rows (blocking source-only rows on CIKs where Wave-1 promoted row-removal rules
fired), determine WHICH promoted rule's predicate actually removes the row, by
replaying each rule's predicate_sql + quarter scope in DuckDB over the row's raw
bdc_holdings columns (the same columns the production applier sees, minus
unified-derived classification fields -- rules touching those are reported as
not_evaluable_on_raw rather than silently skipped).

Cross-checks:
- FV-twin: does a SURVIVING unified row exist at the same (cik, report_date) with
  the same fair value (exact, <1 USD)? Splits dedup-style exclusions (twin
  survives) from FV removed from the dataset (no twin).
- soi.tsv: does the SEC's own BDC structured dataset render this row as an
  investment-axis row with matching FV at the report date? (Same underlying XBRL,
  independent processing -- confirms visibility to consumers of the official
  dataset, NOT funded-vs-commitment semantics.)

Outputs:
  data/output/verify_promoted_exclusions.csv  (one row per E1 row)
  data/output/verify_promoted_exclusions.md   (per-rule summary)

Usage: python scripts/verify_promoted_exclusions.py [--skip-soi]
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import duckdb  # noqa: E402
import pandas as pd  # noqa: E402

from pipeline.config import OUTPUT_DIR  # noqa: E402

DIAGNOSIS_CSV = OUTPUT_DIR / "parser_mismatch_diagnosis.csv"
RULES_DIR = ROOT / "data" / "overrides" / "agent_investigate_rules"
BDC_HOLDINGS_PARQUET = OUTPUT_DIR / "bdc_holdings.parquet"
UNIFIED_CSV = OUTPUT_DIR / "private_markets_holdings.csv"
SOI_ZIP_DIR = ROOT / "data" / "raw" / "sec_datasets" / "bdc_monthly"
OUT_CSV = OUTPUT_DIR / "verify_promoted_exclusions.csv"
OUT_MD = OUTPUT_DIR / "verify_promoted_exclusions.md"

# Columns a predicate may reference that exist (or are renamed) in raw holdings.
RAW_COLUMN_MAP = {
    "bdc_dimensions_raw": "dimensions_raw",
    "bdc_investment_identifier": "investment_identifier",
}
# Unified-derived columns raw rows do not have; provided as NULL so predicates
# referencing them evaluate false -- the rule is reported not_evaluable_on_raw.
UNIFIED_ONLY_COLUMNS = [
    "issuer_name", "asset_category", "issuer_category", "instrument_description",
]

SOI_ID_COLUMNS = [
    "Investment, Identifier Axis",
    "Investment, Name Axis",
    "Investment Axis",
    "InvestmentsIdentifier",
    "Investment, Issuer Name Axis",
    "Investment Company, Nonconsolidated Subsidiary Axis",
]
# soi.tsv value columns are filer-label-specific (custom concepts keep the
# filer's label, e.g. KKR FV = "Initial fair value of Investment"), so rows are
# matched on VALUES: any numeric cell within $1 of the E1 row's fair value.
SOI_META_COLUMNS = {"adsh", "cik", "name", "ddate", "form", "filed", "period",
                    "inlineurl", "cstm"}


def norm_id(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", (s or "").lower())).strip()


def load_rules(ciks: set[str]) -> list[dict]:
    rules = []
    for cik in sorted(ciks):
        d = RULES_DIR / cik.lstrip("0")
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.json")):
            obj = json.loads(p.read_text(encoding="utf-8-sig"))
            if str(obj.get("rule_type")) not in ("row_exclusion", "dedup"):
                continue
            obj["_cik10"] = cik
            obj["_file"] = p.name
            rules.append(obj)
    return rules


def referenced_unified_only(predicate: str) -> list[str]:
    return [c for c in UNIFIED_ONLY_COLUMNS
            if re.search(rf"\b{c}\b", predicate or "")]


def build_frame(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    diag_path = str(DIAGNOSIS_CSV).replace("'", "''")
    con.execute(f"""
        CREATE TEMP TABLE e1 AS
        SELECT * FROM read_csv('{diag_path}', all_varchar=true, header=true)
        WHERE trace = 'E1_promoted_rule_exclusion_candidate'
    """)
    n = con.execute("SELECT count(*) FROM e1").fetchone()[0]
    print(f"[frame] E1 rows: {n}")

    # Join raw columns on exact (cik, accession, dimensions_raw); a dims key can
    # match multiple raw rows only in degenerate cases -- keep the max-FV match.
    con.execute("""
        CREATE TEMP TABLE frame AS
        SELECT e.cik, e.entity_name, e.report_date, e.period, e.accession_number,
               e.context_id, e.source_row_id, e.mechanism,
               TRY_CAST(e.source_fair_value AS DOUBLE) AS source_fair_value,
               r.investment_identifier, r.dimensions_raw,
               TRY_CAST(r.fair_value AS DOUBLE) AS fair_value,
               TRY_CAST(r.cost AS DOUBLE) AS cost,
               TRY_CAST(r.principal_amount AS DOUBLE) AS principal_amount,
               TRY_CAST(r.shares_held AS DOUBLE) AS shares_held,
               TRY_CAST(r.pct_of_net_assets AS DOUBLE) AS pct_of_net_assets
        FROM e1 e
        LEFT JOIN (
            SELECT lpad(CAST(cik AS VARCHAR), 10, '0') AS cik,
                   CAST(accession_number AS VARCHAR) AS accession_number,
                   CAST(dimensions_raw AS VARCHAR) AS dimensions_raw,
                   CAST(investment_identifier AS VARCHAR) AS investment_identifier,
                   fair_value, cost, principal_amount, shares_held, pct_of_net_assets,
                   ROW_NUMBER() OVER (
                       PARTITION BY lpad(CAST(cik AS VARCHAR), 10, '0'),
                                    CAST(accession_number AS VARCHAR),
                                    CAST(dimensions_raw AS VARCHAR)
                       ORDER BY TRY_CAST(fair_value AS DOUBLE) DESC NULLS LAST) AS rn
            FROM read_parquet(?)
        ) r ON r.cik = e.cik AND r.accession_number = e.accession_number
           AND r.dimensions_raw = e.dimensions_raw AND r.rn = 1
    """, [str(BDC_HOLDINGS_PARQUET)])
    n_unjoined = con.execute(
        "SELECT count(*) FROM frame WHERE investment_identifier IS NULL").fetchone()[0]
    if n_unjoined:
        print(f"[frame] WARNING: {n_unjoined} E1 rows missing raw join")
    return con.execute("SELECT * FROM frame").fetchdf()


def evaluate_rules(con: duckdb.DuckDBPyConnection, frame: pd.DataFrame,
                   rules: list[dict]) -> tuple[pd.DataFrame, list[dict]]:
    con.register("eval_base", frame)
    null_cols = ", ".join(f"CAST(NULL AS VARCHAR) AS {c}" for c in UNIFIED_ONLY_COLUMNS)
    alias_cols = ", ".join(f"{raw} AS {uni}" for uni, raw in RAW_COLUMN_MAP.items())
    con.execute(f"""
        CREATE TEMP TABLE eval_frame AS
        SELECT *, {alias_cols}, {null_cols},
               ROW_NUMBER() OVER () AS _rid
        FROM eval_base
    """)

    frame = con.execute("SELECT * FROM eval_frame").fetchdf()
    frame["explained_by"] = ""
    rule_stats: list[dict] = []

    for rule in rules:
        rid = f"{rule['_cik10']}/{rule['rule_id']}"
        pred = rule.get("predicate_sql") or ""
        quarters = [str(q) for q in (rule.get("scope") or {}).get("quarters", ["all"])]
        scope_sql = "TRUE" if quarters == ["all"] else (
            "report_date IN (" + ",".join(f"'{q}'" for q in quarters) + ")")
        missing = referenced_unified_only(pred)
        stat = {"rule": rid, "rule_type": rule.get("rule_type"),
                "cik": rule["_cik10"], "quarters": ";".join(quarters),
                "not_evaluable_cols": ";".join(missing), "hits": 0, "hit_fv": 0.0,
                "status": "ok"}
        if rule.get("rule_type") == "dedup":
            stat["status"] = "dedup_rule_not_replayed"
            rule_stats.append(stat)
            continue
        if not pred.strip():
            stat["status"] = "no_predicate"
            rule_stats.append(stat)
            continue
        try:
            hits = con.execute(f"""
                SELECT _rid FROM eval_frame
                WHERE cik = '{rule['_cik10']}' AND ({scope_sql}) AND ({pred})
            """).fetchdf()
        except Exception as exc:
            stat["status"] = f"predicate_error: {exc}"
            rule_stats.append(stat)
            continue
        hit_rids = set(hits["_rid"].tolist())
        mask = frame["_rid"].isin(hit_rids)
        stat["hits"] = int(mask.sum())
        stat["hit_fv"] = float(frame.loc[mask, "source_fair_value"].fillna(0).sum())
        if missing:
            stat["status"] = "partial_not_evaluable_on_raw"
        frame.loc[mask & (frame["explained_by"] == ""), "explained_by"] = rid
        frame.loc[mask & (frame["explained_by"] != "") &
                  (~frame["explained_by"].str.contains(rid, regex=False)),
                  "explained_by"] += "|" + rid
        rule_stats.append(stat)
        print(f"[rules] {rid}: {stat['hits']} blocking hits "
              f"({stat['hit_fv']:,.0f} FV) status={stat['status']}")

    frame.loc[frame["explained_by"] == "", "explained_by"] = "(unexplained)"
    return frame, rule_stats


def add_twin_check(con: duckdb.DuckDBPyConnection, frame: pd.DataFrame) -> pd.DataFrame:
    uni_path = str(UNIFIED_CSV).replace("'", "''")
    con.register("verify_frame", frame)
    con.execute(f"""
        CREATE TEMP TABLE uni2 AS
        SELECT CAST(cik AS VARCHAR) AS cik, CAST(report_date AS VARCHAR) AS report_date,
               TRY_CAST(fair_value AS DOUBLE) AS fair_value,
               CAST(bdc_investment_identifier AS VARCHAR) AS bdc_id
        FROM read_csv('{uni_path}', all_varchar=true, header=true)
        WHERE lower(CAST(source AS VARCHAR)) = 'bdc'
          AND CAST(cik AS VARCHAR) IN (SELECT DISTINCT cik FROM verify_frame)
    """)
    out = con.execute("""
        SELECT f.*,
            EXISTS (SELECT 1 FROM uni2 u
                    WHERE u.cik = f.cik AND u.report_date = f.report_date
                      AND ABS(COALESCE(u.fair_value, 1e18) -
                              COALESCE(f.fair_value, -1e18)) < 1.0) AS fv_twin_in_unified
        FROM verify_frame f
    """).fetchdf()
    return out


def add_soi_check(frame: pd.DataFrame) -> pd.DataFrame:
    """Match E1 rows to SEC soi.tsv rows: same accession, ddate=report_date, and
    FV within $1 plus identifier compatibility (either normalized equality or a
    15-char prefix containment)."""
    acc_set = set(frame["accession_number"].dropna().astype(str))
    want: dict[str, list[tuple[str, set[float]]]] = {}
    zips = sorted(SOI_ZIP_DIR.glob("*.zip"))
    t0 = time.time()
    for zp in zips:
        try:
            z = zipfile.ZipFile(zp)
            info = next((i for i in z.infolist() if i.filename == "soi.tsv"), None)
            if info is None or info.file_size == 0:
                continue
            reader = csv.DictReader(io.TextIOWrapper(z.open("soi.tsv"), "utf-8",
                                                     errors="replace"), delimiter="\t")
            n_hit = 0
            for row in reader:
                adsh = row.get("adsh", "")
                if adsh not in acc_set:
                    continue
                nums: set[float] = set()
                for col, val in row.items():
                    if col in SOI_META_COLUMNS or not val:
                        continue
                    v = val.strip()
                    if not v or v.endswith("]"):  # skip axis member text fast
                        continue
                    try:
                        nums.add(float(v))
                    except ValueError:
                        continue
                if not nums:
                    continue
                ident = next((row[c] for c in SOI_ID_COLUMNS if row.get(c)), "")
                key = adsh + "|" + (row.get("ddate") or "")
                want.setdefault(key, []).append((norm_id(ident), nums))
                n_hit += 1
            if n_hit:
                print(f"[soi] {zp.name}: {n_hit} candidate rows "
                      f"({time.time() - t0:.0f}s elapsed)")
        except Exception as exc:
            print(f"[soi] WARNING: failed reading {zp.name}: {exc}")

    def fv_in(nums: set[float], fv: float) -> bool:
        return any(abs(n - fv) < 1.0 for n in nums)

    def match(row) -> str:
        key = str(row["accession_number"]) + "|" + str(row["report_date"])
        cands = want.get(key)
        if not cands:
            return "no_soi_coverage"
        fv = row["fair_value"]
        if fv is None or pd.isna(fv):
            return "soi_absent"
        rid_norm = norm_id(str(row["investment_identifier"] or ""))
        for cand_id, nums in cands:
            if fv_in(nums, fv):
                if (cand_id and rid_norm and
                        (cand_id == rid_norm or cand_id[:15] in rid_norm
                         or rid_norm[:15] in cand_id)):
                    return "soi_confirmed"
        for _cand_id, nums in cands:
            if fv_in(nums, fv):
                return "soi_fv_only"
        return "soi_absent"

    frame["soi_check"] = frame.apply(match, axis=1)
    return frame


def write_outputs(frame: pd.DataFrame, rule_stats: list[dict],
                  rules: list[dict]) -> None:
    frame.drop(columns=["_rid"], errors="ignore").to_csv(OUT_CSV, index=False)

    imp_by_rule = {}
    for r in rules:
        imp = r.get("measured_impact") or {}
        imp_by_rule[f"{r['_cik10']}/{r['rule_id']}"] = sum(
            int(v.get("rows", 0)) for v in imp.values() if isinstance(v, dict))

    lines = ["# Promoted-Rule Exclusion Verification (Phase 1)", ""]
    lines.append(f"E1 rows verified: {len(frame)}")
    lines.append("")
    lines.append("## Per-rule replay")
    lines.append("")
    lines.append("| Rule | Blocking hits | Hit FV | Rule's own removal count | Twin-survives | soi_confirmed | Status |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | --- |")
    for s in rule_stats:
        sub = frame[frame["explained_by"].str.contains(s["rule"], regex=False)]
        twin = int(sub["fv_twin_in_unified"].sum()) if "fv_twin_in_unified" in sub else 0
        soi = int((sub.get("soi_check") == "soi_confirmed").sum()) if "soi_check" in sub else 0
        lines.append(
            f"| {s['rule']} | {s['hits']} | {s['hit_fv']:,.0f} | "
            f"{imp_by_rule.get(s['rule'], '')} | {twin} | {soi} | {s['status']} |")
    lines.append("")
    lines.append("## Row outcomes")
    lines.append("")
    lines.append("| Explained by | Rows | Source FV | Twin-survives | soi_confirmed | soi_fv_only | soi_absent | no_soi_coverage |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for expl, sub in frame.groupby("explained_by"):
        fvsum = float(sub["source_fair_value"].fillna(0).sum())
        twin = int(sub["fv_twin_in_unified"].sum()) if "fv_twin_in_unified" in sub else 0
        cnt = (lambda v: int((sub.get("soi_check") == v).sum())
               if "soi_check" in sub else 0)
        lines.append(f"| {expl} | {len(sub)} | {fvsum:,.0f} | {twin} | "
                     f"{cnt('soi_confirmed')} | {cnt('soi_fv_only')} | "
                     f"{cnt('soi_absent')} | {cnt('no_soi_coverage')} |")
    lines.append("")
    lines.append("## Unexplained rows by CIK")
    lines.append("")
    lines.append("| CIK | Entity | Unexplained rows | Source FV |")
    lines.append("| --- | --- | ---: | ---: |")
    unex = frame[frame["explained_by"] == "(unexplained)"]
    for (cik, name), sub in unex.groupby(["cik", "entity_name"]):
        lines.append(f"| {cik} | {name} | {len(sub)} | "
                     f"{float(sub['source_fair_value'].fillna(0).sum()):,.0f} |")
    lines.append("")
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"[out] wrote {OUT_CSV}")
    print(f"[out] wrote {OUT_MD}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--skip-soi", action="store_true", help="Skip the soi.tsv scan")
    args = ap.parse_args()

    con = duckdb.connect()
    frame = build_frame(con)
    ciks = set(frame["cik"].astype(str))
    rules = load_rules(ciks)
    print(f"[rules] loaded {len(rules)} row-removal rules for {len(ciks)} CIKs")
    frame, rule_stats = evaluate_rules(con, frame, rules)
    frame = add_twin_check(con, frame)
    con.close()
    if args.skip_soi:
        frame["soi_check"] = "skipped"
    else:
        frame = add_soi_check(frame)
    write_outputs(frame, rule_stats, rules)

    print("")
    print("Explained-by distribution:")
    print(frame.groupby("explained_by").size().sort_values(ascending=False).to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
