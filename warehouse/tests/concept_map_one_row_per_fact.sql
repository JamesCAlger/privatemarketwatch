-- Slice 3 Task 1: a filed fact matches at most one row of the seed concept_map (local name and namespace glob). Two
-- matching rows would count the fact twice in int_context_feature and int_filing_candidate. Lists each concept and
-- namespace that matches more than one row.
select f.concept_namespace, f.concept_local, count(distinct m.concept_map_id) as map_rows
from (select distinct concept_namespace, concept_local from {{ ref('stg_filed_fact') }}) f
join {{ ref('concept_map') }} m on m.concept_local = f.concept_local and f.concept_namespace glob m.namespace_pattern
group by 1, 2
having count(distinct m.concept_map_id) > 1
