-- Slice 3 Task 1: candidate concepts for share of net assets, by fund. Facts of the five funds' parsed filings whose
-- local name mentions percent or net assets, on contexts that carry an investment identifier member, with how many
-- sit on rows this layer publishes as positions. Row limit through run_sql.py.
with f as (
    select fi.cik, f.accession, f.context_id, f.concept_namespace, f.concept_local
    from stg_filed_fact f
    join stg_filed_filing fi on fi.accession = f.accession
    where f.concept_local ilike '%percent%' or f.concept_local ilike '%netasset%'
)
select
    f.cik
    , regexp_replace(f.concept_namespace, '/[0-9][0-9a-z-]*$', '/*') as namespace_pattern
    , f.concept_local
    , count(*) as facts
    , count(*) filter (where cf.has_identifier_member) as on_identifier_contexts
    , count(*) filter (where s.role = 'position' and s.is_published) as on_published_positions
from f
left join int_context_feature cf on cf.accession = f.accession and cf.context_id = f.context_id
left join int_source_row s on s.accession = f.accession and s.context_id = f.context_id
group by all
having count(*) filter (where cf.has_identifier_member) > 0
order by f.concept_local, f.cik
