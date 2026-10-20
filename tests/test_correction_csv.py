"""Main correction CSV keeps legacy scope and isolates repeated source contexts."""
import csv
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts/v05_evidence'))
from correction_csv import correction_key, append_record, spec_context
from pipeline.unified_holdings import _apply_row_corrections

COLS=['cik','report_date','accession_number','bdc_investment_identifier','field','value',
      'reason','source_evidence','author','date_added','src_context_id']

def record(context=''):
    return append_record(COLS,cik='0001918712',quarter='2025-03-31',accession='0001918712-25-000030',
        identifier='Repeated member',field='issuer_name',value='Correct company',reason='Printed row',
        evidence='cached filing',author='test',added_on='2026-10-20',context=context)

@pytest.mark.parametrize('context,expected',[('', ['Correct company','Correct company']),
    ('c-802',['Correct company','Original']),('c-999',['Original','Original'])])
def test_main_csv_legacy_and_exact_context_scope(tmp_path,context,expected):
    row=record(context)
    p=tmp_path/'corrections.csv'
    with p.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=COLS);w.writeheader();w.writerow(row)
    base={k:row[k] for k in ['cik','report_date','accession_number','bdc_investment_identifier']}
    frame=pd.DataFrame([{**base,'source':'bdc','issuer_name':'Original','src_context_id':ctx} for ctx in ['c-802','c-806']])
    result=_apply_row_corrections(frame,corrections_path=p)
    assert result.issuer_name.tolist()==expected

def test_append_dedup_keeps_contexts_distinct_and_legacy_blank():
    legacy=record();legacy.pop('src_context_id')
    assert correction_key(legacy)==correction_key(record(''))
    assert len({correction_key(legacy),correction_key(record('c-802')),correction_key(record('c-806'))})==3
    assert list(record('c-802'))==COLS
    with pytest.raises(ValueError,match='requires src_context_id'):
        append_record(COLS[:-1],cik='1',quarter='2025-03-31',accession='a',identifier='b',field='issuer_name',
            value='c',reason='d',evidence='e',author='f',added_on='g',context='c-802')

def test_source_context_metadata_does_not_narrow_legacy_spec_scope():
    assert spec_context({'context':'source-evidence-context'})==''
    assert spec_context({'context':'source-evidence-context','correction_context':'c-802'})=='c-802'
