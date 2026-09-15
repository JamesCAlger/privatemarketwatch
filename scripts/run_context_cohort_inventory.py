"""E2: bounded cache-only context coverage across all eligible obligations."""
from __future__ import annotations

import argparse
import csv
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import duckdb
from pipeline.context_inventory import scan_instance
from pipeline.programme.core import atomic_json, now, read_json, sha
from pipeline.programme.runner import candidate_path, heavy_lock
from scripts.run_context_census import ELIGIBLE_OBLIGATIONS, INDEX, REGISTER, select_source

RECONCILIATION = ROOT / "data/output/source_reconciliation_detail.csv"


def literal(path):
    return "'" + str(path).replace("\\", "/").replace("'", "''") + "'"


def load_context_records(con, paths):
    """Project only summary fields and process one saved document at a time.

    Reading all rich context/fact payloads as opaque JSON exhausted the 2 GB
    budget. Typed projection excludes facts, and per-document INSERT bounds
    the non-spillable JSON buffers independently of cohort size.
    """
    con.execute("""CREATE TABLE contexts(cik VARCHAR,quarter VARCHAR,accession VARCHAR,
        context_id VARCHAR,source_role VARCHAR,role_reason VARCHAR,recognized BOOLEAN,
        source_fv DOUBLE,currency VARCHAR,fv_status VARCHAR,dimension_pattern VARCHAR)""")
    con.execute("SET preserve_insertion_order=false")
    for index, path in enumerate(paths, 1):
        con.execute("""INSERT INTO contexts SELECT d.cik,d.quarter,d.accession,
            c.context_id,c."role",c.role_reason,c.extractor_recognized,
            TRY_CAST(c.fair_value AS DOUBLE),c.fair_value_currency,c.fair_value_status,
            array_to_string(list_sort(list_transform(c.dimensions,
                x -> x.kind || ':' || regexp_replace(x.axis,'^.*:', ''))),'|')
            FROM read_json(""" + literal(path) + """, maximum_object_size=134217728,
              columns={cik:'VARCHAR',quarter:'VARCHAR',accession:'VARCHAR',
                contexts:'STRUCT(context_id VARCHAR, "role" VARCHAR, role_reason VARCHAR,
                  extractor_recognized BOOLEAN, fair_value VARCHAR, fair_value_currency VARCHAR,
                  fair_value_status VARCHAR, dimensions STRUCT(axis VARCHAR, kind VARCHAR)[])[]'}) d,
              UNNEST(d.contexts) AS entries(c)""")
        if index % 50 == 0 or index == len(paths):
            print(f"E2 context summaries loaded {index}/{len(paths)}", flush=True)


