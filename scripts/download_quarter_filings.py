"""Download one quarter's 10-Q/10-K (XBRL instance and primary HTML) for named funds.

NETWORK: calls SEC EDGAR. Run only when the owner has asked for the download.

    python scripts/download_quarter_filings.py --quarter 2026-06-30 --ciks 0001803498 0001812554

Per fund: one submissions request, then the filing's XBRL instance and its primary HTML document,
all through ``EdgarClient`` (rate-limited) and the audited HTML guard. Writes only under
``data/raw/filings``: the two caches, plus ``quarter_downloads/<quarter>.csv`` (the filings found,
in the columns of ``bdc_filings_index.csv``) and ``quarter_downloads/<quarter>.manifest.jsonl``
(download receipts). The published filings index and outputs are not touched; adding the quarter
to a build is a separate step.
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

COLUMNS = ["cik", "entity_name", "accession_number", "form_type", "filing_date", "report_date",
           "primary_document", "xbrl_download_status", "xbrl_local_path"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--quarter", required=True, help="report date, YYYY-MM-DD")
    parser.add_argument("--ciks", nargs="+", required=True)
    args = parser.parse_args(argv)

    from pipeline import bdc_filings
    from pipeline.config import BDC_FILING_FORM_TYPES, BDC_HTML_CACHE_DIR, BDC_XBRL_CACHE_DIR, SEC_DOWNLOAD_LOCK_DIR
    from pipeline.edgar_client import EdgarClient
    from pipeline.sec_download_guard import download_bdc_html

    folder = BDC_HTML_CACHE_DIR.parent / "quarter_downloads"
    folder.mkdir(parents=True, exist_ok=True)
    index_file = folder / (args.quarter + ".csv")
    manifest = folder / (args.quarter + ".manifest.jsonl")
    client = EdgarClient()
    rows, failed = [], 0
    for cik in sorted({"".join(ch for ch in c if ch.isdigit()).zfill(10) for c in args.ciks}):
        data = client.get_company_submissions(cik)
        found: list[dict[str, str]] = []
        bdc_filings._collect_filings(found, cik, data.get("name", ""), data.get("filings", {}).get("recent", {}), "2022-01-01")
        matches = [r for r in found if r["report_date"] == args.quarter and r["form_type"] in BDC_FILING_FORM_TYPES]
        latest = max((r["report_date"] for r in found), default="")
        if not matches:
            print("%s %s: no filing for %s (latest report date on file: %s)" % (cik, data.get("name", ""), args.quarter, latest))
            failed += 1
            continue
        for row in matches:
            stripped, plain = cik.lstrip("0"), row["accession_number"].replace("-", "")
            target = BDC_XBRL_CACHE_DIR / stripped / (plain + ".xml")
            base = "https://www.sec.gov/Archives/edgar/data/%s/%s" % (stripped, plain)
            stem = row["primary_document"].rsplit(".", 1)[0]
            if target.exists() and target.stat().st_size > 1024:
                status = "cached"
            elif stem and (bdc_filings._try_download(client, "%s/%s_htm.xml" % (base, stem), target)
                           or bdc_filings._try_download(client, "%s/%s.xml" % (base, stem), target)):
                status = "downloaded"
            else:
                url = bdc_filings._find_xbrl_in_filing_index(client, stripped, plain, row["accession_number"])
                status = "downloaded" if url and bdc_filings._try_download(client, url, target) else "not_found"
            row.update(xbrl_download_status=status, xbrl_local_path=str(target) if status != "not_found" else "")
            rows.append(row)
            # The guard reads the filing from an index file; give it this run's.
            with index_file.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=COLUMNS)
                writer.writeheader()
                writer.writerows(rows)
            receipt = download_bdc_html(client=client, cik=cik, accession=row["accession_number"],
                                        primary_doc=row["primary_document"], agent="download_quarter_filings",
                                        reason="owner request: quarter %s" % args.quarter,
                                        filings_index_file=index_file, manifest_file=manifest, lock_dir=SEC_DOWNLOAD_LOCK_DIR)
            ok = status != "not_found" and receipt.get("status") in ("cached", "downloaded")
            failed += 0 if ok else 1
            print("%s %s | %s %s filed %s | xbrl %s (%s bytes) | html %s (%s bytes)%s" % (
                cik, row["entity_name"], row["form_type"], row["accession_number"], row["filing_date"], status,
                target.stat().st_size if target.exists() else 0, receipt.get("status"), receipt.get("byte_count"),
                "" if ok else " | " + str(receipt.get("error") or receipt.get("stage"))))
    print("filings: %d, problems: %d, index: %s" % (len(rows), failed, index_file))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
