-- Slice 3 Task 3: principal_amount_usd unresolved for want of a rate: fund, date, currency, rows, and the latest quote
-- on or before the report date for that currency (if any).
with u as (
    select n.cik, n.report_date, p.currency, count(*) n
    from int_field_normalised n
    join int_field_normalised p on p.accession = n.accession and p.context_id = n.context_id and p.field = 'principal_amount'
    where n.field = 'principal_amount_usd' and n.reason = 'no_fx_rate'
    group by all
)
select u.*, (select max(rate_date) from stg_fx_rate f where f.currency = u.currency and f.rate_date <= u.report_date) latest_quote
    , (select count(*) from stg_fx_rate f where f.currency = u.currency) quotes_for_currency
from u order by all limit 50
