"""Reparse diagnosed source accessions inside an isolated candidate only.

Each registry entry names one cached instance whose rows the legacy
``bdc_holdings.csv`` lost to a diagnosed extractor defect. The candidate's
unified stage reparses exactly those instances with the frozen current parser
and merges the rows over the frozen legacy artifact, proving that no unrelated
accession changed. Expected row counts and fair-value sums pin the diagnosis.
"""
import os
from decimal import Decimal
from pathlib import Path

import duckdb
import pandas as pd

from pipeline.programme.artifacts import finalize_pair, literal
from pipeline.programme.core import ContractError, atomic_json, sha

ACCESSION='0001193125-23-145196'
SOURCE_SHA='d972ff4b49a5d32174cd525a4e506b0b96a59defb9ef5732f86590429a6e6520'

REFRESHES=(
    dict(cik='1588272',accession=ACCESSION,source_sha256=SOURCE_SHA,
         reason='dei:LegalEntityAxis explicit members were not recognised by the legacy extractor',
         expected_rows=39,expected_fair_value='48731529'),
    dict(cik='2006758',accession='0001193125-26-104070',
         source_sha256='8a1d66c71effecfbb84f7b7ddb78f5b3e4db076f883245e205a3b1ed0b7811e9',
         reason='43.9 MB instance with a >10 MB text node; libxml2 raised and the filing was recorded as parsed with zero records',
         expected_rows=489,expected_fair_value='1859063000'),
)


def refresh_accession(entry):
    from pipeline import config,bdc_filings
    workspace=config.PROJECT_ROOT.resolve()
    if workspace.name!='workspace' or workspace.parent.parent.name!='attempts':
        raise ContractError('Source refresh requires an isolated programme workspace')
    accession=entry['accession'];expected_sha=entry['source_sha256']
    source=config.BDC_XBRL_CACHE_DIR/entry['cik']/(accession.replace('-','')+'.xml')
    if sha(source)!=expected_sha: raise ContractError('Diagnosed source version changed: '+accession)
    path=config.BDC_HOLDINGS_FILE
    with duckdb.connect(config={'threads':2,'memory_limit':'-1'}) as con:
        metadata=con.execute('SELECT * FROM read_csv(?,all_varchar=true) WHERE accession_number=?',
            [str(config.BDC_FILINGS_INDEX_FILE),accession]).fetchdf()
        if len(metadata)!=1: raise ContractError('Refresh filing selection is not unique: '+accession)
        rows=bdc_filings._parse_single_filing(str(source),metadata.iloc[0].to_dict())
        frame=bdc_filings._deduplicate_bdc_holdings(pd.DataFrame(rows))
        total=sum(Decimal(str(value)) for value in frame.fair_value if str(value) not in ('','nan','None'))
        if len(frame)!=entry['expected_rows'] or total!=Decimal(entry['expected_fair_value']):
            raise ContractError('Parser does not reproduce the diagnosed source schedule for '+accession
                +': rows '+str(len(frame))+' fair value '+str(total))
        con.execute('CREATE TABLE prior AS SELECT * FROM read_csv(?,all_varchar=true)',[str(path)])
        prior_count=con.execute('SELECT count(*) FROM prior WHERE accession_number=?',[accession]).fetchone()[0]
        columns=[item[0] for item in con.execute('DESCRIBE prior').fetchall()]
        for column in columns:
            if column not in frame: frame[column]=''
        con.register('reparsed',frame[columns])
        projection=','.join('CAST("'+name+'" AS VARCHAR) AS "'+name+'"' for name in columns)
        con.execute('CREATE TABLE refreshed AS SELECT * FROM prior WHERE accession_number IS DISTINCT FROM ? UNION ALL SELECT '+projection+' FROM reparsed',[accession])
        difference=con.execute('SELECT count(*) FROM ((SELECT * FROM prior WHERE accession_number IS DISTINCT FROM ? EXCEPT ALL SELECT * FROM refreshed WHERE accession_number IS DISTINCT FROM ?) UNION ALL (SELECT * FROM refreshed WHERE accession_number IS DISTINCT FROM ? EXCEPT ALL SELECT * FROM prior WHERE accession_number IS DISTINCT FROM ?))',[accession]*4).fetchone()[0]
        if difference: raise ContractError('Source refresh changed an unrelated accession')
        pending=path.with_suffix('.refreshed.csv')
        con.execute('COPY (SELECT * FROM refreshed) TO '+literal(pending)+' (HEADER)')
        os.replace(pending,path)
        pair=finalize_pair(path,con)
    if sha(source)!=expected_sha: raise ContractError('Diagnosed source changed during refresh: '+accession)
    return dict(cik=entry['cik'],accession=accession,source_sha256=expected_sha,reason=entry['reason'],
        prior_rows=prior_count,reparsed_rows=len(frame),source_fair_value=str(total),
        unrelated_observation_difference=0,artifact=pair)


def refresh_diagnosed(entries=REFRESHES):
    """Apply every registry refresh serially and record one receipt."""
    from pipeline import config
    results=[refresh_accession(entry) for entry in entries]
    receipt=dict(refreshes=results,**{k:v for k,v in results[0].items()}) if results else dict(refreshes=[])
    atomic_json(config.OUTPUT_DIR/'source_refresh.json',receipt)
    return receipt


def refresh_nexpoint():
    """Backward-compatible single-accession refresh (NexPoint Q1-2023)."""
    return refresh_diagnosed([REFRESHES[0]])
