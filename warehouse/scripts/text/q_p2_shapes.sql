-- Slice P fix round 2, 2026-11-26: data cells of shape footnote_mark and number per fund, and footnote-mark cells that
-- hold a placed fact. Read-only.
select t.cik
    , count(*) filter (where cc.shape = 'footnote_mark') as footnote_mark
    , count(*) filter (where cc.shape = 'number') as number
    , count(*) filter (where cc.shape = 'footnote_mark' and exists (select 1 from stg_filed_fact_placement pl
        where pl.accession = cc.accession and coalesce(pl.row_index, pl.shown_row_index) = cc.row_index
          and coalesce(pl.cell_index, pl.shown_cell_index) = cc.cell_index)) as footnote_mark_with_fact
    , count(*) filter (where cc.header_signature = '#footnote_marks') as unheaded_footnote_cells
from int_page_cell_column cc join int_page_table t using (accession, table_index)
group by 1 order by 1
