-- Slice 5 Task 4 diagnostic: how the seven adjacent-rate takers compare with production in cmp_rate. Read-only.
select c.*
from cmp_rate c
join int_rate_adjacent a on a.accession = c.accession and a.taker_context_id = c.context_id
order by c.accession, c.context_id, c.field
