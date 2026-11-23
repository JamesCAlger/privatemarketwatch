-- CI fixture only (warehouse/ci/README.md; enabled by --vars ci_fixture: true, which only warehouse/ci/run_fixture_build.py
-- passes). States the amount each fixture position row must get from int_field_normalised (slice 3): for every field
-- that is not absent, its value, currency, action, the rule that converted it and the rule it was read under. Every
-- other field of a fixture position must be absent with reason no_fact, and every position must have its six amount
-- rows. Returns every expectation that does not hold, so a rule change that moves a fixture amount fails CI until this
-- list is updated.
--
-- converted_by: the global default's rule id (seeds/field_rule_default.csv, ids are stable), or 'fund:' and the fund
-- rule's action (fund rule ids are content hashes). read_by: the concept_map row the facts were read under, or 'fund:'
-- and the action of the fund rule that reads the filer's own concept; null for principal_amount_usd, which is derived.
-- Non-default actions on purpose: c-7's principal is in euros, so its dollar value takes the fund rule to_usd (from
-- principal_usd_reference in the fixture's wrapper copy) at the rate of 2026-03-27, four days before the report date
-- (fixture/fx_rates.csv). c-3's share of net assets is a fraction (0.1) and becomes a percent (fraction_to_percent,
-- the global default built early for that field). c-17's fair value is read under the fund rule concept_is_fair_value.
{{ config(enabled=var('ci_fixture', false)) }}
with expected as (
    select * from (values
          ('c-3', 'fair_value', 1000.0, null, 'as_filed', 'gd_fair_value_usd', 'cm_fair_value', null)
        , ('c-3', 'cost', 990.0, null, 'as_filed', 'gd_cost_usd', 'cm_cost', null)
        , ('c-3', 'principal_amount', 1000.0, 'USD', 'as_filed', 'gd_principal_usd', 'cm_principal', null)
        , ('c-3', 'principal_amount_usd', 1000.0, null, 'as_filed', 'gd_principal_usd_usd', null, null)
        , ('c-3', 'pct_of_net_assets', 10.0, null, 'fraction_to_percent', 'gd_pct_of_net_assets', 'cm_pct_net_assets', null)
        , ('c-4', 'fair_value', 500.0, null, 'as_filed', 'gd_fair_value_usd', 'cm_fair_value', null)
        , ('c-4', 'cost', 510.0, null, 'as_filed', 'gd_cost_usd', 'cm_cost', null)
        , ('c-7', 'fair_value', 200.0, null, 'as_filed', 'gd_fair_value_usd', 'cm_fair_value', null)
        , ('c-7', 'cost', 200.0, null, 'as_filed', 'gd_cost_usd', 'cm_cost', null)
        , ('c-7', 'principal_amount', 180.0, 'EUR', 'as_filed', 'gd_principal_foreign', 'cm_principal', null)
        , ('c-7', 'principal_amount_usd', 194.4, null, 'to_usd', 'fund:to_usd', null, date '2026-03-27')
        , ('c-8', 'fair_value', 100.0, null, 'as_filed', 'gd_fair_value_usd', 'cm_fair_value', null)
        , ('c-8', 'cost', 100.0, null, 'as_filed', 'gd_cost_usd', 'cm_cost', null)
        , ('c-10', 'fair_value', 50.0, null, 'as_filed', 'gd_fair_value_usd', 'cm_fair_value', null)
        , ('c-12', 'fair_value', 30.0, null, 'as_filed', 'gd_fair_value_usd', 'cm_fair_value', null)
        , ('c-13', 'fair_value', 10.0, null, 'as_filed', 'gd_fair_value_usd', 'cm_fair_value', null)
        , ('c-14', 'fair_value', 400.0, null, 'as_filed', 'gd_fair_value_usd', 'cm_fair_value', null)
        , ('c-14', 'principal_amount', 400.0, 'USD', 'as_filed', 'gd_principal_usd', 'cm_principal', null)
        , ('c-14', 'principal_amount_usd', 400.0, null, 'as_filed', 'gd_principal_usd_usd', null, null)
        , ('c-15', 'fair_value', 60.0, null, 'as_filed', 'gd_fair_value_usd', 'cm_fair_value', null)
        , ('c-15', 'principal_amount', 60.0, 'USD', 'as_filed', 'gd_principal_usd', 'cm_principal', null)
        , ('c-15', 'principal_amount_usd', 60.0, null, 'as_filed', 'gd_principal_usd_usd', null, null)
        , ('c-16', 'fair_value', 70.0, null, 'as_filed', 'gd_fair_value_usd', 'cm_fair_value', null)
        , ('c-16', 'principal_amount', 70.0, 'USD', 'as_filed', 'gd_principal_usd', 'cm_principal', null)
        , ('c-16', 'principal_amount_usd', 70.0, null, 'as_filed', 'gd_principal_usd_usd', null, null)
        , ('c-17', 'fair_value', -5.0, null, 'as_filed', 'gd_fair_value_usd', 'fund:concept_is_fair_value', null)
        , ('c-17', 'principal_amount', 500.0, 'USD', 'as_filed', 'gd_principal_usd', 'cm_principal', null)
        , ('c-17', 'principal_amount_usd', 500.0, null, 'as_filed', 'gd_principal_usd_usd', null, null)
        , ('c-18', 'fair_value', 90.0, null, 'as_filed', 'gd_fair_value_usd', 'cm_fair_value', null)
        , ('c-20', 'fair_value', 85.0, null, 'as_filed', 'gd_fair_value_usd', 'cm_fair_value', null)
        , ('c-21', 'fair_value', 0.0, null, 'as_filed', 'gd_fair_value_usd', 'cm_fair_value', null)
        , ('c-24', 'fair_value', 250.0, null, 'as_filed', 'gd_fair_value_usd', 'cm_fair_value', null)
        , ('c-24', 'cost', 250.0, null, 'as_filed', 'gd_cost_usd', 'cm_cost', null)
        , ('c-25', 'fair_value', 150.0, null, 'as_filed', 'gd_fair_value_usd', 'cm_fair_value', null)
        , ('c-25', 'cost', 150.0, null, 'as_filed', 'gd_cost_usd', 'cm_cost', null)
    ) v(context_id, field, value, currency, action, converted_by, read_by, fx_rate_date)
)

