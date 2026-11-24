-- Decides the outcome of each correction on each of its targets (slice 5 Task 3; spec intermediate_spine.md 6.5,
-- design.md correction_application). One row per (correction_id, accession, context_id), the grain of
-- int_correction_target; every loaded correction has at least one row (tests/int_correction_none_dropped.sql).
--
-- outcome / reason:
--   the screen's outcome and reason (int_correction_screen: evidence, procedure, key refused, deferred field, value not
--   of its type, printed fair value not a dash or a zero, conflict), else, in this order:
--   rejected  target_not_position     the target is not a position after corrections (int_row_corrected): the context
--                                     exists but no correction supplied what its role lacked
--   failed    no_fx_rate              a principal at step filed in a foreign currency whose dollar value cannot be
--                                     converted (no quote within var fx_max_age_days)
--   failed    conversion_unresolved   a value at step filed that the conversion rules leave unresolved
--   no_op     already_absent          a withdrawal on a field (or a companion column) that holds no value: status absent
--   no_op     equal_to_normalised     the corrected value equals the normalised value: amounts within
--                                     var cmp_amount_tolerance (fair value, cost, principal and dollar principal differ
--                                     by less than the dollar tolerance; shares, share of net assets and an FX rate by no
--                                     more than the measured one); a currency equal as text
--   applied   (reason empty)          otherwise
-- value_before: the normalised value of the column the correction sets, as text (for a currency of cost or fair value,
-- which int_field_normalised leaves empty, the currency of the unit the field was read in, when it was normalised; for
-- a context corrections make positions, the value int_field_reread gives before corrections). value_after: the value
-- after the correction, as text: step filed, the value the conversion rules give on the corrected read
-- (int_field_reread run filed_corrected); step converted, the number as corrected; a companion, its value. Empty
-- (null) for a withdrawal. Both are null on a target that stops at the screen or at target_not_position.
-- applied_at_step: the step of an applied correction (filed, converted, companion), else null.
-- Agreement with production is not correctness: applying production's corrections makes the two pipelines agree, it
-- does not check a correction against the filing.
with screen as (
    select * from {{ ref('int_correction_screen') }}
)

, promoted as (
    select accession, context_id from {{ ref('int_row_corrected') }} where row_reason <> 'filed'
)

, base as (
    -- the value before corrections of every field row of every position after corrections
    select n.accession, n.context_id, n.field, n.value, n.currency, n.fx_rate, n.status, rd.unit as read_unit
    from {{ ref('int_field_normalised') }} n
    left join {{ ref('int_field_read') }} rd
        on rd.accession = n.accession and rd.context_id = n.context_id and rd.field = n.field
    union all
    select rr.accession, rr.context_id, rr.field, rr.value, rr.currency, rr.fx_rate, rr.status, rr.read_unit
    from (select * from {{ ref('int_field_reread') }} where run = 'raw') rr
    semi join promoted p on p.accession = rr.accession and p.context_id = rr.context_id
)

, filed_after as (
    select accession, context_id, field, value, status, reason
    from {{ ref('int_field_reread') }}
    where run = 'filed_corrected'
)

, filed_usd as (
    select accession, context_id, status, reason from filed_after where field = 'principal_amount_usd'
)

, staged as (
    select
        s.*
        , r.accession is not null as is_position_after
        , b.status as base_status
        , case s.value_column
            when 'value' then b.value
            when 'fx_rate' then b.fx_rate
          end as number_before
        , case
            when s.value_column <> 'currency' then null
            when b.currency is not null then b.currency
            when b.status = 'normalised' then regexp_extract(b.read_unit, '^iso4217:([A-Z]{3})$', 1)
          end as currency_before
        , case when s.step = 'filed' then fa.value end as filed_value
        , case when s.step = 'filed' then fa.status end as filed_status
        , case when s.step = 'filed' then fa.reason end as filed_reason
        , case when s.step = 'filed' and s.field_row = 'principal_amount' then fu.reason end as filed_usd_reason
        , case
            when s.field_row in ('shares', 'pct_of_net_assets') or s.value_column = 'fx_rate'
                then {{ var('cmp_amount_tolerance')['measured'] }}
            else {{ var('cmp_amount_tolerance')['dollar'] }}
          end as tolerance
        , s.field_row in ('fair_value', 'cost', 'principal_amount', 'principal_amount_usd') and s.value_column = 'value'
            as is_dollar_tolerance
    from screen s
    left join {{ ref('int_row_corrected') }} r on r.accession = s.accession and r.context_id = s.context_id
    left join base b on b.accession = s.accession and b.context_id = s.context_id and b.field = s.field_row
    -- (the filters on the screen row sit in the select below, not in these joins' ON clauses: a filter there makes
    -- DuckDB plan a nested-loop join)
    left join filed_after fa on fa.accession = s.accession and fa.context_id = s.context_id and fa.field = s.field_row
    left join filed_usd fu on fu.accession = s.accession and fu.context_id = s.context_id
)

, valued as (
    select
        *
        , case
            when screen_outcome is not null or not is_position_after then null
            when is_withdrawal then null
            when step = 'filed' then filed_value
            when value_column in ('value', 'fx_rate') then value_number
          end as number_after
        , case
            when screen_outcome is not null or not is_position_after or is_withdrawal then null
            when value_column = 'currency' then value_text
          end as currency_after
    from staged
)

, decided as (
    select
        *
        , case
            when screen_outcome is not null then screen_outcome || '|' || screen_reason
            when not is_position_after then 'rejected|target_not_position'
            when step = 'filed' and filed_usd_reason = 'no_fx_rate' then 'failed|no_fx_rate'
            when step = 'filed' and filed_status is distinct from 'normalised' then 'failed|conversion_unresolved'
            when is_withdrawal and value_column = 'value' and number_before is null and base_status = 'absent'
                then 'no_op|already_absent'
            when is_withdrawal and value_column = 'fx_rate' and number_before is null then 'no_op|already_absent'
            when is_withdrawal and value_column = 'currency' and currency_before is null then 'no_op|already_absent'
            when is_withdrawal then 'applied|'
            when value_column = 'currency' and currency_after = currency_before then 'no_op|equal_to_normalised'
            when value_column in ('value', 'fx_rate') and number_before is not null and base_status = 'normalised'
                 and (case when is_dollar_tolerance then abs(number_after - number_before) < tolerance
                           else abs(number_after - number_before) <= tolerance end)
                then 'no_op|equal_to_normalised'
            else 'applied|'
          end as outcome_key
    from valued
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
    , split_part(outcome_key, '|', 1) as outcome
    , nullif(split_part(outcome_key, '|', 2), '') as reason
    , case
        when value_column = 'currency' then currency_before
        else cast(number_before as varchar)
      end as value_before
    , case
        when value_column = 'currency' then currency_after
        else cast(number_after as varchar)
      end as value_after
    , case when split_part(outcome_key, '|', 1) = 'applied' then step end as applied_at_step
    , is_withdrawal
    , number_after
    , currency_after
from decided
