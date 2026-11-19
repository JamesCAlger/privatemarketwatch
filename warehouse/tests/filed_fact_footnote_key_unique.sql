-- Composite key of fact_footnote must be unique. Returns the duplicated keys.
select accession, fact_id, footnote_id, count(*) as n
from {{ ref('stg_filed_fact_footnote') }}
group by 1,2,3
having count(*) > 1
