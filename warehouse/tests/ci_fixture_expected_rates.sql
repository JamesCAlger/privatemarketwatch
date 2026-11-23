-- CI fixture only (warehouse/ci/README.md; enabled by --vars ci_fixture: true, which only warehouse/ci/run_fixture_build.py
-- passes). Slice 4 Task 5, the rate counterpart of ci_fixture_expected_amounts.sql: for each fixture position, every
-- rate field (interest_rate, interest_rate_cash, pik_rate, spread, maturity_date) that is not absent with reason
-- no_fact, with its status, reason, value (or date), rate_kind, action and the rule that converted it. Every other rate
-- field of a fixture position must be absent, no_fact, and every position must have its five rate rows. Returns every
-- expectation that does not hold, so a rule change that moves a fixture rate fails CI until this list is updated.
--
-- converted_by: the global default's rule id (seeds/field_rule_default.csv), or 'fund:' and the fund rule's action
-- (fund rule ids are content hashes); null where no rule decided. The cash leg is decided under the interest_rate rule.
-- The fund reads its rate tag as all-in (filed_rate_reading all_in -> rate_is_all_in) and declares a PIK-only coupon
-- reading (pik_only_tag_reading coupon -> pik_only_is_coupon). What each row is there for:
--   c-3   rate tag 9.00 and PIK tag 2.00: all-in 9.0, cash leg 7.0, PIK 2.0. The legs check
--         (tests/int_field_normalised_rate_legs.sql) runs on this row.
--   c-7   rate 8.0 and spread 5.0 (default fraction_to_percent); no PIK, so the cash leg is empty (no_pik_read).
--   c-24  rate 7.0, cash leg empty (no_pik_read).
--   c-17  only a PIK tag, 12.50: pik_only_is_coupon needs printed text not read yet (action_field.unread_input), so the
--         all-in rate, the cash leg and the spread are unresolved, text_not_read, kind unresolved; the PIK rate is still
--         read (12.5). A missing rate here is not "no rate": the printed schedule shows 12.50 PIK.
--   c-25  rate tag filed as 7.00 (a percent) in a ratio unit: above 1, its scale is not decided by its size
--         (scale_not_decided), so the rate and its cash leg are unresolved, no value.
--   c-8   rate tag in the unit written xbrli:pure: unit kinds are read from the unit text, which knows only 'pure' and
--         'utr:Rate', so the rate is unresolved (unit_not_pure). This pins today's behaviour; none of the five funds
--         writes the prefix.
--   c-4   maturity date 2030-01-01, taken as filed (gd_maturity_date).
{{ config(enabled=var('ci_fixture', false)) }}
with expected as (
    select * from (values
          ('c-3', 'interest_rate', 'normalised', 'applied', 9.0, null::date, 'all_in', 'rate_is_all_in', 'fund:rate_is_all_in')
        , ('c-3', 'interest_rate_cash', 'normalised', 'applied', 7.0, null, null, 'rate_is_all_in', 'fund:rate_is_all_in')
        , ('c-3', 'pik_rate', 'normalised', 'applied', 2.0, null, null, 'fraction_to_percent', 'gd_pik_rate_pure')
        , ('c-7', 'interest_rate', 'normalised', 'applied', 8.0, null, 'all_in', 'rate_is_all_in', 'fund:rate_is_all_in')
        , ('c-7', 'interest_rate_cash', 'absent', 'no_pik_read', null, null, null, 'rate_is_all_in', 'fund:rate_is_all_in')
        , ('c-7', 'spread', 'normalised', 'applied', 5.0, null, null, 'fraction_to_percent', 'gd_spread_pure')
        , ('c-24', 'interest_rate', 'normalised', 'applied', 7.0, null, 'all_in', 'rate_is_all_in', 'fund:rate_is_all_in')
        , ('c-24', 'interest_rate_cash', 'absent', 'no_pik_read', null, null, null, 'rate_is_all_in', 'fund:rate_is_all_in')
        , ('c-17', 'interest_rate', 'unresolved', 'text_not_read', null, null, 'unresolved', null, null)
        , ('c-17', 'interest_rate_cash', 'unresolved', 'text_not_read', null, null, null, null, null)
        , ('c-17', 'spread', 'unresolved', 'text_not_read', null, null, null, null, null)
        , ('c-17', 'pik_rate', 'normalised', 'applied', 12.5, null, null, 'fraction_to_percent', 'gd_pik_rate_pure')
        , ('c-25', 'interest_rate', 'unresolved', 'scale_not_decided', null, null, 'unresolved', 'rate_is_all_in', 'fund:rate_is_all_in')
        , ('c-25', 'interest_rate_cash', 'unresolved', 'scale_not_decided', null, null, null, 'rate_is_all_in', 'fund:rate_is_all_in')
        , ('c-8', 'interest_rate', 'unresolved', 'unit_not_pure', null, null, 'unresolved', 'rate_is_all_in', 'fund:rate_is_all_in')
        , ('c-8', 'interest_rate_cash', 'unresolved', 'unit_not_pure', null, null, null, 'rate_is_all_in', 'fund:rate_is_all_in')
        , ('c-4', 'maturity_date', 'normalised', 'applied', null, date '2030-01-01', null, 'as_filed', 'gd_maturity_date')
    ) v(context_id, field, status, reason, value, value_date, rate_kind, action, converted_by)
)

, normalised as (
    select * from {{ ref('int_field_normalised') }}
    where cik = '0000000001'
      and field in ('interest_rate', 'interest_rate_cash', 'pik_rate', 'spread', 'maturity_date')
)

, actual as (
    select
        n.context_id
        , n.field
        , n.status
        , n.reason
        , n.value
        , n.value_date
        , n.rate_kind
        , n.action
        , case when r.origin = 'global_default' then r.rule_id when fr.action is not null then 'fund:' || fr.action end
            as converted_by
    from normalised n
    -- the cash leg has no rule row of its own: it is decided under the interest_rate rule
    left join {{ ref('int_field_rule') }} r
        on r.accession = n.accession and r.context_id = n.context_id
        and r.field = case when n.field = 'interest_rate_cash' then 'interest_rate' else n.field end
    left join {{ ref('stg_reading_rule') }} fr on fr.rule_id = r.rule_id
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

select 'rate expected, not found or different' as problem, e.context_id, e.field as detail
from expected e
anti join actual a
    on a.context_id = e.context_id and a.field = e.field
    and a.status = e.status
    and a.reason = e.reason
    and ((a.value is null and e.value is null) or abs(a.value - e.value) < 0.000001)
    and a.value_date is not distinct from e.value_date
    and a.rate_kind is not distinct from e.rate_kind
    and a.action is not distinct from e.action
    and a.converted_by is not distinct from e.converted_by
union all
select 'rate with no expectation (only absent no_fact is implied)', a.context_id, a.field || ' ' || a.status || ' ' || a.reason
from actual a
anti join expected e on e.context_id = a.context_id and e.field = a.field
where not (a.status = 'absent' and a.reason = 'no_fact')
union all
select 'position without its five rate rows', context_id, cast(fields as varchar)
from rows_per_position
where fields <> 5
