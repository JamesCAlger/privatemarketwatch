"""E3: cache-only evidence audit of 98 lifecycle exclusions; never edits eligibility."""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import duckdb
from pipeline.context_inventory import scan_instance
from pipeline.programme.core import atomic_json, now, sha
from pipeline.programme.runner import candidate_path, heavy_lock
from scripts.run_context_census import INDEX, REGISTER, select_source

INVESTMENT_TOTAL = re.compile(r"^(InvestmentOwnedAtFairValue|InvestmentsAtFairValue|"
    r"InvestmentsFairValueDisclosure|InvestmentCompanyInvestmentsFairValue|InvestmentsAndOtherFinancialInstruments)$")


def run(dest):
    started = time.monotonic()
    dest.mkdir(parents=True, exist_ok=False)
    con = duckdb.connect(config={"threads": 2, "memory_limit": "-1", "temp_directory": str(dest / "temp")})
    try:
        inputs = {str(p.relative_to(ROOT)): sha(p) for p in (REGISTER, INDEX, Path(__file__),
            ROOT / "pipeline/context_inventory.py", ROOT / "pipeline/bdc_filings.py",
            ROOT / "scripts/run_context_census.py")}
        with REGISTER.open(encoding="utf-8-sig", newline="") as stream:
            obligations = [r for r in csv.DictReader(stream) if r["eligibility_status"] == "not_yet_investment_operating"]
        if len(obligations) != 98 or len({(r["cik"], r["report_date"]) for r in obligations}) != 98:
            raise ValueError("E3 expected 98 distinct lifecycle exclusions")
        atomic_json(dest / "request.json", dict(experiment="E3", started_utc=now(), pid=os.getpid(),
            input_sha256=inputs, obligations=98, seconds=None, threads=2, memory_limit="unlimited"))
        ciks = sorted({r["cik"] for r in obligations})
        filings = con.execute("""SELECT cik,report_date,filing_date,accession_number FROM read_csv(?,all_varchar=true)
            WHERE substr(report_date,1,10) BETWEEN '2023-01-01' AND '2026-03-31'
            AND form_type IN ('10-K','10-Q','10-K/A','10-Q/A') AND lpad(cik,10,'0') IN (SELECT unnest(?))""",
            [str(INDEX), ciks]).fetchdf().fillna("").to_dict("records")
        if len(filings) > 5000:
            raise ValueError("Narrow filing-index row bound exceeded")
        con.execute("CREATE TABLE cf(cik VARCHAR,concept VARCHAR,currency VARCHAR,quarter VARCHAR,accession VARCHAR,filed VARCHAR,amount DOUBLE)")
        cf_status = {}
        for cik in ciks:
            path = ROOT / "data/raw/companyfacts_cache" / (cik + ".json")
            status = dict(path=str(path), complete=False, errors=[], unknown_concepts=[], unresolved_total_units=[])
            try:
                if path.stat().st_size > 30_000_000:
                    raise ValueError("Companyfacts source exceeds 30 MB bound")
                status["sha256"] = sha(path)
                facts = json.loads(path.read_text(encoding="utf-8-sig"))
                if str(facts.get("cik", "")).zfill(10) != cik:
                    raise ValueError("Companyfacts CIK identity mismatch")
                for namespace, tags in facts.get("facts", {}).items():
                    for concept, meta in tags.items():
                        if not INVESTMENT_TOTAL.fullmatch(concept):
                            if "investment" in concept.lower() and "fairvalue" in concept.lower():
                                status["unknown_concepts"].append(namespace + ":" + concept)
                            continue
                        for unit, events in meta.get("units", {}).items():
                            if not re.fullmatch(r"[A-Z]{3}", unit):
                                status["unresolved_total_units"].append(namespace + ":" + concept + ":" + unit)
                                continue
                            con.execute("""INSERT INTO cf SELECT ?,?,?,value->>'end',value->>'accn',
                                value->>'filed',try_cast(value->>'val' AS DOUBLE) FROM json_each(?)
                                WHERE (value->>'start') IS NULL AND (value->>'form') IN ('10-K','10-Q','10-K/A','10-Q/A')
                                AND (value->>'end') BETWEEN '2023-03-31' AND '2026-03-31'""",
                                [cik, namespace + ":" + concept, unit, json.dumps(events)])
                if sha(path) != status["sha256"]:
                    raise ValueError("Companyfacts source changed during read")
                status["complete"] = True
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                status["errors"].append(type(exc).__name__ + ": " + str(exc))
            cf_status[cik] = status
        # Latest filed observation per concept/currency/quarter. Conflicting
        # amounts at that filing remain unassessable, never selected by order.
        con.execute("""CREATE TABLE totals AS SELECT cik,concept,currency,quarter,
            max(accession) accession,max(filed) filed,count(DISTINCT amount) distinct_amounts,
            min(amount) amount FROM (SELECT * FROM cf QUALIFY filed=max(filed) OVER(
                PARTITION BY cik,concept,currency,quarter)) GROUP BY 1,2,3,4""")
        results = []
        for index, obligation in enumerate(obligations, 1):
            cik, quarter = obligation["cik"], obligation["report_date"]
            table = con.execute("SELECT * FROM totals WHERE cik=? AND quarter=?", [cik, quarter])
            names = [d[0] for d in table.description]
            totals = [dict(zip(names, values)) for values in table.fetchall()]
            positives = [r for r in totals if r["distinct_amounts"] == 1 and
                         r["amount"] is not None and math.isfinite(r["amount"]) and r["amount"] > 0]
            source_obligation = dict(obligation)
            if not source_obligation["positive_source_accession"] and positives:
                source_obligation["positive_source_accession"] = max(positives, key=lambda r: (r["filed"], r["accession"]))["accession"]
            accession, selection, choices = select_source(source_obligation, filings)
            compact = accession.replace("-", "")
            if compact and (len(compact) != 18 or not compact.isdigit()):
                raise ValueError("Invalid selected accession identity")
            source = ROOT / "data/raw/filings/bdc_xbrl" / str(int(cik)) / (compact + ".xml")
            inventory = scan_instance(source, cik, quarter)
            counts = inventory["counts"]
            full_scope = inventory["source_complete"] and inventory.get("document_period_ends") == [quarter]
            cf = cf_status[cik]
            conflict = any(r["distinct_amounts"] != 1 or r["amount"] is None or
                           not math.isfinite(r["amount"]) for r in totals)
            if counts["confirmed_position"] or positives:
                verdict = "exclusion_contradicted"
            elif (not full_scope or counts["unresolved"] or not cf["complete"] or
                  cf["unknown_concepts"] or cf["unresolved_total_units"] or conflict):
                verdict = "exclusion_unassessable"
            else:
                verdict = "no_contradiction_observed"
            key = cik + "_" + quarter
            atomic_json(dest / (key + ".json"), dict(obligation=obligation, accession=accession,
                selection=selection, indexed_choices=choices, inventory=inventory,
                companyfacts=cf, latest_investment_totals=totals, verdict=verdict))
            results.append(dict(cik=cik, quarter=quarter, verdict=verdict, accession=accession,
                P=counts["confirmed_position"], A=counts["aggregate"], U=counts["unresolved"],
                primary_scope_complete=full_scope, positive_total_observations=len(positives),
                companyfacts_complete=cf["complete"], companyfacts_conflict=conflict,
                evidence_file=key + ".json", evidence_sha256=sha(dest / (key + ".json"))))
            if index % 10 == 0 or index == 98:
                print(f"E3 exclusions {index}/98; elapsed={time.monotonic()-started:.1f}s", flush=True)
        for relative, expected in inputs.items():
            if sha(ROOT / relative) != expected:
                raise ValueError("E3 input changed: " + relative)
        with (dest / "exclusions.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(results[0]))
            writer.writeheader()
            writer.writerows(results)
        verdicts = {v: sum(r["verdict"] == v for r in results) for v in
            ("exclusion_contradicted", "exclusion_unassessable", "no_contradiction_observed")}
        atomic_json(dest / "summary.json", dict(experiment="E3", obligations=98, verdicts=verdicts,
            denominator_certifiable=not (verdicts["exclusion_contradicted"] or verdicts["exclusion_unassessable"]),
            input_sha256=inputs, companyfacts_sources=cf_status, completed_utc=now(),
            elapsed_seconds=time.monotonic()-started, policy="No eligibility or threshold edits; ambiguity blocks certification"))
        atomic_json(dest / "complete.json", {name: sha(dest / name) for name in ("summary.json", "exclusions.csv")})
        print(str(verdicts), flush=True)
    finally:
        con.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    dest = args.output_dir.resolve()
    if not dest.is_relative_to(ROOT / "scratch"):
        parser.error("E3 output must be under scratch/")
    sys.stdout.reconfigure(encoding="ascii", errors="backslashreplace")
    sys.stderr.reconfigure(encoding="ascii", errors="backslashreplace")
    with heavy_lock(candidate_path("t1-runtime-20260910-v5")):
        run(dest)


if __name__ == "__main__":
    main()
