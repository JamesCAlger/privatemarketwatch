-- Baseline guard (slice 2 Task 6, D15): rows a fund rule position_without_term_fact made positions that production has
-- no row for on the same basis. The rules were written to release only rows production publishes, so the ceiling is
-- 0. Rows in a quarter production lacks (cmp_excluded_quarter) count too: nothing shows they belong.
{{ config(severity='error', warn_if='>0', error_if='>' ~ var('baseline_max')['fund_rule_release_not_in_production']) }}
with prod as (
    select
        accession_number as accession
        , src_context_id as context_id
        , case when accounting_record_class = 'underlying_schedule' then false else true end as is_published
    from {{ ref('stg_holdings') }}
    where src_context_id is not null
)
select s.accession, s.context_id, s.cik, s.report_date, s.position_rule_id, s.is_published
from {{ ref('int_source_row') }} s
anti join prod p on p.accession = s.accession and p.context_id = s.context_id and p.is_published = s.is_published
where s.position_rule_id is not null
