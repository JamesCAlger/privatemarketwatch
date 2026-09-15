from pathlib import Path
import shutil

import duckdb
import pandas as pd
import pytest

from pipeline import config,bdc_filings
from pipeline.programme import source_refresh
from pipeline.programme.artifacts import SCHEMAS


@pytest.mark.needs_cache
def test_cached_nexpoint_reparse_restores_schedule_and_preserves_other_accessions(tmp_path,monkeypatch):
    source=config.BDC_XBRL_CACHE_DIR/'1588272'/'000119312523145196.xml'
    if not source.is_file(): pytest.skip('Diagnosed cached filing unavailable')
    workspace=tmp_path/'attempts/test/workspace'
    output=workspace/'data/output';output.mkdir(parents=True)
    cache=workspace/'data/raw/filings/bdc_xbrl'
    dest=cache/'1588272'/source.name;dest.parent.mkdir(parents=True)
    shutil.copy2(source,dest)
    raw=output/'bdc_holdings.csv'
    schema=SCHEMAS['bdc_holdings.csv']
    prior=pd.DataFrame([{**dict.fromkeys(schema,''),'cik':'0000000123',
        'accession_number':'other','investment_identifier':'Other loan','fair_value':100,'report_date':'2026-03-31'}])
    prior[list(schema)].to_csv(raw,index=False)
    index=output/'bdc_filings_index.csv'
    pd.DataFrame([dict(cik='0001588272',accession_number=source_refresh.ACCESSION,entity_name='NexPoint Capital',
        form_type='10-Q',report_date='2023-03-31',filing_date='2023-05-15')]).to_csv(index,index=False)
    for name,value in dict(PROJECT_ROOT=workspace,OUTPUT_DIR=output,BDC_XBRL_CACHE_DIR=cache,
        BDC_HOLDINGS_FILE=raw,BDC_FILINGS_INDEX_FILE=index).items():
        monkeypatch.setattr(config,name,value)
    monkeypatch.setattr(bdc_filings,'BDC_DEDUPE_AXIS_SPLITS_FILE',output/'splits.csv')
    result=source_refresh.refresh_nexpoint()
    assert result['prior_rows']==0 and result['reparsed_rows']==39
    assert result['unrelated_observation_difference']==0
    with duckdb.connect() as con:
        assert con.execute('SELECT count(*) FROM read_parquet(?)',[str(raw.with_suffix('.parquet'))]).fetchone()[0]==40
        assert con.execute("SELECT sum(fair_value) FROM read_parquet(?) WHERE cik='0001588272'",[str(raw.with_suffix('.parquet'))]).fetchone()[0]==48731529
