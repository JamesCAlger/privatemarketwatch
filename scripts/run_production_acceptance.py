"""Evaluate all production-stack quarter gates on a sealed candidate, cache-only."""
from __future__ import annotations

import argparse
import csv
from pathlib import Path
import sys
import time
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

import duckdb
from pipeline import config,quarter_acceptance,legacy_acceptance_inputs
from pipeline.programme import artifacts
from pipeline.programme.artifacts import literal
from pipeline.programme.core import ContractError,atomic_json,read_json,read_stage,sha,verify_records
from pipeline.programme.runner import candidate_path,heavy_lock

SCRATCH=ROOT/"scratch/2026-09-12_programme_e0"
REGISTER=ROOT/"docs/production_stack/programme_pilot_evidence_2026-09-09/obligations_v3.csv"


def verify_completion(directory):
    records=read_json(directory/"complete.json")
    for name,expected in records.items():
        if not isinstance(expected,str) or sha(directory/name)!=expected:
            raise ContractError("Experiment output changed: "+str(directory/name))


def verify_registered_experiment(directory, register):
    """A completed collector on an older denominator is not current evidence."""
    directory, register = Path(directory), Path(register).resolve()
    verify_completion(directory)
    if 'summary.json' not in read_json(directory / 'complete.json'):
        raise ContractError('Collector summary is not sealed: ' + str(directory))
    summary = read_json(directory / 'summary.json')
    key = str(register.relative_to(ROOT)) if register.is_relative_to(ROOT) else str(register)
    if summary.get('input_sha256', {}).get(key) != sha(register):
        raise ContractError('Collector used a different obligation register: ' + str(directory))


def primary_evidence(holdings,frozen,output,cohort,*,financials=None):
    """Run the existing conservation engine on candidate holdings and frozen inputs.

    Currency is established by the companyfacts producer's explicit USD field
    contract, including exact independent corroboration of override totals.
    Schedule totals remain diagnostic and cannot count as independent anchors.
    """
    from scripts import shadow_conservation_engine as engine
    from pipeline.agent_promoted import load_anchor_overrides
    from pipeline.extract_companyfacts import _BALANCE_SHEET_CONCEPTS
    # Fail on a producer convention change rather than silently inheriting USD.
    if _BALANCE_SHEET_CONCEPTS["investments_at_fair_value"]["unit"]!="USD":
        raise ContractError("Companyfacts FV unit contract changed")
    ff=Path(financials) if financials else frozen/"data/output/fund_financials.csv"
    bdc=frozen/"data/output/bdc_holdings.csv"
    anchor_dir=frozen/"data/overrides/agent_anchor"
    inputs=[ff,bdc,*sorted(anchor_dir.glob("*/*.json")),ROOT/"scripts/shadow_conservation_engine.py",
            ROOT/"pipeline/extract_companyfacts.py",ROOT/"pipeline/agent_promoted.py",
            ROOT/'pipeline/primary_anchor_evidence.py',ROOT/'pipeline/accounting_membership.py']
    hashes={str(p):sha(p) for p in inputs}
    overrides=load_anchor_overrides(anchor_dir)
    with duckdb.connect(config={"threads":2,"memory_limit":"-1"}) as con:
        from pipeline.primary_anchor_evidence import collect_overrides
        metadata=collect_overrides(con,anchor_dir,ff)
        atomic_json(output/'primary_override_evidence.json',metadata)
        con.execute('''CREATE TABLE override_evidence(cik VARCHAR,quarter VARCHAR,currency VARCHAR,
            source_evidence VARCHAR,override_agrees BOOLEAN,evidence_status VARCHAR)''')
        if metadata:
            con.executemany('INSERT INTO override_evidence VALUES (?,?,?,?,?,?)',[
                tuple(r[key] for key in ('cik','quarter','currency','source_evidence','override_agrees','evidence_status'))
                for r in metadata])
        con.execute("CREATE TABLE wrapped(cik VARCHAR)")
        con.executemany("INSERT INTO wrapped VALUES (?)",[(c,) for c in sorted(cohort)])
        con.execute("CREATE TABLE _anchor_override(cik VARCHAR,report_date VARCHAR,anchor_value DOUBLE,basis VARCHAR)")
        if overrides:
            con.executemany("INSERT INTO _anchor_override VALUES (?,?,?,?)",[(r["cik"],r["report_date"],r["anchor_value"],r["basis"]) for r in overrides])
        with patch.multiple(engine,UNIFIED_HOLDINGS_FILE=holdings,
            UNIFIED_HOLDINGS_PARQUET_FILE=output/"no_parquet_fallback.parquet",
            BDC_HOLDINGS_FILE=bdc,BDC_HOLDINGS_PARQUET_FILE=output/"no_bdc_parquet_fallback.parquet",
            FUND_FINANCIALS_FILE=ff):
            engine.run_rule(con,engine.RULES[0])
        con.execute("""COPY (SELECT r.cik,report_date AS quarter,anchor_value,value_sum AS published_value,
          CASE WHEN anchor_used LIKE 'companyfacts%' THEN 'USD'
               WHEN anchor_used LIKE 'verified_override%' AND e.override_agrees THEN e.currency ELSE '' END AS currency,
          CASE WHEN anchor_used LIKE 'companyfacts%' THEN ?
               WHEN anchor_used LIKE 'verified_override%' THEN coalesce(e.source_evidence,'') ELSE '' END AS source_evidence,
          CASE WHEN anchor_used LIKE 'verified_override%' AND e.override_agrees THEN 'verified_override'
               WHEN anchor_used LIKE 'verified_override%' THEN 'unverified_override'
               WHEN anchor_used='companyfacts_fv_plus_cash' THEN 'fund_financials_plus_cash'
               WHEN anchor_used='companyfacts_fv' THEN 'fund_financials'
               WHEN anchor_used='schedule_total' THEN 'schedule_total' ELSE 'unavailable' END AS anchor_kind,
          (anchor_basis='published_rows' OR (anchor_basis='investments_ex_cash' AND
             NOT EXISTS(SELECT 1 FROM _cash_rows c WHERE c.cik=r.cik AND c.report_date=r.report_date))) AS scope_comparable,
          anchor_used,anchor_basis,residual_pct,status,e.evidence_status AS override_evidence_status
          FROM result_fv_conservation r LEFT JOIN override_evidence e
            ON e.cik=r.cik AND e.quarter=r.report_date ORDER BY report_date,r.cik) TO """+literal(output/"primary_anchors.csv")+" (HEADER)",
          [str(ff)+"#sha256="+sha(ff)])
        con.execute("""COPY (SELECT 'conservation' AS engine,'fv_conservation' AS rule_name,cik,
          report_date AS period,CASE WHEN status='reconciles' THEN 'pass'
            WHEN status='no_anchor' THEN 'skip' ELSE 'fail' END AS status,
          residual_pct AS metric,anchor_used||':'||anchor_basis AS mechanism
          FROM result_fv_conservation ORDER BY report_date,cik) TO """+literal(output/"conservation_ledger.csv")+" (HEADER)")
        from pipeline.accounting_membership import build
        build(con,release_id=sha(holdings),holdings=holdings,anchors=output/'primary_anchors.csv')
        con.execute('COPY accounting_membership TO '+literal(output/'accounting_membership.parquet')+' (FORMAT PARQUET)')
        con.execute('COPY accounting_anchor_summaries TO '+literal(output/'accounting_anchor_summaries.csv')+' (HEADER)')
    for path,expected in hashes.items():
        if sha(Path(path))!=expected:
            raise ContractError("Conservation input changed: "+path)
    atomic_json(output/"primary_inputs.json",hashes)


