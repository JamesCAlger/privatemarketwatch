-- Decides which printed tables are schedule tables, their width, and their header lines (text slice P1 and P3,
-- 2026-11-26). One row per (accession, table_index).
--
-- A schedule table: a printed table of a filing (stg_filed_document_row.table_index) that holds the printed row of at
-- least one position (int_page_position placement_status one_row, published or not). A schedule printed over many
-- pages is many tables; each is its own row here.
-- width: the table's modal row width, where a row's width is the sum of its cells' colspans (a missing or
-- non-positive colspan counts 1). Ties go to the larger width. Rowspans are not counted here (int_page_cell resolves
-- them).
-- position_rows: distinct printed rows of positions in the table. first_position_row_in_table: the first of them.
--
-- Header candidates: rows of the table with no facts (fact_count 0), above the first position row, with at least 3
-- non-empty cells (macro page_text). With exactly one candidate, its neighbours are looked at for a second header line:
--   line below  the next row has no facts, is above the first position row and has at least 2 non-empty cells (a
--               heading row has exactly 1). Sub-headers such as "Ref. Rate | Cash | PIK" under "Interest".
--   group line  otherwise, the row directly above has no facts, no cell with rowspan above 1, 1 or 2 non-empty cells,
--   above       and each of them covers (by naive columns, colspans summed) at least 2 and not all of the candidate's
--               non-empty cells. "Interest" over "Ref. Rate | Cash | PIK". A title over the whole table covers all of
--               them and is not a group line.
-- header_status and header_form:
--   one_line   / one_line          exactly one candidate and no second line: header_row_index is it.
--   two_lines  / two_candidates    two candidates on consecutive rows (a first line whose cells span two rows above a
--                                  line of sub-headers): the upper is header_row_index, the lower sub_header_row_index.
--   two_lines  / line_below        the candidate is header_row_index, the line below sub_header_row_index.
--   two_lines  / group_line_above  the group line is header_row_index, the candidate sub_header_row_index.
--   none       / none              no candidate: no header, so no column units for the table.
--   ambiguous  / ambiguous         any other count or layout: no header is taken rather than guessing.
-- header_last_row_in_table: row_in_table of the last header line (null without a header); rows below it are data rows.
with position_row as (
    select distinct accession, table_index, row_index, row_in_table
    from {{ ref('int_page_position') }}
    where placement_status = 'one_row'
)

, filing as (
    select accession, min(cik) as cik, min(report_date) as report_date
    from {{ ref('int_page_position') }}
    group by 1
)

, schedule as (
    select accession, table_index, count(*) as position_rows, min(row_in_table) as first_position_row_in_table
    from position_row
    group by 1, 2
)

, table_row as (
    select
        dr.accession
        , dr.table_index
        , dr.row_index
        , dr.row_in_table
        , dr.fact_count
        , coalesce(list_sum(list_transform(dr.cell_colspans, x -> greatest(coalesce(x, 1), 1))), 0) as row_width
        , len(list_filter(dr.cells, x -> {{ page_text('x') }} <> '')) as non_empty_cells
        , coalesce(list_max(dr.cell_rowspans), 1) as max_rowspan
    from {{ ref('stg_filed_document_row') }} dr
    join schedule s on s.accession = dr.accession and s.table_index = dr.table_index
)

, width as (
    select accession, table_index, row_width as width
    from (select accession, table_index, row_width, count(*) as n from table_row group by 1, 2, 3)
    qualify row_number() over (partition by accession, table_index order by n desc, row_width desc) = 1
)

, candidate as (
    select r.accession, r.table_index, r.row_index, r.row_in_table
    from table_row r
    join schedule s on s.accession = r.accession and s.table_index = r.table_index
    where r.fact_count = 0 and r.row_in_table < s.first_position_row_in_table and r.non_empty_cells >= 3
)

, candidate_summary as (
    select
        accession
        , table_index
        , count(*) as header_candidates
        , min(row_in_table) as first_candidate
        , max(row_in_table) as last_candidate
        , arg_min(row_index, row_in_table) as first_candidate_row_index
        , arg_max(row_index, row_in_table) as last_candidate_row_index
    from candidate
    group by 1, 2
)

, line_below as (
    select c.accession, c.table_index, r.row_index, r.row_in_table
    from candidate_summary c
    join schedule s on s.accession = c.accession and s.table_index = c.table_index
    join table_row r
        on r.accession = c.accession and r.table_index = c.table_index and r.row_in_table = c.first_candidate + 1
    where c.header_candidates = 1 and r.fact_count = 0 and r.row_in_table < s.first_position_row_in_table
        and r.non_empty_cells >= 2
)

