-- A placement carries the same concept and context as the fact it points at. Returns the placements that differ.
select p.accession, p.fact_id, p.concept as placement_concept, f.concept as fact_concept,
       p.context_id as placement_context, f.context_id as fact_context
from {{ ref('stg_filed_fact_placement') }} p
join {{ ref('stg_filed_fact') }} f on f.accession = p.accession and f.fact_id = p.fact_id
where p.concept is distinct from f.concept or p.context_id is distinct from f.context_id
