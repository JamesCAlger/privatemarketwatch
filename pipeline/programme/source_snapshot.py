"""Freeze cached NAV and citation sources required by the current programme."""
from pathlib import Path
import shutil

import duckdb

from pipeline.programme.core import ContractError,sha


def include_sources(root,frozen):
    root,frozen=Path(root),Path(frozen)
    inputs=set()
    unavailable=[]
    universe=frozen/'data/output/combined_universe.csv'
    holdings=frozen/'data/output/private_markets_holdings.csv'
    bdc=frozen/'data/output/bdc_holdings.csv'
    with duckdb.connect(config={'threads':2,'memory_limit':'-1'}) as con:
        if universe.is_file():
            ciks=con.execute("SELECT DISTINCT lpad(cik,10,'0') FROM read_csv(?,all_varchar=true) WHERE vehicle_type='bdc'",[str(universe)]).fetchall()
            for cik, in ciks:
                if not cik.isdigit(): raise ContractError('Invalid source CIK')
                inputs.add('data/raw/companyfacts_cache/'+cik+'.json')
        if holdings.is_file():
            # Only BDC observations in the contracted history window need HTML.
            docs=con.execute("SELECT cik,accession_number,count(*) FROM read_csv(?,all_varchar=true) WHERE source='bdc' AND report_date BETWEEN '2023-03-31' AND '2026-03-31' GROUP BY cik,accession_number",[str(holdings)]).fetchall()
            for cik,accession,count in docs:
                if not cik or not cik.isdigit(): raise ContractError('Invalid source CIK')
                if not accession or not accession.replace('-','').isdigit():
                    unavailable.append(dict(cik=cik,accession_number=accession,rows=count,status='unavailable',
                        reason='Missing or invalid observation accession; no source path constructed'))
                    continue
                inputs.add('data/raw/filings/bdc_html/'+str(int(cik))+'/'+accession.replace('-','')+'.html')
        if bdc.is_file():
            # Monetary unitRef IDs require the exact document definitions, also
            # for historical rows outside the public citation window.
            docs=con.execute('SELECT DISTINCT cik,accession_number FROM read_csv(?,all_varchar=true)',[str(bdc)]).fetchall()
            for cik,accession in docs:
                if not cik or not cik.isdigit() or not accession or not accession.replace('-','').isdigit():
                    unavailable.append(dict(cik=cik,accession_number=accession,status='unavailable',
                        reason='Missing or invalid BDC source identity; no unit path constructed'))
                    continue
                inputs.add('data/raw/filings/bdc_xbrl/'+str(int(cik))+'/'+accession.replace('-','')+'.xml')
    # This accession is absent from the old holdings, precisely the diagnosed defect.
    for kind,extension in (('bdc_xbrl','xml'),('bdc_html','html')):
        inputs.add('data/raw/filings/'+kind+'/1588272/000119312523145196.'+extension)
    records=unavailable
    for index,name in enumerate(sorted(inputs),1):
        source=root/name
        if not source.is_file():
            records.append(dict(path=name,status='unavailable'));continue
        destination=frozen/name;destination.parent.mkdir(parents=True,exist_ok=True)
        before=sha(source)
        shutil.copy2(source,destination)
        if sha(source)!=before or sha(destination)!=before: raise ContractError('Cached source changed during snapshot: '+name)
        records.append(dict(path=name,status='frozen',sha256=before))
        if index%100==0: print('Cached support sources frozen: '+str(index)+'/'+str(len(inputs)),flush=True)
    return records
