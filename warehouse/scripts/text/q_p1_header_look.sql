-- Slice P, 2026-11-26: header lines of sample tables: Blue Owl 2025-12-31 and 2026-03-31, HPS tables with the "."
-- signature. Read-only.
with pick as (
    select t.* from int_page_table t
    where (t.cik = '0001812554' and t.report_date in ('2025-12-31', '2026-03-31', '2025-09-30'))
       or (t.cik = '0001838126' and exists (
            select 1 from int_page_column c where c.accession = t.accession and c.table_index = t.table_index
              and c.header_signature = '.'))
    qualify row_number() over (partition by t.cik, t.report_date, t.header_status order by t.table_index) = 1
)
select p.cik, p.report_date, p.table_index, p.header_status, r.row_in_table, r.fact_count, r.cell_rowspans, r.cell_colspans
    , list_transform(r.cells, x -> left(trim(x), 18)) as cells
from pick p
join stg_filed_document_row r on r.accession = p.accession and r.table_index = p.table_index
where r.row_in_table <= p.header_last_row_in_table + 2
order by 1, 2, 3, 5
