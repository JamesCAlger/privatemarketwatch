"""Small per-document review summaries; source-only, no candidate output values."""
import csv,json
from pathlib import Path
from collections import defaultdict
from decimal import Decimal
OUT=Path(__file__).parent
tables=[];anchors=[]
for p in sorted((OUT/'sources').glob('*.json')):
    doc=json.loads(p.read_text());bytable=defaultdict(list)
    for row in doc.get('source_candidates',[]):bytable[row['table_xpath']].append(row)
    for table in doc.get('tables',[]):
        rows=bytable[table['table_xpath']]
        if not rows:continue
        vals=[Decimal(f['value']) for r in rows for f in r['facts'] if f['field']=='fair_value' and f['value'] is not None]
        tables.append({'reference_id':doc['reference_id'],'table_xpath':table['table_xpath'],'rows':len(rows),
          'unique_contexts':len({r['context_id'] for r in rows}),'fv_fact_sum':str(sum(vals)),'total_word_rows':sum(r['total_word_flag'] for r in rows),
          'heading':' | '.join(table['preceding'][:6])[-1700:],'opening':' | '.join(table['opening_rows'])[:1200],
          'first_source_row':' | '.join(rows[0]['cells'])[:400],'last_source_row':' | '.join(rows[-1]['cells'])[:400]})
    for a in doc.get('anchor_candidates',[]):
        anchors.append({'reference_id':doc['reference_id'],'concept':a['concept'],'value':a['value'],'currency':a['currency'],
         'context_id':a['context_id'],'row_xpath':a['row_xpath'],'row':' | '.join(a['cells'])[:1400]})
for name,rr in [('source_tables.csv',tables),('source_anchors.csv',anchors)]:
    with (OUT/name).open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=list(rr[0]));w.writeheader();w.writerows(rr)
print(json.dumps({'tables':len(tables),'anchors':len(anchors)}))
