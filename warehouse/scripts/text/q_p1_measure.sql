-- Slice P, 2026-11-26: counts per fund of the page-structure models, for the baseline. Read-only.
select '1 positions' as k, cik
    , count(*) filter (where is_published) as a
    , count(*) filter (where is_published and placement_status = 'one_row') as b
    , count(*) filter (where is_published and placement_status = 'several_rows') as c
    , count(*) filter (where is_published and placement_status = 'not_placed') as d
    , count(*) filter (where not is_published and placement_status <> 'one_row') as e
    , 'published | one_row | several | not_placed | unpublished not one_row' as legend
from int_page_position group by 2
union all
select '2 tables', cik, count(*), count(distinct accession)
    , count(*) filter (where header_status = 'one_line'), count(*) filter (where header_status = 'two_lines')
    , count(*) filter (where header_status in ('none', 'ambiguous'))
    , 'tables | filings | one_line | two_lines | none or ambiguous'
from int_page_table group by 2
union all
select '3 cells', t.cik, count(*), count(*) filter (where not c.row_width_ok)
    , count(*) filter (where c.span_rule = 'span_from_row_above'), count(*) filter (where c.span_rule = 'deeper_span')
    , count(distinct case when not c.row_width_ok then c.accession || ':' || c.row_index end)
    , 'cells | cells in rows width not ok | cells span_from_row_above | cells deeper_span | rows width not ok'
from int_page_cell c join int_page_table t using (accession, table_index) group by 2
union all
select '4 cell columns', t.cik, count(*), count(*) filter (where cc.column_col_start is null)
    , count(distinct cc.header_signature), null, null
    , 'data cells | unassigned | distinct signatures'
from int_page_cell_column cc join int_page_table t using (accession, table_index) group by 2
union all
select '5 headings', cik, count(*), count(distinct text), count(*) filter (where is_continued)
    , count(*) filter (where seen_in_prior_filing = false), count(*) filter (where next_row_kind = 'position')
    , 'heading rows | distinct texts | continued | not seen in prior filing | next row position'
from int_page_heading group by 2
union all
select '6 position headings', p.cik, count(distinct p.accession || p.context_id)
    , count(distinct case when ph.context_id is null then p.accession || p.context_id end)
    , count(*) filter (where ph.heading_rank = 1 and not ph.same_table), null, null
    , 'one_row positions | with no heading above | nearest heading in another table'
from int_page_position p left join int_position_heading ph using (accession, context_id)
where p.placement_status = 'one_row' group by 2
union all
select '7 header forms', cik, count(*) filter (where header_form = 'two_candidates')
    , count(*) filter (where header_form = 'line_below'), count(*) filter (where header_form = 'group_line_above')
    , cast(median(n_rows) as bigint), max(n_rows)
    , 'two_candidates | line_below | group_line_above | median rows | max rows'
from int_page_table group by 2
union all
select '8 published tables', t.cik, count(distinct t.accession || ':' || t.table_index), null, null, null, null
    , 'tables holding a published position row'
from int_page_table t join int_page_position p on p.accession = t.accession and p.table_index = t.table_index
where p.is_published group by 2
order by 1, 2