, normalised as (
    select * from {{ ref('int_field_normalised') }}
    where cik = '0000000001'
      -- the amount rows only: the rate rows (slice 4 Task 3) are not part of this fixture's expectations (slice 4 Task 5)
      and (field in {{ amount_rule_fields() }} or field = 'principal_amount_usd')
)

, actual as (
    select
        n.context_id
        , n.field
        , n.status
        , n.reason
        , n.value
        , n.currency
        , n.action
        , case when r.origin = 'global_default' then r.rule_id else 'fund:' || fr.action end as converted_by
        , case when cm.concept_map_id is not null then cm.concept_map_id else 'fund:' || rr.action end as read_by
        , n.fx_rate_date
    from normalised n
    left join {{ ref('int_field_rule') }} r
        on r.accession = n.accession and r.context_id = n.context_id and r.field = n.field
    left join {{ ref('stg_reading_rule') }} fr on fr.rule_id = r.rule_id
    left join {{ ref('int_field_read') }} d
        on d.accession = n.accession and d.context_id = n.context_id and d.field = n.field
    left join {{ ref('concept_map') }} cm on cm.concept_map_id = d.read_rule_id
    left join {{ ref('stg_reading_rule') }} rr on rr.rule_id = d.read_rule_id
)

, position as (
    select accession, context_id
    from {{ ref('int_source_row') }}
    where cik = '0000000001' and role = 'position'
)

, rows_per_position as (
    select p.context_id, count(n.field) as fields
    from position p
    left join normalised n on n.accession = p.accession and n.context_id = p.context_id
    group by p.context_id
)

select 'amount expected, not found or different' as problem, e.context_id, e.field as detail
from expected e
anti join actual a
    on a.context_id = e.context_id and a.field = e.field
    and a.status = 'normalised' and a.reason = 'applied'
    and abs(a.value - e.value) < 0.000001
    and a.currency is not distinct from e.currency
    and a.action = e.action
    and a.converted_by = e.converted_by
    and a.read_by is not distinct from e.read_by
    and a.fx_rate_date is not distinct from e.fx_rate_date
union all
select 'amount with no expectation (only absent no_fact is implied)', a.context_id, a.field || ' ' || a.status || ' ' || a.reason
from actual a
anti join expected e on e.context_id = a.context_id and e.field = a.field
where not (a.status = 'absent' and a.reason = 'no_fact')
union all
select 'position without its six amount rows', context_id, cast(fields as varchar)
from rows_per_position
where fields <> 6
