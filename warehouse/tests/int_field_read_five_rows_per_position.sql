-- Slice 3 Task 2: every position row of int_source_row (published or not) has exactly five rows in int_field_read, one
-- per amount field, and int_field_read has no row for a context that is not a position.
select r.accession, r.context_id, count(f.field) as n
from {{ ref('int_source_row') }} r
left join {{ ref('int_field_read') }} f on f.accession = r.accession and f.context_id = r.context_id
where r.role = 'position'
group by 1, 2
having count(f.field) <> 5 or count(distinct f.field) <> 5
union all
select f.accession, f.context_id, -1 as n
from {{ ref('int_field_read') }} f
anti join {{ ref('int_source_row') }} r on r.accession = f.accession and r.context_id = f.context_id and r.role = 'position'
