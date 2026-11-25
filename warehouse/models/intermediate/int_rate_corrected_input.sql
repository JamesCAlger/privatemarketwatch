-- Decides the inputs of the rate reading on each position a rate correction acts on, before and after the corrections
-- (slice 5 Task 4; spec intermediate_spine.md 6.5). One row per (run, accession, context_id), run 'before' or
-- 'corrected', in the input contract of macro rate_reading plus the correction columns below. A model of its own (not a
-- CTE of int_field_corrected) because two models read it: int_rate_corrected runs the reading on it, and
-- int_correction_application decides each correction's outcome from what the reading gives.
--
-- Production applies rate corrections before its financial step derives the legs and the kind
-- (pipeline/unified_holdings.py: _apply_row_corrections, line 1532, and the agent stores, lines 1545-1556, run before
-- financial_finalization.prepare_artifact, line 1643; pipeline/financial_finalization.py line 13 prepare_artifact calls
-- pipeline/financial_conventions.py prepare, line 63, whose tables conventions (rate_kind) and calculated (all_in,
-- cash) read the corrected interest_rate, pik_rate and interest_rate_kind). So a corrected rate here is an input:
--   positions   every position after corrections (int_row_corrected) that is the target of a correction at step
--               reading_input (seeds/correction_field.csv: interest_rate, pik_rate, interest_rate_kind,
--               interest_rate_cash) that passes int_correction_screen. Two corrections of one input with the same value
--               (a different value is a conflict, refused by the screen): the one production reads last
--               (row_corrections_by_context, then the lowest correction_id)
--   reads       the position's filed reads (macro field_read), with int_rate_adjacent applied as in int_rate_normalised
--               (a taker reads its giver's rate facts)
--   run before     the reading's inputs from those reads, with the same macros as int_rate_normalised (field_rule,
--               rate_scale, rate_tag_cell, rate_reading_input). int_rate_corrected's run before must equal
--               int_field_normalised (tests/int_rate_corrected_before_equals_normalised.sql)
--   run corrected  the same after each correction replaces the read of its input: interest_rate the interest-rate tag,
--               interest_rate_cash the cash-pay tag, pik_rate the PIK rate (no row of the five funds reads a cash-pay
--               tag, so the two tags never compete). The replaced read: status read, reason set_by_correction, the
--               number over 100 in unit pure, no fact, read_rule_id the correction_id; a withdrawal: status absent,
--               reason correction_withdrawn. The rules are chosen again on these reads (field_rule), so a correction
--               that supplies a rate on a PIK-only row makes it a row with a rate tag, and one that supplies a PIK rate
--               may make a row PIK-only. The scale decisions are taken again (a corrected number is a percent over 100,
--               never above 1). The rate-cell test (controller ruling R1) reads the filed print, which no correction
--               changes. Then each corrected input's percent is set to the corrected number exactly (dividing by 100
--               and multiplying back would add float noise).
--   explicit kind  production reads an explicit interest_rate_kind before any tag or fund rule
--               (financial_conventions.py prepare, conventions table: "CASE WHEN NULLIF(NULLIF(interest_rate_kind,''),
--               'unresolved') IS NOT NULL THEN interest_rate_kind"; unified_holdings.py lines 2236-2240). A corrected
--               kind that differs from the kind before decides the reading of interest_rate on its row: the rule
--               becomes the correction (ir_rule_id = the correction_id, resolution rule), with the action of the kind
--               it states: all_in on a row with a rate tag (or cash-pay tag) rate_is_all_in; all_in on a row with no
--               rate tag and a PIK rate pik_only_is_coupon (production: kind all_in and no rate gives all-in = the PIK
--               rate, cash empty); cash on a row with a rate tag rate_is_cash_leg. Anything else (cash with no rate
--               tag, all_in with neither a rate nor a PIK rate) cannot be read: kind_not_decidable, the override is not
--               made. A corrected kind equal to the kind before changes nothing (no_op) and is not used.
-- Correction columns (null on run before): it_, ct_, pk_correction_id, _number, _withdrawal (the correction of the
-- rate tag, cash-pay tag and PIK rate); kind_correction_id, kind_value, kind_before (the kind of int_field_normalised
-- before corrections, read by the run before), kind_action (the override made, or null), kind_not_decidable.
with screened as (
    select
        sc.correction_id
        , sc.accession
        , sc.context_id
        , case
            when sc.value_column = 'rate_kind' then 'kind'
            when sc.field_row = 'interest_rate' then 'it'
            when sc.field_row = 'interest_rate_cash' then 'ct'
            when sc.field_row = 'pik_rate' then 'pk'
          end as input
        , sc.is_withdrawal
        , sc.value_number
        , lower(trim(sc.value)) as kind_value
        , row_number() over (
            partition by sc.accession, sc.context_id, sc.field_row, sc.value_column
            order by case sc.store when 'row_corrections_by_context' then 0 else 1 end, sc.correction_id
          ) as pick
    from {{ ref('int_correction_screen') }} sc
    where sc.screen_outcome is null and sc.step = 'reading_input'
)

