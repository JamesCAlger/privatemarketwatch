-- Decides the canonical value of each rate field of each position row, by applying the rule int_field_rule chose
-- (spec intermediate_spine.md 6.4). One row per (accession, context_id, field): interest_rate (the all-in rate,
-- percent; rate_kind beside it), interest_rate_cash (the cash leg, percent), pik_rate, spread (percent) and
-- maturity_date (in value_date). value_filed stays beside the value. The rate half of int_field_normalised (slice 5
-- Task 1 split it out unchanged; the amount half is int_amount_normalised, and int_field_normalised is the union of
-- the two). Columns are int_field_normalised's: currency, fx_rate and fx_rate_date are null here.
--
-- This model prepares the inputs, one row per position (CTE reading_input): each rate read field with its state and
-- its number in percent, and the rule of each rate rule field. The reading itself, and what each rate action does, is
-- macro rate_reading (macros/rate_reading.sql), so that it can run again on corrected inputs.
-- Input states: value (usable), absent (no fact or nil only), unresolved (why says why). A number in a ratio unit
-- (unit kind pure, seeds/unit_kind.csv) is a fraction: times 100 (fraction_to_percent). Above 1 it may already be a
-- percent; its scale is not decided by its size (controller ruling): unresolved scale_not_decided, unless a fund scale
-- rule kept it as a percent where the row's own print agrees (int_rate_scale, owner ruling B 2026-11-23): then the
-- filed number is the percent. A number in a unit that is not a ratio: unresolved unit_not_pure. The maturity date is a
-- value as read.
with rule as (
    select * from {{ ref('int_field_rule') }}
)

, read as (
    select * from {{ ref('int_field_read') }}
)

, action as (
    select action, built_in_slice, built_early_for_field from {{ ref('reading_action') }}
)

, rate_read_kind as (
    -- slice 4 Task 3: each rate read field, with its unit kind; owner ruling B (2026-11-23): with the scale decision of
    -- int_rate_scale for a number filed above 1 in a ratio unit (kept_as_percent under a fund scale rule, or not)
    select
        rd.accession
        , rd.context_id
        , rd.field
        , rd.status
        , rd.reason
        , rd.value_filed
        , rd.value_date
        , rd.is_nil
        , case when rd.status = 'read' and not rd.is_nil and rd.value_filed is not null then {{ unit_kind('rd.unit') }} end
            as unit_kind
        , case when sc.outcome = 'kept_as_percent' then sc.scale_rule_id end as scale_rule_id
    from read rd
    left join {{ ref('int_rate_scale') }} sc
        on sc.accession = rd.accession and sc.context_id = rd.context_id and sc.field = rd.field
    where rd.field in {{ rate_read_fields() }}
)

, rate_read as (
    -- state: value (usable), absent (no fact or nil only), unresolved (why says why); see the header
    select
        *
        , case
            when status = 'absent' or is_nil then 'absent'
            when status = 'unresolved' then 'unresolved'
            when field = 'maturity_date' then 'value'
            when unit_kind is distinct from 'pure' then 'unresolved'
            when value_filed > 1 and scale_rule_id is null then 'unresolved'
            else 'value'
          end as state
        , case
            when status = 'absent' or is_nil or status = 'unresolved' then reason
            when field = 'maturity_date' then null
            when unit_kind is distinct from 'pure' then 'unit_not_pure'
            when value_filed > 1 and scale_rule_id is null then 'scale_not_decided'
          end as why
        , case when value_filed > 1 and scale_rule_id is not null then value_filed else value_filed * 100 end as pct
    from rate_read_kind
)

