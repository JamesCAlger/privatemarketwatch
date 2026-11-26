-- Slice 5 Task 1, item b: every unit text int_field_read gives a field that takes a unit kind (the five amount fields
-- and the four rate fields), with the unit kind the old macro unit_kind gave it and counts (re-measures appendix A8).
-- Run on the warehouse (or a CI fixture database). Row limit: the caller's.
select
    unit
    , case
        when unit = 'iso4217:USD' then 'usd'
        when regexp_full_match(unit, 'iso4217:[A-Z]{3}') then 'foreign'
        when unit = 'shares' then 'shares'
        when unit in ('pure', 'utr:Rate') then 'pure'
        else 'other'
      end as old_kind
    , count(*) as rows_read
    , count(distinct cik) as funds
    , string_agg(distinct field, ',' order by field) as fields
from main.int_field_read
where field in ('fair_value', 'cost', 'principal_amount', 'shares', 'pct_of_net_assets', 'interest_rate_tag',
                'interest_rate_cash_tag', 'pik_rate', 'spread')
  and unit is not null
group by all
order by old_kind, rows_read desc
