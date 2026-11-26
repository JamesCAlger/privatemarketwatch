-- Slice R phase 2: inputs seen (field, status, rate_kind counts in int_field_normalised for rate fields). Read-only.
select field, status, rate_kind, count(*) n
from int_field_normalised
where field in ('interest_rate','interest_rate_cash','pik_rate','spread')
group by all order by 1,2,3
