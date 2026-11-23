-- Final fix: spread rows filed above 1 (owner review section 4), by status and reason, and the unresolved scale rows.
select field, status, reason, count(*) as n
from int_field_normalised
where field = 'spread' and (abs(value_filed) > 1 or reason = 'scale_not_decided')
group by all order by n desc;
