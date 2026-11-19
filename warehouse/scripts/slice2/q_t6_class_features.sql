-- Task 6: for the 133 owner-review rows (as now held unresolved, production publishing them), the other axes and
-- members on the context and every concept tagged on it, to find the feature each class can be selected on.
with h as (
    select c.basis, c.cik, c.report_date, c.accession, c.context_id, cf.identifier_label, c.fair_value
        , cf.other_axes, cf.other_members
    from cmp_row_set c join int_context_feature cf using (accession, context_id)
    where c.side = 'production_only' and c.role = 'unresolved' and c.cause in ('new_wrong', 'owner_review')
)
select h.cik, h.basis, h.identifier_label, h.report_date, h.context_id
    , array_to_string(h.other_axes, ';') as axes, array_to_string(h.other_members, ';') as members
    , (select string_agg(distinct regexp_replace(f.concept_namespace, '^https?://', '') || '#' || f.concept_local, ' ')
       from stg_filed_fact f where f.accession = h.accession and f.context_id = h.context_id) as concepts
from h
order by 1, 2, 3, 4
