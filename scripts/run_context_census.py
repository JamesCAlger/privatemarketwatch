"""E1: inventory the 33 missing-output obligations using cached primary XML only."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from decimal import Decimal
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import duckdb
from pipeline.context_inventory import fund_quarter_class, scan_instance
from pipeline.programme.core import atomic_json, now, sha

REGISTER = ROOT / "docs/production_stack/programme_pilot_evidence_2026-09-09/obligations_v2.csv"
INDEX = ROOT / "data/output/bdc_filings_index.csv"


def select_source(obligation, filings):
    """Prefer the latest primary filing for the economic quarter, retain provenance."""
    exact = [r for r in filings if r["cik"].zfill(10) == obligation["cik"] and
             r["report_date"][:10] == obligation["report_date"]]
    if exact:
        selected = max(exact, key=lambda r: (r["filing_date"], r["accession_number"]))
        return selected["accession_number"], "latest_indexed_primary_for_quarter", len(exact)
    accession = obligation["positive_source_accession"]
    return accession, "companyfacts_accession_fallback" if accession else "no_selected_accession", 0


def classify_selected_source(result, investment_total):
    """Comparative totals prove investment activity, not a complete position absence."""
    counts = result["counts"]
    complete = result["source_complete"]
    if complete and not result.get("target_instant_contexts"):
        complete = False
        result["errors"].append("Selected source has no instant context for target economic quarter")
    if (complete and not counts["confirmed_position"] and not counts["unresolved"] and
            result.get("document_period_ends") != [result["quarter"]]):
        complete = False
        result["errors"].append("Comparative-only or undated source cannot certify absence; primary-quarter source scope unverified")
    result["assessment_complete"] = complete
    return fund_quarter_class(complete=complete, positions=counts["confirmed_position"],
                             unresolved=counts["unresolved"], investment_total=investment_total)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="ascii", errors="backslashreplace")
    sys.stderr.reconfigure(encoding="ascii", errors="backslashreplace")
    dest = args.output_dir.resolve()
    if not dest.is_relative_to(ROOT / "scratch"):
        parser.error("Census output must be under scratch/")
    dest.mkdir(parents=True, exist_ok=False)
    inputs = {str(p.relative_to(ROOT)): sha(p) for p in
              (REGISTER, INDEX, Path(__file__), ROOT / "pipeline/context_inventory.py", ROOT / "pipeline/bdc_filings.py")}
    with REGISTER.open(encoding="utf-8-sig", newline="") as stream:
        obligations = [r for r in csv.DictReader(stream) if
            r["eligibility_status"].startswith("eligible") and int(r["holdings_rows"]) == 0]
    if len(obligations) != 33:
        raise ValueError("E1 register population changed; expected 33")
    con = duckdb.connect(config={"threads": 2, "memory_limit": "-1"})
    try:
        table = con.execute("""SELECT cik, report_date, filing_date, accession_number
            FROM read_csv(?, all_varchar=true) WHERE report_date >= '2023-01-01'
            AND report_date <= '2026-03-31' AND form_type IN ('10-K','10-Q','10-K/A','10-Q/A')
            AND lpad(cik,10,'0') IN (SELECT unnest(?))""",
            [str(INDEX), sorted({r["cik"] for r in obligations})])
        filings = table.fetchdf().fillna("").to_dict("records")
    finally:
        con.close()
    if len(filings) > 5000:
        raise ValueError("E1 narrow filing-index row bound exceeded")
    atomic_json(dest / "request.json", dict(experiment="E1", started_utc=now(), pid=os.getpid(),
        timeout_seconds=None, memory_limit="unlimited", obligations=33, input_sha256=inputs,
        selection="latest indexed primary for target quarter, else positive-companyfacts accession; target instant required"))
    rows = []
    try:
        for index, obligation in enumerate(obligations, 1):
            cik, quarter = obligation["cik"], obligation["report_date"]
            accession, selection, choices = select_source(obligation, filings)
            if accession and not (len(accession.replace("-", "")) == 18 and accession.replace("-", "").isdigit()):
                raise ValueError("Invalid source accession identity")
            source = ROOT / "data/raw/filings/bdc_xbrl" / str(int(cik)) / (accession.replace("-", "") + ".xml")
            result = scan_instance(source, cik, quarter)
            total = Decimal(obligation["positive_investment_amount"]) if obligation["positive_investment_amount"] else None
            counts = result["counts"]
            status = classify_selected_source(result, total)
            result.update(accession=accession, selection=selection, indexed_choices=choices, classification=status)
            key = cik + "_" + quarter
            atomic_json(dest / (key + ".json"), result)
            row = dict(cik=cik, report_date=quarter, accession=accession, selection=selection, indexed_choices=choices,
                source_complete=result["source_complete"], assessment_complete=result["assessment_complete"], source_sha256=result["sha256"],
                P=counts["confirmed_position"], A=counts["aggregate"], U=counts["unresolved"],
                unrecognized_P=result["unrecognized_position_contexts"], classification=status,
                positive_investment_amount=obligation["positive_investment_amount"],
                errors=" | ".join(result["errors"]), evidence_file=key + ".json")
            rows.append(row)
            print(f"E1 {index}/33 {cik} {quarter}: P={row['P']} A={row['A']} U={row['U']} {status}", flush=True)
        for relative, expected in inputs.items():
            if sha(ROOT / relative) != expected:
                raise ValueError("Census input changed: " + relative)
        with (dest / "fund_quarters.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        summary = dict(experiment="E1", obligations=len(rows), classifications=dict(Counter(r["classification"] for r in rows)),
                       input_sha256=inputs, completed_utc=now(), policy="diagnostic; unresolved exposure is not excused")
        atomic_json(dest / "summary.json", summary)
        atomic_json(dest / "complete.json", dict(summary_sha256=sha(dest / "summary.json"),
                    table_sha256=sha(dest / "fund_quarters.csv"),
                    evidence_sha256={r["evidence_file"]: sha(dest / r["evidence_file"]) for r in rows}))
        print(str(summary["classifications"]), flush=True)
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