, input_correction as (
    select * from screened where pick = 1
)

, position as (
    select r.accession, r.context_id, r.cik, r.report_date
    from {{ ref('int_row_corrected') }} r
    semi join input_correction c on c.accession = r.accession and c.context_id = r.context_id
)

, adjacent as (
    select a.*
    from {{ ref('int_rate_adjacent') }} a
    semi join position p on p.accession = a.accession and p.context_id = a.taker_context_id
    where a.taker_is_position
)

, adj_giver as (
    select accession, giver_context_id as context_id, cik, report_date from adjacent
)

, adj_moved_field as (
    select a.accession, a.taker_context_id as context_id, f.field
    from adjacent a
    cross join (select unnest(['interest_rate_tag', 'interest_rate_cash_tag', 'pik_rate', 'spread']) as field) f
)

, own_read as (
    {{ field_read('position') }}
)

, giver_read as (
    {{ field_read('adj_giver') }}
)

, p_read as (
    select r.*
    from own_read r
    anti join adj_moved_field m on m.accession = r.accession and m.context_id = r.context_id and m.field = r.field
    union all by name
    select g.* replace (a.taker_context_id as context_id, a.cik as cik, a.report_date as report_date)
    from giver_read g
    join adjacent a on a.accession = g.accession and a.giver_context_id = g.context_id
    where g.field in ('interest_rate_tag', 'interest_rate_cash_tag', 'pik_rate', 'spread')
)

, read_correction as (
    select
        accession
        , context_id
        , case input when 'it' then 'interest_rate_tag' when 'ct' then 'interest_rate_cash_tag' else 'pik_rate' end
            as field
        , correction_id
        , is_withdrawal
        , value_number
    from input_correction
    where input in ('it', 'ct', 'pk')
)

, corrected_read as (
    select
        r.* replace (
            case when c.field is null then r.status when c.is_withdrawal then 'absent' else 'read' end as status
            , case when c.field is null then r.reason when c.is_withdrawal then 'correction_withdrawn'
                   else 'set_by_correction' end as reason
            , case when c.field is null then r.value_filed
                   when not c.is_withdrawal then cast(c.value_number / 100 as decimal(38, 10)) end
                as value_filed
            , case when c.field is null then r.value_date end as value_date
            , case when c.field is null then r.unit when not c.is_withdrawal then 'pure' end as unit
            , case when c.field is null then r.decimals end as decimals
            , case when c.field is null then r.fact_id end as fact_id
            , case when c.field is null then r.fact_count else 0 end as fact_count
            , case when c.field is null then r.printed_text end as printed_text
            , case when c.field is null then r.is_nil else false end as is_nil
            , coalesce(c.correction_id, r.read_rule_id) as read_rule_id
        )
    from p_read r
    left join read_correction c on c.accession = r.accession and c.context_id = r.context_id and c.field = r.field
)

, before_rule as (
    {{ field_rule('p_read') }}
)

, corrected_rule as (
    {{ field_rule('corrected_read') }}
)

, before_scale as (
    {{ rate_scale('p_read') }}
)

, corrected_scale as (
    {{ rate_scale('corrected_read') }}
)

