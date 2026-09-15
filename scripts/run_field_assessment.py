"""E4: numeric and categorical source assessment of sealed holdings."""
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
from pipeline.field_assessment import FIELDS, MONEY, POLICY_VERSION, comparison_sql, read_field_document
from pipeline import categorical_field_assessment as categorical
from pipeline.programme import artifacts
from pipeline.programme.core import atomic_json, now, read_json, read_stage, sha
from pipeline.programme.runner import candidate_path, heavy_lock
from pipeline.provenance_reverify import CHEAP_FIELDS, _field_sql
from scripts.run_context_cohort_inventory import load_context_records, literal, RECONCILIATION
from scripts.run_context_census import REGISTER

CANDIDATE = candidate_path("t1-runtime-20260910-v5")
ATTEMPT = CANDIDATE / "attempts/identity-01"
E2 = ROOT / "scratch/2026-09-12_programme_e0/e2-recovery-v2"


def assemble_reference(con):
    """Keep selected-source references and supplemental published anchors apart."""
    con.execute("""CREATE TABLE candidate_keys AS SELECT DISTINCT lpad(cik,10,'0') AS cik,
      CAST(report_date AS VARCHAR)[:10] AS quarter,accession_number AS accession,
      src_context_id AS context_id FROM candidate
      WHERE nullif(src_context_id,'') IS NOT NULL AND nullif(accession_number,'') IS NOT NULL""")
    con.execute("""CREATE TABLE reference_contexts AS
      SELECT c.cik,c.quarter,c.accession,c.context_id,c.source_role,c.source_fv,c.currency,
        CAST(s.source_complete AS BOOLEAN) AS source_complete,'selected_source_roster' AS reference_origin
      FROM contexts c JOIN sources s USING(cik,quarter,accession)
      WHERE c.source_role='confirmed_position'
      UNION ALL
      SELECT k.*, 'unresolved', NULL::DOUBLE,NULL::VARCHAR,false,'published_anchor_only'
      FROM candidate_keys k ANTI JOIN
        (SELECT * FROM contexts WHERE source_role='confirmed_position') c
        ON k.cik=c.cik AND k.quarter=c.quarter AND k.accession=c.accession
        AND k.context_id=c.context_id""")


