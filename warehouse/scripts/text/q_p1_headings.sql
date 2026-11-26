-- Slice P, 2026-11-26: the most frequent heading texts per fund, with their column and next-row kind; and the one
-- table with no header. Read-only.
select 'h' as k, cik, left(text, 60) as text, min(col_start) as col_min, max(col_start) as col_max
    , mode(next_row_kind) as next_kind, count(*) as n
from int_page_heading
group by cik, left(text, 60)
qualify row_number() over (partition by cik order by count(*) desc, left(text, 60)) <= 6
union all
select 'none', cik, accession || ' t' || table_index, first_position_row_in_table, position_rows, header_status, n_rows
from int_page_table where header_status not in ('one_line', 'two_lines')
order by 1, 2, 7 desc
