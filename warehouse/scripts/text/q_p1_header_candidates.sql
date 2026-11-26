-- Slice P, 2026-11-26: header-row candidates per schedule table (rows with no facts, before the table's first position
-- row, with at least 3 non-empty cells): how many per table, and whether they are adjacent. Read-only.
with fv as (
    select fr.cik, fr.accession, pl.row_index
    from int_field_read fr
    join stg_filed_fact_placement pl on pl.accession = fr.accession and pl.fact_id = fr.fact_id
    where fr.field = 'fair_value' and fr.status = 'read' and pl.row_index is not null and not pl.in_hidden
)
, t as (
    select fv.cik, fv.accession, r.table_index, min(r.row_in_table) as first_pos
    from fv join stg_filed_document_row r on r.accession = fv.accession and r.row_index = fv.row_index
    group by all
)
, q as (
    select t.cik, t.accession, t.table_index, r.row_in_table
    from t join stg_filed_document_row r on r.accession = t.accession and r.table_index = t.table_index
    where r.fact_count = 0 and r.row_in_table < t.first_pos
      and len(list_filter(r.cells, x -> trim(replace(x, chr(160), ' ')) <> '')) >= 3
)
, per as (
    select t.cik, t.accession, t.table_index, t.first_pos, count(q.row_in_table) as n_q
        , max(q.row_in_table) - min(q.row_in_table) as spread_rows, min(q.row_in_table) as first_q
    from t left join q using (cik, accession, table_index) group by all
)
select cik, n_q, spread_rows, first_q, count(*) as tables, min(first_pos) as min_first_pos, max(first_pos) as max_first_pos
from per group by all order by cik, tables desc
