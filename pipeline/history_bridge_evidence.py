"""Resolve admitted HTML bridge maturity anchors against the pinned source."""
from datetime import date
import hashlib
import re

import pandas as pd

DATE=re.compile(r'(?<!\d)(\d{1,2})/(\d{1,2})/(\d{4}|\d{2})(?!\d)')


def bridge_cells(tree,source_hash,records,*,reference_tables=None):
    """Visit bridge anchors, never holdings rows; ambiguous cells remain absent."""
    tables=[]
    for table in tree.xpath('//table'):
        rows=[(row,row.xpath('.//td|.//th')) for row in table.xpath('.//tr')]
        rows=[row for row in rows if row[1]]
        if rows: tables.append(rows)
    found=[]
    for row in records:
        if row['html_sha256']!=source_hash: continue
        ti,ri=int(row['table_index']),int(row['row_index'])
        if not (0<=ti<len(tables) and 0<=ri<len(tables[ti])): continue
        if reference_tables is not None:
            rendered=[]
            for cell in tables[ti][ri][1]:
                rendered.append(' '.join(' '.join(cell.itertext()).split()).replace('\u200b',''))
                try: colspan=int(cell.get('colspan','1'))
                except ValueError: colspan=1
                rendered.extend(['']*max(0,colspan-1))
            if not (ti<len(reference_tables) and ri<len(reference_tables[ti])
                    and rendered==reference_tables[ti][ri]): continue
        target=str(row['maturity_date'])[:10]
        candidates=[]
        for cell in tables[ti][ri][1]:
            text=' '.join(''.join(cell.itertext()).split()).replace('\u200b','')
            dates=[]
            for month,day,year in DATE.findall(text):
                try: dates.append(date(int(year)+(2000 if len(year)==2 else 0),int(month),int(day)).isoformat())
                except ValueError: pass
            if dates==[target]: candidates.append((cell,text))
        if len(candidates)!=1: continue
        cell,text=candidates[0]
        fragment='evidence-'+hashlib.sha256((source_hash+f':bridge:t{ti}:r{ri}:maturity_date').encode()).hexdigest()[:24]
        cell.set('data-evidence-anchor',fragment)
        found.append(dict(raw_id_lower=row['raw_id_lower'],report_date=str(row['report_date'])[:10],
            maturity_date=target,source_text=text,fragment=fragment,
            override=f'maturity_date=bridge:{source_hash[:8]}:t{ti}:r{ri}'))
    return found


def attach(con,tree,bridges,*,cik,accession,source_hash,release_id,href,raw_html):
    selected=bridges[(bridges.cik==str(cik).zfill(10)) & (bridges.accession_number==accession)]
    if selected.empty: return
    # The bridge store is small reference data. Only its source anchors are walked.
    from pipeline.html_extract import _extract_tables
    cells=bridge_cells(tree,source_hash,selected.to_dict('records'),reference_tables=_extract_tables(raw_html))
    if not cells: return
    con.register('bridge_cells',pd.DataFrame(cells))
    con.execute("""INSERT INTO history_evidence SELECT h.row_id,'maturity_date',to_json(struct_pack(
        status := 'direct',release_id := ?,row_id := h.row_id,field := 'maturity_date',href := ?||b.fragment,
        source_text := b.source_text,source_sha256 := ?,accession_number := h.accession_number,
        locator_kind := 'admitted_html_bridge',bridge_anchor := b.override))
        FROM history h JOIN bridge_cells b ON lower(trim(h.bdc_investment_identifier))=b.raw_id_lower
        AND CAST(h.report_date AS VARCHAR)=b.report_date AND CAST(h.maturity_date AS VARCHAR)=b.maturity_date
        WHERE h.cik=? AND h.accession_number=? AND h.maturity_precision='day'
        AND list_contains(string_split(coalesce(h.src_field_overrides,''),';'),b.override)
        AND coalesce(h.corrected_fields,'') NOT LIKE '%maturity_date%'
        AND NOT EXISTS(SELECT 1 FROM history_evidence e WHERE e.row_id=h.row_id AND e.field='maturity_date')
        QUALIFY count(*) OVER(PARTITION BY h.row_id)=1""",[release_id,href,source_hash,cik,accession])
    con.unregister('bridge_cells')
