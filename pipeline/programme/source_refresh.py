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

# These reviewed files are necessary to stage the reparsed rows correctly.
# Freezing current Python alone would retain the base candidate's old wrapper.
REFRESH_SUPPORT=(
    dict(path='data/overrides/bdc_xbrl_wrappers/0002008748.json',
         sha256='034e45de3cc88751e7543e3b808d3d68ec986fff3c2fa34a422aa614f0c7bec8',
         reason='Approved Lord Abbett wrapper v2 for the seven diagnosed accession refreshes'),
    dict(path='data/overrides/bdc_xbrl_wrappers/unlisted_bdc_xbrl_reference.json',
         sha256='6641614a571385f2e3d9413ade46ab7e8b94c4867c1fa0327c31e54903b1d5c3',
         reason='Same cohort and metadata; Lord Abbett wrapper_version changes from 1 to 2'),
)

REFRESHES=(
    dict(cik='1588272',accession=ACCESSION,source_sha256=SOURCE_SHA,
         reason='dei:LegalEntityAxis explicit members were not recognised by the legacy extractor',
         expected_rows=39,expected_fair_value='48731529'),
    dict(cik='2006758',accession='0001193125-26-104070',
         source_sha256='8a1d66c71effecfbb84f7b7ddb78f5b3e4db076f883245e205a3b1ed0b7811e9',
         reason='43.9 MB instance with a >10 MB text node; libxml2 raised and the filing was recorded as parsed with zero records',
         expected_rows=489,expected_fair_value='1859063000'),
    # Explicit-member position rules (pipeline/explicit_contexts.py, 2026-09-15).
    # expected_fair_value pins the deduplicated parser output for the whole
    # instance (all periods, before wrapper aggregate filtering); the own-book
    # conservation check against the filer total is recorded in the reason.
    dict(cik='1634452',accession='0001193125-23-145163',
         source_sha256='25359fe2fe7507aa77d9d5cb4e39c3295c44c13bd7e1aa02a47528b946dc00f3',
         reason='AB Private Credit Q1-2023: positions on dei:LegalEntityAxis + instrument axes; 448 rows = companyfacts total 1,179,343,662 exactly',
         expected_rows=448,expected_fair_value='1179343662'),
    dict(cik='1634452',accession='0001193125-23-212335',
         source_sha256='7145a40cb01719c1815a0f6824444599aa632ac3ce84867ecdd05096eb981a60',
         reason='AB Private Credit Q2-2023: same pattern; 38 mis-dated 12/31/2022 lien-family rows excluded by period scope; 461 rows = total 1,227,572,852 exactly',
         expected_rows=461,expected_fair_value='1227572852'),
    dict(cik='1860424',accession='0000950170-23-021345',
         source_sha256='bf6db594786914834f6fc9142e49fa6f3c966ed64f0f233703b276235f503299',
         reason='Onex Direct Lending Q1-2023: positions on EquityMethodInvestmentNonconsolidatedInvesteeAxis + LongtermDebtTypeAxis; 57 rows = 521,760,590 vs total 526,177,088 (-0.84%, two industry subtotals exceed their tagged rows in source)',
         expected_rows=57,expected_fair_value='521760590'),
    dict(cik='2008748',accession='0000930413-24-003190',
         source_sha256='b8b5862bffa8174f6c0ab7a0df8958442bf485b5122a7a2ba32bff323d31abf0',
         reason='Lord Abbett Q3-2024: positions on srt:OwnershipAxis; 33 rows = companyfacts total 313,562,000 exactly',
         expected_rows=33,expected_fair_value='313562000'),
    dict(cik='2008748',accession='0000930413-25-000900',
         source_sha256='3bc4abcbab2563d23b849c31007a2b57ef9e9d578f1a1f1be295cc0fd39bdd21',
         reason='Lord Abbett FY2024 10-K: 50 rows = total 472,588,000 exactly',
         expected_rows=50,expected_fair_value='472588000'),
    dict(cik='2008748',accession='0000930413-25-001811',
         source_sha256='93cc9a5dee1c58a0c756eb0593fb8729e49e221550072dcb91510eca81793a58',
         reason='Lord Abbett Q1-2025: 61 rows = total 591,274,000 exactly',
         expected_rows=61,expected_fair_value='591274000'),
    dict(cik='2008748',accession='0000930413-25-002470',
         source_sha256='cae84c02ec05d12e2e00ec84a6996296d98dc6c2cdaf771803c7d125e2b8a9b9',
         reason='Lord Abbett Q2-2025: 145 current + 91 comparative rows incl. typed category rollups filtered later by the wrapper; parser output pinned',
         expected_rows=236,expected_fair_value='4962957000'),
    dict(cik='2008748',accession='0000930413-25-003431',
         source_sha256='892a702af2d53a1c96d2185a191055d03b83c12541516428974f5cdd4f88d218',
         reason='Lord Abbett Q3-2025: 158 current + comparatives incl. category rollups; parser output pinned',
         expected_rows=251,expected_fair_value='7034064000'),
    dict(cik='2008748',accession='0000930413-26-000841',
         source_sha256='031821ae515ce44340d7c7682d3114e7f5c95f4ba68af7722bb6e6440f08e750',
         reason='Lord Abbett FY2025 10-K: 163 current rows; own-book FV 1,309,928,000 equals filer total exactly (explicit_contexts control); parser output pinned',
         expected_rows=230,expected_fair_value='7397552000'),
    dict(cik='2008748',accession='0000930413-26-001612',
         source_sha256='14a4e423bbb2b070b8bc227682db0e9fad7bd893982f75ddc9f5bc449cc7e2d8',
         reason='Lord Abbett Q1-2026: 185 current rows; own-book FV 1,412,116,000 vs total 1,413,006,000 (890,000 = filer-tagged equity on the industry axis); parser output pinned',
         expected_rows=350,expected_fair_value='12325952000'),
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