def resume_source_assessments(prior, inputs, obligations):
    """Reuse saved source reads only when identities, counts and hashes verify."""
    previous = read_json(prior / "request.json")
    old_inputs = previous["input_sha256"]
    driver = str(Path(__file__).relative_to(ROOT))
    if set(old_inputs) != set(inputs) or any(old_inputs[k] != inputs[k] for k in inputs if k != driver):
        raise ValueError("Source inputs or collector changed; saved assessments cannot be reused")
    with (prior / "source_assessments.csv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    expected = {(r["cik"], r["report_date"]) for r in obligations}
    if len(expected) != len(obligations) or len(rows) != len(expected) or {(r["cik"], r["quarter"]) for r in rows} != expected:
        raise ValueError("Saved source frame does not cover every distinct eligible obligation")
    for row in rows:
        if row["source_complete"] not in {"True", "False"}:
            raise ValueError("Invalid saved source-completeness flag")
        row["source_complete"] = row["source_complete"] == "True"
        for key in ("P", "A", "U"):
            row[key] = int(row[key])
        path = (prior / "documents" / row["document"]).resolve()
        if not path.is_relative_to((prior / "documents").resolve()) or sha(path) != row["evidence_sha256"]:
            raise ValueError("Saved source document changed")
        document = read_json(path)
        if ((document["cik"], document["quarter"], document["accession"]) !=
                (row["cik"], row["quarter"], row["accession"]) or
                document["counts"] != dict(confirmed_position=row["P"], aggregate=row["A"], unresolved=row["U"]) or
                len(document["contexts"]) != row["P"] + row["A"] + row["U"]):
            raise ValueError("Saved source assessment identity/count mismatch")
    return rows


def aggregate_context_records(con, reconciliation_path, dest):
    """Join loaded contexts and export coverage; also exercised on bounded fixtures."""
    con.execute("""CREATE TABLE reconciliation AS SELECT lpad(cik,10,'0') AS cik,
        substr(period,1,10) AS quarter, accession_number AS accession,context_id,
        count(*) AS result_count,
        count(*) FILTER (WHERE status IN ('matched','value_mismatch','missing_from_pipeline')) AS comparison_count
        FROM read_csv(""" + literal(reconciliation_path) + """,all_varchar=true)
        WHERE lpad(cik,10,'0') IN (SELECT cik FROM sources)
        AND substr(period,1,10) BETWEEN '2023-03-31' AND '2026-03-31' AND context_id IS NOT NULL
        GROUP BY 1,2,3,4""")
    con.execute("""CREATE TABLE assessed AS SELECT c.*,coalesce(r.result_count,0) AS result_count,
        coalesce(r.comparison_count,0) AS comparison_count FROM contexts c LEFT JOIN reconciliation r
        USING(cik,quarter,accession,context_id)""")
    con.execute("""CREATE TABLE context_summary AS SELECT cik,quarter,
        count(*) FILTER (WHERE source_role='confirmed_position' AND result_count>0) AS P_with_result,
        count(*) FILTER (WHERE source_role='confirmed_position' AND comparison_count>0) AS P_with_comparison,
        count(*) FILTER (WHERE source_role IN ('confirmed_position','unresolved') AND NOT recognized) AS unrecognized_P_U,
        count(*) FILTER (WHERE source_role IN ('confirmed_position','unresolved')) AS P_U
        FROM assessed GROUP BY 1,2""")
    con.execute("""CREATE TABLE fund_quarters AS SELECT s.*,coalesce(c.P_with_result,0) AS P_with_result,
        coalesce(c.P_with_comparison,0) AS P_with_comparison,
        c.unrecognized_P_U*1.0/nullif(c.P_U,0) AS unrecognized_context_share
        FROM sources s LEFT JOIN context_summary c USING(cik,quarter)""")
    queries = {
        "fund_quarters.csv": "SELECT * FROM fund_quarters ORDER BY cik,quarter",
        "quarter_coverage.csv": """SELECT quarter,count(*) AS eligible_obligations,
            count(*) FILTER(WHERE source_complete='True') AS complete_sources,
            count(*) FILTER(WHERE P_with_result>0) AS obligations_with_P_result,
            count(*) FILTER(WHERE P_with_comparison>0) AS obligations_with_P_comparison,
            count(*) FILTER(WHERE P_with_result>0)*1.0/count(*) AS reconciliation_coverage,
            sum(CAST(P AS BIGINT)) AS P,sum(CAST(A AS BIGINT)) AS A,sum(CAST(U AS BIGINT)) AS U
            FROM fund_quarters GROUP BY 1 ORDER BY 1""",
        "patterns.csv": """SELECT quarter,dimension_pattern,source_role,role_reason,recognized,currency,
            count(*) AS contexts,count(DISTINCT cik) AS funds,
            count(*) FILTER(WHERE fv_status='reported') AS assessable_fv_contexts,
            sum(source_fv) FILTER(WHERE fv_status='reported') AS signed_context_fv,
            sum(abs(source_fv)) FILTER(WHERE fv_status='reported') AS absolute_context_fv
            FROM assessed GROUP BY ALL ORDER BY quarter,source_role,contexts DESC""",
    }
    for name, query in queries.items():
        con.execute("COPY (" + query + ") TO " + literal(dest / name) + " (HEADER)")
    return list(queries)


def run(dest, resume_sources=None, *, reconciliation=None):
    fresh_reconciliation=reconciliation is not None
    reconciliation=Path(reconciliation) if fresh_reconciliation else RECONCILIATION
    started = time.monotonic()
    dest.mkdir(parents=True, exist_ok=False)
    documents = resume_sources / "documents" if resume_sources else dest / "documents"
    if not resume_sources:
        documents.mkdir()
    con = duckdb.connect(config={"threads": 2, "memory_limit": "-1", "temp_directory": str(dest / "temp")})
    try:
        paths = (REGISTER, INDEX, reconciliation, Path(__file__), ROOT / "scripts/run_context_census.py",
                 ROOT / "pipeline/context_inventory.py", ROOT / "pipeline/bdc_filings.py")
        inputs = {str(p.relative_to(ROOT)): sha(p) for p in paths}
        with REGISTER.open(encoding="utf-8-sig", newline="") as stream:
            obligations = [r for r in csv.DictReader(stream) if r["eligibility_status"].startswith("eligible")]
        if (len(obligations) != ELIGIBLE_OBLIGATIONS or
                len({(r["cik"], r["report_date"]) for r in obligations}) != ELIGIBLE_OBLIGATIONS):
            raise ValueError(f"E2 expected {ELIGIBLE_OBLIGATIONS} distinct eligible obligations")
        atomic_json(dest / "request.json", dict(experiment="E2", started_utc=now(), pid=os.getpid(),
            input_sha256=inputs, seconds=None, obligation_count=len(obligations), memory_limit="unlimited", threads=2))
        filings = con.execute("""SELECT cik,report_date,filing_date,accession_number
            FROM read_csv(?,all_varchar=true) WHERE substr(report_date,1,10) BETWEEN '2023-01-01' AND '2026-03-31'
            AND form_type IN ('10-K','10-Q','10-K/A','10-Q/A')
            AND lpad(cik,10,'0') IN (SELECT unnest(?))""",
            [str(INDEX), sorted({r["cik"] for r in obligations})]).fetchdf().fillna("").to_dict("records")
        if len(filings) > 5000:
            raise ValueError("E2 narrow source-index row bound exceeded")
        summaries = resume_source_assessments(resume_sources, inputs, obligations) if resume_sources else []
        if resume_sources:
            atomic_json(dest / "source_resume.json", dict(parent=str(resume_sources),
                parent_request_sha256=sha(resume_sources / "request.json"),
                source_frame_sha256=sha(resume_sources / "source_assessments.csv"),
                document_root=str(documents), verified_documents=len(summaries),
                scope="Reuse recorded source assessments as frozen evidence; unread sources remain unassessed"))
        # This loop parses source documents. Large cross-context transforms below
        # are DuckDB SQL, including pattern grouping and actual reconciliation joins.
        for index, obligation in enumerate([] if resume_sources else obligations, 1):
            cik, quarter = obligation["cik"], obligation["report_date"]
            accession, selection, choices = select_source(obligation, filings)
            compact = accession.replace("-", "")
            if compact and (len(compact) != 18 or not compact.isdigit()):
                raise ValueError("Invalid selected accession identity")
            source = ROOT / "data/raw/filings/bdc_xbrl" / str(int(cik)) / (compact + ".xml")
            result = scan_instance(source, cik, quarter)
            if result["source_complete"] and not result.get("target_instant_contexts"):
                result["source_complete"] = False
                result["errors"].append("Selected source has no target-quarter instant context")
            result.update(accession=accession, selection=selection, indexed_choices=choices)
            filename = cik + "_" + quarter + ".json"
            atomic_json(documents / filename, result)
            counts = result["counts"]
            summaries.append(dict(cik=cik, quarter=quarter, accession=accession, selection=selection,
                source_complete=result["source_complete"], source_sha256=result["sha256"],
                P=counts["confirmed_position"], A=counts["aggregate"], U=counts["unresolved"],
                errors=" | ".join(result["errors"]), document=filename, evidence_sha256=sha(documents / filename)))
            if index % 10 == 0 or index == len(obligations):
                print(f"E2 cached sources {index}/{len(obligations)}; elapsed={time.monotonic()-started:.1f}s", flush=True)
        with (dest / "source_assessments.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(summaries[0]))
            writer.writeheader()
            writer.writerows(summaries)
        con.execute("CREATE TABLE sources AS SELECT * FROM read_csv(" + literal(dest / "source_assessments.csv") + ",all_varchar=true)")
        load_context_records(con, [documents / r["document"] for r in summaries])
        count = con.execute("SELECT count(*) FROM contexts").fetchone()[0]
        if count > 5_000_000 or count != sum(r["P"] + r["A"] + r["U"] for r in summaries):
            raise ValueError("E2 context count bound or P/A/U conservation failed")
        print("E2 joining actual reconciliation records for " + str(count) + " contexts", flush=True)
        aggregate_outputs = aggregate_context_records(con, reconciliation, dest)
        # The historical ledger has zero results; the repaired extraction must
        # independently produce a result for all 39 known source contexts.
        nexpoint = con.execute("SELECT CAST(P AS BIGINT),P_with_result FROM fund_quarters WHERE cik='0001588272' AND quarter='2023-03-31'").fetchone()
        if nexpoint != (39,39 if fresh_reconciliation else 0):
            raise ValueError("NexPoint source/reconciliation control changed: " + str(nexpoint))
        for relative, expected in inputs.items():
            if sha(ROOT / relative) != expected:
                raise ValueError("E2 input changed: " + relative)
        atomic_json(dest / "summary.json", dict(experiment="E2", obligations=len(obligations), contexts=count,
            source_complete=sum(r["source_complete"] for r in summaries),
            input_sha256=inputs, completed_utc=now(), elapsed_seconds=time.monotonic()-started,
            caveat="Context FV may duplicate positions; separate P/A/U and currency. Not portfolio FV or a roster-accuracy pass."))
        outputs = ["summary.json", "source_assessments.csv", *aggregate_outputs]
        if resume_sources:
            outputs.append("source_resume.json")
        atomic_json(dest / "complete.json", {name: sha(dest / name) for name in outputs})
        print(f"E2 complete; {len(obligations)} obligations retained", flush=True)
    finally:
        con.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--resume-sources", type=Path,
                        help="Reuse and verify a complete saved source-assessment frame; no XML rescan")
    parser.add_argument('--reconciliation-file',type=Path,help='Fresh cached-source comparison; requires the repaired NexPoint control')
    args = parser.parse_args()
    dest = args.output_dir.resolve()
    if not dest.is_relative_to(ROOT / "scratch"):
        parser.error("E2 output must be under scratch/")
    prior = args.resume_sources.resolve() if args.resume_sources else None
    if prior and not prior.is_relative_to(ROOT / "scratch"):
        parser.error("Saved source assessments must be under scratch/")
    sys.stdout.reconfigure(encoding="ascii", errors="backslashreplace")
    sys.stderr.reconfigure(encoding="ascii", errors="backslashreplace")
    with heavy_lock(candidate_path("t1-runtime-20260910-v5")):
        run(dest, prior,reconciliation=args.reconciliation_file)


if __name__ == "__main__":
    main()
