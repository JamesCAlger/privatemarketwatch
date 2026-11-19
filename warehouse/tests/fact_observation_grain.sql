-- At most one observation per fund, date, accounting scope and position.
select cik, report_date, accounting_scope_id, position_id, count(*) as n
from {{ ref('fact_observation') }}
group by 1, 2, 3, 4
having count(*) > 1
