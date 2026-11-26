-- Decides the text of each column on each printed position row (text slice R phase 1, 2026-11-26). One row per
-- (accession, row_index, col_start): a position row and a leaf column of its table that holds at least one cell there.
--
-- Position row: a printed row holding the fair value of at least one position (int_page_position placement_status
-- one_row, published or not). positions: how many positions sit on it; is_published: whether any of them is published.
-- Cells: the row's cells of int_page_cell_column whose column_rule is zone or prefix_of_next (a cell of a leaf column),
-- leaving out cells of shape footnote_mark. Cells of the unheaded '#footnote_marks' column and cells given no column are
-- not kept.
-- text: the column's cells on the row joined by one space in cell order. A filer that prints "SOFR +" and "5.25%" in
-- two cells under one header gives "SOFR + 5.25%"; "10.00" and "%" give "10.00 %". This, not a single cell, is the
-- "cell text" every later rate-text model reads.
-- unit_key: the column unit (int_text_column_unit): the first 16 hex characters of md5(cik | table_signature |
-- header_signature). It names no fund.
-- shape: macro text_shape of text (numbers become '#'). code: macro rate_code of text. rate_text: macro is_rate_text.
-- fact_fields: the distinct fields (macro page_field_fact: int_field_read's field, else the concept_map read_field) of
-- the filed facts placed in the row's cells of this column, sorted; empty list when none. fact_count: how many such
-- placements.
with position_row as (
    select accession, row_index, table_index, min(cik) as cik, min(report_date) as report_date
        , bool_or(is_published) as is_published, count(*) as positions
    from {{ ref('int_page_position') }}
    where placement_status = 'one_row'
    group by 1, 2, 3
)

, schedule as (
    select accession, table_index, table_signature
    from {{ ref('int_page_schedule') }}
    where table_signature is not null
)

, cell as (
    select cc.accession, cc.row_index, cc.table_index, cc.column_col_start as col_start, cc.header_signature
        , cc.cell_index, cc.text
    from {{ ref('int_page_cell_column') }} cc
    join position_row p on p.accession = cc.accession and p.row_index = cc.row_index
    where cc.column_rule in ('zone', 'prefix_of_next') and cc.shape <> 'footnote_mark'
)

, field_fact as (
    {{ page_field_fact() }}
)

, cell_fact as (
    select c.accession, c.row_index, c.col_start, list_sort(list_distinct(list(f.field))) as fact_fields
        , count(*) as fact_count
    from cell c
    join field_fact f on f.accession = c.accession and f.row_index = c.row_index and f.cell_index = c.cell_index
    where f.field is not null
    group by 1, 2, 3
)

, joined as (
    select accession, row_index, table_index, col_start, min(header_signature) as header_signature
        , string_agg(text, ' ' order by cell_index) as text, count(*) as n_cells
    from cell
    group by 1, 2, 3, 4
)

select
    j.accession
    , j.row_index
    , j.table_index
    , j.col_start
    , p.cik
    , p.report_date
    , p.is_published
    , p.positions
    , s.table_signature
    , j.header_signature
    , left(md5(p.cik || '|' || s.table_signature || '|' || j.header_signature), 16) as unit_key
    , j.text
    , j.n_cells
    , {{ text_shape('j.text') }} as shape
    , {{ rate_code('j.text') }} as code
    , {{ is_rate_text('j.text') }} as rate_text
    , coalesce(cf.fact_fields, []::varchar[]) as fact_fields
    , coalesce(cf.fact_count, 0) as fact_count
from joined j
join position_row p on p.accession = j.accession and p.row_index = j.row_index
join schedule s on s.accession = j.accession and s.table_index = j.table_index
left join cell_fact cf on cf.accession = j.accession and cf.row_index = j.row_index and cf.col_start = j.col_start
