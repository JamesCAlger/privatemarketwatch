#!/usr/bin/env python3
"""Run HTML extraction engine against all templates and report coverage.

Two comparisons:
  1. Pre-XBRL era (2019-2021): what NEW data the HTML engine unlocks for
     the index (current index has ~0 BDC rows for this era).
  2. XBRL era (2022+): validate HTML extraction against XBRL ground truth
     from ``data/output/bdc_holdings.csv``.

Outputs a summary table to stdout and a CSV at
``data/output/html_extraction_validation.csv`` with per-filing detail.
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path
from typing import Optional

import pandas as pd

from pipeline.html_template import extract_filing_with_template


TEMPLATE_DIR = Path("data/raw/filing_templates")
HTML_DIR = Path("data/raw/filings/bdc_html")
INDEX_CSV = Path("data/output/bdc_filings_index.csv")
XBRL_HOLDINGS_CSV = Path("data/output/bdc_holdings.csv")
OUT_CSV = Path("data/output/html_extraction_validation.csv")


def _load_filing_index() -> pd.DataFrame:
    """Filing metadata keyed by (cik_stripped, accession_stripped)."""
    df = pd.read_csv(INDEX_CSV, dtype=str)
    df["cik_stripped"] = df["cik"].str.lstrip("0").str.zfill(1)
    df["acc_stripped"] = df["accession_number"].str.replace("-", "", regex=False)
    return df[[
        "cik", "cik_stripped", "accession_number", "acc_stripped",
        "entity_name", "form_type", "filing_date", "report_date",
    ]]


def _load_xbrl_baseline() -> pd.DataFrame:
    """Per-(cik, accession) aggregates of the existing XBRL-derived holdings."""
    cols = [
        "cik", "accession_number", "report_date",
        "fair_value", "interest_rate", "maturity_date",
        "principal_amount", "cost",
    ]
    df = pd.read_csv(XBRL_HOLDINGS_CSV, dtype={"cik": str}, usecols=cols)
    # Keep only current-period rows: period == report_date.  bdc_holdings
    # includes comparatives that inflate FV; drop if we ever add back period.
    df["cik_stripped"] = df["cik"].str.lstrip("0").str.zfill(1)
    g = df.groupby(["cik_stripped", "accession_number"]).agg(
        xbrl_rows=("fair_value", "size"),
        xbrl_fv_sum=("fair_value", "sum"),
        xbrl_rate_nonnull=("interest_rate", lambda s: s.notna().sum()),
        xbrl_mat_nonnull=("maturity_date", lambda s: s.notna().sum()),
    ).reset_index()
    g["acc_stripped"] = g["accession_number"].str.replace("-", "", regex=False)
    return g[[
        "cik_stripped", "acc_stripped", "xbrl_rows", "xbrl_fv_sum",
        "xbrl_rate_nonnull", "xbrl_mat_nonnull",
    ]]


def _per_filing_stats(holdings: list[dict]) -> dict:
    """Compute field fill and FV/row stats for a list of extracted holdings."""
    n = len(holdings)
    if n == 0:
        return {
            "rows": 0, "fv_sum": 0.0, "fv_fill": 0.0,
            "rate_fill": 0.0, "mat_fill": 0.0,
            "princ_fill": 0.0, "cost_fill": 0.0,
            "name_fill": 0.0,
        }
    fv_rows = [h for h in holdings if h.get("fair_value") is not None]
    fv_sum = sum(h["fair_value"] for h in fv_rows)
    return {
        "rows": n,
        "fv_sum": fv_sum,
        "fv_fill": len(fv_rows) / n * 100,
        "rate_fill": sum(1 for h in holdings
                         if h.get("interest_rate") is not None) / n * 100,
        "mat_fill": sum(1 for h in holdings
                        if h.get("maturity_date")) / n * 100,
        "princ_fill": sum(1 for h in holdings
                          if h.get("principal_amount") is not None) / n * 100,
        "cost_fill": sum(1 for h in holdings
                         if h.get("cost") is not None) / n * 100,
        "name_fill": sum(1 for h in holdings
                         if h.get("investment_identifier")) / n * 100,
    }


def run_validation() -> pd.DataFrame:
    fidx = _load_filing_index()
    xbrl = _load_xbrl_baseline()

    template_files = sorted(TEMPLATE_DIR.glob("*.json"))
    records: list[dict] = []

    for tpl_path in template_files:
        cik = tpl_path.stem
        try:
            template = json.loads(tpl_path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"[skip] {cik}: bad template {exc}", file=sys.stderr)
            continue

        html_cik_dir = HTML_DIR / cik
        if not html_cik_dir.exists():
            # Try zero-padded fallback
            html_cik_dir = HTML_DIR / cik.zfill(10)
            if not html_cik_dir.exists():
                print(f"[skip] {cik}: no HTML dir", file=sys.stderr)
                continue

        html_files = sorted(html_cik_dir.glob("*.html"))
        cik_fidx = fidx[fidx["cik_stripped"] == cik]

        for html_path in html_files:
            acc_stripped = html_path.stem
            meta_row = cik_fidx[cik_fidx["acc_stripped"] == acc_stripped]
            if meta_row.empty:
                filing_date = "0000-00-00"
                report_date = "0000-00-00"
                form_type = "?"
                entity_name = template.get("entity_name", "")
                accession_number = acc_stripped
            else:
                r = meta_row.iloc[0]
                filing_date = r["filing_date"]
                report_date = r["report_date"]
                form_type = r["form_type"]
                entity_name = r["entity_name"]
                accession_number = r["accession_number"]

            try:
                html = html_path.read_text(encoding="utf-8", errors="replace")
                filing_meta = {
                    "cik": cik,
                    "entity_name": entity_name,
                    "accession_number": accession_number,
                    "form_type": form_type,
                    "filing_date": filing_date,
                    "report_date": report_date,
                }
                holdings, stats = extract_filing_with_template(
                    html, filing_meta, template,
                )
            except Exception as exc:
                print(f"[err] {cik} {acc_stripped}: {exc}", file=sys.stderr)
                traceback.print_exc()
                continue

            row = _per_filing_stats(holdings)
            row.update({
                "cik": cik,
                "entity_name": entity_name,
                "accession_number": accession_number,
                "acc_stripped": acc_stripped,
                "form_type": form_type,
                "filing_date": filing_date,
                "report_date": report_date,
                "year": filing_date[:4] if filing_date else "",
                "variant_id": stats.get("variant_id"),
                "drift_detected": stats.get("drift_detected", False),
                "tables_found": stats.get("tables_found", 0),
            })
            records.append(row)

    df = pd.DataFrame(records)
    if df.empty:
        return df

    # Join XBRL baseline on (cik, acc_stripped)
    df = df.merge(
        xbrl, left_on=["cik", "acc_stripped"],
        right_on=["cik_stripped", "acc_stripped"],
        how="left",
    )
    df = df.drop(columns=["cik_stripped"])
    return df


def _summarize(df: pd.DataFrame) -> None:
    def _era(year: str) -> str:
        if not year or year == "":
            return "unknown"
        if year <= "2021":
            return "pre_XBRL"
        return "XBRL_era"

    df["era"] = df["year"].apply(_era)

    print("=" * 90)
    print("HTML EXTRACTION VALIDATION -- SUMMARY")
    print("=" * 90)
    print()
    print(f"Templates tested: {df['cik'].nunique()}")
    print(f"Filings processed: {len(df)}")
    print(f"Total HTML rows extracted: {df['rows'].sum():,}")
    print(f"Total HTML FV: ${df['fv_sum'].sum()/1e9:,.1f}B")
    print()

    # -- By era --
    print("BY ERA:")
    era_stats = df.groupby("era").agg(
        filings=("rows", "size"),
        rows=("rows", "sum"),
        fv_sum=("fv_sum", "sum"),
        fv_fill=("fv_fill", "mean"),
        rate_fill=("rate_fill", "mean"),
        mat_fill=("mat_fill", "mean"),
        princ_fill=("princ_fill", "mean"),
        name_fill=("name_fill", "mean"),
        drift_pct=("drift_detected",
                   lambda s: s.astype(bool).mean() * 100),
    )
    era_stats["fv_sum"] = era_stats["fv_sum"].apply(lambda x: f"${x/1e9:,.1f}B")
    print(era_stats.to_string())
    print()

    # -- Pre-XBRL coverage uplift --
    pre = df[df["era"] == "pre_XBRL"]
    if not pre.empty:
        print(f"PRE-XBRL (2019-2021) COVERAGE UPLIFT:")
        print(f"  Filings: {len(pre)}")
        print(f"  Rows extracted: {pre['rows'].sum():,}")
        print(f"  FV sum: ${pre['fv_sum'].sum()/1e9:,.1f}B")
        print(f"  Unique CIKs: {pre['cik'].nunique()}")
        print(f"  (Current index has ~313 rows from 1 CIK in this era)")
        print()
        print("  Per-year:")
        by_year = pre.groupby("year").agg(
            filings=("rows", "size"),
            ciks=("cik", "nunique"),
            rows=("rows", "sum"),
            fv_sum=("fv_sum", "sum"),
            avg_fv_fill=("fv_fill", "mean"),
            avg_rate_fill=("rate_fill", "mean"),
        )
        by_year["fv_sum"] = by_year["fv_sum"].apply(lambda x: f"${x/1e9:,.1f}B")
        print(by_year.to_string())
        print()

    # -- XBRL-era validation --
    post = df[df["era"] == "XBRL_era"].copy()
    post = post[post["xbrl_rows"].notna()]
    if not post.empty:
        post["fv_ratio_html_xbrl"] = post["fv_sum"] / post["xbrl_fv_sum"]
        post["row_ratio_html_xbrl"] = post["rows"] / post["xbrl_rows"]
        print(f"XBRL-ERA VALIDATION (HTML vs XBRL ground truth):")
        print(f"  Matched filings: {len(post)}")
        print(f"  HTML total rows: {post['rows'].sum():,}")
        print(f"  XBRL total rows: {int(post['xbrl_rows'].sum()):,}")
        print(f"  HTML total FV:   ${post['fv_sum'].sum()/1e9:,.1f}B")
        print(f"  XBRL total FV:   ${post['xbrl_fv_sum'].sum()/1e9:,.1f}B")
        print(f"  Median HTML/XBRL row ratio: {post['row_ratio_html_xbrl'].median():.2f}")
        print(f"  Median HTML/XBRL FV  ratio: {post['fv_ratio_html_xbrl'].median():.2f}")
        print("  (Ratios ~2.0 expected: HTML extracts both current + comparative")
        print("   periods; XBRL ground truth in bdc_holdings.csv is pre-dedup.)")
        print()
        print("  Per CIK (top 10 by HTML rows):")
        by_cik = post.groupby("cik").agg(
            filings=("rows", "size"),
            html_rows=("rows", "sum"),
            xbrl_rows=("xbrl_rows", "sum"),
            html_fv=("fv_sum", "sum"),
            xbrl_fv=("xbrl_fv_sum", "sum"),
            median_row_ratio=("row_ratio_html_xbrl", "median"),
            median_fv_ratio=("fv_ratio_html_xbrl", "median"),
        ).sort_values("html_rows", ascending=False).head(10)
        by_cik["html_fv"] = by_cik["html_fv"].apply(lambda x: f"${x/1e9:.1f}B")
        by_cik["xbrl_fv"] = by_cik["xbrl_fv"].apply(lambda x: f"${x/1e9:.1f}B")
        print(by_cik.to_string())
        print()

    # -- Extraction failures --
    failures = df[df["rows"] == 0]
    if not failures.empty:
        print(f"EMPTY EXTRACTIONS: {len(failures)} filings produced 0 rows")
        print(failures.groupby("cik").size().sort_values(ascending=False).head(10).to_string())
        print()


def main():
    df = run_validation()
    if df.empty:
        print("No data extracted", file=sys.stderr)
        sys.exit(1)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_CSV, index=False)
    print(f"Saved per-filing detail to {OUT_CSV}")
    print()
    _summarize(df)


if __name__ == "__main__":
    main()