def collect_documents(con, output):
    documents = con.execute("""SELECT DISTINCT cik,accession FROM reference_contexts
      WHERE accession IS NOT NULL ORDER BY 1,2""").fetchall()
    if len(documents) > 2500:
        raise ValueError("Unexpected source population above 2500 documents")
    columns = ["cik", "accession", "context_id", "quarter", "field", "concept", "fact_id", "raw",
               "decimals", "rounding_bound", "unit_ref", "unit_kind", "currency", "reason", "multiplier", "nil"]
    statuses = []
    with (output / "source_facts.csv").open("w", newline="", encoding="utf-8") as stream, \
         (output / 'other_source_facts.csv').open('w', newline='', encoding='utf-8') as other_stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        other_writer = csv.DictWriter(other_stream, fieldnames=['cik','accession','context_id','quarter',
            'field','reference_value','concept','raw','reason','nil'])
        other_writer.writeheader()
        for index, (cik, accession) in enumerate(documents, 1):
            compact = accession.replace("-", "")
            if len(compact) != 18 or not compact.isdigit() or not cik.isdigit():
                raise ValueError("Invalid source accession or CIK")
            path = ROOT / "data/raw/filings/bdc_xbrl" / str(int(cik)) / (compact + ".xml")
            item = read_field_document(path, cik)
            writer.writerows(dict(cik=cik, accession=accession, **f) for f in item["facts"]
                             if "2023-03-31" <= f["quarter"] <= "2026-03-31")
            other_writer.writerows(dict(cik=cik, accession=accession, **f) for f in item['other_facts']
                                   if '2023-03-31' <= f['quarter'] <= '2026-03-31')
            statuses.append(dict(cik=cik, accession=accession, source_path=str(path),
                source_sha256=item["sha256"], complete=item["complete"], errors=" | ".join(item["errors"]),
                facts=len(item["facts"])))
            if index % 10 == 0 or index == len(documents):
                print(f"E4 cached field sources {index}/{len(documents)}", flush=True)
    with (output / "source_documents.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(statuses[0]))
        writer.writeheader(); writer.writerows(statuses)
    con.execute("CREATE TABLE document_status AS SELECT * FROM read_csv(?,all_varchar=true)",
                [str(output / "source_documents.csv")])
    return statuses


def normalize_coupon_references(con):
    """Cash source + separately disclosed PIK, with additive source precision.

    Missing/conflicting PIK and generic/effective-yield facts cannot establish
    the all-in source reference. This reads no candidate rate values.
    """
    con.execute("""CREATE OR REPLACE TABLE fact_groups AS SELECT g.* REPLACE(
        CASE WHEN g.field='interest_rate' AND g.reason='ready' AND p.reason='ready'
            AND p.variants=1 AND p.fact_count>0 THEN g.reference_value+p.reference_value
            ELSE g.reference_value END AS reference_value,
        CASE WHEN g.field='interest_rate' AND g.reason='ready' AND p.reason='ready'
            AND p.variants=1 AND p.fact_count>0 THEN g.precision_bound+p.precision_bound
            ELSE g.precision_bound END AS precision_bound,
        CASE WHEN g.field='interest_rate' AND g.reason='ready' AND
            NOT coalesce(p.reason='ready' AND p.variants=1 AND p.fact_count>0,false)
            THEN 'unresolved_pik_for_all_in_reference' ELSE g.reason END AS reason)
        FROM fact_groups g LEFT JOIN fact_groups p
        ON g.cik=p.cik AND g.accession=p.accession AND g.quarter=p.quarter AND g.context_id=p.context_id
        AND g.field='interest_rate' AND p.field='pik_rate'""")


def assemble_comparisons(con, output, *, reconciliation=None,monetary=None):
    reconciliation=Path(reconciliation) if reconciliation else RECONCILIATION
    con.execute("""CREATE TABLE facts AS SELECT cik,accession,quarter,context_id,field,
      TRY_CAST(raw AS DECIMAL(38,12)) AS raw,TRY_CAST(rounding_bound AS DECIMAL(38,12)) AS rounding_bound,
      CAST(multiplier AS INTEGER) AS multiplier,currency,unit_kind,reason,CAST(nil AS BOOLEAN) AS nil
      FROM read_csv(?,all_varchar=true)""", [str(output / "source_facts.csv")])
    con.execute("""CREATE TABLE fact_groups AS SELECT cik,accession,quarter,context_id,field,
      count(*) FILTER(WHERE NOT nil) AS fact_count,
      count(DISTINCT (raw,currency,unit_kind,multiplier)) FILTER(WHERE NOT nil) AS variants,
      min(raw*multiplier) AS reference_value,min(rounding_bound*multiplier) AS precision_bound,
      min(currency) AS currency,
      CASE WHEN bool_or(NOT nil AND (raw IS NULL OR rounding_bound IS NULL))
        THEN 'unresolved_source_numeric_representation'
        WHEN bool_and(reason='ready' AND raw IS NOT NULL AND rounding_bound IS NOT NULL)
        THEN 'ready' ELSE string_agg(DISTINCT reason,';') END AS reason
      FROM facts GROUP BY 1,2,3,4,5""")
    if 'interest_rate_kind' in {row[0] for row in con.execute('DESCRIBE candidate').fetchall()}:
        normalize_coupon_references(con)
    # Exact anchors and existing reconciliation correspondences can nominate a
    # candidate row. No source numeric value is taken from the production ledger.
    con.execute("""CREATE TABLE reconciliation_links AS SELECT DISTINCT lpad(cik,10,'0') AS cik,
      substr(period,1,10) AS quarter,accession_number AS accession,context_id,output_row_id AS row_id
      FROM read_csv(?,all_varchar=true) WHERE output_row_id IS NOT NULL
      AND lpad(cik,10,'0') IN (SELECT DISTINCT cik FROM obligations)
      AND substr(period,1,10) BETWEEN '2023-03-31' AND '2026-03-31'""", [str(reconciliation)])
    con.execute("""CREATE TABLE links AS
      SELECT DISTINCT r.cik,r.quarter,r.accession,r.context_id,h.row_id
      FROM reference_contexts r JOIN candidate h
      ON r.cik=lpad(h.cik,10,'0') AND r.quarter=CAST(h.report_date AS VARCHAR)[:10]
      AND r.accession=h.accession_number AND r.context_id=h.src_context_id
      UNION
      SELECT DISTINCT r.cik,r.quarter,r.accession,r.context_id,h.row_id
      FROM reference_contexts r JOIN reconciliation_links l USING(cik,quarter,accession,context_id)
      JOIN candidate h ON l.row_id=h.row_id AND l.cik=lpad(h.cik,10,'0')
        AND l.quarter=CAST(h.report_date AS VARCHAR)[:10]""")
    con.execute("""CREATE TABLE quarter_candidate_counts AS SELECT lpad(cik,10,'0') AS cik,
      CAST(report_date AS VARCHAR)[:10] AS quarter,count(*) AS rows FROM candidate GROUP BY 1,2""")
    con.execute("CREATE TABLE fields(field VARCHAR)")
    con.executemany("INSERT INTO fields VALUES (?)", [(f,) for f in FIELDS])
    con.execute("""CREATE TABLE source_fields AS SELECT r.cik,r.quarter,r.accession,r.context_id,
      r.source_role,r.reference_origin,r.source_fv,r.currency AS source_fv_currency,
      r.source_complete AND coalesce(CAST(d.complete AS BOOLEAN),false) AS source_complete,
      f.field,g.fact_count,g.variants,g.reference_value,g.precision_bound,g.currency,g.reason,
      CASE WHEN coalesce(q.rows,0)=0 OR EXISTS(SELECT 1 FROM links l WHERE
        l.cik=r.cik AND l.quarter=r.quarter AND l.accession=r.accession AND l.context_id=r.context_id)
        THEN 'ready' ELSE 'unresolved_source_candidate_correspondence' END AS correspondence_status
      FROM reference_contexts r CROSS JOIN fields f
      LEFT JOIN fact_groups g USING(cik,quarter,accession,context_id,field)
      LEFT JOIN document_status d USING(cik,accession)
      LEFT JOIN quarter_candidate_counts q USING(cik,quarter)""")
    parts = []
    for field in FIELDS:
        currency = f"nullif(h.{field}_currency,'')" if field in MONEY else "NULL::VARCHAR"
        parts.append(f"""SELECT l.cik,l.quarter,l.accession,l.context_id,'{field}' AS field,
          count(*) AS candidate_rows,min(TRY_CAST(CAST(h.{field} AS VARCHAR) AS DECIMAL(38,12))) AS published,
          min({currency}) AS published_currency
          FROM links l JOIN candidate h USING(row_id) GROUP BY 1,2,3,4""")
    con.execute("CREATE TABLE published AS " + " UNION ALL ".join(parts))
    from pipeline.monetary_reference import normalize
    monetary=monetary or {}
    normalize(con,quotes=monetary.get('quotes',[]),decisions=monetary.get('decisions',[]))
    con.execute("COPY monetary_reference_audit TO "+literal(output/'monetary_reference_audit.parquet')+" (FORMAT PARQUET)")
    con.execute("CREATE TABLE assessments AS " + comparison_sql())


def export_summaries(con, output, *, table='assessments', prefix=''):
    if table not in ('assessments', 'other_assessments') or prefix not in ('', 'other_'):
        raise ValueError('Unknown field assessment export')
    query = """SELECT quarter,field,reference_origin,category,assessment_reason,
      source_fv_currency,count(*) AS observations,
      sum(abs(source_fv)) AS absolute_source_context_fv,
      count(*) FILTER(WHERE source_fv IS NULL) AS observations_without_source_fv
      FROM assessments GROUP BY ALL ORDER BY quarter,field,reference_origin,category,assessment_reason"""
    query = query.replace('FROM assessments', 'FROM '+table)
    con.execute("COPY (" + query + ") TO " + literal(output / (prefix+"categories.csv")) + " (HEADER)")
    coverage = """SELECT quarter,field,reference_origin,source_fv_currency,
      count(*) FILTER(WHERE category IN ('correct','incorrect','missing_output')) AS assessed,
      count(*) FILTER(WHERE category NOT IN ('not_disclosed','not_applicable')) AS disclosed_or_unresolved,
      count(*) FILTER(WHERE category IN ('correct','incorrect','missing_output'))*1.0 /
        nullif(count(*) FILTER(WHERE category NOT IN ('not_disclosed','not_applicable')),0) AS assessed_row_share,
      sum(abs(source_fv)) FILTER(WHERE category IN ('correct','incorrect','missing_output')) /
        nullif(sum(abs(source_fv)) FILTER(WHERE category NOT IN ('not_disclosed','not_applicable')),0) AS assessed_source_fv_share,
      'UNASSESSABLE' AS accuracy_status,'assessability floors pending owner amendment; incomplete roster remains explicit' AS reason
      FROM assessments GROUP BY ALL ORDER BY quarter,field,reference_origin,source_fv_currency"""
    coverage = coverage.replace('FROM assessments', 'FROM '+table)
    con.execute("COPY (" + coverage + ") TO " + literal(output / (prefix+"assessability.csv")) + " (HEADER)")
    con.execute("COPY "+table+" TO " + literal(output / (prefix+"assessments.parquet")) + " (FORMAT PARQUET)")


def run(output,*,attempt=ATTEMPT,source_directory=None,context_directory=None):
    started = time.monotonic()
    output.mkdir(parents=True, exist_ok=False)
    result = read_json(attempt / "result.json")
    print("E4 verify sealed identity bundle", flush=True)
    read_stage(attempt, result["identity"], artifacts.required("identity"))
    reconciliation=RECONCILIATION
    source_inputs=[]
    if source_directory:
        from scripts.run_production_acceptance import verify_completion
        source_directory=Path(source_directory)
        verify_completion(source_directory)
        if read_json(source_directory/'summary.json')['holdings_sha256']!=sha(attempt/'bundle/private_markets_holdings.csv'):
            raise ValueError('Source comparison belongs to different holdings')
        reconciliation=source_directory/'pairs/source_reconciliation_detail.csv'
        source_inputs=[source_directory/'complete.json']
    context_directory=Path(context_directory) if context_directory else E2
    for name, expected in read_json(context_directory / "complete.json").items():
        if sha(context_directory / name) != expected:
            raise ValueError("E2 completion artifact changed: " + name)
    resume=context_directory/'source_resume.json'
    source_root = Path(read_json(resume)["document_root"]) if resume.is_file() else context_directory/'documents'
    from pipeline.monetary_fx import load_inputs
    candidate_root=attempt.parent.parent
    monetary=load_inputs(candidate_root/'frozen/data/reference/monetary_conversion')
    if monetary['inputs']:
        snapshot=read_json(candidate_root/'snapshot.json')
        if sha(candidate_root/'snapshot.json')!=read_json(candidate_root/'snapshot_complete.json')['manifest_sha256']:
            raise ValueError('FX input snapshot seal mismatch')
        frozen_hashes={r['path']:r['sha256'] for r in snapshot['artifacts']}
        for path,value in monetary['inputs'].items():
            if frozen_hashes.get(Path(path).relative_to(candidate_root/'frozen').as_posix())!=value:
                raise ValueError('Monetary reference differs from frozen candidate inputs')
    inputs = [Path(__file__), ROOT / "pipeline/field_assessment.py", ROOT / "pipeline/provenance_reverify.py",
              ROOT / 'pipeline/categorical_field_assessment.py',
              ROOT / 'pipeline/monetary_reference.py',ROOT / 'pipeline/monetary_fx.py',
              ROOT / 'scripts/programme_closeout/fx.py',*[Path(p) for p in monetary['inputs']],
              ROOT / "pipeline/bdc_filings.py", REGISTER, reconciliation, attempt / "result.json", context_directory / "complete.json",*source_inputs]
    hashes = {str(p.relative_to(ROOT)): sha(p) for p in inputs}
    atomic_json(output / "request.json", dict(experiment="E4", started_utc=now(), pid=os.getpid(),
        policy=POLICY_VERSION, input_sha256=hashes, seconds=None, memory_limit=None,
        candidate=str(attempt), interpretation="context field fidelity; not a deduplicated portfolio or completeness certification"))
    with duckdb.connect(config={"threads":2,"memory_limit":"-1"}) as con:
        con.execute("SET temp_directory=?", [str(output / "temp")])
        con.execute("CREATE TABLE obligations AS SELECT * FROM read_csv(?,all_varchar=true)", [str(REGISTER)])
        con.execute("""CREATE TABLE candidate AS SELECT h.* FROM read_parquet(?) h
          SEMI JOIN (SELECT * FROM obligations WHERE eligibility_status LIKE 'eligible%') o
          ON lpad(h.cik,10,'0')=o.cik
          AND CAST(h.report_date AS VARCHAR)[:10]=o.report_date""", [str(attempt / "bundle/private_markets_holdings.parquet")])
        # Replay each quarter in SQL. No multi-million-row pandas materialization.
        replay_summaries = []
        for (quarter,) in con.execute("SELECT DISTINCT report_date FROM obligations ORDER BY 1").fetchall():
            con.execute("CREATE OR REPLACE VIEW h AS SELECT * FROM candidate WHERE CAST(report_date AS VARCHAR)[:10]=" + literal(quarter))
            con.execute("CREATE OR REPLACE TABLE replay AS " + " UNION ALL ".join(_field_sql(f,c) for f,c in CHEAP_FIELDS.items()))
            con.execute("COPY replay TO " + literal(output / ("replay-" + quarter + ".parquet")) + " (FORMAT PARQUET)")
            replay_summaries.extend(dict(quarter=quarter,field=f,status=s,observations=n)
                for f,s,n in con.execute("SELECT field,cheap_status,count(*) FROM replay GROUP BY 1,2 ORDER BY 1,2").fetchall())
            print("E4 provenance replay " + quarter, flush=True)
        atomic_json(output / "replay_summary.json", replay_summaries)
        con.execute("CREATE TABLE sources AS SELECT * FROM read_csv(?,all_varchar=true)", [str(context_directory / "source_assessments.csv")])
        source_rows = con.execute("SELECT document,evidence_sha256 FROM sources ORDER BY cik,quarter").fetchall()
        source_paths = []
        for name, expected in source_rows:
            path = source_root / name
            if not path.resolve().is_relative_to(source_root.resolve()) or sha(path) != expected:
                raise ValueError("Frozen context evidence changed")
            source_paths.append(path)
        load_context_records(con, source_paths)
        assemble_reference(con)
        statuses = collect_documents(con, output)
        stale = con.execute("""SELECT s.cik,s.quarter,s.accession FROM sources s
          JOIN document_status d USING(cik,accession)
          WHERE nullif(s.source_sha256,'') IS NOT NULL
          AND s.source_sha256 IS DISTINCT FROM d.source_sha256""").fetchall()
        if stale:
            raise ValueError("Cached source changed since frozen context assessment: " + repr(stale[:10]))
        print("E4 assemble source precision comparisons", flush=True)
        assemble_comparisons(con, output,reconciliation=reconciliation,monetary=monetary)
        export_summaries(con, output)
        categorical.assemble_comparisons(con, output/'other_source_facts.csv')
        export_summaries(con, output, table='other_assessments', prefix='other_')
        counts = dict(con.execute("SELECT category,count(*) FROM assessments GROUP BY 1").fetchall())
        other_counts = dict(con.execute('SELECT category,count(*) FROM other_assessments GROUP BY 1').fetchall())
        reference_count = con.execute("SELECT count(*) FROM reference_contexts").fetchone()[0]
        if sum(counts.values()) != reference_count * 8:
            raise ValueError("Field category partition does not conserve reference observations")
        if sum(other_counts.values()) != reference_count * len(categorical.FIELDS):
            raise ValueError('Categorical partition does not conserve reference observations')
        obligation_status = con.execute("""SELECT count(*),count(*) FILTER(WHERE source_complete='True'),
          count(*) FILTER(WHERE P='0') FROM sources""").fetchone()
        for relative, expected in hashes.items():
            if sha(ROOT / relative) != expected:
                raise ValueError("E4 input changed: " + relative)
        for doc in statuses:
            if doc["source_sha256"] and sha(Path(doc["source_path"])) != doc["source_sha256"]:
                raise ValueError("E4 source changed after collection")
        atomic_json(output / "summary.json", dict(experiment="E4", completed_utc=now(),
            elapsed_seconds=time.monotonic()-started, reference_contexts=reference_count, categories=counts,
            categorical_policy=categorical.POLICY_VERSION, other_categories=other_counts,
            obligations=obligation_status[0], complete_obligations=obligation_status[1],
            obligations_without_confirmed_positions=obligation_status[2], field_documents=len(statuses),
            incomplete_field_documents=sum(not r["complete"] for r in statuses),
            accuracy_status="UNASSESSABLE", assessability_floors="pending_owner_amendment",
            limitations=["Selected-source P contexts are not a deduplicated position roster.",
              "Supplemental candidate anchors are reported separately; their position role is unproved.",
              "Absent or unresolved XML contexts block completeness certification.",
              "Unmatched source contexts in populated quarters require correspondence review; they are not presumed missing.",
              "Nil/absent numeric tags mean not disclosed in XBRL, not absent from narrative or schedule text.",
              "Weights are absolute source context FV by currency; they may repeat investments.",
              "No instrument-applicability collector: no automatic not_applicable labels.",
              "Existing reconciliation nominates row IDs only; candidate values and source facts are re-read."]))
    outputs = [p for p in output.iterdir() if p.is_file() and p.suffix in {".csv", ".parquet", ".json"}]
    atomic_json(output / "complete.json", {p.name:sha(p) for p in outputs})
    print("E4 complete: " + str(counts), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument('--candidate',default='t1-runtime-20260910-v5')
    parser.add_argument('--attempt',default='identity-01')
    parser.add_argument('--source-directory',type=Path,help='Completed independent source evaluation of this candidate')
    parser.add_argument('--context-directory',type=Path,help='Completed source context inventory')
    args = parser.parse_args()
    output = args.output_dir.resolve()
    if not output.is_relative_to(ROOT / "scratch"):
        parser.error("E4 output must be under scratch/")
    sys.stdout.reconfigure(encoding="ascii", errors="backslashreplace")
    sys.stderr.reconfigure(encoding="ascii", errors="backslashreplace")
    candidate=candidate_path(args.candidate)
    attempt=(candidate/'attempts'/args.attempt).resolve()
    if attempt.parent!=candidate/'attempts': parser.error('Invalid attempt')
    with heavy_lock(candidate):
        run(output,attempt=attempt,source_directory=args.source_directory,context_directory=args.context_directory)


if __name__ == "__main__":
    main()
