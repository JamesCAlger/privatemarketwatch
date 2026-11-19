-- Composite key of context_member must be unique. Returns the duplicated keys.
select accession, context_id, axis, count(*) as n
from {{ ref('stg_filed_context_member') }}
group by 1,2,3
having count(*) > 1
