-- Text slice R phase 3: positions of int_text_rate_read per fund and field, by status and source grade.
-- Published positions only in the columns pub_*; all positions in the others.
with long as (
    select cik, is_published, 'reference_rate' as field, reference_rate_status as status, reference_rate_grade as grade from int_text_rate_read
    union all select cik, is_published, 'spread', spread_status, spread_grade from int_text_rate_read
    union all select cik, is_published, 'floor', floor_status, floor_grade from int_text_rate_read
    union all select cik, is_published, 'all_in_rate', all_in_rate_status, all_in_rate_grade from int_text_rate_read
    union all select cik, is_published, 'cash_rate', cash_rate_status, cash_rate_grade from int_text_rate_read
    union all select cik, is_published, 'pik_rate', pik_rate_status, pik_rate_grade from int_text_rate_read
    union all select cik, is_published, 'pik_spread', pik_spread_status, pik_spread_grade from int_text_rate_read
    union all select cik, is_published, 'rate_type:' || coalesce(rate_type, 'none'), 'type', null from int_text_rate_read
)
select cik, field, status, coalesce(grade, '') as grade, count(*) as positions
    , count(*) filter (where is_published) as pub_positions
from long
where status <> 'not_printed'
group by all
order by 1, 2, 3, 4