def run(candidate,attempt,output,*,field_directory=None,frontend_directory=None,source_directory=None,
        context_directory=None,exclusion_directory=None,acceptance_policy=None):
    started=time.monotonic()
    result=read_json(attempt/"result.json")
    read_stage(attempt,result["identity"],artifacts.required("identity"))
    snapshot=read_json(candidate/"snapshot.json")
    if sha(candidate/"snapshot.json")!=read_json(candidate/"snapshot_complete.json")["manifest_sha256"]:
        raise ContractError("Candidate snapshot manifest changed")
    output.mkdir(parents=True,exist_ok=False)
    frozen=candidate/"frozen"
    holdings=attempt/"bundle/private_markets_holdings.csv"
    hp_sha=sha(holdings)
    source_directory=Path(source_directory) if source_directory else None
    context_directory=Path(context_directory) if context_directory else SCRATCH/'e2-recovery-v2'
    exclusion_directory=Path(exclusion_directory) if exclusion_directory else SCRATCH/'e3-v1'
    verify_registered_experiment(context_directory, REGISTER)
    verify_registered_experiment(exclusion_directory, REGISTER)
    if source_directory:
        verify_completion(source_directory)
        if read_json(source_directory/'summary.json')['holdings_sha256']!=hp_sha:
            raise ContractError('Independent source evaluation belongs to different holdings')
    field_directory=Path(field_directory) if field_directory else SCRATCH/'e4-v2'
    verify_completion(field_directory)
    e4_request=read_json(field_directory/"request.json")
    if Path(e4_request["candidate"]).resolve()!=attempt.resolve():
        raise ContractError("E4 field comparison belongs to another candidate attempt")
    e4_result_key=str((attempt/"result.json").relative_to(ROOT))
    if e4_request["input_sha256"][e4_result_key]!=sha(attempt/"result.json"):
        raise ContractError("E4 candidate identity changed")
    code=[Path(__file__),ROOT/"pipeline/quarter_acceptance.py",ROOT/"pipeline/quarter_evidence.py",
          ROOT/'pipeline/acceptance_policy.py',
          ROOT/'pipeline/legacy_acceptance_inputs.py',ROOT/'pipeline/review_queue.py',
          ROOT/'pipeline/investigation_state.py',ROOT/'scripts/shadow_adapter.py',
          ROOT/"data/reference/quarter_acceptance_programme_thresholds.json"]
    code_hashes={str(p):sha(p) for p in code}
    atomic_json(output/"request.json",dict(candidate=str(candidate),identity_sha256=sha(attempt/"result.json"),
        holdings_sha256=hp_sha,code_sha256=code_hashes,seconds=None,memory_limit=None))
    manifest_path=frozen/"data/reference/wrapper_cohort_manifest.json"
    if not manifest_path.exists():
        manifest_path=frozen/config.WRAPPER_COHORT_MANIFEST_FILE.relative_to(ROOT)
    cohort=quarter_acceptance.load_cohort(manifest_path)
    used={"data/output/fund_financials.csv","data/output/bdc_holdings.csv",str(manifest_path.relative_to(frozen)).replace("\\","/")}
    selected=[r for r in snapshot["artifacts"] if r["path"] in used or r["path"].startswith("data/overrides/agent_anchor/")]
    recorded={r["path"] for r in selected}
    required=used|{p.relative_to(frozen).as_posix() for p in (frozen/"data/overrides/agent_anchor").glob("*/*.json")}
    if required-recorded:
        raise ContractError("Unrecorded primary input: "+repr(sorted(required-recorded)))
    verify_records(frozen,selected)
    print("P4 calculate independent primary-anchor observations",flush=True)
    candidate_financials=attempt/'bundle/fund_financials.csv'
    primary_evidence(holdings,frozen,output,cohort,
        financials=candidate_financials if candidate_financials.is_file() else None)
    queue=output/'uncollected_review_queue.csv'
    if source_directory:
        print('P4 collect existing source-blocker queue from sealed source results',flush=True)
        legacy_acceptance_inputs.collect_source_queue(holdings,source_directory,output/'legacy_source')
        queue=output/'legacy_source/review_queue.csv'
    print('P4 snapshot existing cohort investigation records without applying rules',flush=True)
    legacy_acceptance_inputs.snapshot_investigations(quarter_acceptance.INVESTIGATE_DIR,
        output/'legacy_investigations',holdings,set(cohort))
    investigation_manifest=output/'legacy_investigations/investigation_inputs.json'
    investigation_store=output/'legacy_investigations/store'
    files={}
    def add(name,path,bound=False):
        files[name]=dict(path=str(path.resolve()),sha256=sha(path))
        if bound:
            files[name]["holdings_sha256"]=hp_sha
    add("obligations",REGISTER)
    add("contexts",context_directory/"fund_quarters.csv")
    add("exclusions",exclusion_directory/"exclusions.csv")
    add("fields",field_directory/"assessments.parquet",True)
    if (field_directory/'other_assessments.parquet').is_file():
        add('other_fields',field_directory/'other_assessments.parquet',True)
    add("gics_hierarchy",config.GICS_HIERARCHY_FILE)
    add("primary_anchors",output/"primary_anchors.csv",True)
    add('accounting_membership',output/'accounting_membership.parquet',True)
    add('accounting_anchor_summaries',output/'accounting_anchor_summaries.csv',True)
    add("legacy_ledger",output/"conservation_ledger.csv",True)
    if source_directory:
        add('legacy_queue',queue,True)
    add('legacy_investigate',investigation_manifest,True)
    # Reconciliation supplies nominated source/output links only. Collectors
    # reread candidate row IDs and values; no complete-roster claim is made.
    add("reconciliation",source_directory/'pairs/source_reconciliation_detail.csv'
        if source_directory else config.OUTPUT_DIR/"source_reconciliation_detail.csv",True)
    parent_record=result['identity']['parents'].get('unified')
    if not parent_record:
        raise ContractError('Identity stage has no recorded unified parent')
    parent_attempt=(attempt.parent/parent_record['attempt']).resolve()
    if parent_attempt.parent!=attempt.parent or sha(parent_attempt/'result.json')!=parent_record['result_sha256']:
        raise ContractError('Unified parent is not the recorded immutable attempt')
    parent=parent_attempt/'bundle/agent_fix_application_audit.csv'
    if parent.exists():
        add("legacy_audit",parent,True)
    for name in ('input_admission_audit','spread_unit_audit'):
        path=parent.parent/(name+'.csv')
        if path.is_file(): add(name,path,True)
    if frontend_directory:
        directory=Path(frontend_directory)
        exported=read_json(directory/'holdings_history/manifest.json')
        if exported['holdings_sha256']!=hp_sha:
            raise ContractError('Public export belongs to another holdings release')
        for name,filename in (('public_portfolio','portfolio_characteristics.json'),
            ('public_sectors','gics_sector_breakdown.json'),('public_contributors','public_partition_contributors.json')):
            add(name,directory/filename,True)
    for name in artifacts.OUTPUT_SCHEMAS:
        directory=source_directory/'pairs' if source_directory else attempt/'bundle'
        for path in (directory/name,(directory/name).with_suffix(".parquet")):
            if path.is_file():
                add(path.name,path,True)
    evidence=output/"evidence.json"
    from pipeline import acceptance_policy as policy
    default_policy=frozen/'data/reference/production_acceptance_policy.json'
    policy_path=acceptance_policy or (default_policy if default_policy.is_file() else None)
    adopted,policy_inputs=policy.load(policy_path,evidence_files=files)
    atomic_json(output/'policy_inputs.json',policy_inputs)
    atomic_json(evidence,dict(holdings_sha256=hp_sha,files=files,**adopted,
        notes='Policy adoptions are evidence-bound; evaluation grants no publication approval'))
    with REGISTER.open(newline="",encoding="utf-8-sig") as stream:
        quarters=sorted({r["report_date"] for r in csv.DictReader(stream)})
    summaries=[]
    pair_cache=set()  # Only this run; file hashes are rechecked each quarter.
    for quarter in quarters:
        print("P4 evaluate "+quarter,flush=True)
        verdict=quarter_acceptance.compute_acceptance(target_quarter=quarter,
            holdings_path=holdings,manifest_path=manifest_path,
            ledger_path=output/"conservation_ledger.csv",queue_path=queue,
            audit_path=parent,investigate_dir=investigation_store,
            programme_evidence=evidence,programme_pair_cache=pair_cache)
        quarter_acceptance.write_acceptance(verdict,json_path=output/(quarter+".json"),funds_path=output/(quarter+"-funds.csv"))
        summaries.append(dict(quarter=quarter,verdict=verdict["verdict"],
            statuses={status:sum(c["status"]==status for c in verdict["checks"]) for status in ("PASS","FAIL","UNASSESSABLE")},
            checks=len(verdict["checks"])))
    for path,expected in code_hashes.items():
        if sha(Path(path))!=expected:
            raise ContractError("P4 code changed during evaluation")
    policy.verify(policy_inputs)
    legacy_acceptance_inputs.verify_investigations(investigation_manifest,holdings,set(cohort))
    if source_directory:
        verify_completion(output/'legacy_source')
    atomic_json(output/"summary.json",dict(quarters=summaries,elapsed_seconds=time.monotonic()-started,
        release_readiness="blocked",scope="13-quarter candidate evaluation; missing evidence remains explicit"))
    atomic_json(output/"complete.json",{p.name:sha(p) for p in output.iterdir() if p.is_file()})
    print("P4 evaluation complete; inspect individual failing and unassessable rows",flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir",type=Path,required=True)
    parser.add_argument("--candidate",default="t1-runtime-20260910-v5")
    parser.add_argument("--attempt",default="identity-01")
    parser.add_argument('--field-directory',type=Path,help='Completed E4 assessment of this exact candidate')
    parser.add_argument('--frontend-directory',type=Path,help='Unpacked candidate frontend data with a bound history manifest')
    parser.add_argument('--source-directory',type=Path,help='Completed independent source and companion evaluation')
    parser.add_argument('--context-directory',type=Path,help='Completed context inventory using the fresh reconciliation')
    parser.add_argument('--exclusion-directory',type=Path,help='Completed E3 audit bound to the current obligation register')
    parser.add_argument('--acceptance-policy',type=Path,
        help='Versioned evidence-bound owner adoptions; otherwise read the frozen policy if present')
    args=parser.parse_args()
    output=args.output_dir.resolve()
    if not output.is_relative_to(ROOT/"scratch"):
        parser.error("P4 evaluation writes only under scratch/")
    candidate=candidate_path(args.candidate)
    attempt=(candidate/"attempts"/args.attempt).resolve()
    if attempt.parent!=candidate/"attempts":
        parser.error("Invalid attempt")
    with heavy_lock(candidate):
        run(candidate,attempt,output,field_directory=args.field_directory,frontend_directory=args.frontend_directory,
            source_directory=args.source_directory,context_directory=args.context_directory,
            exclusion_directory=args.exclusion_directory,
            acceptance_policy=args.acceptance_policy)


if __name__=="__main__":
    main()
