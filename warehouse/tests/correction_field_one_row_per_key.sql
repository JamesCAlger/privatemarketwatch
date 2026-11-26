-- Slice 5 Task 2: seed correction_field has one row per (correction_field, store_pattern).
select correction_field, store_pattern, count(*) as n
from {{ ref('correction_field') }}
group by all
having count(*) > 1
