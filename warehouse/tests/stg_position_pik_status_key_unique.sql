-- One PIK status row per fund, date and position.
select cik, report_date, position_id, count(*) as n
from {{ ref('stg_position_pik_status') }}
group by 1, 2, 3
having count(*) > 1
