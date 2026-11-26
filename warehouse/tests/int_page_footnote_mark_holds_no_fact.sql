-- Text slice P (review of fix round 2, 2026-11-26): a cell classed as a footnote mark never holds a placed fact. A
-- bracketed number with a fact in it is a negative amount, not a footnote reference (macro page_text; about 6,900
-- such cells were misread before fix round 2). Fails on any footnote-mark cell that a fact is placed in or shown in.
select cc.accession, cc.row_index, cc.cell_index, cc.text
from {{ ref('int_page_cell_column') }} cc
where cc.shape = 'footnote_mark'
  and exists (
      select 1 from {{ ref('stg_filed_fact_placement') }} pl
      where pl.accession = cc.accession
        and coalesce(pl.row_index, pl.shown_row_index) = cc.row_index
        and coalesce(pl.cell_index, pl.shown_cell_index) = cc.cell_index
  )
