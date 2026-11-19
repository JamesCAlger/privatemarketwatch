-- A position belongs to one fund and one accounting scope.
select position_id
from {{ ref('stg_holdings') }}
group by 1
having count(distinct cik) > 1 or count(distinct accounting_scope_id) > 1