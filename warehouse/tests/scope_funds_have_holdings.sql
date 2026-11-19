-- Every fund in scope has holdings at the latest report date, and the scope itself is not empty.
-- Without this, an empty staging table would let every other test pass.
with latest as (
    select max(report_date) as d from {{ ref('stg_holdings') }}
)
select s.cik, 'no holdings at the latest report date' as problem
from {{ ref('stg_v05_scope') }} s
left join {{ ref('stg_holdings') }} h
       on h.cik = s.cik and h.report_date = (select d from latest)
group by 1
having count(h.row_id) = 0
union all
select null, 'scope is empty'
where (select count(*) from {{ ref('stg_v05_scope') }}) = 0