"""Freeze cached NAV and citation sources required by the current programme."""
from pathlib import Path
import re
import shutil

import duckdb

from pipeline.programme.core import ContractError,contained,sha


def freeze_refresh_support(root, frozen=None, *, support_files=None):
    """Validate reviewed wrapper dependencies before copying any candidate data.

    With a destination, overlay only those exact reviewed bytes. A cold twin
    keeps its base snapshot unchanged and never calls this function.
    """
    if support_files is None:
        from pipeline.programme.source_refresh import REFRESH_SUPPORT
        support_files=REFRESH_SUPPORT
    verified=[]
    seen=set()
    for item in support_files:
        relative=item['path']
        if (not re.fullmatch(r'(?:data/overrides/bdc_xbrl_wrappers/(?:[0-9]{10}|unlisted_bdc_xbrl_reference)|data/reference/cash_only_quarters)\.json',relative)
                or relative in seen or not re.fullmatch(r'[0-9a-f]{64}',item['sha256'])):
            raise ContractError('Invalid or repeated refresh support input: '+relative)
        seen.add(relative)
        source=contained(root,relative)
        if sha(source)!=item['sha256']:
            raise ContractError('Reviewed refresh support changed: '+relative)
        verified.append((source,item))
    records=[]
    for source,item in verified:
        if frozen is not None:
            destination=contained(frozen,item['path'],existing=False)
            destination.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(source,destination)
            if sha(source)!=item['sha256'] or sha(destination)!=item['sha256']:
                raise ContractError('Refresh support changed during snapshot: '+item['path'])
        records.append(dict(path=item['path'],sha256=item['sha256'],
            role='reviewed diagnosed-refresh support',reason=item['reason']))
    return records


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
    # Diagnosed refresh accessions may be absent from the old holdings (that is
    # the defect); freeze their instances and HTML so the candidate can reparse.
    from pipeline.programme.source_refresh import REFRESHES
    for entry in REFRESHES:
        for kind,extension in (('bdc_xbrl','xml'),('bdc_html','html')):
            inputs.add('data/raw/filings/'+kind+'/'+entry['cik']+'/'+entry['accession'].replace('-','')+'.'+extension)
    # A zero-position exception need not appear in the holdings source list.
    # Freeze its explicitly reviewed instance so public wording can replay it.
    exceptions=Path(root)/'data/reference/cash_only_quarters.json'
    if exceptions.is_file():
        from pipeline.programme.core import read_json
        package=read_json(exceptions)
        if package.get('schema_version')!='cash-only-quarter-exceptions.v1':
            raise ContractError('Unknown cash-only source package')
        for item in package['records']:
            cik,accession=item['cik'],item['accession']
            if not re.fullmatch(r'[0-9]{10}',cik) or not re.fullmatch(r'[0-9]{10}-[0-9]{2}-[0-9]{6}',accession):
                raise ContractError('Invalid cash-only source identity')
            relative='data/raw/filings/bdc_xbrl/'+str(int(cik))+'/'+accession.replace('-','')+'.xml'
            source=contained(root,relative)
            if sha(source)!=item['source_sha256']:
                raise ContractError('Cash-only source changed before snapshot')
            inputs.add(relative)
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
