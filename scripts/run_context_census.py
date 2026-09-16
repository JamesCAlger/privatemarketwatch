"""E1: inventory missing-output obligations using cached primary XML only."""
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
from pipeline.context_inventory import CASH_ONLY_PUBLIC_WORDING, fund_quarter_class, scan_instance
from pipeline.programme.core import atomic_json, now, sha

REGISTER = ROOT / "docs/production_stack/programme_pilot_evidence_2026-09-09/obligations_v3.csv"
ELIGIBLE_OBLIGATIONS = 804
ZERO_OUTPUT_OBLIGATIONS = 25
EXCLUDED_OBLIGATIONS = 106
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


def _source_path(cache_root, cik, accession):
    compact = accession.replace("-", "")
    if not cik.isdigit() or (compact and (len(compact) != 18 or not compact.isdigit())):
        raise ValueError("Invalid selected source identity")
    return Path(cache_root) / str(int(cik)) / (compact + ".xml")


def scan_selected_source(obligation, filings, *, cache_root=None, scanner=None):
    """Read the target-quarter XML, retaining any cover-only amendment evidence.

    A later amendment without a target-quarter instant does not replace the
    original schedule. This only selects among cached filings for the SAME
    report date and form family; it never substitutes a later comparative.
    Missing, invalid, incomplete or financially populated amendments stop the
    search. Narrative changes in an amendment are outside this XML assessment.
    """
    cache_root = cache_root or ROOT / "data/raw/filings/bdc_xbrl"
    scanner = scanner or scan_instance
    cik, quarter = obligation["cik"], obligation["report_date"]
    accession, selection, _ = select_source(obligation, filings)
    exact = {}
    for row in filings:
        if row["cik"].zfill(10) != cik or row["report_date"][:10] != quarter:
            continue
        key = row["accession_number"]
        value = (row["filing_date"], row.get("form_type", ""))
        if key in exact and exact[key] != value:
            raise ValueError("Conflicting filing metadata for one source accession")
        exact[key] = value
    if len(exact) > 20:
        raise ValueError("Target-quarter source selection exceeds 20 distinct filings")
    choices = sorted(exact, key=lambda a: (exact[a][0], a), reverse=True) or [accession]
    trace = []
    result = None
    for index, accession in enumerate(choices):
        form = exact.get(accession, ("", ""))[1]
        result = scanner(_source_path(cache_root, cik, accession), cik, quarter)
        entry = dict(accession=accession, form_type=form, path=result["path"],
            sha256=result["sha256"], source_complete=result["source_complete"],
            document_period_ends=result.get("document_period_ends", []),
            target_instant_contexts=result.get("target_instant_contexts", 0),
            disposition="selected")
        trace.append(entry)
        can_skip = (form in {"10-K/A", "10-Q/A"} and result["source_complete"]
            and result.get("document_period_ends") == [quarter]
            and result.get("target_instant_contexts") == 0)
        next_form = exact[choices[index + 1]][1] if index + 1 < len(choices) else ""
        if can_skip and next_form in {form.removesuffix("/A"), form}:
            entry["disposition"] = "amendment_without_target_instant"
            continue
        break
    if len(trace) > 1:
        selection = "same_quarter_source_after_cover_only_amendment"
        if result.get("document_period_ends") != [quarter]:
            result["source_complete"] = False
            result["errors"].append("Earlier source does not prove the same primary economic quarter")
    result.update(accession=accession, selection=selection, indexed_choices=len(exact),
                  source_selection=trace)
    return result


def verify_source_selection(document, *, cache_root=None):
    """A resumed assessment must still refer to the same cached source bytes.

    This includes skipped amendments: changing one could change which schedule
    should have been selected. Unhashed existing files cannot be safely reused.
    """
    cache_root = cache_root or ROOT / "data/raw/filings/bdc_xbrl"
    trace = document.get("source_selection")
    if trace is None:
        trace = [dict(accession=document["accession"], path=document["path"],
                      sha256=document["sha256"], disposition="selected")]
    if not trace or len(trace) > 20 or len({r["accession"] for r in trace}) != len(trace):
        raise ValueError("Invalid saved source selection trace")
    if (trace[-1]["accession"] != document["accession"] or
            trace[-1]["sha256"] != document["sha256"] or
            trace[-1]["disposition"] != "selected" or
            any(r["disposition"] != "amendment_without_target_instant" for r in trace[:-1])):
        raise ValueError("Saved source selection differs from the selected document")
    for item in trace:
        path = _source_path(cache_root, document["cik"], item["accession"])
        if Path(item["path"]).resolve() != path.resolve():
            raise ValueError("Saved source path does not match its accession")
        expected = item["sha256"]
        if expected:
            if not path.is_file() or sha(path) != expected:
                raise ValueError("Cached source changed since assessment")
        elif path.exists():
            raise ValueError("Unhashed or newly available source requires a fresh assessment")



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
    cash = (Decimal(result["cash_equivalent_total"])
            if result.get("cash_equivalent_status") == "reported" else None)
    status = fund_quarter_class(complete=complete, positions=counts["confirmed_position"],
        unresolved=counts["unresolved"], investment_total=investment_total, cash_equivalent_total=cash)
    result["public_status_wording"] = (
        CASH_ONLY_PUBLIC_WORDING if status == "eligible_no_position_facts" and result.get("cash_only_contexts")
        else "No portfolio position facts disclosed." if status == "eligible_no_position_facts" else "")
    return status


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
    # Register v3 (2026-09-15): 8 of v2's 33 eligible zero-output rows moved to
    # not_yet_reporting on EDGAR no-filing evidence, leaving 25 for E1.
    if (len(obligations) != ZERO_OUTPUT_OBLIGATIONS or
            len({(r["cik"], r["report_date"]) for r in obligations}) != ZERO_OUTPUT_OBLIGATIONS):
        raise ValueError(f"E1 register population changed; expected {ZERO_OUTPUT_OBLIGATIONS} distinct obligations")
    con = duckdb.connect(config={"threads": 2, "memory_limit": "-1"})
    try:
        table = con.execute("""SELECT cik, report_date, filing_date, accession_number, form_type
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
        timeout_seconds=None, memory_limit="unlimited", obligations=len(obligations), input_sha256=inputs,
        selection="latest indexed same-quarter XML, with evidenced cover-only amendment fallback; target instant required"))
    rows = []
    try:
        for index, obligation in enumerate(obligations, 1):
            cik, quarter = obligation["cik"], obligation["report_date"]
            result = scan_selected_source(obligation, filings)
            accession, selection, choices = (result[k] for k in ("accession", "selection", "indexed_choices"))
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
                cash_equivalent_total=result.get("cash_equivalent_total"),
                cash_equivalent_status=result.get("cash_equivalent_status", "unavailable"),
                public_status_wording=result["public_status_wording"],
                errors=" | ".join(result["errors"]), evidence_file=key + ".json")
            rows.append(row)
            print(f"E1 {index}/{len(obligations)} {cik} {quarter}: P={row['P']} A={row['A']} U={row['U']} {status}", flush=True)
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
