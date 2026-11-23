-- Slice 4 Task 1: int_repeated_commitment_value per fund, report date and scope: position rows, commitment lines,
-- commitment lines with a non-zero fair value, and flagged lines. Read-only.
select cik, report_date, scope, is_published
    , count(*) as positions
    , count(*) filter (where is_commitment_line) as commitment_lines
    , count(*) filter (where is_repeated_commitment_value) as flagged
from int_repeated_commitment_value
group by all
having count(*) filter (where is_commitment_line) > 0
order by cik, report_date, scope
