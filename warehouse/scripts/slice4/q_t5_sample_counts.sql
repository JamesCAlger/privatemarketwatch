-- Slice 4 Task 5 repair (c): how many rows q_t4_open_rows.sql opens per cause detail (up to 4 per field, cause and
-- detail, both bases), so the baseline doc quotes one consistent sample size.
with g as (
    select field, cause, cause_detail, count(*) as n
    from cmp_rate
    where cause is not null
    group by all
)
select cause, cause_detail, sum(least(n, 4)) as opened, count(*) as field_groups
from g
group by all
union all
select 'total', null, sum(least(n, 4)), count(*) from g
order by 1, 2
