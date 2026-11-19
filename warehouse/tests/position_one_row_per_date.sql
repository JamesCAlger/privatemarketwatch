-- A position has one observation per report date.
select position_id, report_date, count(*) as n
from {{ ref('stg_holdings') }}
group by 1, 2
having count(*) > 1