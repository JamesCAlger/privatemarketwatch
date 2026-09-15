"""Check EDGAR for filings covering cohort fund-quarters that have no cached filing.

Owner-authorized standing waiver (2026-09-15): for eligible or excluded
fund-quarters whose cached filings index has no 10-K/10-Q, ask the SEC
submissions API whether such a filing exists. This script only READS the
submissions JSON (rate-limited EdgarClient) and writes a CSV report; it does not
download instances or change any production output. Cached companyfacts remain
a secondary source and are not consulted here.

Usage:
  python -m scripts.check_filing_gaps --gaps <csv with cik,quarter> --out <dir>
  python -m scripts.check_filing_gaps --from-evidence --out <dir>   # e3-v1 + e1-v2 gaps
"""
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from pipeline import config
from pipeline.edgar_client import EdgarClient

SCRATCH = Path("scratch/2026-09-12_programme_e0")
INDEX = config.OUTPUT_DIR / "bdc_filings_index.csv"
FORMS = {"10-K", "10-K/A", "10-Q", "10-Q/A"}


def gaps_from_evidence() -> list[tuple[str, str]]:
    rows: set[tuple[str, str]] = set()
    with (SCRATCH / "e3-v1/exclusions.csv").open(newline="", encoding="utf-8-sig") as s:
        for r in csv.DictReader(s):
            if r["verdict"] == "exclusion_unassessable" and not r["accession"]:
                rows.add((r["cik"].zfill(10), r["quarter"]))
    with (SCRATCH / "e1-v2/fund_quarters.csv").open(newline="", encoding="utf-8-sig") as s:
        for r in csv.DictReader(s):
            if r["classification"] == "source_unavailable":
                rows.add((r["cik"].zfill(10), r["report_date"]))
    return sorted(rows)


def indexed(cik: str) -> set[str]:
    out = set()
    with INDEX.open(newline="", encoding="utf-8-sig") as s:
        for r in csv.DictReader(s):
            if r["cik"].zfill(10) == cik:
                out.add(r["accession_number"])
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--gaps")
    p.add_argument("--from-evidence", action="store_true")
    p.add_argument("--out", required=True)
    a = p.parse_args()
    if a.from_evidence:
        gaps = gaps_from_evidence()
    else:
        with open(a.gaps, newline="", encoding="utf-8-sig") as s:
            gaps = sorted({(r["cik"].zfill(10), r["quarter"]) for r in csv.DictReader(s)})
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    client = EdgarClient()
    submissions: dict[str, dict] = {}
    report = []
    for cik in sorted({c for c, _ in gaps}):
        try:
            data = client.get_company_submissions(cik)
        except Exception as exc:  # noqa: BLE001
            print(f"{cik}: submissions failed: {exc}", flush=True)
            submissions[cik] = {"error": str(exc)}
            continue
        recent = data.get("filings", {}).get("recent", {})
        filings = []
        for j, form in enumerate(recent.get("form", [])):
            if form in FORMS:
                filings.append(dict(form=form, accession=recent["accessionNumber"][j],
                                    filing_date=recent["filingDate"][j],
                                    report_date=recent["reportDate"][j],
                                    primary=recent["primaryDocument"][j]))
        for page in data.get("filings", {}).get("files", []):
            try:
                pd_ = client.get_json("https://data.sec.gov/submissions/" + page["name"])
            except Exception:  # noqa: BLE001
                continue
            for j, form in enumerate(pd_.get("form", [])):
                if form in FORMS:
                    filings.append(dict(form=form, accession=pd_["accessionNumber"][j],
                                        filing_date=pd_["filingDate"][j],
                                        report_date=pd_["reportDate"][j],
                                        primary=pd_["primaryDocument"][j]))
        submissions[cik] = dict(name=data.get("name"), filings=filings)
        (out / f"{cik}.json").write_text(json.dumps(submissions[cik], indent=1), encoding="utf-8")
    for cik, quarter in gaps:
        sub = submissions.get(cik, {})
        filings = sub.get("filings", [])
        known = indexed(cik)
        matches = [f for f in filings if f["report_date"] == quarter]
        earliest = min((f["report_date"] for f in filings), default="")
        status = ("submissions_error" if "error" in sub else
                  "filing_exists_not_indexed" if matches and not any(f["accession"] in known for f in matches) else
                  "filing_indexed" if matches else
                  "no_filing_for_quarter")
        report.append(dict(cik=cik, entity=sub.get("name", ""), quarter=quarter, status=status,
                           matching_accessions=";".join(f["accession"] + ":" + f["form"] for f in matches),
                           earliest_periodic_report_date=earliest,
                           periodic_filings_total=len(filings)))
        print(f"{cik} {quarter} {status} {report[-1]['matching_accessions']} earliest={earliest}", flush=True)
    with (out / "filing_gaps.csv").open("w", newline="", encoding="utf-8") as s:
        w = csv.DictWriter(s, fieldnames=list(report[0].keys()))
        w.writeheader()
        w.writerows(report)
    summary = {}
    for r in report:
        summary[r["status"]] = summary.get(r["status"], 0) + 1
    (out / "summary.json").write_text(json.dumps(dict(
        checked_utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        fund_quarters=len(report), statuses=summary), indent=2), encoding="utf-8")
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
