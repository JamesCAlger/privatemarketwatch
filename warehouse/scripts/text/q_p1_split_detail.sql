-- Slice P, 2026-11-26: tagged fields whose placed facts fall under more than one header signature in one table: which
-- signatures, how many facts under each, and one example cell text per signature. Read-only.
with f as (
    select fr.cik, fr.accession, cc.table_index, fr.field, cc.header_signature, count(*) as n, min(cc.text) as example
    from int_field_read fr
    join stg_filed_fact_placement pl on pl.accession = fr.accession and pl.fact_id = fr.fact_id
    join int_page_cell_column cc on cc.accession = pl.accession
        and cc.row_index = coalesce(pl.row_index, pl.shown_row_index)
        and cc.cell_index = coalesce(pl.cell_index, pl.shown_cell_index)
    where fr.status = 'read' and cc.header_signature is not null
    group by all
)
select cik, accession, table_index, field, string_agg(header_signature || '=' || n || ' [' || example || ']', ' ; ') as split
from f
where (accession, table_index, field) in (
    select (accession, table_index, field) from f group by accession, table_index, field having count(*) > 1)
group by all order by 1, 2, 3, 4
