-- Decides the rate fields of each position a rate correction acts on, by running the rate reading (macro rate_reading)
-- on the inputs of int_rate_corrected_input, before and after the corrections (slice 5 Task 4). One row per (run,
-- accession, context_id, field), run 'before' or 'corrected', in int_rate_normalised's columns, plus on every row of
-- run corrected the position's correction state:
--   it_changed, ct_changed, pk_changed  a correction of the rate tag, cash-pay tag or PIK rate changes that input: a
--                           value that is not the input's usable number before (beyond var cmp_rate_tolerance), or a
--                           withdrawal of an input that was not absent. A correction that changes nothing is no_op in
--                           int_correction_application
--   kind_changed            a corrected kind that differs from the kind before
--   row_failure             why the corrections of the row are not stored, when at least one input changed (else null):
--     legs_do_not_add       the legs check (spec section 7) fails on the corrected reading: the reading's own check of
--                           two filed rate tags (reason legs_do_not_add), or all three legs normalised and cash plus PIK
--                           differs from the all-in rate by more than var rate_legs_tolerance
--     pik_above_rate        the corrected PIK rate is above the all-in rate tag plus var pik_above_rate_margin under
--                           rate_is_all_in (the reading leaves both legs unresolved, as production does)
--     kind_not_decidable    a corrected kind that differs from the kind before but has no rate to read
--                           (int_rate_corrected_input)
--     rate_reading_unresolved  a changed input whose own field ends without a value although the correction set one
--                           (interest_rate for the rate tag and the kind, interest_rate_cash for the cash-pay tag,
--                           pik_rate for the PIK rate): the corrected value cannot be read under the row's rules
--   On a row with a failure every correction of an input is failed with that reason, and int_field_corrected keeps the
--   rate fields as before (never stored).
-- Run before must equal int_field_normalised on a filed position and int_field_reread run raw on a promoted one
-- (tests/int_rate_corrected_before_equals_normalised.sql): the second run is the same chain.
-- Agreement with production is not correctness: the reading re-runs production's corrections, it does not check them.
with input as (
    select * from {{ ref('int_rate_corrected_input') }}
)

, before_input as (
    select * exclude (run, it_correction_id, it_number, it_withdrawal, ct_correction_id, ct_number, ct_withdrawal,
                      pk_correction_id, pk_number, pk_withdrawal, kind_correction_id, kind_value, kind_before,
                      kind_action, kind_not_decidable)
    from input
    where run = 'before'
)

, corrected_input as (
    select * exclude (run, it_correction_id, it_number, it_withdrawal, ct_correction_id, ct_number, ct_withdrawal,
                      pk_correction_id, pk_number, pk_withdrawal, kind_correction_id, kind_value, kind_before,
                      kind_action, kind_not_decidable)
    from input
    where run = 'corrected'
)

, before_out as (
    select * from ({{ rate_reading('before_input') }})
)

, corrected_out as (
    select * from ({{ rate_reading('corrected_input') }})
)

, change as (
    -- what each correction changes, against the inputs before
    select
        c.accession
        , c.context_id
        , c.it_correction_id is not null and case
            when c.it_withdrawal then coalesce(b.it_state, 'absent') <> 'absent'
            else not coalesce(b.it_state = 'value' and abs(b.it_pct - c.it_number) <= {{ var('cmp_rate_tolerance') }}, false)
          end as it_changed
        , c.ct_correction_id is not null and case
            when c.ct_withdrawal then coalesce(b.ct_state, 'absent') <> 'absent'
            else not coalesce(b.ct_state = 'value' and abs(b.ct_pct - c.ct_number) <= {{ var('cmp_rate_tolerance') }}, false)
          end as ct_changed
        , c.pk_correction_id is not null and case
            when c.pk_withdrawal then coalesce(b.pk_state, 'absent') <> 'absent'
            else not coalesce(b.pk_state = 'value' and abs(b.pk_pct - c.pk_number) <= {{ var('cmp_rate_tolerance') }}, false)
          end as pk_changed
        , c.kind_correction_id is not null and c.kind_value is distinct from c.kind_before as kind_changed
        , coalesce(c.it_withdrawal, false) as it_withdrawal
        , coalesce(c.ct_withdrawal, false) as ct_withdrawal
        , coalesce(c.pk_withdrawal, false) as pk_withdrawal
        , coalesce(c.kind_not_decidable, false) as kind_not_decidable
    from (select * from input where run = 'corrected') c
    join (select * from input where run = 'before') b on b.accession = c.accession and b.context_id = c.context_id
)

, legs as (
    select
        accession
        , context_id
        , any_value(reason) filter (where field = 'interest_rate') as ir_reason
        , any_value(status) filter (where field = 'interest_rate') as ir_status
        , any_value(status) filter (where field = 'interest_rate_cash') as cash_status
        , any_value(status) filter (where field = 'pik_rate') as pk_status
        , any_value(value) filter (where field = 'interest_rate' and status = 'normalised') as all_in
        , any_value(value) filter (where field = 'interest_rate_cash' and status = 'normalised') as cash
        , any_value(value) filter (where field = 'pik_rate' and status = 'normalised') as pik
    from corrected_out
    group by 1, 2
)

, failure as (
    select
        ch.*
        , case
            when not (ch.it_changed or ch.ct_changed or ch.pk_changed or ch.kind_changed) then null
            when l.ir_reason = 'legs_do_not_add' then 'legs_do_not_add'
            when l.all_in is not null and l.cash is not null and l.pik is not null
                 and abs(l.cash + l.pik - l.all_in) > {{ var('rate_legs_tolerance') }} then 'legs_do_not_add'
            when l.ir_reason = 'pik_above_rate' then 'pik_above_rate'
            when ch.kind_not_decidable then 'kind_not_decidable'
            when (ch.it_changed and not ch.it_withdrawal and l.ir_status <> 'normalised')
                 or (ch.kind_changed and l.ir_status <> 'normalised')
                 or (ch.ct_changed and not ch.ct_withdrawal and l.cash_status <> 'normalised')
                 or (ch.pk_changed and not ch.pk_withdrawal and l.pk_status <> 'normalised')
                then 'rate_reading_unresolved'
          end as row_failure
    from change ch
    join legs l on l.accession = ch.accession and l.context_id = ch.context_id
)

select
    'before' as run
    , b.*
    , cast(null as boolean) as it_changed
    , cast(null as boolean) as ct_changed
    , cast(null as boolean) as pk_changed
    , cast(null as boolean) as kind_changed
    , cast(null as varchar) as row_failure
from before_out b
union all by name
select
    'corrected' as run
    , c.*
    , f.it_changed
    , f.ct_changed
    , f.pk_changed
    , f.kind_changed
    , f.row_failure
from corrected_out c
join failure f on f.accession = c.accession and f.context_id = c.context_id
