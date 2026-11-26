-- Text slice R phase 1 (2026-11-26): the key of each rate-text model is unique (null parts counted as '~'),
-- int_text_reference_rate_read has a row for every position with a printed row, and int_text_worklist.changed_state is
-- null everywhere (the "changed" state is not built in phase 1). Returns one row per duplicated key (n > 1), missing
-- position (n = 0) or filled changed_state (n = -1).
select 'int_text_cell' as model, accession || '|' || row_index || '|' || col_start as key, count(*) as n
from {{ ref('int_text_cell') }} group by 1, 2 having count(*) > 1
union all
select 'int_text_reference_rate_read', accession || '|' || context_id, count(*)
from {{ ref('int_text_reference_rate_read') }} group by 1, 2 having count(*) > 1
union all
select 'int_text_reference_rate_read', p.accession || '|' || p.context_id, 0
from {{ ref('int_page_position') }} p
anti join {{ ref('int_text_reference_rate_read') }} r on r.accession = p.accession and r.context_id = p.context_id
where p.placement_status = 'one_row'
union all
select 'int_text_check_legend', cik || '|' || accession || '|' || code || '|' || name || '|' || coalesce(abbreviation, '~'), count(*)
from {{ ref('int_text_check_legend') }} group by 1, 2 having count(*) > 1
union all
select 'int_text_check_legend_code', cik || '|' || code_key, count(*)
from {{ ref('int_text_check_legend_code') }} group by 1, 2 having count(*) > 1
union all
select 'int_text_measure_sofr_level', accession || '|' || context_id, count(*)
from {{ ref('int_text_measure_sofr_level') }} group by 1, 2 having count(*) > 1
union all
select 'int_text_measure_sofr_level_unit', unit_key || '|' || report_date || '|' || code_key, count(*)
from {{ ref('int_text_measure_sofr_level_unit') }} group by 1, 2 having count(*) > 1
union all
select 'int_text_check_shape_legs', shape_key || '|' || number_label || '|' || tag_field, count(*)
from {{ ref('int_text_check_shape_legs') }} group by 1, 2 having count(*) > 1
union all
select 'int_text_worklist changed_state', work_key, -1
from {{ ref('int_text_worklist') }} where changed_state is not null
union all
select 'int_text_check_legend_read', accession || '|' || context_id, count(*)
from {{ ref('int_text_check_legend_read') }} group by 1, 2 having count(*) > 1
union all
select 'int_text_check_legend_quarter', unit_key || '|' || report_date, count(*)
from {{ ref('int_text_check_legend_quarter') }} group by 1, 2 having count(*) > 1
union all
select 'int_text_check_base_cluster', accession || '|' || context_id || '|' || basis, count(*)
from {{ ref('int_text_check_base_cluster') }} group by 1, 2 having count(*) > 1
union all
select 'int_text_check_base_cluster_group', cik || '|' || report_date || '|' || basis || '|' || coalesce(rate_label, '~'), count(*)
from {{ ref('int_text_check_base_cluster_group') }} group by 1, 2 having count(*) > 1
