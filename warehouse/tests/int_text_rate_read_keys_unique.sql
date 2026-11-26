-- Text slice R phase 3 (2026-11-26): the grain of each model of the accepted-rule read is unique (null parts counted as
-- '~'). Returns one row per duplicated key.
select 'int_text_check_fixed_rate' as model, unit_key || '|' || shape as key, count(*) as n
from {{ ref('int_text_check_fixed_rate') }} group by 1, 2 having count(*) > 1
union all
select 'int_text_legend_rate', cik || '|' || accession || '|' || code_key, count(*)
from {{ ref('int_text_legend_rate') }} group by 1, 2 having count(*) > 1
union all
select 'int_text_rate_read_cell', accession || '|' || context_id || '|' || unit_key || '|' || number_index, count(*)
from {{ ref('int_text_rate_read_cell') }} group by 1, 2 having count(*) > 1
union all
select 'int_text_rate_read', accession || '|' || context_id, count(*)
from {{ ref('int_text_rate_read') }} group by 1, 2 having count(*) > 1
union all
select 'int_text_rate_constraint', accession || '|' || context_id || '|' || constraint_name, count(*)
from {{ ref('int_text_rate_constraint') }} group by 1, 2 having count(*) > 1
union all
select 'int_text_rate_held', accession || '|' || context_id || '|' || field || '|' || rule_id, count(*)
from {{ ref('int_text_rate_held') }} group by 1, 2 having count(*) > 1
union all
select 'int_text_rate_finding', cik || '|' || constraint_name || '|' || rule_id, count(*)
from {{ ref('int_text_rate_finding') }} group by 1, 2 having count(*) > 1
union all
select 'int_text_rate_read null key', coalesce(accession, '~') || '|' || coalesce(context_id, '~'), count(*)
from {{ ref('int_text_rate_read') }} where accession is null or context_id is null group by 1, 2
union all
select 'int_text_rate_read_cell null key', coalesce(accession, '~') || '|' || coalesce(context_id, '~'), count(*)
from {{ ref('int_text_rate_read_cell') }} where accession is null or context_id is null or unit_key is null
group by 1, 2
