-- Slice P, 2026-11-26: (1) leaves of one Blue Owl two-line table; (2) Blue Owl rows whose width is not the table's;
-- (3) tagged fields whose placed facts split across signatures in one table, by fund and field. Read-only.
select '1 leaves' as k, c.cik, c.table_index::varchar as a, c.col_start::varchar as b, c.zone_end::varchar as c
    , c.header_signature as d, null::bigint as n
from int_page_column c
where c.accession = (select max(accession) from int_page_table where cik = '0001812554' and header_form = 'two_candidates')
  and c.table_index = (select min(table_index) from int_page_table where header_form = 'two_candidates'
                       and accession = (select max(accession) from int_page_table where cik = '0001812554' and header_form = 'two_candidates'))
union all
select '2 width', t.cik, t.header_form, c.span_rule, t.width::varchar
    , left(string_agg(c.col_start || ':' || left(c.text, 14), ' | ' order by c.cell_index), 200), count(distinct c.row_index)
from int_page_cell c join int_page_table t using (accession, table_index)
where not c.row_width_ok
group by t.cik, t.header_form, c.span_rule, t.width, c.accession, c.row_index
union all
select '3 split', x.cik, x.field, null, null, null, count(*)
from (
    select fr.cik, fr.accession, cc.table_index, fr.field, count(distinct cc.header_signature) as sigs
    from int_field_read fr
    join stg_filed_fact_placement pl on pl.accession = fr.accession and pl.fact_id = fr.fact_id
    join int_page_cell_column cc on cc.accession = pl.accession
        and cc.row_index = coalesce(pl.row_index, pl.shown_row_index)
        and cc.cell_index = coalesce(pl.cell_index, pl.shown_cell_index)
    where fr.status = 'read' and cc.header_signature is not null
    group by all
) x
where x.sigs > 1
group by all
order by 1, 2, 3, 4
