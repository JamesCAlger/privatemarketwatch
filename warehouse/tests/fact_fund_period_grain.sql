-- One row per fund and report date.
select cik, report_date, count(*) as n
from {{ ref('fact_fund_period') }}
group by 1, 2
having count(*) > 1
