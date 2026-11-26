{#- The rate reading (slice 5 Task 1): from the rate inputs of each position, in percent, and the rules int_field_rule
    chose, the rows of interest_rate (the all-in rate, rate_kind beside it), interest_rate_cash (the cash leg), pik_rate,
    spread and maturity_date, in int_field_normalised's columns. Moved unchanged out of int_field_normalised (its CTEs
    interest to scaled and the last three branches of its union) so that it can run on normalised inputs
    (int_rate_normalised) and, later, on corrected ones. Returns a query (a WITH clause and a select): call it as a
    subquery, select * from ({{ rate_reading('inputs') }}).

    inputs: a relation (a CTE name or a ref) with one row per position and these columns:
      accession, context_id, cik, report_date
      the chosen rule of each rate rule field, prefixed ir_ (interest_rate), pk_ (pik_rate), sp_ (spread), md_
      (maturity_date): <p>_rule_id, <p>_action, <p>_resolution, <p>_is_built (macro action_is_built); a null
      <p>_resolution means the position has no rule row for that field, and gives no row for it
      each read input, prefixed it_ (rate tag), ct_ (cash-pay tag), pk_ (PIK rate), sp_ (spread), md_ (maturity date):
        <p>_state    value (usable), absent (no fact or nil only), unresolved
        <p>_why      the reason of a state that is not value
        <p>_pct      the number in percent (it_, ct_, pk_, sp_)
        <p>_filed    the number as filed (it_, ct_, pk_, sp_)
        <p>_read_status, <p>_read_reason  int_field_read's status and reason (pk_, sp_, md_)
        md_date      the maturity date read
        <p>_scale_rule_id  the fund scale rule that kept a filed number above 1 as a percent, or null (it_, ct_, pk_, sp_)
      rate_cell_prints_pik  the rate tag's own printed cell prints a PIK (int_rate_tag_cell.prints_pik; false when not)

    What the reading does (the slice 4 Task 3 report says where each action's meaning was read):
    the interest_rate reading gives the all-in rate (ir_), the cash leg (cash_) and the kind, from the rule of
    interest_rate. Legs as production (pipeline/financial_conventions.py prepare, tables conventions and calculated):
      rate_is_all_in    all-in = interest-rate tag; cash = all-in less PIK where a PIK rate is read, else cash = all-in
                        (reason cash_equals_all_in; owner ruling A, 2026-11-23: PIK absent counts as zero. Production
                        leaves this cash leg empty. Residual risk: a PIK that exists but is not tagged gives an
                        overstated cash leg; controller ruling R1: not where the rate's printed cell prints a PIK, reason
                        pik_printed_not_tagged, unresolved); a PIK rate above the tag plus var pik_above_rate_margin
                        (0.01, production's margin) leaves both unresolved (pik_above_rate)
      rate_is_cash_leg  cash = interest-rate tag; all-in = cash plus PIK where a PIK rate is read, else empty
                        (cash_leg_without_pik)
      a cash-pay tag    is the cash leg under either reading (production: the concept names its own kind)
      both tags         production keeps the first fact in the instance (pipeline/bdc_filings.py, "keep first
                        non-None"); here both are kept where they agree with the PIK rate (all-in = cash + PIK, or under
                        rate_is_cash_leg the two cash legs equal) within var rate_legs_tolerance, else both unresolved
                        (legs_do_not_add). No row of the five funds files both
      pik_only_is_coupon  all-in = the PIK rate; cash left empty (pik_only_coupon): production's code on this branch sets
                        the cash leg only from a filed rate
      pik_only_is_margin  the rate is not known: both unresolved (pik_is_margin)
      Both PIK-only arithmetics cannot be reached in a build while action_field.unread_input is set on them (controller
      ruling of 2026-11-23: every such row is text_not_read in int_field_rule and never gets here). They are kept, and
      unit-tested, so that clearing unread_input (which needs a selector on the loan class and the printed rate type,
      see the seed notes) does not need this code written again.
    An input that is unresolved (two values, a unit that is not a ratio, a scale not decided) leaves both unresolved
    with its reason. kind: all_in, cash or unresolved (production's interest_rate_kind). pik_rate, spread and
    maturity_date are read under their own rule (CTE scaled). Rate statuses add these reasons: scale_not_decided,
    unit_not_pure, legs_do_not_add, pik_above_rate, cash_leg_without_pik, pik_only_coupon (cash leg not set; status
    absent), pik_is_coupon (spread not set under the coupon reading; status absent), pik_is_margin, not_a_date (as
    read), cash_equals_all_in (normalised), pik_printed_not_tagged.
    scale_rule_ids on interest_rate and interest_rate_cash lists the scale rules of every rate input read for the reading
    (rate tag, cash-pay tag, PIK rate), including a PIK rate that on the all-in row only fed the check against the tag
    (pik_above_rate); it does not prove the listed input changed this row's value. -#}
{% macro rate_reading(inputs) -%}
with rate_rule as (
    -- the four rule rows of each position, in the long form the reading below reads
    select
        i.accession
        , i.context_id
        , f.field
        , i.cik
        , i.report_date
        , case f.field when 'interest_rate' then i.ir_rule_id when 'pik_rate' then i.pk_rule_id
                       when 'spread' then i.sp_rule_id else i.md_rule_id end as rule_id
        , case f.field when 'interest_rate' then i.ir_action when 'pik_rate' then i.pk_action
                       when 'spread' then i.sp_action else i.md_action end as action
        , case f.field when 'interest_rate' then i.ir_resolution when 'pik_rate' then i.pk_resolution
                       when 'spread' then i.sp_resolution else i.md_resolution end as resolution
        , case f.field when 'interest_rate' then i.ir_is_built when 'pik_rate' then i.pk_is_built
                       when 'spread' then i.sp_is_built else i.md_is_built end as is_built
        , i.rate_cell_prints_pik
    from {{ inputs }} i
    cross join (select unnest(list_value{{ rate_rule_fields() }}) as field) f
    -- a rule field with no rule row (resolution null; int_field_rule never gives a null resolution) gives no rate row,
    -- as before the split, where the reading joined the rule rows that exist
    where case f.field when 'interest_rate' then i.ir_resolution when 'pik_rate' then i.pk_resolution
                       when 'spread' then i.sp_resolution else i.md_resolution end is not null
)

, rate_input as (
    -- the read inputs of each position
    select
        * exclude (cik, report_date, ir_rule_id, ir_action, ir_resolution, ir_is_built, pk_rule_id, pk_action,
                   pk_resolution, pk_is_built, sp_rule_id, sp_action, sp_resolution, sp_is_built, md_rule_id, md_action,
                   md_resolution, md_is_built, rate_cell_prints_pik)
    from {{ inputs }}
)

, interest as (
    select
        r.accession
        , r.context_id
        , r.cik
        , r.report_date
        , r.rule_id
        , r.action
        , r.resolution
        , r.is_built
        , i.*  exclude (accession, context_id)
        , coalesce(i.it_state, 'absent') <> 'absent' as has_it
        , coalesce(i.ct_state, 'absent') <> 'absent' as has_ct
        -- controller ruling R1 (2026-11-23): the rate tag's own printed cell prints a PIK (int_rate_tag_cell)
        , coalesce(r.rate_cell_prints_pik, false) as rate_cell_prints_pik
        , case
            when i.it_state = 'unresolved' then i.it_why
            when i.ct_state = 'unresolved' then i.ct_why
            when i.pk_state = 'unresolved' then i.pk_why
          end as input_why
    from rate_rule r
    join rate_input i on i.accession = r.accession and i.context_id = r.context_id
    where r.field = 'interest_rate'
)

, interest_legs as (
    select
        *
        -- outcome: one label per case, read by the three columns below
        , case
            when resolution in ('rule_conflict', 'feature_missing', 'text_not_read') then resolution
            when resolution = 'rule' and not is_built then 'action_not_built'
            when resolution = 'rule' and action in ('rate_is_all_in', 'rate_is_cash_leg') then
                case
                    when input_why is not null then 'input_unresolved'
                    when has_it and has_ct and action = 'rate_is_all_in' then
                        case when abs(ct_pct + coalesce(pk_pct, 0) - it_pct) <= {{ var('rate_legs_tolerance') }}
                             then 'all_in_both' else 'legs_do_not_add' end
                    when has_it and has_ct then
                        case when abs(ct_pct - it_pct) <= {{ var('rate_legs_tolerance') }}
                             then 'cash' else 'legs_do_not_add' end
                    when has_ct or action = 'rate_is_cash_leg' then 'cash'
                    when pk_state = 'value' and pk_pct > it_pct + {{ var('pik_above_rate_margin') }} then 'pik_above_rate'
                    else 'all_in'
                end
            when resolution = 'rule' and action = 'pik_only_is_coupon' then
                case when pk_state = 'value' then 'coupon' else 'input_unresolved' end
            when resolution = 'rule' and action = 'pik_only_is_margin' then 'pik_is_margin'
            when resolution = 'rule' then 'action_not_built'
            when has_it or has_ct then 'no_rule'
            else 'absent'
          end as outcome
    from interest
)

, interest_out as (
    select
        *
        , case outcome
            when 'all_in' then it_pct
            when 'all_in_both' then it_pct
            when 'cash' then case when pk_state = 'value' then coalesce(ct_pct, it_pct) + pk_pct end
            when 'coupon' then pk_pct
          end as ir_value
        , case outcome
            -- owner ruling A, 2026-11-23: no PIK rate read (pk_state absent; an unresolved PIK rate never reaches
            -- outcome all_in) means the cash leg is the all-in rate
            when 'all_in' then case when pk_state = 'value' then it_pct - pk_pct else it_pct end
            when 'all_in_both' then ct_pct
            when 'cash' then coalesce(ct_pct, it_pct)
          end as cash_value
        , case
            when outcome in ('all_in', 'all_in_both', 'coupon') then 'all_in'
            when outcome = 'cash' then 'cash'
            else 'unresolved'
          end as rate_kind
        , case
            when outcome in ('all_in', 'all_in_both', 'coupon') then 'normalised'
            when outcome = 'cash' and pk_state = 'value' then 'normalised'
            when outcome = 'absent' then 'absent'
            else 'unresolved'
          end as ir_status
        , case
            when outcome in ('all_in', 'all_in_both', 'coupon') then 'applied'
            when outcome = 'cash' and pk_state = 'value' then 'applied'
            when outcome = 'cash' then 'cash_leg_without_pik'
            when outcome = 'input_unresolved' then coalesce(input_why, pk_why)
            when outcome = 'absent' then coalesce(it_why, 'no_fact')
            when outcome = 'no_rule' then coalesce(case when it_state = 'unresolved' then it_why end,
                                                   case when ct_state = 'unresolved' then ct_why end, 'no_rule')
            else outcome
          end as ir_reason
        , case
            -- controller ruling R1: no PIK rate read, but the rate cell prints a PIK: the page contradicts cash = all-in
            when outcome = 'all_in' and pk_state is distinct from 'value' and rate_cell_prints_pik then 'unresolved'
            when outcome in ('all_in_both', 'cash', 'all_in') then 'normalised'
            when outcome in ('coupon', 'absent') then 'absent'
            else 'unresolved'
          end as cash_status
        , case
            when outcome in ('all_in_both', 'cash') then 'applied'
            when outcome = 'all_in' and pk_state = 'value' then 'applied'
            when outcome = 'all_in' and rate_cell_prints_pik then 'pik_printed_not_tagged'
            when outcome = 'all_in' then 'cash_equals_all_in'
            when outcome = 'coupon' then 'pik_only_coupon'
            when outcome = 'input_unresolved' then coalesce(input_why, pk_why)
            when outcome = 'absent' then coalesce(ct_why, 'no_fact')
            when outcome = 'no_rule' then coalesce(case when ct_state = 'unresolved' then ct_why end,
                                                   case when it_state = 'unresolved' then it_why end, 'no_rule')
            else outcome
          end as cash_reason
    from interest_legs
)

, scaled as (
    -- pik_rate, spread and maturity_date under their own rule
    select
        r.accession
        , r.context_id
        , r.field
        , r.cik
        , r.report_date
        -- owner ruling B: a PIK rate or spread whose filed number above 1 a fund scale rule kept as a percent names that
        -- rule and its action (the default fraction_to_percent did not give the value)
        , case
            when r.resolution = 'rule' and r.action = 'fraction_to_percent' and r.field = 'pik_rate'
                and i.pk_scale_rule_id is not null then i.pk_scale_rule_id
            when r.resolution = 'rule' and r.action = 'fraction_to_percent' and r.field = 'spread'
                and i.sp_scale_rule_id is not null then i.sp_scale_rule_id
            else r.rule_id
          end as rule_id
        , case
            when r.resolution = 'rule' and r.action = 'fraction_to_percent' and r.field = 'pik_rate'
                and i.pk_scale_rule_id is not null then 'ratio_value_is_percent'
            when r.resolution = 'rule' and r.action = 'fraction_to_percent' and r.field = 'spread'
                and i.sp_scale_rule_id is not null then 'ratio_value_is_percent'
            else r.action
          end as action
        , case
            when r.field = 'pik_rate' then i.pk_scale_rule_id
            when r.field = 'spread' and r.action = 'pik_only_is_margin' then i.pk_scale_rule_id
            when r.field = 'spread' then i.sp_scale_rule_id
          end as scale_rule_ids
        , case r.field when 'pik_rate' then i.pk_filed when 'spread' then
            case when r.action = 'pik_only_is_margin' then i.pk_filed else i.sp_filed end end as value_filed
        , case
            when r.resolution in ('rule_conflict', 'feature_missing', 'text_not_read') then 'unresolved'
            when r.resolution = 'rule' and not r.is_built then 'unresolved'
            when r.resolution = 'rule' and r.action = 'pik_only_is_coupon' then 'absent'
            when r.resolution = 'rule' and r.action = 'pik_only_is_margin' then
                case when i.pk_state = 'value' then 'normalised' else 'unresolved' end
            when r.resolution = 'rule' and r.action in ('fraction_to_percent', 'as_filed') then
                case r.field when 'pik_rate' then i.pk_state when 'spread' then i.sp_state else i.md_state end
            when r.resolution = 'rule' then 'unresolved'
            when (case r.field when 'pik_rate' then i.pk_state when 'spread' then i.sp_state else i.md_state end)
                = 'absent' then 'absent'
            else 'unresolved'
          end as state
        , case
            when r.resolution in ('rule_conflict', 'feature_missing', 'text_not_read') then r.resolution
            when r.resolution = 'rule' and not r.is_built then 'action_not_built'
            when r.resolution = 'rule' and r.action = 'pik_only_is_coupon' then 'pik_is_coupon'
            when r.resolution = 'rule' and r.action = 'pik_only_is_margin' then coalesce(i.pk_why, 'applied')
            when r.resolution = 'rule' and r.action in ('fraction_to_percent', 'as_filed') then
                coalesce(case r.field when 'pik_rate' then i.pk_why when 'spread' then i.sp_why else i.md_why end,
                         'applied')
            -- an action with no value for this field (printed_margin_cash_plus_pik never wins: text_not_read); defensive
            when r.resolution = 'rule' then 'action_not_built'
            -- no rule: as read, else no_rule (a number in a unit that is not a ratio). An unresolved maturity date keeps
            -- its read reason (not_a_date, values_differ), as pik_rate and spread do (slice 4 Task 5 repair g)
            when (case r.field when 'pik_rate' then i.pk_state when 'spread' then i.sp_state else i.md_state end)
                = 'absent' then case r.field when 'pik_rate' then i.pk_why when 'spread' then i.sp_why else i.md_why end
            when (case r.field when 'pik_rate' then i.pk_read_status when 'spread' then i.sp_read_status
                               else i.md_read_status end)
                = 'unresolved' then case r.field when 'pik_rate' then i.pk_read_reason when 'spread' then i.sp_read_reason
                                                 else i.md_read_reason end
            else 'no_rule'
          end as reason
        , case
            when r.action = 'pik_only_is_margin' then i.pk_pct
            when r.field = 'pik_rate' then i.pk_pct
            when r.field = 'spread' then i.sp_pct
          end as value
        , case when r.field = 'maturity_date' then i.md_date end as value_date
    from rate_rule r
    join rate_input i on i.accession = r.accession and i.context_id = r.context_id
    where r.field in ('pik_rate', 'spread', 'maturity_date')
)

select
    accession
    , context_id
    , 'interest_rate' as field
    , cik
    , report_date
    , case when ir_status = 'normalised' then ir_value end as value
    , cast(null as varchar) as currency
    , coalesce(it_filed, ct_filed, case when action = 'pik_only_is_coupon' then pk_filed end) as value_filed
    , action
    , rule_id
    , ir_status as status
    , ir_reason as reason
    , cast(null as double) as fx_rate
    , cast(null as date) as fx_rate_date
    , cast(null as date) as value_date
    , rate_kind
    , case when ir_status = 'normalised' then nullif(concat_ws(',', it_scale_rule_id, ct_scale_rule_id, pk_scale_rule_id), '') end
        as scale_rule_ids
from interest_out
union all
select
    accession
    , context_id
    , 'interest_rate_cash' as field
    , cik
    , report_date
    , case when cash_status = 'normalised' then cash_value end as value
    , cast(null as varchar) as currency
    , coalesce(ct_filed, case when action = 'rate_is_cash_leg' then it_filed end) as value_filed
    , action
    , rule_id
    , cash_status as status
    , cash_reason as reason
    , cast(null as double) as fx_rate
    , cast(null as date) as fx_rate_date
    , cast(null as date) as value_date
    , cast(null as varchar) as rate_kind
    , case when cash_status = 'normalised' then nullif(concat_ws(',', it_scale_rule_id, ct_scale_rule_id, pk_scale_rule_id), '') end
        as scale_rule_ids
from interest_out
union all
select
    accession
    , context_id
    , field
    , cik
    , report_date
    , case when status = 'normalised' and field <> 'maturity_date' then value end as value
    , cast(null as varchar) as currency
    , value_filed
    , action
    , rule_id
    , status
    , reason
    , cast(null as double) as fx_rate
    , cast(null as date) as fx_rate_date
    , case when status = 'normalised' then value_date end as value_date
    , cast(null as varchar) as rate_kind
    , case when status = 'normalised' then scale_rule_ids end as scale_rule_ids
from (select * exclude (state), case state when 'value' then 'normalised' else state end as status from scaled)
{%- endmacro %}
