-- Slice 3 Task 2: every unresolved field, with the facts behind it.
select r.cik, r.report_date, r.accession, r.context_id, r.field, r.reason, r.fact_count, s.is_published
    , string_agg(f.value_text || ' ' || f.unit_id || ' ' || f.fact_id, ' ; ') as facts
from int_field_read r
join int_source_row s on s.accession = r.accession and s.context_id = r.context_id
join stg_filed_fact f on f.accession = r.accession and f.context_id = r.context_id
join concept_map m on m.concept_local = f.concept_local and f.concept_namespace glob m.namespace_pattern and m.field = r.field
where r.status = 'unresolved'
group by all
order by 1, 2, 4
