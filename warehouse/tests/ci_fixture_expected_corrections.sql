-- CI fixture only (warehouse/ci/README.md; enabled by --vars ci_fixture: true, which only warehouse/ci/run_fixture_build.py
-- passes). Slice 5 Task 6, the corrections counterpart of ci_fixture_expected_amounts.sql and _rates.sql: the outcome of
-- every fixture correction (int_correction_application), the contexts corrections make positions (int_row_corrected)
-- and the corrected values that show each mechanism (int_field_corrected). Returns every expectation that does not
-- hold and every correction outcome with no expectation, so a change that moves a fixture correction fails CI until
-- this list is updated.
-- What each correction is there for (stores in ci/fixture/):
--   applied     c-24 cost 240 (row store by context; filed 250), step converted. The older c-3 cost 990 equals the
--               filed cost, so it is no_op.
--   no_op       c-7 cost 200 and c-3 cost 990 (equal to the filed cost, equal_to_normalised); the add_row cost on c-91
--               (equal to c-91's filed cost 100).
--   rejected    target_not_found: c-99 (no such context); the B2 leaf's three values (keyed by a production row id;
--               the fixture's production holdings file has no rows); the second fund's identifier row (no such filing).
--   deferred    field_not_held: c-4 issuer name, the c-19 relabel, the add_row metadata fields.
--   untagged    the wrapper copy's c-27 fair value 0: c-27 has a principal and no fair-value fact (rule 3, not_schedule)
--               and prints a dash in its fair-value cell, so the correction applies at step filed and makes it a
--               position (correction_supplies_fair_value). The older c-4 principal 500 applies at step filed too, and its
--               dollar principal is derived from it.
--   rate        c-3 PIK rate 3.0 (filed 2.0): the rate reading runs again (step reading_input), so the cash leg is
--               derived again: 9.0 all-in minus 3.0 PIK = 6.0 (was 7.0); the all-in rate stays 9.0.
--   row_add     the agent rule's position on c-91 (rule 1, not_schedule: an issuer-axis context with a cost only):
--               fair value 100, principal 100 USD applied (correction_adds_row).
-- A passing fixture shows the mechanisms run as stated on invented rows; it does not show any correction is right.
{{ config(enabled=var('ci_fixture', false)) }}
with expected_outcome as (
    select * from (values
          ('row_corrections_by_context', 'c-24', 'cost', 'applied', null, 'converted', '240.0')
        , ('row_corrections_by_context', 'c-7', 'cost', 'no_op', 'equal_to_normalised', null, '200.0')
        , ('row_corrections', 'c-3', 'cost', 'no_op', 'equal_to_normalised', null, '990.0')
        , ('row_corrections_by_context', 'c-99', 'cost', 'rejected', 'target_not_found', null, null)
        , ('row_corrections', '', 'cost', 'rejected', 'target_not_found', null, null)
        , ('agent_b2_corrections', '', 'interest_rate_cash', 'rejected', 'target_not_found', null, null)
        , ('agent_b2_corrections', '', 'interest_rate_kind', 'rejected', 'target_not_found', null, null)
        , ('agent_b2_corrections', '', 'pik_rate', 'rejected', 'target_not_found', null, null)
        , ('row_corrections_by_context', 'c-4', 'issuer_name', 'deferred', 'field_not_held', null, null)
        , ('wrapper:relabelled_contexts', 'c-19', 'identifier', 'deferred', 'field_not_held', null, null)
        , ('wrapper:untagged_values', 'c-27', 'fair_value', 'applied', null, 'filed', '0.0')
        , ('wrapper:untagged_values', 'c-4', 'principal_amount', 'applied', null, 'filed', '500.0')
        , ('row_corrections_by_context', 'c-3', 'pik_rate', 'applied', null, 'reading_input', '3.0')
        , ('agent_investigate_rules', 'c-91', 'fair_value', 'applied', null, 'converted', '100.0')
        , ('agent_investigate_rules', 'c-91', 'principal_amount', 'applied', null, 'converted', '100.0')
        , ('agent_investigate_rules', 'c-91', 'principal_amount_currency', 'applied', null, 'companion', 'USD')
        , ('agent_investigate_rules', 'c-91', 'principal_amount_usd', 'applied', null, 'converted', '100.0')
        , ('agent_investigate_rules', 'c-91', 'cost', 'no_op', 'equal_to_normalised', null, '100.0')
        , ('agent_investigate_rules', 'c-91', 'bdc_dimensions_raw', 'deferred', 'field_not_held', null, null)
        , ('agent_investigate_rules', 'c-91', 'bdc_investment_identifier', 'deferred', 'field_not_held', null, null)
        , ('agent_investigate_rules', 'c-91', 'issuer_name', 'deferred', 'field_not_held', null, null)
        , ('agent_investigate_rules', 'c-91', 'source', 'deferred', 'field_not_held', null, null)
        , ('agent_investigate_rules', 'c-91', 'source_row_id', 'deferred', 'field_not_held', null, null)
    ) v(store, context_id, field, outcome, reason, applied_at_step, value_after)
)

, actual_outcome as (
    select
        c.store
        , coalesce(a.context_id, c.context_id, '') as context_id
        , c.field
        , a.outcome
        , a.reason
        , a.applied_at_step
        , a.value_after
    from {{ ref('stg_correction') }} c
    left join {{ ref('int_correction_application') }} a on a.correction_id = c.correction_id
    where c.cik in ('0000000001', '0000000002')
)

, expected_row as (
    select * from (values
          ('c-27', 'not_schedule', 3, 'correction_supplies_fair_value')
        , ('c-91', 'not_schedule', 1, 'correction_adds_row')
    ) v(context_id, role_filed, role_rule_filed, row_reason)
)

, actual_row as (
    select context_id, role_filed, role_rule_filed, row_reason
    from {{ ref('int_row_corrected') }}
    where cik = '0000000001' and row_reason <> 'filed'
)

, expected_value as (
    -- (context, field, value before corrections, corrected value, status, reason, set by a correction)
    select * from (values
          ('c-24', 'cost', 250.0, 240.0, 'corrected', 'correction_converted', true)
        , ('c-3', 'pik_rate', 2.0, 3.0, 'corrected', 'correction_reading_input', true)
        , ('c-3', 'interest_rate_cash', 7.0, 6.0, 'corrected', 'applied', true)
        , ('c-3', 'interest_rate', 9.0, 9.0, 'normalised', 'applied', false)
        , ('c-27', 'fair_value', null, 0.0, 'corrected', 'correction_filed', true)
        , ('c-4', 'principal_amount', null, 500.0, 'corrected', 'correction_filed', true)
        , ('c-4', 'principal_amount_usd', null, 500.0, 'corrected', 'derived_from_corrected_principal', true)
        , ('c-91', 'fair_value', null, 100.0, 'corrected', 'correction_converted', true)
        , ('c-91', 'principal_amount', null, 100.0, 'corrected', 'correction_converted', true)
    ) v(context_id, field, value_normalised, value, status, reason, has_correction)
)

, actual_value as (
    select context_id, field, value_normalised, value, status, reason, correction_id is not null as has_correction
    from {{ ref('int_field_corrected') }}
    where cik = '0000000001'
)

select 'correction outcome expected, not found or different' as problem, e.store || ' ' || e.context_id as context_id,
       e.field as detail
from expected_outcome e
anti join actual_outcome a
    on a.store = e.store and a.context_id = e.context_id and a.field = e.field
    and a.outcome is not distinct from e.outcome
    and a.reason is not distinct from e.reason
    and a.applied_at_step is not distinct from e.applied_at_step
    and (e.value_after is null
         or a.value_after = e.value_after
         or abs(try_cast(a.value_after as double) - try_cast(e.value_after as double)) < 0.000001)
union all
select 'correction outcome with no expectation', a.store || ' ' || a.context_id,
       a.field || ' ' || coalesce(a.outcome, 'no outcome') || ' ' || coalesce(a.reason, '')
from actual_outcome a
anti join expected_outcome e on e.store = a.store and e.context_id = a.context_id and e.field = a.field
union all
select 'promoted row expected, not found or different', e.context_id, e.row_reason
from expected_row e
anti join actual_row a
    on a.context_id = e.context_id and a.role_filed = e.role_filed and a.role_rule_filed = e.role_rule_filed
    and a.row_reason = e.row_reason
union all
select 'promoted row with no expectation', a.context_id, a.row_reason
from actual_row a
anti join expected_row e on e.context_id = a.context_id
union all
select 'corrected value expected, not found or different', e.context_id, e.field
from expected_value e
anti join actual_value a
    on a.context_id = e.context_id and a.field = e.field
    and ((a.value_normalised is null and e.value_normalised is null) or abs(a.value_normalised - e.value_normalised) < 0.000001)
    and ((a.value is null and e.value is null) or abs(a.value - e.value) < 0.000001)
    and a.status = e.status
    and a.reason = e.reason
    and a.has_correction = e.has_correction
