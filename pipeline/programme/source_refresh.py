"""Reparse the diagnosed source accession inside an isolated candidate only."""
import os
from decimal import Decimal
from pathlib import Path

import duckdb
import pandas as pd

from pipeline.programme.artifacts import finalize_pair, literal
from pipeline.programme.core import ContractError, atomic_json, sha

ACCESSION='0001193125-23-145196'
SOURCE_SHA='d972ff4b49a5d32174cd525a4e506b0b96a59defb9ef5732f86590429a6e6520'


def refresh_nexpoint():
    from pipeline import config,bdc_filings
    workspace=config.PROJECT_ROOT.resolve()
    if workspace.name!='workspace' or workspace.parent.parent.name!='attempts':
        raise ContractError('Source refresh requires an isolated programme workspace')
    source=config.BDC_XBRL_CACHE_DIR/'1588272'/(ACCESSION.replace('-','')+'.xml')
    if sha(source)!=SOURCE_SHA: raise ContractError('Diagnosed NexPoint source version changed')
    path=config.BDC_HOLDINGS_FILE
    with duckdb.connect(config={'threads':2,'memory_limit':'-1'}) as con:
        metadata=con.execute('SELECT * FROM read_csv(?,all_varchar=true) WHERE accession_number=?',
            [str(config.BDC_FILINGS_INDEX_FILE),ACCESSION]).fetchdf()
        if len(metadata)!=1: raise ContractError('NexPoint filing selection is not unique')
        rows=bdc_filings._parse_single_filing(str(source),metadata.iloc[0].to_dict())
        frame=bdc_filings._deduplicate_bdc_holdings(pd.DataFrame(rows))
        if len(frame)!=39 or sum(Decimal(str(value)) for value in frame.fair_value)!=Decimal('48731529'):
            raise ContractError('NexPoint parser does not conserve the diagnosed source schedule')
        con.execute('CREATE TABLE prior AS SELECT * FROM read_csv(?,all_varchar=true)',[str(path)])
        prior_count=con.execute('SELECT count(*) FROM prior WHERE accession_number=?',[ACCESSION]).fetchone()[0]
        columns=[item[0] for item in con.execute('DESCRIBE prior').fetchall()]
        for column in columns:
            if column not in frame: frame[column]=''
        con.register('reparsed',frame[columns])
        projection=','.join('CAST("'+name+'" AS VARCHAR) AS "'+name+'"' for name in columns)
        con.execute('CREATE TABLE refreshed AS SELECT * FROM prior WHERE accession_number IS DISTINCT FROM ? UNION ALL SELECT '+projection+' FROM reparsed',[ACCESSION])
        difference=con.execute('SELECT count(*) FROM ((SELECT * FROM prior WHERE accession_number IS DISTINCT FROM ? EXCEPT ALL SELECT * FROM refreshed WHERE accession_number IS DISTINCT FROM ?) UNION ALL (SELECT * FROM refreshed WHERE accession_number IS DISTINCT FROM ? EXCEPT ALL SELECT * FROM prior WHERE accession_number IS DISTINCT FROM ?))',[ACCESSION]*4).fetchone()[0]
        if difference: raise ContractError('Source refresh changed an unrelated accession')
        pending=path.with_suffix('.refreshed.csv')
        con.execute('COPY (SELECT * FROM refreshed) TO '+literal(pending)+' (HEADER)')
        os.replace(pending,path)
        pair=finalize_pair(path,con)
    if sha(source)!=SOURCE_SHA: raise ContractError('NexPoint source changed during refresh')
    result=dict(accession=ACCESSION,source_sha256=SOURCE_SHA,prior_rows=prior_count,reparsed_rows=39,
        source_fair_value='48731529',unrelated_observation_difference=0,artifact=pair)
    atomic_json(config.OUTPUT_DIR/'source_refresh.json',result)
    return result
