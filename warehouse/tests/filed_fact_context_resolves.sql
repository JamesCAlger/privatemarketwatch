-- Every fact's context exists in the same filing. Returns the facts that do not resolve.
select f.accession, f.fact_id, f.context_id
from {{ ref('stg_filed_fact') }} f
left join {{ ref('stg_filed_context') }} c on c.accession = f.accession and c.context_id = f.context_id
where c.context_id is null
