-- Decides which rows of the schedule tables are heading rows (text slice P4, 2026-11-26). One row per heading row:
-- (accession, row_index). Says nothing about what a heading means (industry, section, issuer, brand): a later slice.
--
-- A heading row: a row of a schedule table that has a header (int_page_table header_status one_line or two_lines),
-- below the last header line, with no facts (fact_count 0) and exactly one non-empty cell (int_page_cell). Rows above
-- the first position row count too ("Biotechnology" under the header, before the first loan). Rows of tables without
-- a header are not read here.
-- col_start, text: the one cell's true first column and text (macro page_text).
-- Plain features, not a classification:
--   is_continued          the lowercased text contains 'continued'.
--   next_row_kind         the next row of the same table that has a non-empty cell: heading (a heading row),
--                         position (the printed row of a position, int_page_position one_row), other, or
--                         end_of_table when no such row follows in the table.
--   seen_in_prior_filing  the same text is a heading row in the fund's previous filing here (the accession with the
--                         latest report_date before this one among int_page_table's filings of the same cik); null for
--                         the fund's first filing.
with header_table as (
    select accession, table_index, cik, report_date, header_last_row_in_table
    from {{ ref('int_page_table') }}
    where header_status in ('one_line', 'two_lines')
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
        , d.row_fact_count = 0 and d.non_empty_cells = 1 as is_heading
        , case
            when d.row_fact_count = 0 and d.non_empty_cells = 1 then 'heading'
            when p.row_index is not null then 'position'
            else 'other'
        end as row_kind
    from data_row d
    left join position_row p on p.accession = d.accession and p.row_index = d.row_index
)

, with_next as (
    select
        k.*
        , coalesce(lead(k.row_kind) over (partition by k.accession, k.table_index order by k.row_in_table), 'end_of_table')
            as next_row_kind
    from kinded k
)

, heading as (
    select w.accession, w.table_index, w.row_index, w.row_in_table, w.col_start, w.first_text as text, w.next_row_kind
        , h.cik, h.report_date
    from with_next w
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
    , h.col_start
    , h.text
    , strpos(lower(h.text), 'continued') > 0 as is_continued
    , h.next_row_kind
    , case
        when f.filing_seq = 1 then null
        else pt.text is not null
    end as seen_in_prior_filing
from heading h
join filing_order f on f.accession = h.accession
left join filing_text pt on pt.cik = h.cik and pt.filing_seq = f.filing_seq - 1 and pt.text = h.text
