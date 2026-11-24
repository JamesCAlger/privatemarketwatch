-- Decides, for each correction target (int_correction_target), every outcome that needs no normalised value: whether
-- the correction is an evidence note, a procedure, a field this layer does not hold, a refused key, a value that is not
-- of its field's type, a conflict, or a printed fair value that is not a dash or a zero (slice 5 Task 3). One row per
-- target, same grain. screen_outcome and screen_reason are null on a target that goes on to the value stage
-- (int_correction_application), which needs the position set after corrections (int_row_corrected) and the values.
-- Split from int_correction_application because int_row_corrected decides which contexts corrections make positions
-- from the targets that pass this screen, and the application needs that set.
--
-- What each correction sets (field_row, value_column): the field row of int_field_corrected and the column on it.
--   step filed / converted     field_row = layer_field, value_column 'value'
--   interest_rate_kind         field_row interest_rate, value_column 'rate_kind' (a column of that row)
--   step companion             field_row = companion_of (the main field), value_column = layer_field ('currency' or
--                              'fx_rate'); a companion with no column here (principal_fx_status) has none
-- is_withdrawal: kind value or add_row with an empty value (the store withdraws the field).
--
-- Screen, the first that fires:
--   no_op     evidence_only            kind evidence (sets nothing)
--   no_op     procedure_not_built      kind exception (a whole-coupon exemption; its procedure is not built,
--                                      slice 5 decision 5)
--   rejected  target_not_found         no target (key not_found, or a context the filed layer lacks)
--   rejected  bridge_ambiguous         a production_bridge key whose production rows name several contexts (owner
--                                      answer 2026-11-24: the bridge must not pick one)
--   rejected  expected_value_differs   a relabel whose expected label is not the context's identifier label
--   deferred  field_not_held           step deferred (names, classes, industry, relabels, the agent position metadata)
--   deferred  no_companion_column      a companion this layer has no column for
--   deferred  rate_reading_not_rerun   a rate field (interest_rate, its cash leg, rate_kind, pik_rate, spread,
--                                      maturity_date): applied by Task 4, which re-runs the rate reading on corrected
--                                      inputs. Until then no rate value changes
--   failed    value_not_numeric        an amount or FX rate whose value is not a number
--   failed    unit_not_known           a currency (value_unit, or a currency companion's value) that is not USD and not
--                                      a currency of stg_fx_rate
--   rejected  printed_cell_not_found   a fair value at step filed on a context with no fair-value fact whose printed
--                                      fair-value cell cannot be found (int_correction_fair_value_cell)
--   rejected  printed_cell_not_dash_or_zero  the same, where the printed cell is not a dash or a zero (owner answer of
--                                      2026-11-24 on decision 4)
--   rejected  conflict                 two corrections that pass the above set the same column of the same field row
--                                      of one target to different values (a withdrawal differs from any value);
--                                      neither applies (decision 7)
with target as (
    select
        t.*
        , c.value
        , c.value_unit
        , c.expected_value
        , nullif(m.companion_of, '') as companion_of
    from {{ ref('int_correction_target') }} t
    join {{ ref('stg_correction') }} c on c.correction_id = t.correction_id
    left join {{ ref('correction_field') }} m
        on m.correction_field = t.field and regexp_full_match(t.store, m.store_pattern)
)

, known_currency as (
    select 'USD' as currency
    union
    select distinct currency from {{ ref('stg_fx_rate') }}
)

, described as (
    select
        t.*
        , case
            when t.step = 'companion' then t.companion_of
            when t.layer_field = 'rate_kind' then 'interest_rate'
            else t.layer_field
          end as field_row
        , case
            when t.step = 'companion' then t.layer_field
            when t.layer_field = 'rate_kind' then 'rate_kind'
            when t.step in ('filed', 'converted', 'reading_input') then 'value'
          end as value_column
        , t.kind in ('value', 'add_row') and coalesce(trim(t.value), '') = '' as is_withdrawal
        , try_cast(trim(t.value) as double) as value_number
        , upper(trim(t.value)) as value_text
        , cf.identifier_label
        , cf.fair_value_fact_count
    from target t
    left join {{ ref('int_context_feature') }} cf on cf.accession = t.accession and cf.context_id = t.context_id
)

, first_screen as (
    select
        d.*
        , case
            when d.kind = 'evidence' then 'no_op|evidence_only'
            when d.kind = 'exception' then 'no_op|procedure_not_built'
            when d.key_resolution = 'production_bridge' and d.context_id is null then 'rejected|bridge_ambiguous'
            when d.context_id is null or d.target_role is null then 'rejected|target_not_found'
            when d.kind = 'relabel' and d.expected_value is distinct from d.identifier_label
                then 'rejected|expected_value_differs'
            when d.step = 'deferred' then 'deferred|field_not_held'
            when d.step = 'companion' and d.value_column is null then 'deferred|no_companion_column'
            when d.field_row in {{ rate_output_fields() }} then 'deferred|rate_reading_not_rerun'
            when d.value_column in ('value', 'fx_rate') and not d.is_withdrawal and d.value_number is null
                then 'failed|value_not_numeric'
            when d.value_column = 'currency' and not d.is_withdrawal
                 and d.value_text not in (select currency from known_currency) then 'failed|unit_not_known'
            when d.value_unit is not null and upper(trim(d.value_unit)) not in (select currency from known_currency)
                then 'failed|unit_not_known'
            when d.step = 'filed' and d.field_row = 'fair_value' and d.fair_value_fact_count = 0
                 and (fc.printed_cell is null) then 'rejected|printed_cell_not_found'
            when d.step = 'filed' and d.field_row = 'fair_value' and d.fair_value_fact_count = 0
                 and not fc.prints_dash_or_zero then 'rejected|printed_cell_not_dash_or_zero'
          end as first_key
        , fc.printed_cell
    from described d
    left join {{ ref('int_correction_fair_value_cell') }} fc
        on fc.accession = d.accession and fc.context_id = d.context_id
)

, surviving as (
    -- the value each surviving correction sets, as one comparable text (a number as a double, a currency upper case)
    select
        *
        , case
            when is_withdrawal then '<withdrawn>'
            when value_column = 'currency' then value_text
            else cast(value_number as varchar)
          end as value_key
    from first_screen
    where first_key is null
)

, conflict as (
    select accession, context_id, field_row, value_column
    from surviving
    group by 1, 2, 3, 4
    having count(distinct value_key) > 1
)

, conflicted as (
    select
        f.*
        , case when f.first_key is null and x.accession is not null then 'rejected|conflict' end as conflict_key
    from first_screen f
    left join conflict x
        on x.accession = f.accession and x.context_id = f.context_id and x.field_row = f.field_row
        and x.value_column = f.value_column
)

select
    correction_id
    , store
    , kind
    , cik
    , accession
    , context_id
    , field
    , layer_field
    , step
    , key_resolution
    , target_count
    , target_role
    , report_date
    , field_row
    , value_column
    , value
    , value_unit
    , is_withdrawal
    , value_number
    , value_text
    , printed_cell
    , split_part(coalesce(first_key, conflict_key), '|', 1) as screen_outcome
    , split_part(coalesce(first_key, conflict_key), '|', 2) as screen_reason
from conflicted
