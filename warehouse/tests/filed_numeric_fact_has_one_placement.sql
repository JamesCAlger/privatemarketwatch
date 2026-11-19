-- Every numeric fact (one that names a unit) has exactly one placement in the document. Returns the facts that do not.
select f.accession, f.fact_id, count(p.fact_id) as placements
from {{ ref('stg_filed_fact') }} f
left join {{ ref('stg_filed_fact_placement') }} p on p.accession = f.accession and p.fact_id = f.fact_id
where f.unit_id is not null
group by 1, 2
having count(p.fact_id) <> 1
