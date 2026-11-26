-- Slice R phase 1: how the corrected rate fields look per fund (status, kind, value range). Read-only.
select cik, field, status, rate_kind, count(*) as n, round(median(value), 3) as med, round(max(value), 3) as mx
from int_field_corrected
where field in ('interest_rate', 'interest_rate_cash', 'pik_rate', 'spread')
group by all order by 1, 2, 3, 4
