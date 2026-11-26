-- Text slice R phase 2 (2026-11-26): the key of each proposal seed and proposal model is unique (null parts counted as
-- '~'), every proposal has exactly one verdict row, and every column unit of the proposals is a rate-candidate column.
-- Returns one row per duplicated key (n > 1), proposal without a verdict (n = 0) or proposed unit that is not a rate
-- candidate (n = -1).
select 'text_proposed_shape_role' as model, run_id || '|' || unit_key || '|' || shape || '|' || number_index as key
    , count(*) as n
from {{ ref('text_proposed_shape_role') }} group by 1, 2 having count(*) > 1
union all
select 'text_proposed_code', run_id || '|' || unit_key || '|' || code, count(*)
from {{ ref('text_proposed_code') }} group by 1, 2 having count(*) > 1
union all
select 'int_text_rate_proposed', accession || '|' || context_id || '|' || unit_key || '|' || number_index, count(*)
from {{ ref('int_text_rate_proposed') }} group by 1, 2 having count(*) > 1
union all
select 'int_text_rate_proposed_position', accession || '|' || context_id, count(*)
from {{ ref('int_text_rate_proposed_position') }} group by 1, 2 having count(*) > 1
union all
select 'int_text_check_number_tag', accession || '|' || context_id || '|' || unit_key || '|' || number_index, count(*)
from {{ ref('int_text_check_number_tag') }} group by 1, 2 having count(*) > 1
union all
select 'int_text_check_leg_arithmetic', accession || '|' || context_id || '|' || identity, count(*)
from {{ ref('int_text_check_leg_arithmetic') }} group by 1, 2 having count(*) > 1
union all
select 'int_text_base_rate_window', report_date || '|' || rate_name, count(*)
from {{ ref('int_text_base_rate_window') }} group by 1, 2 having count(*) > 1
union all
select 'int_text_check_base_level', accession || '|' || context_id || '|' || candidate_rate, count(*)
from {{ ref('int_text_check_base_level') }} group by 1, 2 having count(*) > 1
union all
select 'int_text_check_base_level_quarter', code_unit_key || '|' || code_key || '|' || report_date, count(*)
from {{ ref('int_text_check_base_level_quarter') }} group by 1, 2 having count(*) > 1
union all
select 'int_text_check_code_legend', unit_key || '|' || code_key || '|' || accession, count(*)
from {{ ref('int_text_check_code_legend') }} group by 1, 2 having count(*) > 1
union all
select 'int_text_proposal_verdict'
    , proposal_kind || '|' || unit_key || '|' || coalesce(shape, '~') || '|' || coalesce(code, '~'), count(*)
from {{ ref('int_text_proposal_verdict') }} group by 1, 2 having count(*) > 1
union all
select 'int_text_proposal_verdict', 'column|' || p.unit_key, 0
from {{ ref('text_proposed_column') }} p
anti join {{ ref('int_text_proposal_verdict') }} v on v.proposal_kind = 'column' and v.unit_key = p.unit_key
union all
select 'int_text_proposal_verdict', 'shape|' || p.unit_key || '|' || p.shape, 0
from (select distinct unit_key, shape from {{ ref('text_proposed_shape_role') }}) p
anti join {{ ref('int_text_proposal_verdict') }} v
    on v.proposal_kind = 'shape' and v.unit_key = p.unit_key and v.shape = p.shape
union all
select 'int_text_proposal_verdict', 'code|' || p.unit_key || '|' || p.code, 0
from {{ ref('text_proposed_code') }} p
anti join {{ ref('int_text_proposal_verdict') }} v
    on v.proposal_kind = 'code' and v.unit_key = p.unit_key and v.code = p.code
{%- if not var('ci_fixture', false) %}
-- Not on the CI fixture: its invented fund has none of the proposals' column units.
union all
select 'text_proposed_column', p.unit_key, -1
from {{ ref('text_proposed_column') }} p
anti join {{ ref('int_text_column_unit') }} u on u.unit_key = p.unit_key and u.is_rate_candidate
{%- endif %}
