-- Decides the column units of each schedule table that has a header (text slice P3, 2026-11-26). One row per leaf
-- column: (accession, table_index, col_start).
--
-- Header lines come from int_page_table: the upper line (header_row_index) and, for a two-line header, the lower line
-- (sub_header_row_index). Their cells and true columns come from int_page_cell. A header cell counts only if its text
-- holds a letter or a digit: a spacer cell printing "." or "$" is treated as empty.
-- Leaf columns:
--   - a lower-line cell whose col_start lies inside an upper-line cell is one leaf: header_text the upper cell's text,
--     sub_header_text its own ("Interest" over "Cash").
--   - a lower-line cell under no upper-line cell is one leaf: header_text its own text, sub_header_text null ("Units"
--     under an empty upper cell; "Company" beside a group line that only covers the rate columns).
--   - an upper-line cell that holds no lower-line cell is one leaf: header_text its text, sub_header_text null
--     ("Company" spanning both lines).
-- So one header gives the same leaves whether its first line spans two rows or a group line sits above it.
-- col_start, col_end: the leaf cell's printed columns.
-- zone_end: the last column a data cell may start in and still belong to this leaf: one before the next leaf's
-- col_start, or for the rightmost leaf the table's last column (width - 1, or its own col_end if that is further).
-- Columns under an empty header cell therefore belong to the leaf on their left (a "$" cell and the number after it,
-- or a "%" after the number, stay with their header). Columns left of the first leaf belong to none.
-- column_index: the leaf's position from the left, 0-based.
-- header_signature: macro page_signature of header_text, and for a leaf with a sub-header, that of header_text, '/',
-- that of sub_header_text ("Interest" over "Cash" gives "interest/cash").
with header_table as (
    select accession, table_index, cik, report_date, width, header_row_index, sub_header_row_index
    from {{ ref('int_page_table') }}
    where header_status in ('one_line', 'two_lines')
)

, upper_cell as (
    select c.accession, c.table_index, c.col_start, c.col_end, c.text
    from {{ ref('int_page_cell') }} c
    join header_table h on h.accession = c.accession and h.header_row_index = c.row_index
    where regexp_matches(c.text, '[A-Za-z0-9]')
)

, lower_cell as (
    select c.accession, c.table_index, c.col_start, c.col_end, c.text
    from {{ ref('int_page_cell') }} c
    join header_table h on h.accession = c.accession and h.sub_header_row_index = c.row_index
    where regexp_matches(c.text, '[A-Za-z0-9]')
)

, leaf as (
    select
        l.accession
        , l.table_index
        , l.col_start
        , l.col_end
        , coalesce(u.text, l.text) as header_text
        , case when u.text is not null then l.text end as sub_header_text
    from lower_cell l
    left join upper_cell u
        on u.accession = l.accession and u.table_index = l.table_index and l.col_start between u.col_start and u.col_end
    union all
    select u.accession, u.table_index, u.col_start, u.col_end, u.text as header_text, null as sub_header_text
    from upper_cell u
    where not exists (
        select 1 from lower_cell l
        where l.accession = u.accession and l.table_index = u.table_index and l.col_start between u.col_start and u.col_end
    )
)

select
    l.accession
    , l.table_index
    , h.cik
    , h.report_date
    , row_number() over (partition by l.accession, l.table_index order by l.col_start) - 1 as column_index
    , l.col_start
    , l.col_end
    , coalesce(lead(l.col_start) over (partition by l.accession, l.table_index order by l.col_start) - 1,
               greatest(h.width - 1, l.col_end)) as zone_end
    , l.header_text
    , l.sub_header_text
    , case
        when l.sub_header_text is null then {{ page_signature('l.header_text') }}
        else {{ page_signature('l.header_text') }} || '/' || {{ page_signature('l.sub_header_text') }}
    end as header_signature
from leaf l
join header_table h on h.accession = l.accession and h.table_index = l.table_index
