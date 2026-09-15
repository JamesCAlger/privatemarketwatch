"""E3: cache-only evidence audit of lifecycle/reporting exclusions; never edits eligibility.

E3-v2 (2026-09-15, owner standing waiver): an exclusion with no cached filing
may reach a certified verdict from POSITIVE EDGAR evidence supplied through
``--filing-gaps`` (the scripts/check_filing_gaps.py CSV plus its per-CIK
submissions JSON). Cached companyfacts is the secondary contradiction source.
Absence of evidence never certifies anything: a missing row, a submissions
error, or a CSV row that disagrees with its own submissions JSON stays
``exclusion_unassessable``.

E3-v3 (2026-09-15, owner decision): an investment-FV concept outside
INVESTMENT_TOTAL blocks certification only when it carries at least one fact
whose period end is at or before the excluded quarter (or a fact with no period
end at all). Those facts are recorded in the evidence. A concept whose facts all
postdate the quarter cannot carry evidence about it and no longer blocks.

The v3 register also excludes not_yet_reporting obligations. These require
verified EDGAR absence of a primary filing, irrespective of comparative
investment facts in a later filing. All such facts remain in the evidence.
"""
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
from scripts.run_context_census import EXCLUDED_OBLIGATIONS, INDEX, REGISTER, select_source

INVESTMENT_TOTAL = re.compile(r"^(InvestmentOwnedAtFairValue|InvestmentsAtFairValue|"
    r"InvestmentsFairValueDisclosure|InvestmentCompanyInvestmentsFairValue|InvestmentsAndOtherFinancialInstruments)$")
COMPANYFACTS_DIR = ROOT / "data/raw/companyfacts_cache"
INSTANCES_DIR = ROOT / "data/raw/filings/bdc_xbrl"
# Upper bound matches the register horizon. The lower bound is open so the
# secondary check can see prior-period instants (comparatives in a fund's
# first 10-Q); primary verdicts only ever read totals at the exact quarter.
CF_WINDOW = ("1900-01-01", "2026-03-31")
FILING_GAP_FORMS = ("10-K", "10-K/A", "10-Q", "10-Q/A")
VERDICTS = ("exclusion_contradicted", "exclusion_contradicted_filing_exists", "exclusion_unassessable",
            "no_contradiction_observed", "no_periodic_filing_confirmed")
POLICY = ("No eligibility or threshold edits; ambiguity blocks certification. "
          "no_periodic_filing_confirmed certifies that EDGAR lists no 10-K/10-Q for the quarter and the "
          "entity's first periodic report is later; it is not proof the fund was not investing. "
          "exclusion_contradicted_filing_exists means EDGAR lists a periodic filing for the quarter, so the "
          "no-filing premise fails and the instance must be inventoried before the exclusion can stand. "
          "An unmapped investment-FV companyfacts concept blocks a verdict only when it carries a fact with "
          "period end at or before the quarter (or no period end); those facts are recorded in the evidence.")


def _display(path):
    path = Path(path).resolve()
    return str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)


def unknown_concept_facts(meta):
    """Every fact on an unmapped investment-FV concept: any unit, form or period."""
    facts = []
    for unit, events in meta.get("units", {}).items():
        for event in events:
            facts.append(dict(unit=unit, start=event.get("start"), end=event.get("end"), val=event.get("val"),
                              accn=event.get("accn"), filed=event.get("filed"), form=event.get("form")))
    return sorted(facts, key=lambda f: (f["end"] or "", f["filed"] or "", f["accn"] or ""))


def blocking_unknown_facts(facts_by_concept, quarter):
    """Facts on unmapped concepts that could bear on the quarter: end <= quarter, or no end.

    Only these block certification. A concept whose facts all postdate the
    quarter cannot contradict or certify anything about it.
    """
    blocking = {}
    for concept, facts in facts_by_concept.items():
        hits = [f for f in facts if not f["end"] or f["end"] <= quarter]
        if hits:
            blocking[concept] = hits
    return blocking


