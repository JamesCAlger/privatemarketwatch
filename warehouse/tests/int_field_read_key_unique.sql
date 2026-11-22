-- Slice 3 Task 2: one row per accession, context_id and field in int_field_read.
select accession, context_id, field, count(*) as n
from {{ ref('int_field_read') }}
group by 1, 2, 3
having count(*) > 1
