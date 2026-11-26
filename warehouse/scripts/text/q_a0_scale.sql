-- Slice A, 2026-11-26: scale of Apollo's tagged spread and rates, and production's rate columns. Read-only.
select 'holdings_cols' as k, string_agg(column_name, ', ') as v, null as n
from information_schema.columns where table_name = 'stg_holdings'
  and regexp_matches(column_name, 'rate|spread|floor|matur|coupon|pik|corrected|industry')
union all
select 'scale_' || field, case when value_normalised < 1 then 'under_1' else 'one_or_more' end, count(*)
from int_field_corrected where cik = '0001837532' and field in ('spread', 'interest_rate', 'pik_rate', 'interest_rate_cash') and value_normalised is not null
group by all
order by 1, 2