def load_filing_gaps(path):
    """Read the EDGAR filing-gap CSV and the per-CIK submissions JSON beside it."""
    path = Path(path).resolve()
    rows = {}
    with path.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            key = (row["cik"].zfill(10), row["quarter"])
            if key in rows:
                raise ValueError("Filing-gap evidence repeats a fund-quarter: " + "/".join(key))
            rows[key] = row
    submissions = {}
    for cik in sorted({key[0] for key in rows}):
        sub_path = path.with_name(cik + ".json")
        if sub_path.exists():
            submissions[cik] = dict(path=sub_path, sha256=sha(sub_path),
                                    data=json.loads(sub_path.read_text(encoding="utf-8-sig")))
    return dict(path=path, sha256=sha(path), rows=rows, submissions=submissions)


def assess_filing_gap(cik, quarter, gaps):
    """Return (verdict or None, evidence) for an exclusion with no selected accession.

    The CSV row is only trusted when it agrees with the submissions JSON it was
    derived from. None means the EDGAR evidence cannot certify or contradict.
    """
    evidence = dict(source_csv=str(gaps["path"]), source_csv_sha256=gaps["sha256"], row=None, reason=None)
    row = gaps["rows"].get((cik, quarter))
    if row is None:
        evidence["reason"] = "no_filing_gap_row"
        return None, evidence
    evidence["row"] = dict(row)
    status = row["status"]
    if status == "submissions_error":
        evidence["reason"] = "submissions_error"
        return None, evidence
    sub = gaps["submissions"].get(cik)
    if sub is None:
        evidence["reason"] = "submissions_json_missing"
        return None, evidence
    evidence.update(submissions_json=str(sub["path"]), submissions_json_sha256=sub["sha256"])
    filings = [f for f in sub["data"].get("filings", []) if f.get("form") in FILING_GAP_FORMS]
    matches = sorted(f["accession"] for f in filings if f.get("report_date") == quarter)
    earliest = min((f["report_date"] for f in filings), default="")
    evidence.update(json_matching_accessions=matches, json_earliest_periodic_report_date=earliest,
                    json_periodic_filings_total=len(filings))
    if (earliest != row["earliest_periodic_report_date"] or str(len(filings)) != row["periodic_filings_total"]
            or bool(matches) != bool(row["matching_accessions"])):
        evidence["reason"] = "csv_json_disagreement"
        return None, evidence
    if status in ("filing_exists_not_indexed", "filing_indexed"):
        if not matches:
            evidence["reason"] = "csv_json_disagreement"
            return None, evidence
        evidence["reason"] = status
        return "exclusion_contradicted_filing_exists", evidence
    if status == "no_filing_for_quarter":
        if not earliest:
            evidence["reason"] = "no_periodic_filings_on_edgar"
            return None, evidence
        if earliest > quarter:
            evidence["reason"] = "earliest_periodic_report_after_quarter"
            return "no_periodic_filing_confirmed", evidence
        evidence["reason"] = "earliest_periodic_report_not_after_quarter"
        return None, evidence
    evidence["reason"] = "unrecognized_status:" + status
    return None, evidence


