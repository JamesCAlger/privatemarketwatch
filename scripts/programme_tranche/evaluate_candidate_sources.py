"""Reconcile a sealed candidate with cached instances, using private output caches.

This evaluation never promotes a correction or changes the frozen candidate.
The eleven-pair inventory distinguishes source inputs from rebuilt diagnostics.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import logging
from pathlib import Path
import shutil
import sys
import time
from unittest.mock import patch

import duckdb

from pipeline import config
from pipeline.programme import artifacts
from pipeline.programme.core import ContractError, atomic_json, read_json, read_stage, sha, verify_records
from pipeline.programme.runner import ROOT, candidate_path, heavy_lock


def verified_stage(candidate, name, stage):
    attempt=(candidate/'attempts'/name).resolve()
    if attempt.parent != candidate/'attempts':
        raise ContractError('Invalid stage attempt')
    result=read_json(attempt/'result.json')
    read_stage(attempt,result['identity'],artifacts.required(stage))
    return attempt,result


def evaluate(candidate, identity_name, evidence_name, returns_name, output):
    started=time.monotonic()
    identity,identity_result=verified_stage(candidate,identity_name,'identity')
    evidence,evidence_result=verified_stage(candidate,evidence_name,'evidence')
    returns,returns_result=verified_stage(candidate,returns_name,'returns')
    for result in (evidence_result,returns_result):
        parent=result['identity']['parents']['identity']
        if parent['attempt'] != identity.name or parent['result_sha256'] != sha(identity/'result.json'):
            raise ContractError('Evaluation stages have different identity parents')
    parent=identity_result['identity']['parents']['unified']
    unified,unified_result=verified_stage(candidate,parent['attempt'],'unified')
    if parent['result_sha256'] != sha(unified/'result.json'):
        raise ContractError('Unified parent identity changed')
    frozen=candidate/'frozen'
    snapshot=read_json(candidate/'snapshot.json')
    if sha(candidate/'snapshot.json') != read_json(candidate/'snapshot_complete.json')['manifest_sha256']:
        raise ContractError('Snapshot changed')
    verify_records(frozen,snapshot['artifacts'],exact=True)
    output.mkdir(parents=True,exist_ok=False)
    hp=identity/'bundle/private_markets_holdings.csv'
    bound=sha(hp)
    inputs={str(p):sha(p) for p in [candidate/'snapshot.json',identity/'result.json',
        evidence/'result.json',returns/'result.json',unified/'result.json',Path(__file__)]}
    atomic_json(output/'request.json',dict(candidate=str(candidate),identity_attempt=str(identity),
        holdings_sha256=bound,input_sha256=inputs,seconds=None,memory_limit=None,
        source_scope='Cached indexed BDC instances with filing report date 2023-03-31 through 2026-03-31; missing sources explicit'))

    # Redirect module bindings before importing readers with config defaults.
    overrides={}
    for name,value in vars(config).items():
        if not isinstance(value,Path):
            continue
        resolved=value.resolve()
        if resolved.is_relative_to(ROOT/'data/output'):
            overrides[name]=output/'diagnostics'/resolved.relative_to(ROOT/'data/output')
        elif resolved.is_relative_to(ROOT/'data/reference') or resolved.is_relative_to(ROOT/'data/overrides'):
            overrides[name]=frozen/resolved.relative_to(ROOT)
    overrides.update(OUTPUT_DIR=output/'diagnostics',UNIFIED_HOLDINGS_FILE=hp,
        UNIFIED_HOLDINGS_PARQUET_FILE=hp.with_suffix('.parquet'),
        BDC_HOLDINGS_FILE=unified/'bundle/bdc_holdings.csv',
        BDC_HOLDINGS_PARQUET_FILE=unified/'bundle/bdc_holdings.parquet',
        FUND_FINANCIALS_FILE=identity/'bundle/fund_financials.csv',
        BDC_FILINGS_INDEX_FILE=frozen/config.BDC_FILINGS_INDEX_FILE.relative_to(ROOT),
        BDC_HTML_CACHE_DIR=frozen/config.BDC_HTML_CACHE_DIR.relative_to(ROOT))
    (output/'diagnostics').mkdir()

    def deny_external(event,args):
        if event in ('socket.connect','socket.sendto','socket.getaddrinfo'):
            raise PermissionError('Source evaluation forbids network calls')
        if event=='open' and isinstance(args[0],(str,bytes)):
            path=Path(args[0]).resolve()
            mode=args[1] if isinstance(args[1],str) else ''
            flags=args[2] if isinstance(args[2],int) else 0
            import os
            if (any(c in mode for c in 'wax+') or flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC)):
                if not path.is_relative_to(output):
                    raise PermissionError('Source evaluation write outside private output: '+str(path))
    sys.dont_write_bytecode=True
    sys.addaudithook(deny_external)
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    with ExitStack() as stack:
        stack.enter_context(patch.multiple(config,**overrides))
        from pipeline import source_reconciliation as recon
        from pipeline import bdc_xbrl_wrapper,bdc_xbrl_html_bridge
        from pipeline import bdc_aggregate_overrides
        # Imports can already exist in interactive/tests; pin them explicitly.
        stack.enter_context(patch.multiple(recon,**{name:value for name,value in overrides.items() if hasattr(recon,name)}))
        stack.enter_context(patch.multiple(bdc_aggregate_overrides,
            **{name:value for name,value in overrides.items() if hasattr(bdc_aggregate_overrides,name)}))
        stack.enter_context(patch.object(bdc_xbrl_wrapper,'WRAPPER_SPECS',
            bdc_xbrl_wrapper._load_specs_from_json(config.OVERRIDES_DIR/'bdc_xbrl_wrappers')))
        stack.enter_context(patch.multiple(bdc_xbrl_html_bridge,
            BDC_HTML_CACHE_DIR=config.BDC_HTML_CACHE_DIR,OVERRIDES_DIR=config.OVERRIDES_DIR))
        with duckdb.connect(config={'threads':2,'memory_limit':'-1'}) as con:
            con.execute('SET temp_directory=?',[str(output/'temp')])
            holdings=con.execute('SELECT * FROM read_csv(?,all_varchar=true)',[str(hp)]).fetchdf()
            index=con.execute("""SELECT DISTINCT * FROM read_csv(?,all_varchar=true)
                WHERE report_date BETWEEN '2023-03-31' AND '2026-03-31'
                ORDER BY cik,accession_number""",[str(config.BDC_FILINGS_INDEX_FILE)]).fetchdf().fillna('')
        if len(index)>10000:
            raise ContractError('Unexpected filing population above 10000 index records')
        sources=[]
        for item in index.to_dict('records'):
            value=item.get('xbrl_local_path','')
            path=Path(value).resolve() if value else None
            if path and not path.is_relative_to(ROOT/'data/raw/filings/bdc_xbrl'):
                raise ContractError('Indexed source is outside cached BDC instances')
            present=bool(path and path.is_file())
            sources.append(dict(cik=item['cik'],accession=item['accession_number'],
                path=str(path) if path else None,status='available' if present else 'unavailable',
                sha256=sha(path) if present else None))
        atomic_json(output/'source_inputs.json',sources)
        print('Reconcile '+str(len(index))+' indexed filings against the sealed holdings',flush=True)
        detail,metrics,status=recon.run_bdc_source_reconciliation_cached(
            unified_df=holdings,filings_index_df=index,force=True)
        for item in sources:
            if item['sha256'] and sha(Path(item['path']))!=item['sha256']:
                raise ContractError('Cached source changed during evaluation: '+item['path'])
        print('Build current column-contract issues and source-reconciliation adapters',flush=True)
        from pipeline.column_validation import run_column_quality_validation
        reports=run_column_quality_validation(holdings,existing_reports={'source_reconciliation_detail':detail})
        for name,frame in reports.items():
            frame.to_csv(output/'diagnostics'/(name+'.csv'),index=False)
        del holdings,detail,reports

        print('Replay declared provenance in SQL; independent field checks remain in E4',flush=True)
        from pipeline.provenance_reverify import CHEAP_FIELDS,_field_sql,_CHEAP_REASON
        with duckdb.connect(config={'threads':2,'memory_limit':'-1'}) as con:
            con.execute('SET temp_directory=?',[str(output/'temp')])
            con.execute('CREATE VIEW h AS SELECT * FROM read_parquet('+artifacts.literal(hp.with_suffix('.parquet'))+')')
            replay=' UNION ALL '.join(_field_sql(field,column) for field,column in CHEAP_FIELDS.items())
            reason='CASE '+''.join('WHEN cheap_status='+artifacts.literal(k)+' THEN '+artifacts.literal(v)+' '
                for k,v in sorted(_CHEAP_REASON.items()))+"ELSE 'unchecked_trivial' END"
            query='SELECT *,NULL::DOUBLE AS instance_raw,\'not_checked\' AS full_status,'+reason+" AS reason_code,? AS holdings_artifact_mtime FROM ("+replay+')'
            stamp=datetime.fromtimestamp(hp.stat().st_mtime,timezone.utc).isoformat()
            con.execute('COPY ('+query+') TO '+artifacts.literal(output/'diagnostics/provenance_ledger.csv')+' (HEADER)',[stamp])
            locations={
                'private_markets_holdings.csv':(identity/'bundle','finalized holdings'),
                'position_matches.csv':(identity/'bundle','finalized matching'),
                'position_id_edges.csv':(identity/'bundle','finalized identity edges'),
                'bdc_holdings.csv':(unified/'bundle','refreshed extraction input'),
                'position_returns.csv':(returns/'bundle','finalized financial returns'),
                'position_pik_status.csv':(evidence/'bundle','rebuilt PIK evidence'),
                'nport_holdings.csv':(frozen/'data/output','unchanged cached raw input'),
                'bdc_ixbrl_field_status.csv':(frozen/'data/output','unchanged cached overlay input; not a fresh completeness attestation'),
                'source_reconciliation_detail.csv':(output/'diagnostics','fresh independent cached-source comparison'),
                'provenance_ledger.csv':(output/'diagnostics','current declared replay; full source tier not checked here'),
                'row_validation_issues.csv':(output/'diagnostics','column contracts and fresh source adapter; other validation families not run here')}
            pair_inventory={}
            for name,(directory,role) in locations.items():
                source=directory/name
                if not source.is_file():
                    pair_inventory[name]=dict(status='UNASSESSABLE',reason='Missing artifact',role=role)
                    continue
                destination=output/'pairs'/name
                destination.parent.mkdir(exist_ok=True)
                shutil.copy2(source,destination)
                # Existing stage pairs are checked first. Source-only frozen
                # inputs receive a fresh typed rendering without changing them.
                if source.with_suffix('.parquet').exists():
                    artifacts.verify_pair(source,con)
                result=artifacts.finalize_pair(destination,con)
                pair_inventory[name]=dict(status='PASS',role=role,source_path=str(source),source_sha256=sha(source),
                    csv=str(destination),parquet=str(destination.with_suffix('.parquet')),**result)
            atomic_json(output/'pair_inventory.json',pair_inventory)
    verify_records(frozen,snapshot['artifacts'],exact=True)
    for path,expected in inputs.items():
        if sha(Path(path))!=expected:
            raise ContractError('Evaluation input changed: '+path)
    atomic_json(output/'summary.json',dict(holdings_sha256=bound,elapsed_seconds=time.monotonic()-started,
        indexed_filings=len(sources),unavailable_sources=sum(s['status']=='unavailable' for s in sources),
        companion_statuses={name:row['status'] for name,row in pair_inventory.items()},
        scope='Representation parity is separate from source correctness and completeness; no roster certification'))
    atomic_json(output/'complete.json',{p.relative_to(output).as_posix():sha(p)
        for p in sorted(output.rglob('*')) if p.is_file() and 'temp' not in p.relative_to(output).parts})
    print('Candidate source evaluation complete',flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate',required=True)
    parser.add_argument('--identity-attempt',default='identity-01')
    parser.add_argument('--evidence-attempt',default='evidence-01')
    parser.add_argument('--returns-attempt',default='returns-01')
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args()
    output=args.output_dir.resolve()
    if not output.is_relative_to(ROOT/'scratch'):
        parser.error('Evaluation writes only under scratch')
    candidate=candidate_path(args.candidate)
    with heavy_lock(candidate):
        evaluate(candidate,args.identity_attempt,args.evidence_attempt,args.returns_attempt,output)


if __name__=='__main__':
    main()
