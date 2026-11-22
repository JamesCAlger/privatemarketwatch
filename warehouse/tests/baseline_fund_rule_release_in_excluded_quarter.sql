-- Baseline (slice 3 Task 1, item c): rows a fund rule position_without_term_fact made positions in a fund-quarter
-- production lacks (cmp_excluded_quarter). The guard baseline_fund_rule_release_not_in_production skips those quarters,
-- because there is no production side to compare with; this test counts them instead, so a new release there is seen.
-- Measured 2026-11-22: 0 (Ares, Blue Owl and Apollo at 2026-09-30). Ceiling in dbt_project.yml.
{{ config(severity='error', warn_if='>0', error_if='>' ~ var('baseline_max')['fund_rule_release_in_excluded_quarter']) }}
select s.accession, s.context_id, s.cik, s.report_date, s.position_rule_id, s.is_published
from {{ ref('int_source_row') }} s
join {{ ref('cmp_excluded_quarter') }} x on x.cik = s.cik and x.report_date = s.report_date
where s.position_rule_id is not null
