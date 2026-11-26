-- Decides the coverage state of every column unit and every shape unit (text slice R phase 1, 2026-11-26; spec section
-- 4.2 and step 2 of section 4; shares since fix round 1; per-row check since fix round 2). One row per unit: work_key
-- (the unit_key of a column, the shape_key of a shape).
--
-- Units: every column unit of int_text_column_unit (unit_type 'column') and every shape unit of int_text_shape_unit
-- (unit_type 'shape'; rate-candidate columns only).
-- rows_in_unit: positions on the unit's non-empty position-row texts (int_text_cell.positions summed; for a shape, the
-- shape unit's positions). Counted in positions because a reading is per position.
-- Each position int_text_reference_rate_read reads (status read; for a shape, matched on unit_key and macro
-- text_shape_key of the read text) gets one read status, from the only check that tests a single row: the legend of
-- its own filing (int_text_check_legend_read.legend_verdict) for the rule that read it.
--   read_unspecified  read by a label_is_unspecified rule (verdict not_applicable): it names no rate, so it never counts
--                     as read for coverage.
--   read_failed       the filing's legend is mixed or contradicts the rule.
--   read_and_checked  the filing's legend agrees with the rule.
--   read_unchecked    no legend for the code in the filing, or one with no abbreviation (unclear).
-- No arithmetic check counts: the SOFR level and implied-base models are measurements (fix round 2; baseline note
-- section 13).
-- Counts: rows_read (read positions other than read_unspecified), rows_read_checked, rows_read_unchecked,
-- rows_read_failed, rows_read_unspecified. share_read = rows_read / rows_in_unit; share_read_checked = rows_read_checked
-- / rows_in_unit.
-- Quarter lists ('YYYY-MM-DD' joined by ','): failing_quarters (a read_failed position there), checked_quarters
-- (a read_and_checked position there).
-- state, the first that applies:
--   uncovered          no read_printed_column rule names the column (for a shape: its column), or no position is read
--                      (read_unspecified positions do not count).
--   failed_check       some position is read_failed (see failing_quarters).
--   covered            share_read_checked >= var text_covered_min_share (0.95): at least 95% of the unit's positions are
--                      read and confirmed by their own filing's legend.
--   covered_unchecked  share_read >= 0.95, fewer than 95% confirmed: no check available for the rest.
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
        , case
            when l.legend_verdict = 'not_applicable' then 'read_unspecified'
            when l.legend_verdict in ('mixed', 'contradicts') then 'read_failed'
            when l.legend_verdict = 'agrees' then 'read_and_checked'
            else 'read_unchecked'
        end as read_status
    from {{ ref('int_text_reference_rate_read') }} r
    left join {{ ref('int_text_check_legend_read') }} l on l.accession = r.accession and l.context_id = r.context_id
    where r.status = 'read'
)

{% set summary_columns %}
        count(*) filter (where read_status <> 'read_unspecified') as rows_read
        , count(*) filter (where read_status = 'read_and_checked') as rows_read_checked
        , count(*) filter (where read_status = 'read_unchecked') as rows_read_unchecked
        , count(*) filter (where read_status = 'read_failed') as rows_read_failed
        , count(*) filter (where read_status = 'read_unspecified') as rows_read_unspecified
        , string_agg(distinct strftime(report_date, '%Y-%m-%d'), ',' order by strftime(report_date, '%Y-%m-%d'))
            filter (where read_status = 'read_failed') as failing_quarters
        , string_agg(distinct strftime(report_date, '%Y-%m-%d'), ',' order by strftime(report_date, '%Y-%m-%d'))
            filter (where read_status = 'read_and_checked') as checked_quarters
    from read_row
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
    , coalesce(rows_read_checked, 0) as rows_read_checked
    , coalesce(rows_read_unchecked, 0) as rows_read_unchecked
    , coalesce(rows_read_failed, 0) as rows_read_failed
    , coalesce(rows_read_unspecified, 0) as rows_read_unspecified
    , coalesce(rows_read, 0) / nullif(rows_in_unit, 0) as share_read
    , coalesce(rows_read_checked, 0) / nullif(rows_in_unit, 0) as share_read_checked
    , failing_quarters
    , checked_quarters
    , case
        when read_rule_ids is null or coalesce(rows_read, 0) = 0 then 'uncovered'
        when rows_read_failed > 0 then 'failed_check'
        when coalesce(rows_read_checked, 0) / nullif(rows_in_unit, 0) >= {{ bar }} then 'covered'
        when coalesce(rows_read, 0) / nullif(rows_in_unit, 0) >= {{ bar }} then 'covered_unchecked'
        else 'partly_covered'
    end as state
    , null::varchar as changed_state
from unit_row
