-- The rate direction of stg_fx_rate: usd_per_unit is US dollars for one unit of the currency. FRED H.10 (series
-- DEXUSEU) for 2018-10-01: one euro = 1.1567 dollars. Also: one row per currency and date, every rate above zero.
select 'known rate missing or wrong' as problem, count(*) as n
from {{ ref('stg_fx_rate') }}
where currency = 'EUR' and rate_date = date '2018-10-01' and usd_per_unit = 1.1567
having count(*) <> 1
union all
select 'duplicate currency and date', count(*)
from (select currency, rate_date from {{ ref('stg_fx_rate') }} group by 1, 2 having count(*) > 1)
having count(*) > 0
union all
select 'rate not above zero or a null key', count(*)
from {{ ref('stg_fx_rate') }}
where usd_per_unit is null or usd_per_unit <= 0 or currency is null or rate_date is null
having count(*) > 0
