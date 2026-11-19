-- Every fact that names a unit finds it in the same filing. Returns the facts that do not.
select f.accession, f.fact_id, f.unit_id
from {{ ref('stg_filed_fact') }} f
left join {{ ref('stg_filed_unit') }} u on u.accession = f.accession and u.unit_id = f.unit_id
where f.unit_id is not null and u.unit_id is null
