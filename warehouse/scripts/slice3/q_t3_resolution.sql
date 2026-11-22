-- Slice 3 Task 3: int_field_rule resolution and origin counts per field.
select field, resolution, origin, action, parameter, count(*) n, max(candidate_count) max_candidates
from int_field_rule group by all order by all limit 200
