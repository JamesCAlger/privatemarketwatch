-- Final fix wave: one-sided rows per basis, side, cause and detail in the current build.
select basis, side, cause, coalesce(cause_detail, '') as cause_detail, count(*) as n
from cmp_row_set
where side <> 'both'
group by all
order by all
