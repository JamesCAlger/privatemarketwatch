-- Composite key of context must be unique. Returns the duplicated keys.
select accession, context_id, count(*) as n
from {{ ref('stg_filed_context') }}
group by 1,2
having count(*) > 1