, rate_input as (
    -- one row per position: the three rate tags, the spread and the maturity date as read
    select
        accession
        , context_id
        , any_value(state) filter (where field = 'interest_rate_tag') as it_state
        , any_value(why) filter (where field = 'interest_rate_tag') as it_why
        , any_value(pct) filter (where field = 'interest_rate_tag') as it_pct
        , any_value(value_filed) filter (where field = 'interest_rate_tag') as it_filed
        , any_value(state) filter (where field = 'interest_rate_cash_tag') as ct_state
        , any_value(why) filter (where field = 'interest_rate_cash_tag') as ct_why
        , any_value(pct) filter (where field = 'interest_rate_cash_tag') as ct_pct
        , any_value(value_filed) filter (where field = 'interest_rate_cash_tag') as ct_filed
        , any_value(state) filter (where field = 'pik_rate') as pk_state
        , any_value(why) filter (where field = 'pik_rate') as pk_why
        , any_value(pct) filter (where field = 'pik_rate') as pk_pct
        , any_value(value_filed) filter (where field = 'pik_rate') as pk_filed
        , any_value(status) filter (where field = 'pik_rate') as pk_read_status
        , any_value(reason) filter (where field = 'pik_rate') as pk_read_reason
        , any_value(state) filter (where field = 'spread') as sp_state
        , any_value(why) filter (where field = 'spread') as sp_why
        , any_value(pct) filter (where field = 'spread') as sp_pct
        , any_value(value_filed) filter (where field = 'spread') as sp_filed
        , any_value(status) filter (where field = 'spread') as sp_read_status
        , any_value(reason) filter (where field = 'spread') as sp_read_reason
        , any_value(state) filter (where field = 'maturity_date') as md_state
        , any_value(why) filter (where field = 'maturity_date') as md_why
        , any_value(value_date) filter (where field = 'maturity_date') as md_date
        , any_value(status) filter (where field = 'maturity_date') as md_read_status
        , any_value(reason) filter (where field = 'maturity_date') as md_read_reason
        , any_value(scale_rule_id) filter (where field = 'interest_rate_tag') as it_scale_rule_id
        , any_value(scale_rule_id) filter (where field = 'interest_rate_cash_tag') as ct_scale_rule_id
        , any_value(scale_rule_id) filter (where field = 'pik_rate') as pk_scale_rule_id
        , any_value(scale_rule_id) filter (where field = 'spread') as sp_scale_rule_id
    from rate_read
    group by 1, 2
)

, rate_rule as (
    -- the chosen rule of each rate rule field, with whether its action is built for the field
    select
        ru.accession
        , ru.context_id
        , ru.field
        , ru.cik
        , ru.report_date
        , ru.rule_id
        , ru.action
        , ru.resolution
        , {{ action_is_built('a.built_in_slice', 'a.built_early_for_field', 'ru.field') }} as is_built
    from rule ru
    left join action a on a.action = ru.action
    where ru.field in {{ rate_rule_fields() }}
)

, rate_rule_wide as (
    -- the four rule rows of each position side by side (int_field_rule gives every position all four)
    select
        accession
        , context_id
        , any_value(cik) filter (where field = 'interest_rate') as cik
        , any_value(report_date) filter (where field = 'interest_rate') as report_date
        , any_value(rule_id) filter (where field = 'interest_rate') as ir_rule_id
        , any_value(action) filter (where field = 'interest_rate') as ir_action
        , any_value(resolution) filter (where field = 'interest_rate') as ir_resolution
        , any_value(is_built) filter (where field = 'interest_rate') as ir_is_built
        , any_value(rule_id) filter (where field = 'pik_rate') as pk_rule_id
        , any_value(action) filter (where field = 'pik_rate') as pk_action
        , any_value(resolution) filter (where field = 'pik_rate') as pk_resolution
        , any_value(is_built) filter (where field = 'pik_rate') as pk_is_built
        , any_value(rule_id) filter (where field = 'spread') as sp_rule_id
        , any_value(action) filter (where field = 'spread') as sp_action
        , any_value(resolution) filter (where field = 'spread') as sp_resolution
        , any_value(is_built) filter (where field = 'spread') as sp_is_built
        , any_value(rule_id) filter (where field = 'maturity_date') as md_rule_id
        , any_value(action) filter (where field = 'maturity_date') as md_action
        , any_value(resolution) filter (where field = 'maturity_date') as md_resolution
        , any_value(is_built) filter (where field = 'maturity_date') as md_is_built
    from rate_rule
    group by 1, 2
)

, reading_input as (
    -- one row per position: the rules, the read inputs and whether the rate tag's printed cell prints a PIK
    select
        r.*
        , i.* exclude (accession, context_id)
        -- controller ruling R1 (2026-11-23): the rate tag's own printed cell prints a PIK (int_rate_tag_cell)
        , coalesce(tc.prints_pik, false) as rate_cell_prints_pik
    from rate_rule_wide r
    join rate_input i on i.accession = r.accession and i.context_id = r.context_id
    left join {{ ref('int_rate_tag_cell') }} tc on tc.accession = r.accession and tc.context_id = r.context_id
)

select * from ({{ rate_reading('reading_input') }})
