-- The concept-release guard itself, on invented rows (macro concept_release_unmatched). Must be listed: n1, a published
-- position at rule 9 whose only term fact is a fund concept rule (cr1) and that production does not have; n2, the same
-- in a JV schedule where production has the context only on the published basis. Must not be listed: y1 (production
-- has it, same basis); s1 (standard term fact); c1 (cash); a1 (aggregate); k1 (rule 3, not_schedule); x1 (a quarter
-- production lacks). Returns a row for every expectation that does not hold.
with rows_in as (
    select * from (values
          ('A', 'n1', '1', date '2026-03-31', 'position', 9, false, true, 'cr1')
        , ('A', 'n2', '1', date '2026-03-31', 'position', 7, false, false, 'cr1')
        , ('A', 'y1', '1', date '2026-03-31', 'position', 9, false, true, 'cr1')
        , ('A', 's1', '1', date '2026-03-31', 'position', 9, false, true, 'standard')
        , ('A', 'c1', '1', date '2026-03-31', 'position', 9, true, true, 'cr1')
        , ('A', 'a1', '1', date '2026-03-31', 'aggregate', 4, false, false, 'cr1')
        , ('A', 'k1', '1', date '2026-03-31', 'not_schedule', 3, false, false, 'cr1')
        , ('B', 'x1', '1', date '2026-09-30', 'position', 9, false, true, 'cr1')
    ) v(accession, context_id, cik, report_date, role, role_rule, is_cash, is_published, term_fact_source)
)
, prod as (
    select * from (values
          ('A', 'y1', true)
        , ('A', 'n2', true)
    ) v(accession, context_id, is_published)
)
, excluded as (
    select * from (values ('1', date '2026-09-30')) v(cik, report_date)
)
, got as (
    {{ concept_release_unmatched('rows_in', 'prod', 'excluded') }}
)
, expected as (
    select * from (values ('n1'), ('n2')) v(context_id)
)
select 'missing' as problem, e.context_id from expected e anti join got g using (context_id)
union all
select 'unexpected', g.context_id from got g anti join expected e using (context_id)
