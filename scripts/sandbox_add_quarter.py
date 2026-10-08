"""Add a downloaded quarter's filings to a fund sandbox's per-filing inputs.

A fund sandbox (``scripts/fund_ledger_trial.py``) seeds its inputs from the published outputs, so
it knows no filing newer than those. This adds the filings fetched by
``scripts/download_quarter_filings.py`` to the sandbox's filings index and re-derives, from the
cached files only, the inputs the sandbox stages do not rebuild themselves: parsed holdings, fund
income, derivatives, sector breakdown and position PIK evidence. No network call.

    python scripts/fund_ledger_trial.py --label q2 --ciks <ciks> --until highlights     # seed
    set PM_OUTPUT_DIR=scratch\\fund_sandbox\\q2\\output
    python scripts/sandbox_add_quarter.py --quarter 2026-06-30
    python scripts/fund_ledger_trial.py --label q2 --from highlights --until highlights
    python scripts/refresh_ixbrl_field_status.py --ciks <ciks>
    python scripts/fund_ledger_trial.py --label q2 --from financials

Refuses to run unless ``PM_OUTPUT_DIR`` points inside ``scratch/fund_sandbox``.
"""
from __future__ import annotations

import argparse
import csv
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def add_to_index(index_file: Path, found_file: Path) -> list[dict[str, str]]:
    """Append the found filings of funds already in the index; return the rows added."""
    with index_file.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        columns, existing = list(reader.fieldnames or []), list(reader)
    with found_file.open(encoding="utf-8-sig", newline="") as handle:
        found = list(csv.DictReader(handle))
    funds = {r["cik"].lstrip("0") for r in existing}
    known = {r["accession_number"] for r in existing}
    added = [r for r in found if r["cik"].lstrip("0") in funds and r["accession_number"] not in known
             and r.get("xbrl_download_status") in ("cached", "downloaded")]
    if added:
        with index_file.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(existing + [{c: r.get(c, "") for c in columns} for r in added])
    return added


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--quarter", required=True, help="report date, YYYY-MM-DD")
    args = parser.parse_args(argv)
    target = Path(os.environ.get("PM_OUTPUT_DIR", "")).resolve() if os.environ.get("PM_OUTPUT_DIR") else None
    if target is None or (ROOT / "scratch" / "fund_sandbox").resolve() not in target.parents:
        parser.error("PM_OUTPUT_DIR must point inside scratch/fund_sandbox")

    from pipeline.config import BDC_FILINGS_INDEX_FILE, BDC_HTML_CACHE_DIR

    found_file = BDC_HTML_CACHE_DIR.parent / "quarter_downloads" / (args.quarter + ".csv")
    if not found_file.exists():
        parser.error("no downloaded filings for that quarter: %s" % found_file)
    added = add_to_index(BDC_FILINGS_INDEX_FILE, found_file)
    for row in added:
        print("index + %s %s %s %s" % (row["cik"], row["form_type"], row["accession_number"], row["report_date"]), flush=True)
    with BDC_FILINGS_INDEX_FILE.open(encoding="utf-8-sig", newline="") as handle:
        ciks = sorted({r["cik"].zfill(10) for r in csv.DictReader(handle) if r["report_date"] == args.quarter})
    if not ciks:
        print("no fund in this sandbox has a filing for %s" % args.quarter)
        return 1
    code = subprocess.run([sys.executable, "scripts/rebuild_outputs.py", "--bdc-holdings", "--ciks", *ciks,
                           "--income", "--derivatives", "--sector-breakdown"], cwd=ROOT).returncode
    if code:
        return code
    from pipeline.bdc_position_pik import extract_bdc_position_pik_evidence
    evidence = extract_bdc_position_pik_evidence()
    print("position PIK evidence: %d rows" % len(evidence))

    import duckdb
    con = duckdb.connect()
    print("rows at %s: file | fund | rows" % args.quarter)
    for name, day in (("bdc_holdings.csv", "period"), ("bdc_fund_income.csv", "report_date"),
                      ("bdc_sector_breakdown.csv", "report_date"), ("bdc_position_pik_evidence.csv", "report_date")):
        path = target / name
        if not path.exists():
            print("   %s | missing" % name)
            continue
        reader = "read_csv('%s', header=true, all_varchar=true, sample_size=-1)" % path.as_posix()
        columns = [r[0] for r in con.execute("DESCRIBE SELECT * FROM " + reader).fetchall()]
        day = day if day in columns else ("report_date" if "report_date" in columns else "period")
        for cik, n in con.execute("SELECT lpad(regexp_replace(CAST(cik AS VARCHAR),'[^0-9]','','g'),10,'0'), count(*) FROM %s "
                                  "WHERE CAST(%s AS VARCHAR)[:10]='%s' GROUP BY 1 ORDER BY 1" % (reader, day, args.quarter)).fetchall():
            print("   %s | %s | %d" % (name, cik, n))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
