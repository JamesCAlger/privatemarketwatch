-- Slice P, 2026-11-26: rows directly above a one_line header that have no facts and 1 or 2 non-empty cells (a group
-- line above the header), by fund and text. Read-only.
select t.cik, t.header_status, string_agg(c.text, ' | ' order by c.col_start) as texts
    , max(c.col_end - c.col_start + 1) as widest, min(t.width) as table_width, count(distinct t.accession || t.table_index) as tables
    , count(distinct t.accession) as filings
from int_page_table t
join stg_filed_document_row r on r.accession = t.accession and r.table_index = t.table_index
    and r.row_index = t.header_row_index - 1 and r.fact_count = 0
join int_page_cell c on c.accession = r.accession and c.row_index = r.row_index
where t.header_status in ('one_line', 'two_lines')
group by t.cik, t.header_status, t.accession, t.table_index
having count(*) between 1 and 2
order by 1
