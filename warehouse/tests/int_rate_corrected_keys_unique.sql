-- Slice 5 Task 4: the keys of the rate correction models are unique. int_rate_adjacent: (accession, taker_context_id)
-- and (accession, giver_context_id), a context gives to or takes from one other only; int_rate_corrected_input:
-- (run, accession, context_id); int_rate_corrected: (run, accession, context_id, field).
select 'int_rate_adjacent taker' as model, accession || '|' || taker_context_id as key_, count(*) as n
from {{ ref('int_rate_adjacent') }} group by 2 having count(*) > 1
union all
select 'int_rate_adjacent giver', accession || '|' || giver_context_id, count(*)
from {{ ref('int_rate_adjacent') }} group by 2 having count(*) > 1
union all
select 'int_rate_corrected_input', run || '|' || accession || '|' || context_id, count(*)
from {{ ref('int_rate_corrected_input') }} group by 2 having count(*) > 1
union all
select 'int_rate_corrected', run || '|' || accession || '|' || context_id || '|' || field, count(*)
from {{ ref('int_rate_corrected') }} group by 2 having count(*) > 1
