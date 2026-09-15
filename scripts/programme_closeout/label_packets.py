"""Create bounded literal-source packets for legacy label discrepancies."""
import csv,json,os,threading,re
from pathlib import Path
from collections import Counter
from lxml import etree
from scripts.programme_closeout.candidate import sha,atomic_json
from scripts.programme_reference.source_reader import clean,local
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'docs/production_stack/programme_closeout_evidence_2026-09-09/labels'
def main():
    OUT.mkdir(parents=True,exist_ok=True)
    comparison=list(csv.DictReader((ROOT/'docs/production_stack/programme_pilot_evidence_2026-09-09/legacy_label_comparison.csv').open()))
    selected={}
    for r in comparison:
        if r['legacy_error']=='True' or r['join_count']!='1':selected.setdefault(r['label_key'],[]).append(r)
    assert len(selected)<=30
    labels={r['_key']:r for r in map(json.loads,(ROOT/'data/gold/labels/position_labels.jsonl').read_text().splitlines())}
    results=[];grouped={}
    for key,fields in selected.items():
        label=labels[key];grouped.setdefault(label.get('source_ref',{}).get('doc',''),[]).append((label,fields))
    for source,items in grouped.items():
        path=ROOT/source
        tree=etree.parse(str(path),etree.HTMLParser(no_network=True,recover=True,huge_tree=True)) if source and path.is_file() and path.stat().st_size<120_000_000 else None
        docsha=sha(path) if tree is not None else None
        text=clean(tree.getroot()) if tree is not None else ''
        contexts={n.get('id'):clean(n) for n in tree.xpath('//*[substring(name(), string-length(name()) - 6) = "context"]')} if tree is not None else {}
        rows=tree.xpath('//tr[not(.//tr)]') if tree is not None else []
        for label,fields in items:
            ident=label['source_identifier'];needle=ident
            # This is a review search, never a label/source join.
            for sep in (' - ',' | ', ', First',', Senior',', Second',', Common',', Preferred'):
                needle=needle.split(sep)[0]
            needle=needle[:80].strip()
            for specific in ('Ivy Hill Asset Management','Senior Direct Lending Program','AthenaHealth','Denali Equity Holdings',
                             'Sentinel Buyer','Aurelia Netherlands','Blue Owl Cross-Strategy Opportunities','OCIC SLF LLC'):
                if specific in ident:needle=specific
            matches=[]
            candidate_rows=[]
            for row in rows:
                if needle.casefold() not in clean(row).casefold():continue
                candidate_rows.append(row)
                candidate_rows.extend(row.xpath('following-sibling::tr[position()<=3]'))
            seen=set()
            for row in candidate_rows:
                xpath=tree.getpath(row)
                if xpath in seen:continue
                seen.add(xpath)
                table=row.xpath('ancestor::table[1]')[0]
                matches.append(dict(xpath=tree.getpath(row),cells=[clean(c) for c in row.xpath('./td|./th')],
                    table_xpath=tree.getpath(table),opening=[clean(r) for r in table.xpath('./tr[position()<=3]')],
                    facts=[dict(concept=f.get('name'),context=f.get('contextref'),context_text=contexts.get(f.get('contextref')),unit=f.get('unitref'),text=clean(f),scale=f.get('scale')) for f in row.xpath('.//*[@contextref and @name]')]))
            results.append(dict(key=label['_key'],label=label,flagged_fields=fields,path=source,source_sha256=docsha,
                   search_needle=needle,matches=matches[:90],match_count=len(matches),
                   passages=[text[max(0,m.start()-120):m.end()+600] for m in list(re.finditer(re.escape(needle),text,re.I))[:12]],
                   status='literal_review_candidates' if tree is not None else 'source_unavailable'))
        print('Label source '+str(source)+' reviewed',flush=True)
    atomic_json(OUT/'packets.json',results)
    summary=[dict(key=r['key'],source=r['path'],needle=r['search_needle'],matches=r['match_count'],
        flags=[dict(field=f['field'],reference=f['reference'],candidate=f['candidate'],join=f['join_count']) for f in r['flagged_fields']]) for r in results]
    atomic_json(OUT/'summary.json',summary);print(json.dumps(summary,ensure_ascii=True),flush=True);
if __name__=='__main__':main()
