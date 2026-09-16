"""Replay approved cash-only source exceptions before adding public wording."""
from datetime import date
from decimal import Decimal
import json
from pathlib import Path
import re

from pipeline.context_inventory import CASH_ONLY_PUBLIC_WORDING, scan_instance
from pipeline.programme.core import sha


def verify_cash_only(result, *, cik, quarter, source_sha256):
    """An absent holdings row alone cannot establish this source exception."""
    counts=result.get('counts',{})
    if (result.get('cik')!=cik or result.get('quarter')!=quarter
            or result.get('sha256')!=source_sha256 or not result.get('source_complete')
            or not result.get('target_instant_contexts')
            or result.get('document_period_ends')!=[quarter]
            or counts.get('confirmed_position')!=0 or counts.get('unresolved')!=0
            or not result.get('cash_only_contexts')
            or result.get('cash_equivalent_status')!='reported'):
        raise ValueError('Cash-only source exception is not established: '+cik+' '+quarter)
    cash=Decimal(result.get('cash_equivalent_total') or 'NaN')
    if not cash.is_finite() or cash<=0:
        raise ValueError('Cash-only exception needs a positive disclosed cash balance')


def collect_cash_only_statuses(con, *, reference, cache, cohort, start, end):
    reference=Path(reference)
    if not reference.is_file():
        return []
    expected=sha(reference)
    package=json.loads(reference.read_text(encoding='utf-8'))
    if package.get('schema_version')!='cash-only-quarter-exceptions.v1' or set(package)!={'schema_version','records'}:
        raise ValueError('Unknown cash-only exception package')
    seen=set()
    result=[]
    for record in package['records']:
        if set(record)!={'cik','quarter','accession','source_sha256','decision'}:
            raise ValueError('Malformed cash-only exception record')
        cik,quarter,accession=record['cik'],record['quarter'],record['accession']
        if (not re.fullmatch(r'\d{10}',cik) or not re.fullmatch(r'\d{10}-\d{2}-\d{6}',accession)
                or not re.fullmatch(r'[a-f0-9]{64}',record['source_sha256']) or not record['decision']
                or date.fromisoformat(quarter).isoformat()!=quarter or (cik,quarter) in seen):
            raise ValueError('Invalid or duplicate cash-only exception identity')
        seen.add((cik,quarter))
        if cik not in cohort or not start<=quarter<=end:
            continue
        rows=con.execute('SELECT count(*) FROM history WHERE cik=? AND report_date=?::DATE',[cik,quarter]).fetchone()[0]
        if rows:
            continue
        source=Path(cache)/str(int(cik))/(accession.replace('-','')+'.xml')
        if not source.is_file() or sha(source)!=record['source_sha256']:
            raise ValueError('Cash-only exception source changed or is unavailable')
        observed=scan_instance(source,cik,quarter)
        verify_cash_only(observed,cik=cik,quarter=quarter,source_sha256=record['source_sha256'])
        if sha(source)!=record['source_sha256']:
            raise ValueError('Cash-only source changed during verification')
        result.append(dict(cik=cik,quarter=quarter,code='eligible_no_position_facts',
            message=CASH_ONLY_PUBLIC_WORDING,accession_number=accession,
            source_sha256=record['source_sha256'],reference_sha256=expected))
    if sha(reference)!=expected:
        raise ValueError('Cash-only exception package changed during verification')
    return result