def run(dest, *, register=REGISTER, index=INDEX, companyfacts_dir=COMPANYFACTS_DIR,
        instances_dir=INSTANCES_DIR, expected=EXCLUDED_OBLIGATIONS, filing_gaps=None, filing_gaps_sha256=None):
    started = time.monotonic()
    dest.mkdir(parents=True, exist_ok=False)
    con = duckdb.connect(config={"threads": 2, "memory_limit": "-1", "temp_directory": str(dest / "temp")})
    try:
        sources = [Path(p) for p in (register, index, Path(__file__),
            ROOT / "pipeline/context_inventory.py", ROOT / "pipeline/bdc_filings.py",
            ROOT / "scripts/run_context_census.py")]
        gaps = None
        if filing_gaps is not None:
            gaps = load_filing_gaps(filing_gaps)
            if filing_gaps_sha256 is not None and gaps["sha256"] != filing_gaps_sha256.lower():
                raise ValueError("Filing-gap evidence sha256 mismatch: expected " + filing_gaps_sha256 +
                                 " observed " + gaps["sha256"])
            sources.append(gaps["path"])
            sources.extend(sub["path"] for sub in gaps["submissions"].values())
        inputs = {_display(p): sha(p) for p in sources}
        with Path(register).open(encoding="utf-8-sig", newline="") as stream:
            obligations = [r for r in csv.DictReader(stream) if r["eligibility_status"] in
                           {"not_yet_investment_operating", "not_yet_reporting"}]
        total = len(obligations)
        if total != expected or len({(r["cik"], r["report_date"]) for r in obligations}) != expected:
            raise ValueError("E3 expected %d distinct lifecycle exclusions" % expected)
        atomic_json(dest / "request.json", dict(experiment="E3", started_utc=now(), pid=os.getpid(),
            input_sha256=inputs, obligations=total, seconds=None, threads=2, memory_limit="unlimited",
            filing_gaps=None if gaps is None else dict(path=str(gaps["path"]), sha256=gaps["sha256"],
                rows=len(gaps["rows"]), submissions_json=len(gaps["submissions"]))))
        ciks = sorted({r["cik"] for r in obligations})
        filings = con.execute("""SELECT cik,report_date,filing_date,accession_number FROM read_csv(?,all_varchar=true)
            WHERE substr(report_date,1,10) BETWEEN '2023-01-01' AND '2026-03-31'
            AND form_type IN ('10-K','10-Q','10-K/A','10-Q/A') AND lpad(cik,10,'0') IN (SELECT unnest(?))""",
            [str(index), ciks]).fetchdf().fillna("").to_dict("records")
        if len(filings) > 5000:
            raise ValueError("Narrow filing-index row bound exceeded")
        con.execute("CREATE TABLE cf(cik VARCHAR,concept VARCHAR,currency VARCHAR,quarter VARCHAR,accession VARCHAR,filed VARCHAR,amount DOUBLE)")
        cf_status = {}
        cf_unknown = {}
        for cik in ciks:
            path = Path(companyfacts_dir) / (cik + ".json")
            status = dict(path=str(path), complete=False, errors=[], unknown_concepts=[],
                          unknown_concept_facts={}, unresolved_total_units=[])
            cf_unknown[cik] = {}
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
                                name = namespace + ":" + concept
                                facts_on_concept = unknown_concept_facts(meta)
                                status["unknown_concepts"].append(name)
                                status["unknown_concept_facts"][name] = dict(
                                    facts=len(facts_on_concept),
                                    earliest_period_end=min((f["end"] for f in facts_on_concept if f["end"]), default=None),
                                    facts_without_period_end=sum(1 for f in facts_on_concept if not f["end"]))
                                cf_unknown[cik][name] = facts_on_concept
                            continue
                        for unit, events in meta.get("units", {}).items():
                            if not re.fullmatch(r"[A-Z]{3}", unit):
                                status["unresolved_total_units"].append(namespace + ":" + concept + ":" + unit)
                                continue
                            con.execute("""INSERT INTO cf SELECT ?,?,?,value->>'end',value->>'accn',
                                value->>'filed',try_cast(value->>'val' AS DOUBLE) FROM json_each(?)
                                WHERE (value->>'start') IS NULL AND (value->>'form') IN ('10-K','10-Q','10-K/A','10-Q/A')
                                AND (value->>'end') BETWEEN ? AND ?""",
                                [cik, namespace + ":" + concept, unit, json.dumps(events), CF_WINDOW[0], CF_WINDOW[1]])
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
        for index_no, obligation in enumerate(obligations, 1):
            cik, quarter = obligation["cik"], obligation["report_date"]
            table = con.execute("SELECT * FROM totals WHERE cik=? AND quarter=?", [cik, quarter])
            names = [d[0] for d in table.description]
            totals = [dict(zip(names, values)) for values in table.fetchall()]
            positives = [r for r in totals if r["distinct_amounts"] == 1 and
                         r["amount"] is not None and math.isfinite(r["amount"]) and r["amount"] > 0]
            reporting_exclusion = obligation["eligibility_status"] == "not_yet_reporting"
            source_obligation = dict(obligation)
            if reporting_exclusion:
                source_obligation["positive_source_accession"] = ""
            elif not source_obligation["positive_source_accession"] and positives:
                source_obligation["positive_source_accession"] = max(positives, key=lambda r: (r["filed"], r["accession"]))["accession"]
            accession, selection, choices = select_source(source_obligation, filings)
            compact = accession.replace("-", "")
            if compact and (len(compact) != 18 or not compact.isdigit()):
                raise ValueError("Invalid selected accession identity")
            source = Path(instances_dir) / str(int(cik)) / (compact + ".xml")
            inventory = scan_instance(source, cik, quarter)
            counts = inventory["counts"]
            full_scope = inventory["source_complete"] and inventory.get("document_period_ends") == [quarter]
            cf = cf_status[cik]
            conflict = any(r["distinct_amounts"] != 1 or r["amount"] is None or
                           not math.isfinite(r["amount"]) for r in totals)
            # Secondary source: any positive investment-total fact at or before
            # the quarter (raw facts, any filing) contradicts "not yet operating".
            prior_count, prior_earliest, prior_max = con.execute("""SELECT count(*),min(quarter),max(amount)
                FROM cf WHERE cik=? AND quarter<=? AND amount>0 AND isfinite(amount)""", [cik, quarter]).fetchone()
            prior_positive = dict(facts=int(prior_count), earliest_period_end=prior_earliest, max_amount=prior_max)
            # E3-v3: an unmapped investment-FV concept blocks only through facts
            # that could bear on this quarter (end <= quarter, or no end).
            unknown_blocking = blocking_unknown_facts(cf_unknown[cik], quarter)
            cf_ok = cf["complete"] and not unknown_blocking and not cf["unresolved_total_units"]
            filing_gap = None
            secondary = "not_applied"
            if reporting_exclusion:
                # A comparative investment total does not establish a primary
                # filing. The index or verified submissions must establish it.
                if choices:
                    verdict = "exclusion_contradicted_filing_exists"
                elif gaps is not None:
                    gap_verdict, filing_gap = assess_filing_gap(cik, quarter, gaps)
                    verdict = gap_verdict or "exclusion_unassessable"
                else:
                    verdict = "exclusion_unassessable"
                secondary = "comparative_facts_retained"
            elif counts["confirmed_position"] or positives:
                verdict = "exclusion_contradicted"
            elif (not full_scope or counts["unresolved"] or not cf["complete"] or
                  unknown_blocking or cf["unresolved_total_units"] or conflict):
                verdict = "exclusion_unassessable"
            else:
                verdict = "no_contradiction_observed"
            if not reporting_exclusion and not accession and gaps is not None:
                gap_verdict, filing_gap = assess_filing_gap(cik, quarter, gaps)
                if gap_verdict == "no_periodic_filing_confirmed":
                    if prior_count:
                        secondary = "contradicted"
                        verdict = "exclusion_contradicted"
                    elif not cf_ok:
                        secondary = "unavailable"
                        filing_gap["reason"] = "companyfacts_secondary_check_unavailable"
                        verdict = "exclusion_unassessable"
                    else:
                        secondary = "clear"
                        verdict = gap_verdict
                elif gap_verdict == "exclusion_contradicted_filing_exists":
                    verdict = gap_verdict
                elif verdict != "exclusion_contradicted":
                    verdict = "exclusion_unassessable"
            key = cik + "_" + quarter
            atomic_json(dest / (key + ".json"), dict(obligation=obligation, accession=accession,
                selection=selection, indexed_choices=choices, inventory=inventory,
                companyfacts=cf, latest_investment_totals=totals, prior_positive_facts=prior_positive,
                unknown_concept_facts_at_or_before_quarter=unknown_blocking,
                filing_gap=filing_gap, secondary_check=secondary, verdict=verdict))
            results.append(dict(cik=cik, quarter=quarter, verdict=verdict, accession=accession,
                eligibility_status=obligation["eligibility_status"], indexed_primary_filings=choices,
                P=counts["confirmed_position"], A=counts["aggregate"], U=counts["unresolved"],
                primary_scope_complete=full_scope, positive_total_observations=len(positives),
                companyfacts_complete=cf["complete"], companyfacts_conflict=conflict,
                unknown_concepts=len(cf["unknown_concepts"]),
                unknown_concept_blocking_facts=sum(len(v) for v in unknown_blocking.values()),
                prior_positive_facts=prior_count, prior_positive_earliest=prior_earliest or "",
                filing_gap_status="" if filing_gap is None or filing_gap["row"] is None else filing_gap["row"]["status"],
                filing_gap_reason="" if filing_gap is None else filing_gap["reason"] or "",
                earliest_periodic_report_date="" if filing_gap is None else filing_gap.get("json_earliest_periodic_report_date", ""),
                secondary_check=secondary,
                evidence_file=key + ".json", evidence_sha256=sha(dest / (key + ".json"))))
            if index_no % 10 == 0 or index_no == total:
                print(f"E3 exclusions {index_no}/{total}; elapsed={time.monotonic()-started:.1f}s", flush=True)
        for path in sources:
            if sha(path) != inputs[_display(path)]:
                raise ValueError("E3 input changed: " + _display(path))
        with (dest / "exclusions.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(results[0]))
            writer.writeheader()
            writer.writerows(results)
        verdicts = {v: sum(r["verdict"] == v for r in results) for v in VERDICTS}
        contradicted = verdicts["exclusion_contradicted"] + verdicts["exclusion_contradicted_filing_exists"]
        atomic_json(dest / "summary.json", dict(experiment="E3", obligations=total, verdicts=verdicts,
            denominator_certifiable=not (contradicted or verdicts["exclusion_unassessable"]),
            input_sha256=inputs, companyfacts_sources=cf_status, completed_utc=now(),
            filing_gaps=None if gaps is None else dict(path=str(gaps["path"]), sha256=gaps["sha256"],
                submissions_json_sha256={cik: sub["sha256"] for cik, sub in gaps["submissions"].items()}),
            secondary_check={s: sum(r["secondary_check"] == s for r in results)
                             for s in ("not_applied", "clear", "contradicted", "unavailable", "comparative_facts_retained")},
            elapsed_seconds=time.monotonic()-started, policy=POLICY))
        atomic_json(dest / "complete.json", {name: sha(dest / name) for name in ("summary.json", "exclusions.csv")})
        print(str(verdicts), flush=True)
    finally:
        con.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--filing-gaps", type=Path, default=None,
                        help="filing_gaps.csv from scripts/check_filing_gaps.py; per-CIK JSON must sit beside it")
    parser.add_argument("--filing-gaps-sha256", default=None,
                        help="expected sha256 of --filing-gaps; the run is refused on mismatch")
    args = parser.parse_args()
    dest = args.output_dir.resolve()
    if not dest.is_relative_to(ROOT / "scratch"):
        parser.error("E3 output must be under scratch/")
    if args.filing_gaps_sha256 and args.filing_gaps is None:
        parser.error("--filing-gaps-sha256 requires --filing-gaps")
    sys.stdout.reconfigure(encoding="ascii", errors="backslashreplace")
    sys.stderr.reconfigure(encoding="ascii", errors="backslashreplace")
    with heavy_lock(candidate_path("t1-runtime-20260910-v5")):
        run(dest, filing_gaps=args.filing_gaps, filing_gaps_sha256=args.filing_gaps_sha256)


if __name__ == "__main__":
    main()
