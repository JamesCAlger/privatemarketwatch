-- One row per filed context: accession and context_id are unique together, and every filed context has a row.
select accession, context_id, count(*) as n
from {{ ref('int_context_feature') }}
group by 1, 2
having count(*) > 1
union all
select c.accession, c.context_id, 0 as n
from {{ ref('stg_filed_context') }} c
anti join {{ ref('int_context_feature') }} f on f.accession = c.accession and f.context_id = c.context_id
