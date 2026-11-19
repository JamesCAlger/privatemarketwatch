-- Baseline guard (slice 2 Task 6, fix round 1): positions at rule 7 or 9 whose only term fact comes from a fund concept
-- rule, that production has no row for on the same basis, in the compared quarters (macro concept_release_unmatched).
-- Sibling of baseline_fund_rule_release_not_in_production.sql (label rules). Ceiling 0.
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
{{ concept_release_unmatched('rows_in', 'prod', 'excluded') }}
