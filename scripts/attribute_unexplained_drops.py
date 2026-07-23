"""Attribute the rule-unexplained E1 blocker rows to deterministic mechanism classes.

Input: the 286 rows in verify_promoted_exclusions.csv with explained_by='(unexplained)'
(Ares ~$14.8B, MidCap ~$2.5B, KKR ~$340M, remnants). All are present in raw
bdc_holdings, absent from unified, unexplained by promoted rules or the global
aggregate predicate. Tests, in priority order:

  A. issuer_subtotal_sum_match  -- row FV equals the sum of >=2 surviving unified
     rows for the same (cik, report_date) whose identifier contains the row's
     extracted company name (issuer-group subtotal line, printed-SOI class).
  B. same_fv_other_quarter      -- a surviving unified row with the same company
     name and the SAME fair value exists at a DIFFERENT report_date
     (stale/comparative duplicate fact).
  C. rollforward_multi_fact     -- row carries only FV/cost concepts and its
     identifier appears with >=3 distinct FVs in the same accession
     (affiliate rollforward-note fact, 1940-Act table class).
  D. unattributed               -- none of the above.

Outputs: data/output/unexplained_drop_attribution.csv / .md
Usage: python scripts/attribute_unexplained_drops.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import duckdb  # noqa: E402
import pandas as pd  # noqa: E402

from pipeline.config import OUTPUT_DIR  # noqa: E402

VERIFY_CSV = OUTPUT_DIR / "verify_promoted_exclusions.csv"
DIAG_CSV = OUTPUT_DIR / "parser_mismatch_diagnosis.csv"
UNIFIED_CSV = OUTPUT_DIR / "private_markets_holdings.csv"
RAW_PARQUET = OUTPUT_DIR / "bdc_holdings.parquet"
OUT_CSV = OUTPUT_DIR / "unexplained_drop_attribution.csv"
OUT_MD = OUTPUT_DIR / "unexplained_drop_attribution.md"

_ENTITY_NAME_RE = re.compile(
    r"([A-Z][\w&.,'/() -]*?(?:Inc\.?|LLC|L\.L\.C\.|Corp\.?|Corporation|"
    r"L\.P\.|LP\b|Ltd\.?|Limited|Co\.|Company|Holdings?|PLC))\s*$",
)


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", (s or "").lower())).strip()


_ENTITY_ANY_RE = re.compile(
    r"([A-Z][\w&.,'/() -]*?(?:Inc\.?|LLC|L\.L\.C\.|Corp\.?|Corporation|"
    r"L\.P\.|LP\b|Ltd\.?|Limited|Co\.|Company|Holdings?|PLC))(?=[\s,|]|$)",
)


def extract_company(identifier: str) -> str:
    """Entity-suffixed company name from the identifier ('' when none found).
    Tries the trailing name first (MidCap 'Industry Company' format), then the
    first suffixed name anywhere (KKR 'Company, Industry N' format)."""
    text = str(identifier or "").strip().rstrip("0123456789 |,")
    m = _ENTITY_NAME_RE.search(text)
    if m:
        return m.group(1).strip()
    m = _ENTITY_ANY_RE.search(text)
    return m.group(1).strip() if m else ""


def main() -> int:
    un = pd.read_csv(VERIFY_CSV, dtype=str)
    un = un[un["explained_by"] == "(unexplained)"].copy()
    diag = pd.read_csv(DIAG_CSV, dtype=str)[
        ["cik", "accession_number", "source_row_id", "concept_names"]
    ]
    un = un.merge(diag, on=["cik", "accession_number", "source_row_id"], how="left")
    un["fv"] = pd.to_numeric(un["fair_value"], errors="coerce")
    un["company"] = un["investment_identifier"].map(extract_company)
    un["company_norm"] = un["company"].map(norm)
    print(f"[attr] unexplained rows: {len(un)}; with extracted company: "
          f"{(un['company'] != '').sum()}")

    con = duckdb.connect()
    uni_path = str(UNIFIED_CSV).replace("'", "''")
    con.execute(f"""
        CREATE TEMP TABLE uni AS
        SELECT CAST(cik AS VARCHAR) AS cik,
               CAST(report_date AS VARCHAR) AS report_date,
               TRY_CAST(fair_value AS DOUBLE) AS fv,
               trim(regexp_replace(regexp_replace(
                   lower(COALESCE(bdc_investment_identifier, '')),
                   '[^a-z0-9]+', ' ', 'g'), ' +', ' ', 'g')) AS ident_norm
        FROM read_csv('{uni_path}', all_varchar=true, header=true)
        WHERE lower(CAST(source AS VARCHAR)) = 'bdc'
          AND CAST(cik AS VARCHAR) IN ('0001278752','0001287750','0001851322',
                                       '0001930679','0001976336')
    """)
    uni = con.execute("SELECT * FROM uni").fetchdf()
    con.close()

    # multi-FV identifiers per accession (rollforward evidence) from raw
    con2 = duckdb.connect()
    multi = con2.execute("""
        SELECT lpad(CAST(cik AS VARCHAR), 10, '0') AS cik,
               CAST(accession_number AS VARCHAR) AS accession_number,
               CAST(investment_identifier AS VARCHAR) AS investment_identifier,
               count(DISTINCT TRY_CAST(fair_value AS DOUBLE)) AS n_fv
        FROM read_parquet(?)
        GROUP BY 1, 2, 3
    """, [str(RAW_PARQUET)]).fetchdf()
    con2.close()
    multi_key = {
        (r.cik, r.accession_number, r.investment_identifier): int(r.n_fv)
        for r in multi.itertuples()
    }

    fv_only = un["concept_names"].fillna("").map(
        lambda c: set(c.split("|")) <= {"InvestmentOwnedAtFairValue",
                                        "InvestmentOwnedAtCost", ""}
    )

    results = []
    for i, row in un.iterrows():
        fv = row["fv"]
        cname = row["company_norm"]
        attribution = "D_unattributed"
        evidence = ""
        if pd.isna(fv) or not cname:
            results.append((attribution, "no fv or company name extracted"))
            continue
        cand = uni[(uni["cik"] == row["cik"]) &
                   uni["ident_norm"].str.contains(re.escape(cname), na=False)]
        same_q = cand[cand["report_date"] == row["report_date"]]
        # A: subtotal = sum of >= 2 surviving same-quarter rows
        if len(same_q) >= 2:
            total = float(same_q["fv"].fillna(0).sum())
            if abs(total - fv) <= max(1000.0, 0.005 * abs(fv)):
                attribution = "A_issuer_subtotal_sum_match"
                evidence = (f"sum of {len(same_q)} surviving rows = {total:,.0f} "
                            f"vs row fv {fv:,.0f}")
        # A2: subtotal sum matches the surviving rows of a DIFFERENT quarter
        # (rollforward begin/end balance tagged with an off-by-one period)
        if attribution == "D_unattributed" and not cand.empty:
            for other_date, grp in cand.groupby("report_date"):
                if other_date == row["report_date"] or len(grp) < 2:
                    continue
                total = float(grp["fv"].fillna(0).sum())
                if abs(total - fv) <= max(1000.0, 0.005 * abs(fv)):
                    attribution = "A2_subtotal_sum_match_other_quarter"
                    evidence = (f"sum of {len(grp)} surviving rows at {other_date} "
                                f"= {total:,.0f} vs row fv {fv:,.0f}")
                    break
        # B: same fv at another quarter (stale/comparative duplicate)
        if attribution == "D_unattributed":
            other_q = cand[(cand["report_date"] != row["report_date"]) &
                           (cand["fv"].sub(fv).abs() < 1.0)]
            if not other_q.empty:
                attribution = "B_same_fv_other_quarter"
                evidence = ("surviving row with identical fv at "
                            + ",".join(sorted(other_q["report_date"].unique())[:3]))
        # C: rollforward-note fact (fv/cost-only concepts, multi-FV identifier)
        if attribution == "D_unattributed" and fv_only.loc[i]:
            n_fv = multi_key.get(
                (row["cik"], row["accession_number"], row["investment_identifier"]), 0)
            if n_fv >= 3:
                attribution = "C_rollforward_multi_fact"
                evidence = f"identifier has {n_fv} distinct FVs in the accession"
        results.append((attribution, evidence))

    un["attribution"] = [r[0] for r in results]
    un["attribution_evidence"] = [r[1] for r in results]

    out_cols = ["cik", "entity_name", "report_date", "accession_number",
                "source_row_id", "investment_identifier", "company", "fv",
                "concept_names", "mechanism", "attribution", "attribution_evidence"]
    un[out_cols].to_csv(OUT_CSV, index=False)

    lines = ["# Unexplained-Drop Attribution", "",
             f"Rows attributed: {len(un)}", "",
             "| CIK | Entity | Attribution | Rows | Source FV |",
             "| --- | --- | --- | ---: | ---: |"]
    for (cik, name, attr), sub in un.groupby(["cik", "entity_name", "attribution"]):
        lines.append(f"| {cik} | {name} | {attr} | {len(sub)} | "
                     f"{sub['fv'].fillna(0).sum():,.0f} |")
    lines.append("")
    lines.append("## Residual D_unattributed samples")
    lines.append("")
    for _, r in un[un["attribution"] == "D_unattributed"].nlargest(15, "fv").iterrows():
        lines.append(f"- {r['cik']} {r['report_date']} fv={r['fv']:,.0f} : "
                     f"{str(r['investment_identifier'])[:100]}")
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"[attr] wrote {OUT_CSV}")
    print(f"[attr] wrote {OUT_MD}")
    print()
    print(un.groupby(["cik", "attribution"]).agg(
        rows=("attribution", "size"), fv=("fv", "sum")).to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
