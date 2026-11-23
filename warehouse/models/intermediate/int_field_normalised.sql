-- Decides the canonical value of each amount field and each rate field of each position row, by applying the rule
-- int_field_rule chose (spec intermediate_spine.md 6.4). One row per (accession, context_id, field): fair_value, cost,
-- principal_amount, principal_amount_usd, shares, pct_of_net_assets, and since slice 4 Task 3 interest_rate (the
-- all-in rate, percent; rate_kind beside it), interest_rate_cash (the cash leg, percent), pik_rate, spread (percent)
-- and maturity_date (in value_date). value_filed stays beside the value. The rate part is at the end of the file
-- (CTEs rate_read to scaled); where each rate action's meaning was read is in the slice 4 Task 3 report.
-- Rate statuses add these reasons: scale_not_decided (a ratio-unit value above 1), unit_not_pure, legs_do_not_add,
-- pik_above_rate, cash_leg_without_pik, pik_only_coupon (cash leg not set; status absent),
-- pik_is_coupon (spread not set under the coupon reading; status absent), pik_is_margin, not_a_date (as read).
-- Status normalised with reason cash_equals_all_in: the cash leg under rate_is_all_in where no PIK rate is read (owner
-- ruling A, 2026-11-23; it was absent, reason no_pik_read, as production's code). Except (controller ruling R1,
-- 2026-11-23): where the rate tag's own printed cell prints a PIK (int_rate_tag_cell.prints_pik: the word 'pik' on its
-- own in that one cell), the cash leg is unresolved, reason pik_printed_not_tagged: the page says part of the coupon is
-- PIK, no PIK rate is tagged, so cash = all-in would contradict the page.
-- scale_rule_ids on interest_rate and interest_rate_cash lists the scale rules of every rate input read for the
-- reading (rate tag, cash-pay tag, PIK rate), including a PIK rate that on the all-in row only fed the check against
-- the tag (pik_above_rate); it does not prove the listed input changed this row's value.
--
-- What each action does (where its meaning was read is in the slice 3 Task 3 report):
--   as_filed              value = value_filed. For principal_amount_usd: value = the principal, already in dollars.
--   reported_in_usd       value = value_filed: an amount in a foreign unit taken as dollars.
--   to_usd                principal_amount_usd = principal times usd_per_unit (stg_fx_rate) of the principal's
--                         currency, on the report date or the latest earlier quote no more than var fx_max_age_days
--                         (7) days before it. No such quote: unresolved, reason no_fx_rate (production leaves the
--                         principal unconverted: missing_reference_fx). Same rule as scripts/programme_closeout/fx.py.
--   cost_foreign_is_par   cost = the US dollar cost fact; principal = the foreign cost fact, in its currency.
--   par_tagged_as_units   principal = the share count times value_scale, currency USD (production reads the empty
--                         principal unit as USD); shares left empty (status normalised, reason moved_to_principal).
--   units_tagged_as_par   shares = the principal fact's number. The principal is kept as filed (as production).
--   bracketed_unsigned    value = minus value_filed (the printed sign).
--   fraction_to_percent   value = value_filed times 100. Built here for pct_of_net_assets only (production stores a
--                         percent: docs/reference/schemas.md line 25, pipeline/staging_bdc.py lines 2945-2949); for
--                         rates it stays slice 4 (seeds/reading_action.csv built_early_for_field).
--   ratio_value_is_percent  (owner ruling B, 2026-11-23) a rate number filed above 1 in a ratio unit is already a
--                         percent: value = value_filed, no times 100. Decided per row by int_rate_scale (a fund scale
--                         rule naming the filing and field, and the row's own print agrees). A PIK rate or spread so
--                         decided names the scale rule as its rule_id and this action; the all-in rate and cash leg keep
--                         their reading's rule. scale_rule_ids lists the scale rules behind a normalised rate value
--                         (comma-separated; null where none).
-- An action counts as built for a field when reading_action.built_in_slice is 3 or built_early_for_field names the
-- field, or its slice is 4 and the field is a rate field (macro action_is_built); otherwise the field is unresolved,
-- action_not_built.
-- Status:
--   normalised  a rule applied (reason applied, or moved_to_principal on shares)
--   absent      no fact (reason no_fact), only nil facts (nil), or for principal_amount_usd a principal that is absent
--   unresolved  reason: values_differ / units_differ / fact_without_number (as read, no rule settled it), no_rule,
--               rule_conflict, feature_missing (a top-ranked rule needs a row feature that is null), text_not_read (a
--               top-ranked rule needs printed text no model reads yet, action_field.unread_input),
--               action_not_built (the action is not built for this field yet), no_fx_rate,
--               principal_unresolved (principal_amount_usd of an unresolved principal)
with rule as (
    select * from {{ ref('int_field_rule') }}
)

, read as (
    select * from {{ ref('int_field_read') }}
)

, action as (
    select action, built_in_slice, built_early_for_field from {{ ref('reading_action') }}
)

, two_unit_context as (
    select accession, context_id from rule where action = 'cost_foreign_is_par'
)

, two_unit_cost as (
    {{ two_unit_cost_facts('two_unit_context') }}
)

, shares_read as (
    select accession, context_id, value_filed from read where field = 'shares'
)

, principal_read as (
    select accession, context_id, value_filed from read where field = 'principal_amount'
)

, five as (
    -- the five read fields with the value their rule gives
    select
        ru.accession
        , ru.context_id
        , ru.field
        , ru.cik
        , ru.report_date
        , rd.value_filed
        , rd.unit
        , rd.status as read_status
        , rd.reason as read_reason
        , rd.is_nil
        , ru.rule_id
        , ru.action
        , ru.resolution
        , {{ action_is_built('a.built_in_slice', 'a.built_early_for_field', 'ru.field') }} as is_built
        , case
            when ru.action in ('as_filed', 'reported_in_usd') then rd.value_filed
            when ru.action = 'fraction_to_percent' then rd.value_filed * 100
            when ru.action = 'bracketed_unsigned' then - rd.value_filed
            when ru.action = 'cost_foreign_is_par' and ru.field = 'cost' then t.usd_value
            when ru.action = 'cost_foreign_is_par' and ru.field = 'principal_amount' then t.foreign_value
            when ru.action = 'par_tagged_as_units' and ru.field = 'principal_amount' then sh.value_filed * ru.value_scale
            when ru.action = 'units_tagged_as_par' and ru.field = 'shares' then pr.value_filed
          end as value
        , case
            when ru.field <> 'principal_amount' then null
            when ru.action = 'as_filed' then regexp_extract(rd.unit, '^iso4217:([A-Z]{3})$', 1)
            when ru.action = 'cost_foreign_is_par' then regexp_extract(t.foreign_unit, '^iso4217:([A-Z]{3})$', 1)
            when ru.action = 'par_tagged_as_units' then 'USD'
          end as currency
    from rule ru
    join read rd on rd.accession = ru.accession and rd.context_id = ru.context_id and rd.field = ru.field
    left join action a on a.action = ru.action
    left join two_unit_cost t on t.accession = ru.accession and t.context_id = ru.context_id
    left join shares_read sh on sh.accession = ru.accession and sh.context_id = ru.context_id
    left join principal_read pr on pr.accession = ru.accession and pr.context_id = ru.context_id
    where ru.field in {{ amount_rule_fields() }}
)

, five_status as (
    select
        *
        , case
            when resolution in ('rule_conflict', 'feature_missing', 'text_not_read') then 'unresolved'
            when resolution = 'rule' and not is_built then 'unresolved'
            when resolution = 'rule' then 'normalised'
            when read_status = 'absent' or is_nil then 'absent'
            else 'unresolved'
          end as status
        , case
            when resolution in ('rule_conflict', 'feature_missing', 'text_not_read') then resolution
            when resolution = 'rule' and not is_built then 'action_not_built'
            when resolution = 'rule' and action = 'par_tagged_as_units' and field = 'shares' then 'moved_to_principal'
            when resolution = 'rule' then 'applied'
            when read_status = 'absent' then 'no_fact'
            when is_nil then 'nil'
            when read_status = 'unresolved' then read_reason
            else 'no_rule'
          end as reason
    from five
)

, principal as (
    select * from five_status where field = 'principal_amount'
)

, usd_rule as (
    select * from rule where field = 'principal_amount_usd'
)

, usd_fx as (
    -- the quote for the principal's currency at the report date: that day or the latest earlier one
    select
        u.accession
        , u.context_id
        , fx.usd_per_unit
        , fx.rate_date
    from usd_rule u
    join principal p on p.accession = u.accession and p.context_id = u.context_id
    asof join {{ ref('stg_fx_rate') }} fx
        on fx.currency = p.currency and fx.rate_date <= u.report_date
    where u.action = 'to_usd'
)

, usd as (
    select
        u.accession
        , u.context_id
        , 'principal_amount_usd' as field
        , u.cik
        , u.report_date
        , p.value as value_filed
        , u.rule_id
        , u.action
        , u.resolution
        , {{ action_is_built('a.built_in_slice', 'a.built_early_for_field', "'principal_amount_usd'") }} as is_built
        , p.status as principal_status
        , p.reason as principal_reason
        , case
            when u.action = 'to_usd'
                and fx.rate_date >= u.report_date - to_days({{ var('fx_max_age_days') }}) then fx.usd_per_unit
          end as fx_rate
        , case
            when u.action = 'to_usd'
                and fx.rate_date >= u.report_date - to_days({{ var('fx_max_age_days') }}) then fx.rate_date
          end as fx_rate_date
    from usd_rule u
    join principal p on p.accession = u.accession and p.context_id = u.context_id
    left join action a on a.action = u.action
    left join usd_fx fx on fx.accession = u.accession and fx.context_id = u.context_id
)

, usd_status as (
    select
        *
        , case
            when resolution = 'rule' and action = 'as_filed' then value_filed
            when resolution = 'rule' and action = 'to_usd' then value_filed * fx_rate
          end as value
        , case
            when principal_status = 'absent' then 'absent'
            when principal_status = 'unresolved' then 'unresolved'
            when resolution in ('rule_conflict', 'feature_missing', 'text_not_read') then 'unresolved'
            when resolution = 'rule' and not is_built then 'unresolved'
            when resolution = 'rule' and action = 'to_usd' and fx_rate is null then 'unresolved'
            when resolution = 'rule' then 'normalised'
            else 'unresolved'
          end as status
        , case
            when principal_status = 'absent' then principal_reason
            when principal_status = 'unresolved' then 'principal_unresolved'
            when resolution in ('rule_conflict', 'feature_missing', 'text_not_read') then resolution
            when resolution = 'rule' and not is_built then 'action_not_built'
            when resolution = 'rule' and action = 'to_usd' and fx_rate is null then 'no_fx_rate'
            when resolution = 'rule' then 'applied'
            else 'no_rule'
          end as reason
    from usd
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
    -- state: value (usable), absent (no fact or nil only), unresolved (why says why). A number is usable as a fraction
    -- in a ratio unit: times 100 (fraction_to_percent). Above 1 it may already be a percent; its scale is not decided by
    -- its size (controller ruling): unresolved scale_not_decided, unless a fund scale rule kept it as a percent where
    -- the row's own print agrees (int_rate_scale, owner ruling B 2026-11-23): then the filed number is the percent.
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

, interest as (
    -- the interest_rate reading: the all-in rate (ir_), the cash leg (cash_) and the kind, from the rule of
    -- interest_rate. Legs as production (pipeline/financial_conventions.py prepare, tables conventions and calculated):
    --   rate_is_all_in    all-in = interest-rate tag; cash = all-in less PIK where a PIK rate is read, else cash =
    --                     all-in (reason cash_equals_all_in; owner ruling A, 2026-11-23: PIK absent counts as zero.
    --                     Production leaves this cash leg empty. Residual risk: a PIK that exists but is not tagged
    --                     gives an overstated cash leg; controller ruling R1: not where the rate's printed cell prints
    --                     a PIK, reason pik_printed_not_tagged, unresolved); a PIK rate above the tag plus var pik_above_rate_margin (0.01,
    --                     production's margin) leaves both unresolved (pik_above_rate)
    --   rate_is_cash_leg  cash = interest-rate tag; all-in = cash plus PIK where a PIK rate is read, else empty
    --                     (cash_leg_without_pik)
    --   a cash-pay tag    is the cash leg under either reading (production: the concept names its own kind)
    --   both tags         production keeps the first fact in the instance (pipeline/bdc_filings.py, "keep first
    --                     non-None"); here both are kept where they agree with the PIK rate (all-in = cash + PIK, or
    --                     under rate_is_cash_leg the two cash legs equal) within var rate_legs_tolerance, else both
    --                     unresolved (legs_do_not_add). No row of the five funds files both
    --   pik_only_is_coupon  all-in = the PIK rate; cash left empty (pik_only_coupon): production's code on this branch
    --                     sets the cash leg only from a filed rate
    --   pik_only_is_margin  the rate is not known: both unresolved (pik_is_margin)
    --   Both PIK-only arithmetics cannot be reached in a build while action_field.unread_input is set on them
    --   (controller ruling of 2026-11-23: every such row is text_not_read in int_field_rule and never gets here). They
    --   are kept, and unit-tested, so that clearing unread_input (which needs a selector on the loan class and the
    --   printed rate type, see the seed notes) does not need this code written again.
    -- An input that is unresolved (two values, a unit that is not a ratio, a scale not decided) leaves both unresolved
    -- with its reason. kind: all_in, cash or unresolved (production's interest_rate_kind).
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
        , coalesce(tc.prints_pik, false) as rate_cell_prints_pik
        , case
            when i.it_state = 'unresolved' then i.it_why
            when i.ct_state = 'unresolved' then i.ct_why
            when i.pk_state = 'unresolved' then i.pk_why
          end as input_why
    from rate_rule r
    join rate_input i on i.accession = r.accession and i.context_id = r.context_id
    left join {{ ref('int_rate_tag_cell') }} tc on tc.accession = r.accession and tc.context_id = r.context_id
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
    , field
    , cik
    , report_date
    , case when status = 'normalised' then value end as value
    , case when status = 'normalised' then currency end as currency
    , value_filed
    , action
    , rule_id
    , status
    , reason
    , cast(null as double) as fx_rate
    , cast(null as date) as fx_rate_date
    , cast(null as date) as value_date
    , cast(null as varchar) as rate_kind
    , cast(null as varchar) as scale_rule_ids
from five_status
union all
select
    accession
    , context_id
    , field
    , cik
    , report_date
    , case when status = 'normalised' then value end as value
    , cast(null as varchar) as currency
    , value_filed
    , action
    , rule_id
    , status
    , reason
    , case when status = 'normalised' then fx_rate end as fx_rate
    , case when status = 'normalised' then fx_rate_date end as fx_rate_date
    , cast(null as date) as value_date
    , cast(null as varchar) as rate_kind
    , cast(null as varchar) as scale_rule_ids
from usd_status
union all
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
