-- Slice 5 Task 6: outcome counts of int_correction_application at the end of the slice (for HANDOFF and the
-- changelog), per outcome and reason, with the number of distinct corrections and of correction targets.
select outcome, coalesce(reason, '') as reason, count(*) as targets, count(distinct correction_id) as corrections
from main.int_correction_application
group by all
union all
select 'TOTAL', '', count(*), count(distinct correction_id) from main.int_correction_application
union all
select 'row_reason ' || row_reason, '', count(*), null from main.int_row_corrected group by row_reason
order by 1, 2
