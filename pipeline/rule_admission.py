"""Manifest-bound rule admission and actual-loader audit for a holdings build.

Legacy promoted stores are replayed compatibly until their original promotion
evidence is migrated. They are explicitly unverified in the acceptance audit;
directory placement cannot establish a passing admission metric.
"""
from contextvars import ContextVar
import csv
from functools import wraps
from inspect import signature
import json
from pathlib import Path

import duckdb

from pipeline.programme.core import atomic_json,sha,digest

_audit=ContextVar('rule_admission_audit',default=None)


def record(path,status,loaded,reason):
    audit=_audit.get()
    if audit is not None:
        audit['inputs'].append(dict(path=str(path),admission_status=status,loaded=bool(loaded),reason=reason,
            sha256=sha(path) if Path(path).is_file() else ''))


def reject_contract(path, reason):
    """Record that a discovered input failed validation before it was loaded.

    Admission is checked before parsing; replace that tentative audit event so
    a rejected file is never falsely reported as an executed correction.
    """
    audit = _audit.get()
    if audit is not None:
        for event in reversed(audit['inputs']):
            if event['path'] == str(path):
                prior = event['admission_status']
                event.update(admission_status='rejected_contract', loaded=False,
                    reason=f'Input contract rejected ({prior}): {reason}')
                return
    record(path, 'rejected_contract', False, reason)


def admitted(path,base,*,allow_legacy=True):
    path,base=Path(path),Path(base)
    from pipeline.rule_promotion import assert_ready
    assert_ready(base)
    if '.proposed.' in path.name.lower() or path.name.startswith('_') or any(p.startswith('_') for p in path.relative_to(base).parts[:-1]):
        record(path,'proposed_or_retired',False,'Proposal or retired input is not loadable')
        return False
    manifest=base/'admission_manifest.json'
    if not manifest.is_file():
        record(path,'legacy_unverified',allow_legacy,'Original promotion manifest has not been migrated; cannot pass admission gate')
        return allow_legacy
    data=json.loads(manifest.read_text(encoding='utf-8-sig'))
    if data.get('format_version') not in (1,2): raise ValueError('Unsupported rule admission manifest')
    entry=data.get('entries',{}).get(path.relative_to(base).as_posix(),{})
    if data['format_version']==2 and entry.get('admission_status')=='legacy_unverified':
        if entry.get('sha256')!=sha(path):
            record(path,'legacy_unverified',False,'Legacy rule changed after inventory')
            raise ValueError('Legacy rule changed after admission inventory: '+str(path))
        record(path,'legacy_unverified',allow_legacy,'Inventoried legacy input; original approval remains unavailable')
        return allow_legacy
    accepted=entry.get('admission_status')=='promoted' and entry.get('sha256')==sha(path) and bool(entry.get('evidence'))
    if entry.get('evidence_sha256') is not None:
        accepted=accepted and entry['evidence_sha256']==digest(entry.get('evidence'))
        accepted=accepted and entry.get('evidence',{}).get('gate',{}).get('verdict')=='PASS'
    record(path,entry.get('admission_status','not_admitted'),accepted,
        'Manifest and content identity verified' if accepted else 'Missing admission, evidence or matching content hash')
    if entry.get('admission_status')=='promoted' and not accepted:
        raise ValueError('Promoted rule no longer matches its admission evidence: '+str(path))
    return accepted


def register_promotion(base,path,*,evidence):
    """Called only after the existing promoter's independent gates pass."""
    if not evidence: raise ValueError('Admission requires promotion evidence')
    base,path=Path(base).resolve(),Path(path).resolve()
    if not path.is_relative_to(base) or '.proposed.' in path.name.lower(): raise ValueError('Invalid admission path')
    target=base/'admission_manifest.json'
    if not target.exists():
        uncovered=[p for p in base.rglob('*.json') if p.resolve()!=path
            and '.proposed.' not in p.name.lower() and not p.name.startswith('_')
            and not any(part.startswith('_') for part in p.relative_to(base).parts[:-1])]
        if uncovered:
            raise ValueError('Migrate existing promotion evidence before creating a partial manifest')
    data=json.loads(target.read_text(encoding='utf-8-sig')) if target.exists() else dict(format_version=1,entries={})
    data['entries'][path.relative_to(base).as_posix()]=dict(admission_status='promoted',sha256=sha(path),evidence=evidence)
    atomic_json(target,data)


def record_spreads(corrections):
    audit=_audit.get()
    if audit is not None:
        audit['spreads'].extend(dict(cik=str(c['cik']).zfill(10),report_date=str(c['report_date'])[:10],
            identifier=str(c['identifier']),expected_pct=str(c['agentA_value_pct'])) for c in corrections)


def _write(directory,audit,frame):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    with (directory/'input_admission_audit.csv').open('w',newline='',encoding='utf-8') as stream:
        writer=csv.DictWriter(stream,fieldnames=['path','admission_status','loaded','reason','sha256'])
        writer.writeheader();writer.writerows(audit['inputs'])
    with duckdb.connect(config={'threads':2,'memory_limit':'-1'}) as con:
        con.execute('CREATE TABLE expected(cik VARCHAR,report_date VARCHAR,identifier VARCHAR,expected_pct VARCHAR)')
        if audit['spreads']:
            con.executemany('INSERT INTO expected VALUES (?,?,?,?)',[tuple(row.values()) for row in audit['spreads']])
        if frame is not None and {'row_id','cik','report_date','bdc_investment_identifier','basis_spread'}<=set(frame.columns):
            con.register('written',frame)
            result=con.execute("""SELECT w.row_id,e.*,TRY_CAST(w.basis_spread AS DOUBLE) AS actual_pct
                FROM (SELECT DISTINCT * FROM expected) e LEFT JOIN written w
                ON lpad(CAST(w.cik AS VARCHAR),10,'0')=e.cik
                AND CAST(w.report_date AS VARCHAR)[:10]=e.report_date AND w.bdc_investment_identifier=e.identifier
                ORDER BY e.cik,e.report_date,e.identifier,w.row_id""").fetchdf()
        else:
            result=con.execute('SELECT NULL::VARCHAR AS row_id,*,NULL::DOUBLE AS actual_pct FROM expected').fetchdf()
        result.to_csv(directory/'spread_unit_audit.csv',index=False)


def capture_inputs(destination, *, output_parameter=None):
    def decorate(function):
        parameters = signature(function)
        @wraps(function)
        def wrapped(*args,**kwargs):
            selected = parameters.bind(*args, **kwargs).arguments.get(output_parameter) if output_parameter else None
            directory = Path(selected).parent if selected is not None else destination()
            audit=dict(inputs=[],spreads=[]);token=_audit.set(audit);frame=None
            try:
                from pipeline.correction_execution import session
                with session():
                    frame=function(*args,**kwargs)
                return frame
            finally:
                _audit.reset(token)
                _write(directory,audit,frame)
        return wrapped
    return decorate
