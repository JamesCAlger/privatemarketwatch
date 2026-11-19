-- Every dimension member sits on a context of the same filing. Returns the members that do not.
select m.accession, m.context_id, m.axis
from {{ ref('stg_filed_context_member') }} m
left join {{ ref('stg_filed_context') }} c on c.accession = m.accession and c.context_id = m.context_id
where c.context_id is null
