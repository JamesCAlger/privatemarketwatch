-- Releases in a fund-quarter production lacks (cmp_excluded_quarter) are not compared: there is nothing to compare
-- with (the macro concept_release_unmatched leaves them out). They are counted, by guard and fund-quarter, in
-- docs/baseline_roles_2026-11-19.md, "Releases not checked: quarters production lacks" (final fix wave F4; the sibling
-- guard baseline_fund_rule_release_not_in_production does the same).
-- Baseline guard (slice 2 Task 6, fix round 1): positions at rule 7 or 9 whose only term fact comes from a fund concept
-- rule, that production has no row for on the same basis, in the compared quarters (macro concept_release_unmatched).
-- Rows pinned by key in var concept_rule_release_pinned (accession|context_id) are left out (final fix wave F3); a pin
-- that no longer matches such a row fails tests/concept_rule_release_pin_live.sql. Ceiling 0.
{{ config(severity='error', warn_if='>0', error_if='>' ~ var('baseline_max')['concept_rule_release_not_in_production']) }}
with rows_in as (
    select s.accession, s.context_id, s.cik, s.report_date, s.role, s.role_rule, s.is_cash, s.is_published
        , cf.term_fact_source
    from {{ ref('int_source_row') }} s
    join {{ ref('int_context_feature') }} cf on cf.accession = s.accession and cf.context_id = s.context_id
)
, prod as (
    select
        accession_number as accession
        , src_context_id as context_id
        , accounting_record_class is distinct from 'underlying_schedule' as is_published
    from {{ ref('stg_holdings') }}
    where src_context_id is not null
)
, excluded as (
    select cik, report_date from {{ ref('cmp_excluded_quarter') }}
)
, unmatched as (
    {{ concept_release_unmatched('rows_in', 'prod', 'excluded') }}
)
, pinned as (
    select unnest([{% for k in var('concept_rule_release_pinned', []) %}'{{ k }}'{% if not loop.last %}, {% endif %}{% endfor %}]::varchar[]) as release_key
)
select u.*
from unmatched u
where u.accession || '|' || u.context_id not in (select release_key from pinned)
