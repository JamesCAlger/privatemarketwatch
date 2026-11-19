-- Composite key of fact_placement must be unique. Returns the duplicated keys.
select accession, fact_id, count(*) as n
from {{ ref('stg_filed_fact_placement') }}
group by 1,2
having count(*) > 1
