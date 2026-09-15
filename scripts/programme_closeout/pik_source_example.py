"""Pin a native position-level PIK fact and its actual reporting duration."""
import json,os,threading
from pathlib import Path
from lxml import etree
import duckdb
from scripts.programme_closeout.candidate import atomic_json,sha
ROOT=Path(__file__).resolve().parents[2]
BASE=ROOT/'docs/production_stack/programme_closeout_evidence_2026-09-09'

def main():
    
    path=ROOT/'data/output/bdc_position_pik_evidence.csv'
    obligations=ROOT/'docs/production_stack/programme_pilot_evidence_2026-09-09/obligations_v2.csv'
    con=duckdb.connect();con.execute('SET threads=2');con.execute("SET memory_limit='-1'")
    records=con.execute('''SELECT e.* FROM read_csv(?,all_varchar=true) e WHERE position_level='True'
      AND try_cast(amount AS DOUBLE)>0 AND period=report_date AND report_date LIKE '202%-03-31'
      AND report_date>='2023-03-31' AND report_date<='2026-03-31'
      AND cik IN (SELECT distinct cik FROM read_csv(?,all_varchar=true)) ORDER BY cik,report_date,context_id LIMIT 4''',[str(path),str(obligations)]).df().to_dict('records')
    con.close();results=[]
    for r in records:
        acc=r['accession_number'].replace('-','');xml=ROOT/'data/raw/filings/bdc_xbrl'/str(int(r['cik']))/(acc+'.xml')
        if not xml.is_file() or xml.stat().st_size>120_000_000:continue
        tree=etree.parse(str(xml),etree.XMLParser(no_network=True,resolve_entities=False,huge_tree=True))
        contexts=tree.xpath('//*[local-name()="context" and @id=$ctx]',ctx=r['context_id'])
        facts=tree.xpath('//*[@contextRef=$ctx and local-name()=$concept]',ctx=r['context_id'],concept=r['concept'])
        if len(contexts)!=1 or not facts:continue
        for f in facts:
            units=tree.xpath('//*[local-name()="unit" and @id=$unit]',unit=f.get('unitRef'))
            results.append(dict(cik=r['cik'],accession=r['accession_number'],source_path=str(xml.relative_to(ROOT)),source_sha256=sha(xml),
              concept=f.tag,value=f.text,decimals=f.get('decimals'),fact_xpath=tree.getpath(f),
              context_xml=etree.tostring(contexts[0],encoding='unicode'),unit_xml=[etree.tostring(u,encoding='unicode') for u in units],
              start=contexts[0].xpath('string(.//*[local-name()="startDate"])'),end=contexts[0].xpath('string(.//*[local-name()="endDate"])'),
              evidence_kind=r['evidence_kind'],matched_identifier=r['matched_identifier'],
              interpretation='Position-level positive PIK-income fact for the explicit source duration. Not a schedule-rate proxy, and not evidence of distress or a terms amendment.',
              review='Native fact/context/unit independently re-read; mapping to a unique holding and point-in-time status still needs separate evidence. Development, not hold-out.'))
    if not results:raise ValueError('No native positive PIK source example resolved')
    atomic_json(BASE/'review/pik_native_examples.json',results)
    print(json.dumps([dict(cik=r['cik'],value=r['value'],start=r['start'],end=r['end'],evidence=r['evidence_kind']) for r in results]),flush=True);
if __name__=='__main__':main()