, near_cell as (
    -- the non-empty cells of the single candidate and of the row directly above it, at their naive columns
    select
        c.accession
        , c.table_index
        , dr.row_in_table = c.first_candidate as is_candidate
        , coalesce(sum(greatest(coalesce(dr.cell_colspans[i], 1), 1)) over (
            partition by dr.accession, dr.row_index order by i rows between unbounded preceding and 1 preceding), 0)
            as col_start
        , greatest(coalesce(dr.cell_colspans[i], 1), 1) as colspan
        , {{ page_text('dr.cells[i]') }} as text
    from candidate_summary c
    join {{ ref('stg_filed_document_row') }} dr
        on dr.accession = c.accession and dr.table_index = c.table_index
        and dr.row_in_table in (c.first_candidate - 1, c.first_candidate)
    , range(1, dr.cell_count + 1) t(i)
    where c.header_candidates = 1
)

, group_cover as (
    select g.accession, g.table_index, g.col_start, count(m.col_start) as covered
        , (select count(*) from near_cell a
           where a.accession = g.accession and a.table_index = g.table_index and a.is_candidate and a.text <> '')
            as candidate_cells
    from near_cell g
    left join near_cell m
        on m.accession = g.accession and m.table_index = g.table_index and m.is_candidate and m.text <> ''
        and m.col_start between g.col_start and g.col_start + g.colspan - 1
    where not g.is_candidate and g.text <> ''
    group by 1, 2, 3
)

, group_line as (
    select c.accession, c.table_index, r.row_index
    from candidate_summary c
    join table_row r
        on r.accession = c.accession and r.table_index = c.table_index and r.row_in_table = c.first_candidate - 1
    where c.header_candidates = 1 and r.fact_count = 0 and r.max_rowspan <= 1 and r.non_empty_cells between 1 and 2
        and not exists (select 1 from line_below b where b.accession = c.accession and b.table_index = c.table_index)
        and not exists (
            select 1 from group_cover g
            where g.accession = c.accession and g.table_index = c.table_index
                and (g.covered < 2 or g.covered >= g.candidate_cells)
        )
)

, decided as (
    select
        s.accession
        , s.table_index
        , s.position_rows
        , s.first_position_row_in_table
        , coalesce(c.header_candidates, 0) as header_candidates
        , case
            when c.header_candidates is null then 'none'
            when c.header_candidates = 2 and c.last_candidate = c.first_candidate + 1 then 'two_candidates'
            when c.header_candidates = 1 and b.row_index is not null then 'line_below'
            when c.header_candidates = 1 and g.row_index is not null then 'group_line_above'
            when c.header_candidates = 1 then 'one_line'
            else 'ambiguous'
        end as header_form
        , c.first_candidate_row_index
        , c.last_candidate_row_index
        , c.last_candidate
        , b.row_index as below_row_index
        , b.row_in_table as below_row_in_table
        , g.row_index as group_row_index
    from schedule s
    left join candidate_summary c on c.accession = s.accession and c.table_index = s.table_index
    left join line_below b on b.accession = s.accession and b.table_index = s.table_index
    left join group_line g on g.accession = s.accession and g.table_index = s.table_index
)

select
    d.accession
    , d.table_index
    , f.cik
    , f.report_date
    , n.n_rows
    , w.width
    , d.position_rows
    , d.first_position_row_in_table
    , d.header_candidates
    , case
        when d.header_form = 'one_line' then 'one_line'
        when d.header_form in ('two_candidates', 'line_below', 'group_line_above') then 'two_lines'
        else d.header_form
    end as header_status
    , d.header_form
    , case
        when d.header_form = 'group_line_above' then d.group_row_index
        when d.header_form in ('one_line', 'two_candidates', 'line_below') then d.first_candidate_row_index
    end as header_row_index
    , case
        when d.header_form = 'two_candidates' then d.last_candidate_row_index
        when d.header_form = 'line_below' then d.below_row_index
        when d.header_form = 'group_line_above' then d.first_candidate_row_index
    end as sub_header_row_index
    , case
        when d.header_form = 'line_below' then d.below_row_in_table
        when d.header_form in ('one_line', 'two_candidates', 'group_line_above') then d.last_candidate
    end as header_last_row_in_table
from decided d
join filing f on f.accession = d.accession
join width w on w.accession = d.accession and w.table_index = d.table_index
join (select accession, table_index, count(*) as n_rows from table_row group by 1, 2) n
    on n.accession = d.accession and n.table_index = d.table_index
