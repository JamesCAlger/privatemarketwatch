-- Slice 5 Task 3 proof: target rows by outcome and reason over all stores and funds, with the key resolution.
select outcome, coalesce(reason, '') as reason, key_resolution, count(*) as targets, count(distinct correction_id) as corrections
from main.int_correction_application
group by all
order by 1, 2, 3
