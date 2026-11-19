-- Composite key of footnote must be unique. Returns the duplicated keys.
select accession, footnote_id, count(*) as n
from {{ ref('stg_filed_footnote') }}
group by 1,2
having count(*) > 1
