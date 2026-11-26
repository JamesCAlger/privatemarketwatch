-- Slice 5 Task 3: the keys of the four correction models are unique. int_correction_target and
-- int_correction_application: (correction_id, accession, context_id), a null context counted as one value;
-- int_row_corrected: (accession, context_id); int_field_corrected: (accession, context_id, field). Also
-- int_correction_screen (the target grain).
select 'int_correction_target' as model, correction_id || '|' || coalesce(accession, '') || '|' || coalesce(context_id, '') as key_, count(*) as n
from {{ ref('int_correction_target') }} group by 2 having count(*) > 1
union all
select 'int_correction_screen', correction_id || '|' || coalesce(accession, '') || '|' || coalesce(context_id, ''), count(*)
from {{ ref('int_correction_screen') }} group by 2 having count(*) > 1
union all
select 'int_correction_application', correction_id || '|' || coalesce(accession, '') || '|' || coalesce(context_id, ''), count(*)
from {{ ref('int_correction_application') }} group by 2 having count(*) > 1
union all
select 'int_row_corrected', accession || '|' || context_id, count(*)
from {{ ref('int_row_corrected') }} group by 2 having count(*) > 1
union all
select 'int_field_corrected', accession || '|' || context_id || '|' || field, count(*)
from {{ ref('int_field_corrected') }} group by 2 having count(*) > 1
