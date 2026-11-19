-- Composite key of unit must be unique. Returns the duplicated keys.
select accession, unit_id, count(*) as n
from {{ ref('stg_filed_unit') }}
group by 1,2
having count(*) > 1
