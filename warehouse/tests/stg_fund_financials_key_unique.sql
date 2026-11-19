-- One financials row per fund and date.
select cik, report_date, count(*) as n
from {{ ref('stg_fund_financials') }}
group by 1, 2
having count(*) > 1
