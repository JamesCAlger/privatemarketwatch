-- Slice P fix round 1, 2026-11-26: cells given no column because their row's width is not the table's, by filing and
-- table, with facts placed in them. Read-only.
select cc.accession, t.report_date, cc.table_index, count(distinct cc.row_index) as row_count, count(*) as cell_count
    , count(*) filter (where exists (select 1 from stg_filed_fact_placement pl where pl.accession = cc.accession
        and coalesce(pl.row_index, pl.shown_row_index) = cc.row_index and coalesce(pl.cell_index, pl.shown_cell_index) = cc.cell_index)) as cells_with_fact
from int_page_cell_column cc join int_page_table t using (accession, table_index)
where cc.column_rule = 'none_row_width_differs'
group by all order by 1, 3
