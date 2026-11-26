-- Decides which rows of the schedule tables are heading rows, and how they stack (text slice P4, 2026-11-26; runs
-- added in fix round 1). One row per heading row: (accession, row_index). Says nothing about what a heading means
-- (industry, section, issuer, brand): a later slice.
--
-- A heading row: a row of a schedule table that has a header (int_page_table header_status one_line or two_lines),
-- below the last header line, with no facts (fact_count 0) and exactly one non-empty cell (int_page_cell). Rows above
-- the first position row count too ("Biotechnology" under the header, before the first loan). Rows of tables without
-- a header are not read here.
-- col_start, text: the one cell's true first column and text (macro page_text).
-- schedule_seq: the schedule of the heading's table (int_page_schedule).
-- Runs: the data rows of one schedule (rows below the header lines that have a non-empty cell, in every table of the
-- schedule) are put in document order (row_index). A run is a maximal stretch of consecutive heading rows in that
-- order. Rows with no text, header lines and titles are not data rows, so blank rows and a page break with a repeated
-- header do not end a run; any other data row (a position, a subtotal, a note with two cells) does. A run never
-- crosses a schedule boundary.
--   run_length            heading rows in the run.
--   run_position          1 for the run's first (top) heading, up to run_length.
--   depth_from_bottom     run_length - run_position: 0 for the heading directly above the rows that follow, 1 for the
--                         one above it, and so on. A structural count, not a level: a run of one is depth 0 whatever
--                         its text says.
-- Plain features, not a classification:
--   is_continued          the lowercased text contains 'continued'.
--   next_row_kind         the next row of the same table that has a non-empty cell: heading (a heading row),
--                         position (the printed row of a position, int_page_position one_row), other, or
--                         end_of_table when no such row follows in the table.
--   seen_in_prior_filing  the same text is a heading row in the fund's previous filing here (the accession with the
--                         latest report_date before this one among int_page_table's filings of the same cik); null for
--                         the fund's first filing.
with header_table as (
    select t.accession, t.table_index, t.cik, t.report_date, t.header_last_row_in_table, s.schedule_seq
    from {{ ref('int_page_table') }} t
    join {{ ref('int_page_schedule') }} s on s.accession = t.accession and s.table_index = t.table_index
    where t.header_status in ('one_line', 'two_lines')
)

, data_row as (
    -- every row below the header that has a non-empty cell
    select
        c.accession
        , c.table_index
        , c.row_index
        , c.row_in_table
        , max(c.row_fact_count) as row_fact_count
        , count(*) as non_empty_cells
        , min(c.col_start) as col_start
        , min(c.text) as first_text
    from {{ ref('int_page_cell') }} c
    join header_table h
        on h.accession = c.accession and h.table_index = c.table_index and c.row_in_table > h.header_last_row_in_table
    group by 1, 2, 3, 4
)

, position_row as (
    select distinct accession, row_index
    from {{ ref('int_page_position') }}
    where placement_status = 'one_row'
)

, kinded as (
    select
        d.*
        , h.schedule_seq
        , d.row_fact_count = 0 and d.non_empty_cells = 1 as is_heading
        , case
            when d.row_fact_count = 0 and d.non_empty_cells = 1 then 'heading'
            when p.row_index is not null then 'position'
            else 'other'
        end as row_kind
    from data_row d
    join header_table h on h.accession = d.accession and h.table_index = d.table_index
    left join position_row p on p.accession = d.accession and p.row_index = d.row_index
)

, with_run as (
    select
        k.*
        , coalesce(lead(k.row_kind) over (partition by k.accession, k.table_index order by k.row_in_table), 'end_of_table')
            as next_row_kind
        -- rows that are not headings, counted up to this row: constant along a run of headings
        , sum(case when k.is_heading then 0 else 1 end) over (
            partition by k.accession, k.schedule_seq order by k.row_index rows between unbounded preceding and current row)
            as run_group
    from kinded k
)

, heading as (
    select
        w.accession
        , w.table_index
        , w.row_index
        , w.row_in_table
        , w.schedule_seq
        , w.col_start
        , w.first_text as text
        , w.next_row_kind
        , count(*) over (partition by w.accession, w.schedule_seq, w.run_group) as run_length
        , row_number() over (partition by w.accession, w.schedule_seq, w.run_group order by w.row_index) as run_position
        , h.cik
        , h.report_date
    from with_run w
    join header_table h on h.accession = w.accession and h.table_index = w.table_index
    where w.is_heading
)

, filing_order as (
    select cik, accession, dense_rank() over (partition by cik order by report_date, accession) as filing_seq
    from (select distinct cik, accession, report_date from {{ ref('int_page_table') }})
)

, filing_text as (
    select distinct h.cik, f.filing_seq, h.text
    from heading h
    join filing_order f on f.accession = h.accession
)

select
    h.accession
    , h.row_index
    , h.table_index
    , h.row_in_table
    , h.cik
    , h.report_date
    , h.schedule_seq
    , h.col_start
    , h.text
    , h.run_length
    , h.run_position
    , h.run_length - h.run_position as depth_from_bottom
    , strpos(lower(h.text), 'continued') > 0 as is_continued
    , h.next_row_kind
    , case
        when f.filing_seq = 1 then null
        else pt.text is not null
    end as seen_in_prior_filing
from heading h
join filing_order f on f.accession = h.accession
left join filing_text pt on pt.cik = h.cik and pt.filing_seq = f.filing_seq - 1 and pt.text = h.text
