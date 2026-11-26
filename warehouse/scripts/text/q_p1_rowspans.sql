-- Slice P, 2026-11-26: rows with a rowspan above 1 in tables that hold a position's fair-value fact, and the row
-- below each, with cells, colspans and rowspans. A sample per fund. Read-only.
with fv as (
    select fr.cik, fr.accession, pl.row_index
    from int_field_read fr
    join stg_filed_fact_placement pl on pl.accession = fr.accession and pl.fact_id = fr.fact_id
    where fr.field = 'fair_value' and fr.status = 'read' and pl.row_index is not null and not pl.in_hidden
)
, sched as (
    select distinct fv.cik, fv.accession, r.table_index
    from fv join stg_filed_document_row r on r.accession = fv.accession and r.row_index = fv.row_index
)
, rs as (
    select s.cik, r.accession, r.table_index, r.row_index, r.row_in_table, r.fact_count, r.cells, r.cell_colspans,
        r.cell_rowspans
        , row_number() over (partition by s.cik order by r.accession desc, r.row_index) as k
    from sched s join stg_filed_document_row r on r.accession = s.accession and r.table_index = s.table_index
    where list_max(r.cell_rowspans) > 1
)
select rs.cik, rs.accession, rs.table_index, rs.row_in_table, rs.fact_count, rs.cell_rowspans, rs.cell_colspans
    , list_transform(rs.cells, x -> left(trim(x), 15)) as cells
    , nx.cell_colspans as next_colspans, list_transform(nx.cells, x -> left(trim(x), 15)) as next_cells
    , nx.fact_count as next_facts
from rs
left join stg_filed_document_row nx on nx.accession = rs.accession and nx.row_index = rs.row_index + 1
where rs.k <= 4
order by 1, 2, 4
