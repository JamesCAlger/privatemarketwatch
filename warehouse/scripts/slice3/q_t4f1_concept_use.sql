-- Slice 3 Task 4 fix round 1: where a filer concept (variables cik, concept = local name) is filed: per filing, the
-- namespace, report date, facts, facts on position contexts, and position contexts that also carry a standard
-- concept_map fact of the field (variable field).
with f as (
    select fi.cik, fi.document_period_end_date as rd, f.accession, f.context_id, f.concept_namespace
    from stg_filed_fact f
    join stg_filed_filing fi on fi.accession = f.accession
    where fi.cik = getvariable('cik') and f.concept_local = getvariable('concept')
)
select f.accession, f.rd, f.concept_namespace, count(*) n_facts
    , count(*) filter (where s.role = 'position') as on_positions
    , count(*) filter (where s.role = 'position' and exists (
        select 1 from stg_filed_fact g join concept_map m on m.concept_local = g.concept_local
            and g.concept_namespace glob m.namespace_pattern and m.field = getvariable('field')
        where g.accession = f.accession and g.context_id = f.context_id)) as positions_with_standard_fact
from f
left join int_source_row s on s.accession = f.accession and s.context_id = f.context_id
group by all order by 2, 1
limit 50
