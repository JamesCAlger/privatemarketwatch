-- Task 5, Blue Owl amendment: c-1013 of 0001812554-26-000027. Its members, its facts, the printed rows its facts sit
-- on (and the rows around them), and every context in the filing whose label names OWL-HP FINANCE or LSI Financing.
with acc as (select '0001812554-26-000027' as accession)
select 'member' k, m.context_id, m.axis, m.member, null::varchar v
from stg_filed_context_member m, acc where m.accession = acc.accession and m.context_id in ('c-1012', 'c-1013')
union all
select 'fact', f.context_id, f.concept_namespace, f.concept_local, f.value_numeric::varchar
from stg_filed_fact f, acc where f.accession = acc.accession and f.context_id in ('c-1012', 'c-1013')
union all
select 'label', cf.context_id, cf.identifier_label, r.role || ' ' || r.is_published, cf.fair_value::varchar
from int_context_feature cf join int_source_row r using (accession, context_id), acc
where cf.accession = acc.accession and regexp_matches(lower(cf.identifier_label), 'owl-hp|lsi financing')
order by 1, 2, 3
