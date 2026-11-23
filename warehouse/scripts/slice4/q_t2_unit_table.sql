-- Slice 4 Task 2: units of the read rows per new field and fund (unit as filed; '(none)' for a read row with no unit,
-- which is the date field). Unit kind as int_field_rule would give it today (usd, foreign, shares, pure, other).
select r.field, r.cik, coalesce(r.unit, '(none)') as unit
    , case
        when r.unit is null then '(no unit)'
        when r.unit = 'iso4217:USD' then 'usd'
        when regexp_full_match(r.unit, 'iso4217:[A-Z]{3}') then 'foreign'
        when r.unit = 'shares' then 'shares'
        when r.unit = 'pure' then 'pure'
        else 'other'
      end as unit_kind_today
    , count(*) as read_rows
    , count(*) filter (where r.is_nil) as nil_rows
    , min(r.value_filed) as min_value, max(r.value_filed) as max_value
    , min(r.value_date) as min_date, max(r.value_date) as max_date
from int_field_read r
where r.status = 'read'
  and r.field in ('interest_rate_tag', 'interest_rate_cash_tag', 'pik_rate', 'spread', 'maturity_date')
group by all
order by 1, 2, 3
