"""Audited opt-in downloader for missing BDC filing HTML.

This script is the approved terminal entry point for agent workflows that need
missing BDC HTML evidence. It only downloads accessions already present in the
BDC filings index and records every attempt in the SEC download manifest.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline import config
from pipeline.edgar_client import EdgarClient
from pipeline.sec_download_guard import (
    SecDownloadError,
    bdc_html_cache_path,
    download_bdc_html,
    normalize_accession,
    normalize_cik,
)


def _load_targets(cik: str, accessions: list[str], missing: bool) -> list[dict[str, str]]:
    cik_norm = normalize_cik(cik)
    if not cik_norm:
        raise SystemExit("--cik is required")
    if not config.BDC_FILINGS_INDEX_FILE.exists():
        raise SystemExit(f"Missing filings index: {config.BDC_FILINGS_INDEX_FILE}")

    wanted = {normalize_accession(acc) for acc in accessions}
    rows: list[dict[str, str]] = []
    with config.BDC_FILINGS_INDEX_FILE.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            row_cik = normalize_cik(row.get("cik", ""))
            if row_cik != cik_norm:
                continue
            try:
                row_acc = normalize_accession(row.get("accession_number", ""))
            except SecDownloadError:
                continue
            if wanted and row_acc not in wanted:
                continue
            if missing:
                path = bdc_html_cache_path(row_cik, row_acc)
                if path.exists() and path.stat().st_size >= 1024:
                    continue
            rows.append({k: (v or "") for k, v in row.items()})

    rows.sort(
        key=lambda row: (
            row.get("report_date", ""),
            row.get("filing_date", ""),
            row.get("accession_number", ""),
        ),
        reverse=True,
    )
    return rows


def _target_summary(row: dict[str, str]) -> dict[str, Any]:
    cik = normalize_cik(row.get("cik", ""))
    accession = normalize_accession(row.get("accession_number", ""))
    path = bdc_html_cache_path(cik, accession)
    cached = path.exists() and path.stat().st_size >= 1024
    return {
        "cik": cik,
        "accession_number": accession,
        "form_type": row.get("form_type", ""),
        "report_date": row.get("report_date", ""),
        "filing_date": row.get("filing_date", ""),
        "primary_document": row.get("primary_document", ""),
        "cached": cached,
        "cache_path": str(path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download missing BDC HTML through the audited SEC guard.",
    )
    parser.add_argument("--cik", required=True, help="BDC CIK to inspect/download")
    parser.add_argument(
        "--accession",
        action="append",
        default=[],
        help="Specific accession to download. May be repeated.",
    )
    parser.add_argument(
        "--missing",
        action="store_true",
        help="Download missing indexed HTML filings for the CIK, up to --max-downloads.",
    )
    parser.add_argument(
        "--max-downloads",
        type=int,
        default=10,
        help="Hard cap per run. Default: 10.",
    )
    parser.add_argument("--agent", default="", help="Agent/session name for audit receipts")
    parser.add_argument(
        "--reason",
        default="wrapper_evidence",
        help="Reason stored in the audit manifest.",
    )
    parser.add_argument("--dry-run", action="store_true", help="List targets without downloading")
    args = parser.parse_args()

    if args.max_downloads < 1:
        raise SystemExit("--max-downloads must be at least 1")
    if not args.accession and not args.missing:
        raise SystemExit("Provide --accession or --missing")

    rows = _load_targets(args.cik, args.accession, args.missing)
    if args.accession:
        found = {normalize_accession(row.get("accession_number", "")) for row in rows}
        missing_accessions = [acc for acc in args.accession if normalize_accession(acc) not in found]
        if missing_accessions:
            raise SystemExit(
                "Accessions not found for this CIK in bdc_filings_index.csv: "
                + ", ".join(missing_accessions)
            )

    if len(rows) > args.max_downloads:
        rows = rows[: args.max_downloads]

    if args.dry_run:
        for row in rows:
            print(json.dumps(_target_summary(row), sort_keys=True))
        print(json.dumps({"dry_run": True, "target_count": len(rows)}, sort_keys=True))
        return 0

    client = EdgarClient()
    failed = 0
    for row in rows:
        record = download_bdc_html(
            client=client,
            cik=row.get("cik", ""),
            accession=row.get("accession_number", ""),
            primary_doc=row.get("primary_document", ""),
            agent=args.agent,
            reason=args.reason,
        )
        if record.get("status") == "failed":
            failed += 1
        print(json.dumps(record, sort_keys=True))

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
