"""Download BDC primary HTML documents that the filings index knows but the cache lacks.

Owner-authorized network use (2026-09-15). Goes through the audited SEC download
guard (rate-limited EdgarClient). Only filings already present in
data/output/bdc_filings_index.csv are considered; nothing is discovered here.

Usage: python scripts/fetch_missing_html.py --ciks 0001930087 0001901612 [--dry-run]
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

from pipeline import config
from pipeline.bdc_filings import download_html_filing
from pipeline.edgar_client import EdgarClient

INDEX = config.OUTPUT_DIR / "bdc_filings_index.csv"


def missing_rows(ciks: set[str]) -> list[dict]:
    rows = []
    with INDEX.open(newline="", encoding="utf-8-sig") as stream:
        for row in csv.DictReader(stream):
            cik = str(row.get("cik", "")).zfill(10)
            if cik not in ciks:
                continue
            accession = row.get("accession_number") or row.get("accession") or ""
            primary = row.get("primary_document") or row.get("primary_doc") or ""
            if not accession or not primary:
                continue
            nodash = accession.replace("-", "")
            cache = config.BDC_HTML_CACHE_DIR / cik.lstrip("0") / f"{nodash}.html"
            cache_padded = config.BDC_HTML_CACHE_DIR / cik / f"{nodash}.html"
            if cache.is_file() or cache_padded.is_file():
                continue
            rows.append(dict(cik=cik, accession=accession, primary=primary,
                             form=row.get("form_type") or row.get("form") or "",
                             period=row.get("report_date") or ""))
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ciks", nargs="+", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    ciks = {c.zfill(10) for c in args.ciks}
    rows = missing_rows(ciks)
    print(f"{len(rows)} indexed filings lack a cached HTML document", flush=True)
    for r in rows:
        print(f"  {r['cik']} {r['accession']} {r['form']} {r['period']} {r['primary']}", flush=True)
    if args.dry_run or not rows:
        return
    client = EdgarClient()
    ok = 0
    for r in rows:
        path = download_html_filing(client, r["cik"].lstrip("0"), r["accession"], r["primary"],
                                    agent="fetch_missing_html", reason="delivery_gap_cached_html_missing")
        status = "ok" if path else "FAILED"
        ok += bool(path)
        print(f"  {status} {r['accession']} -> {path}", flush=True)
    print(f"downloaded {ok}/{len(rows)}", flush=True)


if __name__ == "__main__":
    main()
