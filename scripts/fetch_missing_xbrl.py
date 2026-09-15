"""Re-download XBRL instances for indexed filings whose cached file is missing.

Owner-authorized network use (2026-09-15). Uses the pipeline's own XBRL
downloader on the FULL filings index so other rows are preserved; only the
named accessions have their download status cleared and retried.

Usage: python -m scripts.fetch_missing_xbrl --accessions 0001193125-24-063364 [--dry-run]
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from pipeline import config
from pipeline.bdc_filings import _download_xbrl_instances
from pipeline.edgar_client import EdgarClient


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--accessions", nargs="+", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    index = pd.read_csv(config.BDC_FILINGS_INDEX_FILE, dtype=str)
    targets = index["accession_number"].isin(set(args.accessions))
    print(f"{int(targets.sum())} index rows match", flush=True)
    for _, row in index[targets].iterrows():
        path = row.get("xbrl_local_path")
        path = "" if path is None or (isinstance(path, float) and pd.isna(path)) else str(path)
        exists = bool(path) and Path(path).is_file()
        print(f"  {row['cik']} {row['accession_number']} {row['form_type']} {row['report_date']} "
              f"status={row.get('xbrl_download_status')} file_exists={exists}", flush=True)
    if args.dry_run:
        return
    index.loc[targets, "xbrl_download_status"] = None
    index.loc[targets, "xbrl_local_path"] = None
    updated = _download_xbrl_instances(EdgarClient(), index)
    for _, row in updated[updated["accession_number"].isin(set(args.accessions))].iterrows():
        print(f"  -> {row['accession_number']} {row['xbrl_download_status']} {row['xbrl_local_path']}", flush=True)


if __name__ == "__main__":
    main()
