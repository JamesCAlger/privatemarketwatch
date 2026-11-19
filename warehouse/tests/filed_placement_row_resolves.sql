-- Every placement that names a document row finds it in the same filing. Returns the placements that do not.
select p.accession, p.fact_id, p.row_index
from {{ ref('stg_filed_fact_placement') }} p
left join {{ ref('stg_filed_document_row') }} r on r.accession = p.accession and r.row_index = p.row_index
where p.row_index is not null and r.row_index is null
