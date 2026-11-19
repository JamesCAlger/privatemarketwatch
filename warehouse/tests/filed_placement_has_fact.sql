-- Every placement has a fact in the instance. Returns the placements that do not.
select p.accession, p.fact_id, p.concept
from {{ ref('stg_filed_fact_placement') }} p
left join {{ ref('stg_filed_fact') }} f on f.accession = p.accession and f.fact_id = p.fact_id
where f.fact_id is null
