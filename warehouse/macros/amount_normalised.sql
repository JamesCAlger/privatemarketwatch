{#- The body of model int_amount_normalised, moved here unchanged (slice 5 Task 3) so that int_field_reread can run it on
    the rows corrections make positions. The model's header says what it decides. Inputs: rule_rel, read_rel. -#}
{% macro amount_normalised(rule_rel, read_rel) -%}
with rule as (
    select * from {{ rule_rel }}
)

, read as (
    select * from {{ read_rel }}
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
{%- endmacro %}
