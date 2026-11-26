-- Decides the coverage state of every column unit and every shape unit (text slice R phase 1, 2026-11-26; spec section
-- 4.2 and step 2 of section 4; shares and dated checks since fix round 1). One row per unit: work_key (the unit_key of
-- a column, the shape_key of a shape).
--
-- Units: every column unit of int_text_column_unit (unit_type 'column') and every shape unit of int_text_shape_unit
-- (unit_type 'shape'; rate-candidate columns only).
-- rows_in_unit: positions on the unit's non-empty position-row texts (int_text_cell.positions summed; for a shape, the
-- shape unit's positions). Counted in positions because a reading is per position.
-- rows_read: positions of the unit that int_text_reference_rate_read reads (status read; for a shape, matched on
-- unit_key and macro text_shape_key of the read text).
-- Per read position, its checks (each dated: only its own filing and quarter count):
--   legend   int_text_check_legend_read.legend_verdict: fails when contradicts or mixed, passes when agrees.
--   cluster  int_text_check_base_cluster_group, basis 'rule', the row's fund, quarter and reference rate: fails when
--            check_state fail, passes when pass.
--   row check: fails if either fails; passes if either passes and none fails; unchecked otherwise.
-- rows_read_by_passing_rule, rows_read_failing: positions whose row check passes / fails.
-- share_read = rows_read / rows_in_unit; share_read_passing = rows_read_by_passing_rule / rows_in_unit.
-- Quarter lists ('YYYY-MM-DD' joined by ','): failing_quarters (a read position fails there), legend_agree_quarters,
-- legend_mixed_quarters, legend_contradict_quarters, cluster_pass_quarters, cluster_fail_quarters.
-- state, the first that applies:
--   uncovered          no read_printed_column rule names the column (for a shape: its column), or the rules read none
--                      of the unit's positions.
--   failed_check       some read position fails a check (see failing_quarters).
--   covered            share_read_passing >= var text_covered_min_share (0.95): at least 95% of the unit's positions are
--                      read by rules that pass a check in their own quarter.
--   covered_unchecked  share_read >= 0.95, but fewer than 95% are confirmed by a check.
--   partly_covered     some positions are read, fewer than 95%.
-- changed_state: the spec's "changed" (a covered unit whose content shifted) is NOT built in phase 1: always null.
{% set bar = var('text_covered_min_share') %}
with column_unit as (
    select unit_key, cik, is_rate_candidate, read_rule_ids
    from {{ ref('int_text_column_unit') }}
)

, column_rows as (
    select unit_key, sum(positions) as rows_in_unit
    from {{ ref('int_text_cell') }}
    where text <> ''
    group by 1
)

, shape_unit as (
    select s.shape_key, s.unit_key, s.cik, s.shape, s.shape_key_text, s.positions as rows_in_unit, c.read_rule_ids
    from {{ ref('int_text_shape_unit') }} s
    join column_unit c on c.unit_key = s.unit_key
)

, read_row as (
    select r.accession, r.context_id, r.unit_key, r.report_date
        , {{ text_shape_key('r.cell_text') }} as shape_key_text
        , l.legend_verdict
        , g.check_state as cluster_state
    from {{ ref('int_text_reference_rate_read') }} r
    left join {{ ref('int_text_check_legend_read') }} l on l.accession = r.accession and l.context_id = r.context_id
    left join {{ ref('int_text_check_base_cluster_group') }} g
        on g.cik = r.cik and g.report_date = r.report_date and g.basis = 'rule' and g.rate_label = r.reference_rate
    where r.status = 'read'
)

, row_check as (
    select *
        , case
            when legend_verdict in ('contradicts', 'mixed') or cluster_state = 'fail' then 'fails'
            when legend_verdict = 'agrees' or cluster_state = 'pass' then 'passes'
            else 'unchecked'
        end as row_check
    from read_row
)

{% set summary_columns %}

        count(*) as rows_read
        , count(*) filter (where row_check = 'passes') as rows_read_by_passing_rule
        , count(*) filter (where row_check = 'fails') as rows_read_failing
        , string_agg(distinct strftime(report_date, '%Y-%m-%d'), ',' order by strftime(report_date, '%Y-%m-%d'))
            filter (where row_check = 'fails') as failing_quarters
        , string_agg(distinct strftime(report_date, '%Y-%m-%d'), ',' order by strftime(report_date, '%Y-%m-%d'))
            filter (where legend_verdict = 'agrees') as legend_agree_quarters
        , string_agg(distinct strftime(report_date, '%Y-%m-%d'), ',' order by strftime(report_date, '%Y-%m-%d'))
            filter (where legend_verdict = 'mixed') as legend_mixed_quarters
        , string_agg(distinct strftime(report_date, '%Y-%m-%d'), ',' order by strftime(report_date, '%Y-%m-%d'))
            filter (where legend_verdict = 'contradicts') as legend_contradict_quarters
        , string_agg(distinct strftime(report_date, '%Y-%m-%d'), ',' order by strftime(report_date, '%Y-%m-%d'))
            filter (where cluster_state = 'pass') as cluster_pass_quarters
        , string_agg(distinct strftime(report_date, '%Y-%m-%d'), ',' order by strftime(report_date, '%Y-%m-%d'))
            filter (where cluster_state = 'fail') as cluster_fail_quarters
    from row_check
{% endset %}

, column_check as (
    select unit_key, {{ summary_columns }}
    group by unit_key
)

, shape_check as (
    select unit_key, shape_key_text, {{ summary_columns }}
    group by unit_key, shape_key_text
)

, unit_row as (
    select c.unit_key as work_key, 'column' as unit_type, c.unit_key, null::varchar as shape_key, c.cik
        , null::varchar as shape, c.is_rate_candidate, c.read_rule_ids, coalesce(cr.rows_in_unit, 0) as rows_in_unit
        , k.* exclude (unit_key)
    from column_unit c
    left join column_rows cr on cr.unit_key = c.unit_key
    left join column_check k on k.unit_key = c.unit_key
    union all by name
    select s.shape_key as work_key, 'shape' as unit_type, s.unit_key, s.shape_key, s.cik, s.shape, true as is_rate_candidate
        , s.read_rule_ids, s.rows_in_unit, k.* exclude (unit_key, shape_key_text)
    from shape_unit s
    left join shape_check k on k.unit_key = s.unit_key and k.shape_key_text = s.shape_key_text
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
    , rows_in_unit
    , coalesce(rows_read, 0) as rows_read
    , coalesce(rows_read_by_passing_rule, 0) as rows_read_by_passing_rule
    , coalesce(rows_read_failing, 0) as rows_read_failing
    , coalesce(rows_read, 0) / nullif(rows_in_unit, 0) as share_read
    , coalesce(rows_read_by_passing_rule, 0) / nullif(rows_in_unit, 0) as share_read_passing
    , failing_quarters
    , legend_agree_quarters
    , legend_mixed_quarters
    , legend_contradict_quarters
    , cluster_pass_quarters
    , cluster_fail_quarters
    , case
        when read_rule_ids is null or coalesce(rows_read, 0) = 0 then 'uncovered'
        when rows_read_failing > 0 then 'failed_check'
        when coalesce(rows_read_by_passing_rule, 0) / nullif(rows_in_unit, 0) >= {{ bar }} then 'covered'
        when coalesce(rows_read, 0) / nullif(rows_in_unit, 0) >= {{ bar }} then 'covered_unchecked'
        else 'partly_covered'
    end as state
    , null::varchar as changed_state
from unit_row
