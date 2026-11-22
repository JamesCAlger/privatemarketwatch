-- Slice 3 Task 1: a (field, concept, namespace pattern) appears once in the seed concept_map.
select field, concept_local, namespace_pattern, count(*) as n
from {{ ref('concept_map') }}
group by 1, 2, 3
having count(*) > 1
