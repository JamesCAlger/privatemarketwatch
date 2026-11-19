-- Fix round 3: contexts carrying both the us-gaap fair value and a filer fair-value concept; do the values agree?
with filer as (
  select ff.accession, ff.context_id, count(distinct ff.value_numeric) nvals, min(ff.value_numeric) v
  from stg_filed_fact ff
  join stg_filed_filing fi on fi.accession = ff.accession
  join filer_concept s on s.cik = fi.cik and s.concept_namespace = ff.concept_namespace
    and s.concept_local = ff.concept_local and s.maps_to = 'fair_value'
  group by 1, 2
)
select cf.cik, cf.has_identifier_member, cf.is_filing_period_end
  , case when cf.fair_value is null or f.nvals <> 1 then 'not comparable' when cf.fair_value = f.v then 'agree' else 'differ' end as cmp
  , count(*) n, sum(cf.fair_value) std_fv, sum(f.v) filer_fv
from int_context_feature cf join filer f using (accession, context_id)
where cf.fair_value_filer_concept_also_present
group by all order by all
