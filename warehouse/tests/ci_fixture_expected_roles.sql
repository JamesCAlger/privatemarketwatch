-- CI fixture only (warehouse/ci/README.md; enabled by --vars ci_fixture: true, which only warehouse/ci/run_fixture_build.py
-- passes). The invented fund 0000000001 has one context per row-role rule; this test states the role each must get and
-- the filing each quarter must select or refuse. Returns every expectation that does not hold, and every fixture row
-- with no expectation, so a rule change that moves a fixture row fails CI until this list is updated.
{{ config(enabled=var('ci_fixture', false)) }}
with expected_role as (
    select * from (values
          ('0000000001-26-000011', 'c-1', 'not_schedule', 1, false, false, 'fund')
        , ('0000000001-26-000011', 'c-2', 'not_schedule', 1, false, false, 'fund')
        , ('0000000001-26-000011', 'c-3', 'position', 9, false, true, 'fund')
        , ('0000000001-26-000011', 'c-4', 'position', 9, false, true, 'fund')
        , ('0000000001-26-000011', 'c-5', 'aggregate', 4, false, false, 'fund')
        , ('0000000001-26-000011', 'c-6', 'aggregate', 6, false, false, 'fund')
        , ('0000000001-26-000011', 'c-7', 'position', 9, false, true, 'fund')
        , ('0000000001-26-000011', 'c-8', 'position', 9, false, true, 'fund')
        , ('0000000001-26-000011', 'c-9', 'comparative', 2, false, false, 'fund')
        , ('0000000001-26-000011', 'c-10', 'position', 8, true, true, 'fund')
        , ('0000000001-26-000011', 'c-11', 'aggregate', 5, false, false, 'fund')
        , ('0000000001-26-000011', 'c-12', 'position', 9, true, true, 'fund')
        , ('0000000001-26-000011', 'c-13', 'position', 9, true, true, 'fund')
        , ('0000000001-26-000011', 'c-14', 'position', 7, false, false, 'Fixture JV LLC')
        , ('0000000001-26-000011', 'c-15', 'position', 7, false, false, 'Fixture JV LLC')
        , ('0000000001-26-000011', 'c-16', 'position', 7, false, false, 'FixtureSubsidiaryMember')
        , ('0000000001-26-000011', 'c-17', 'position', 9, false, true, 'fund')
        , ('0000000001-26-000011', 'c-18', 'position', 9, false, true, 'fund')
        , ('0000000001-26-000011', 'c-19', 'unresolved', 9, false, false, 'fund')
        , ('0000000001-26-000011', 'c-20', 'position', 9, false, true, 'fund')
        , ('0000000001-26-000011', 'c-21', 'position', 9, false, true, 'fund')
        , ('0000000001-26-000011', 'c-22', 'unresolved', 3, false, false, 'fund')
        , ('0000000001-26-000011', 'c-23', 'aggregate', 6, false, false, 'fund')
        , ('0000000001-26-000011', 'c-24', 'position', 9, false, true, 'fund')
        , ('0000000001-26-000011', 'c-25', 'position', 9, false, true, 'fund')
        , ('0000000001-26-000011', 'c-26', 'unresolved', 4, false, false, 'fund')
        -- slice 5 Task 6: two contexts that only a correction makes positions (ci_fixture_expected_corrections.sql);
        -- their filed role does not change
        , ('0000000001-26-000011', 'c-27', 'not_schedule', 3, false, false, 'fund')
        , ('0000000001-26-000011', 'c-91', 'not_schedule', 1, false, false, 'fund')
        , ('0000000001-26-000012', 'c-1', 'superseded', 0, false, false, 'fund')
        , ('0000000001-26-000001', 'c-1', 'superseded', 0, false, false, 'fund')
        , ('0000000001-26-000002', 'c-1', 'superseded', 0, false, false, 'fund')
    ) v(accession, context_id, role, role_rule, is_cash, is_published, scope)
)

, actual_role as (
    select accession, context_id, role, role_rule, is_cash, is_published, scope
    from {{ ref('int_source_row') }}
    where cik = '0000000001'
)

-- Which fund rule decided, where one must: the concept rules (c-17, c-18), the subtotal rule (c-23), the release rule
-- (c-20, c-21), the cash identifier (c-13). Read through the rule's action, so the test does not depend on rule ids.
, expected_rule as (
    select * from (values
          ('c-17', 'concept_rule_id', 'concept_is_fair_value')
        , ('c-18', 'concept_rule_id', 'concept_is_term_fact')
        , ('c-23', 'rule_id', 'subtotal_on_fair_value')
        , ('c-20', 'position_rule_id', 'position_without_term_fact')
        , ('c-21', 'position_rule_id', 'position_without_term_fact')
        , ('c-13', 'cash_rule_id', 'set_is_cash')
    ) v(context_id, rule_column, action)
)

, fixture_row as (
    select *
    from {{ ref('int_source_row') }}
    where cik = '0000000001' and accession = '0000000001-26-000011'
)

, rule_used as (
    select context_id, 'concept_rule_id' as rule_column, concept_rule_id as rule_value from fixture_row
    union all select context_id, 'rule_id', rule_id from fixture_row
    union all select context_id, 'position_rule_id', position_rule_id from fixture_row
    union all select context_id, 'cash_rule_id', cash_rule_id from fixture_row
)

, actual_rule as (
    select u.context_id, u.rule_column, r.action
    from rule_used u
    join {{ ref('stg_reading_rule') }} r on r.rule_id = u.rule_value
)

, expected_filing as (
    select * from (values
          (date '2026-03-31', '0000000001-26-000011', 'original_after_cover_only_amendment', null)
        , (date '2025-12-31', null, null, 'two_originals_same_quarter')
    ) v(report_date, accession, selection_rule, refusal_reason)
)

, actual_filing as (
    select report_date, accession, selection_rule, refusal_reason
    from {{ ref('int_filing_selected') }}
    where cik = '0000000001'
)

select 'role expected, not found or different' as problem, e.accession, e.context_id, e.role as detail
from expected_role e
anti join actual_role a
    on a.accession = e.accession and a.context_id = e.context_id and a.role = e.role and a.role_rule = e.role_rule
    and a.is_cash = e.is_cash and a.is_published = e.is_published and a.scope = e.scope
union all
select 'row with no expectation', a.accession, a.context_id, a.role
from actual_role a
anti join expected_role e on e.accession = a.accession and e.context_id = a.context_id
union all
select 'fund rule expected, not found', '0000000001-26-000011', e.context_id, e.rule_column || ' ' || e.action
from expected_rule e
anti join actual_rule a on a.context_id = e.context_id and a.rule_column = e.rule_column and a.action = e.action
union all
select 'filing selection differs', e.accession, cast(e.report_date as varchar), coalesce(e.selection_rule, e.refusal_reason)
from expected_filing e
anti join actual_filing a
    on a.report_date = e.report_date and a.accession is not distinct from e.accession
    and a.selection_rule is not distinct from e.selection_rule and a.refusal_reason is not distinct from e.refusal_reason
union all
select 'filing selection with no expectation', a.accession, cast(a.report_date as varchar), coalesce(a.selection_rule, a.refusal_reason)
from actual_filing a
anti join expected_filing e on e.report_date = a.report_date
