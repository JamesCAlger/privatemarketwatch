-- Every row of seeds/filer_concept.csv matches at least one filed fact: same filer (cik), exact namespace and local
-- name. A typo in the seed cannot pass silently.
select s.*
from {{ ref('filer_concept') }} s
anti join (
    select distinct fi.cik, f.concept_namespace, f.concept_local
    from {{ ref('stg_filed_fact') }} f
    join {{ ref('stg_filed_filing') }} fi on fi.accession = f.accession
) f on f.cik = s.cik and f.concept_namespace = s.concept_namespace and f.concept_local = s.concept_local