, p_cell as (
    {{ rate_tag_cell('p_read') }}
)

, before_input as (
    {{ rate_reading_input('before_rule', 'p_read', 'before_scale', 'p_cell') }}
)

, corrected_input as (
    {{ rate_reading_input('corrected_rule', 'corrected_read', 'corrected_scale', 'p_cell') }}
)

, before_kind as (
    -- the kind before corrections, as the reading gives it on the run before
    select accession, context_id, rate_kind
    from ({{ rate_reading('before_input') }})
    where field = 'interest_rate'
)

, overlaid as (
    select
        ci.*
        , it.correction_id as it_correction_id
        , cast(it.value_number as decimal(38, 10)) as it_number
        , it.is_withdrawal as it_withdrawal
        , ct.correction_id as ct_correction_id
        , cast(ct.value_number as decimal(38, 10)) as ct_number
        , ct.is_withdrawal as ct_withdrawal
        , pk.correction_id as pk_correction_id
        , cast(pk.value_number as decimal(38, 10)) as pk_number
        , pk.is_withdrawal as pk_withdrawal
        , k.correction_id as kind_correction_id
        , k.kind_value
        , bk.rate_kind as kind_before
        , case
            when k.correction_id is null or k.kind_value = bk.rate_kind then null
            when k.kind_value = 'all_in' and (coalesce(ci.it_state, 'absent') <> 'absent'
                                              or coalesce(ci.ct_state, 'absent') <> 'absent') then 'rate_is_all_in'
            when k.kind_value = 'all_in' and ci.pk_state = 'value' then 'pik_only_is_coupon'
            when k.kind_value = 'cash' and (coalesce(ci.it_state, 'absent') <> 'absent'
                                            or coalesce(ci.ct_state, 'absent') <> 'absent') then 'rate_is_cash_leg'
          end as kind_action
    from corrected_input ci
    left join (select * from input_correction where input = 'it') it
        on it.accession = ci.accession and it.context_id = ci.context_id
    left join (select * from input_correction where input = 'ct') ct
        on ct.accession = ci.accession and ct.context_id = ci.context_id
    left join (select * from input_correction where input = 'pk') pk
        on pk.accession = ci.accession and pk.context_id = ci.context_id
    left join (select * from input_correction where input = 'kind') k
        on k.accession = ci.accession and k.context_id = ci.context_id
    left join before_kind bk on bk.accession = ci.accession and bk.context_id = ci.context_id
)

select
    'before' as run
    , b.*
    , cast(null as varchar) as it_correction_id
    , cast(null as decimal(38, 10)) as it_number
    , cast(null as boolean) as it_withdrawal
    , cast(null as varchar) as ct_correction_id
    , cast(null as decimal(38, 10)) as ct_number
    , cast(null as boolean) as ct_withdrawal
    , cast(null as varchar) as pk_correction_id
    , cast(null as decimal(38, 10)) as pk_number
    , cast(null as boolean) as pk_withdrawal
    , cast(null as varchar) as kind_correction_id
    , cast(null as varchar) as kind_value
    , cast(null as varchar) as kind_before
    , cast(null as varchar) as kind_action
    , cast(null as boolean) as kind_not_decidable
from before_input b
union all by name
select
    'corrected' as run
    , o.* replace (
        case when o.kind_action is not null then o.kind_correction_id else o.ir_rule_id end as ir_rule_id
        , coalesce(o.kind_action, o.ir_action) as ir_action
        , case when o.kind_action is not null then 'rule' else o.ir_resolution end as ir_resolution
        , case when o.kind_action is not null then true else o.ir_is_built end as ir_is_built
        , case when o.it_correction_id is not null and not o.it_withdrawal then o.it_number else o.it_pct end as it_pct
        , case when o.ct_correction_id is not null and not o.ct_withdrawal then o.ct_number else o.ct_pct end as ct_pct
        , case when o.pk_correction_id is not null and not o.pk_withdrawal then o.pk_number else o.pk_pct end as pk_pct
    )
    , o.kind_correction_id is not null and o.kind_value is distinct from o.kind_before and o.kind_action is null
        as kind_not_decidable
from overlaid o
