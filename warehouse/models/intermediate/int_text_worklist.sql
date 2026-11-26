-- Decides the coverage state of every column unit and every shape unit (text slice R phase 1, 2026-11-26; spec section
-- 4.2 and step 2 of section 4: "covered, not covered, or changed"). One row per unit: work_key (the unit_key of a
-- column, the shape_key of a shape).
--
-- Units: every column unit of int_text_column_unit (unit_type 'column'), and every shape unit of int_text_shape_unit
-- (unit_type 'shape'; rate-candidate columns only).
-- "A rule reads it":
--   column  an existing read_printed_column rule names the column (int_text_column_unit.read_rule_ids).
--   shape   its column is read so, and at least one of its texts gets status read in int_text_reference_rate_read
--           (a map_code or label_is_unspecified rule maps its code; matched on unit_key and macro text_shape of the
--           read text). A shape whose code no rule maps is not read, even inside a read column.
-- Checks on what a rule reads (rows of int_text_reference_rate_read with status read in the unit):
--   legend       the map_code rules those rows used (int_text_check_legend_rule.state): fails when any is 'mixed' or
--                'contradicts'; passes when any is 'agrees' and none fails.
--   spread_base  rows read as SOFR (int_text_check_spread_base, is_read_sofr) per quarter: a quarter with at least
--                var text_spread_base_min_rows (10) checked rows fails when its pass share is below var
--                text_spread_base_min_share (0.90), passes otherwise. Quarters with fewer checked rows do not count.
-- state:
--   uncovered          no rule reads the unit.
--   failed_check       a rule reads it and a check fails.
--   covered            a rule reads it, a check applies and none fails.
--   covered_unchecked  a rule reads it and no check applies.
-- changed_state: the spec's "changed" (a covered unit whose content shifted) is NOT built in phase 1: always null.
with column_unit as (
    select unit_key, cik, is_rate_candidate, read_rule_ids, position_cells
    from {{ ref('int_text_column_unit') }}
)

, shape_unit as (
    select s.shape_key, s.unit_key, s.cik, s.shape, s.cell_count, c.read_rule_ids
    from {{ ref('int_text_shape_unit') }} s
    join column_unit c on c.unit_key = s.unit_key
)

, read_row as (
    select r.unit_key, {{ text_shape('r.cell_text') }} as shape, r.map_rule_id, l.state as legend_state
    from {{ ref('int_text_reference_rate_read') }} r
    left join {{ ref('int_text_check_legend_rule') }} l on l.rule_id = r.map_rule_id
    where r.status = 'read'
)

, base_row as (
    select unit_key, {{ text_shape('cell_text') }} as shape, report_date, check_state
    from {{ ref('int_text_check_spread_base') }}
    where is_read_sofr
)

{% set min_rows = var('text_spread_base_min_rows') %}
{% set min_share = var('text_spread_base_min_share') %}

, base_quarter_column as (
    select unit_key, report_date, count(*) filter (where check_state in ('pass', 'fail')) as checked
        , count(*) filter (where check_state = 'pass') as passed
    from base_row group by 1, 2
)

, base_quarter_shape as (
    select unit_key, shape, report_date, count(*) filter (where check_state in ('pass', 'fail')) as checked
        , count(*) filter (where check_state = 'pass') as passed
    from base_row group by 1, 2, 3
)

, column_check as (
    select c.unit_key
        , coalesce(rd.n_read, 0) as n_read
        , coalesce(rd.legend_fail, false) as legend_fail
        , coalesce(rd.legend_pass, false) as legend_pass
        , coalesce(bq.quarters_checked, 0) as base_quarters_checked
        , coalesce(bq.quarters_failed, 0) as base_quarters_failed
    from column_unit c
    left join (
        select unit_key, count(*) as n_read, bool_or(legend_state in ('contradicts', 'mixed')) as legend_fail
            , bool_or(legend_state = 'agrees') as legend_pass
        from read_row group by 1
    ) rd on rd.unit_key = c.unit_key
    left join (
        select unit_key, count(*) as quarters_checked
            , count(*) filter (where passed / checked < {{ min_share }}) as quarters_failed
        from base_quarter_column where checked >= {{ min_rows }} group by 1
    ) bq on bq.unit_key = c.unit_key
)

, shape_check as (
    select s.shape_key
        , coalesce(rd.n_read, 0) as n_read
        , coalesce(rd.legend_fail, false) as legend_fail
        , coalesce(rd.legend_pass, false) as legend_pass
        , coalesce(bq.quarters_checked, 0) as base_quarters_checked
        , coalesce(bq.quarters_failed, 0) as base_quarters_failed
    from shape_unit s
    left join (
        select unit_key, shape, count(*) as n_read, bool_or(legend_state in ('contradicts', 'mixed')) as legend_fail
            , bool_or(legend_state = 'agrees') as legend_pass
        from read_row group by 1, 2
    ) rd on rd.unit_key = s.unit_key and rd.shape = s.shape
    left join (
        select unit_key, shape, count(*) as quarters_checked
            , count(*) filter (where passed / checked < {{ min_share }}) as quarters_failed
        from base_quarter_shape where checked >= {{ min_rows }} group by 1, 2
    ) bq on bq.unit_key = s.unit_key and bq.shape = s.shape
)

, unit_row as (
    select c.unit_key as work_key, 'column' as unit_type, c.unit_key, null::varchar as shape_key, c.cik
        , null::varchar as shape, c.is_rate_candidate, c.read_rule_ids, c.position_cells as texts
        , c.read_rule_ids is not null as is_read, k.n_read, k.legend_fail, k.legend_pass, k.base_quarters_checked
        , k.base_quarters_failed
    from column_unit c
    join column_check k on k.unit_key = c.unit_key
    union all
    select s.shape_key, 'shape', s.unit_key, s.shape_key, s.cik, s.shape, true, s.read_rule_ids, s.cell_count
        , s.read_rule_ids is not null and k.n_read > 0, k.n_read, k.legend_fail, k.legend_pass, k.base_quarters_checked
        , k.base_quarters_failed
    from shape_unit s
    join shape_check k on k.shape_key = s.shape_key
)

select
    work_key
    , unit_type
    , unit_key
    , shape_key
    , cik
    , shape
    , is_rate_candidate
    , read_rule_ids
    , texts
    , n_read
    , case when legend_fail then 'fails' when legend_pass then 'passes' else 'not_applicable' end as legend_check
    , base_quarters_checked
    , base_quarters_failed
    , case
        when not is_read then 'uncovered'
        when legend_fail or base_quarters_failed > 0 then 'failed_check'
        when legend_pass or base_quarters_checked > 0 then 'covered'
        else 'covered_unchecked'
    end as state
    , null::varchar as changed_state
from unit_row
