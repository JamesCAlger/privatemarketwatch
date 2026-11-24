-- Decides the canonical value of each amount field of each position row, by applying the rule int_field_rule chose
-- (spec intermediate_spine.md 6.4). One row per (accession, context_id, field): fair_value, cost, principal_amount,
-- principal_amount_usd, shares, pct_of_net_assets. value_filed stays beside the value. The amount half of
-- int_field_normalised (slice 5 Task 1 split it out unchanged; the rate half is int_rate_normalised, and
-- int_field_normalised is the union of the two). Columns are int_field_normalised's: the rate columns (value_date,
-- rate_kind, scale_rule_ids) are null here.
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
--                         rates see int_rate_normalised (seeds/reading_action.csv built_early_for_field).
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
