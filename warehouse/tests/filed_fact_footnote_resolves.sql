-- Every fact-footnote pair points at an existing footnote and an existing fact. Returns the pairs that do not.
select ff.accession, ff.fact_id, ff.footnote_id,
       fn.footnote_id is null as footnote_missing,
       f.fact_id is null      as fact_missing
from {{ ref('stg_filed_fact_footnote') }} ff
left join {{ ref('stg_filed_footnote') }} fn on fn.accession = ff.accession and fn.footnote_id = ff.footnote_id
left join {{ ref('stg_filed_fact') }} f on f.accession = ff.accession and f.fact_id = ff.fact_id
where fn.footnote_id is null or f.fact_id is null
