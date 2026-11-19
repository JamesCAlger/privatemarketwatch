-- Pins the SET of fund-quarters left out of the comparison (owner, 2026-11-19), not only their count: any quarter in
-- cmp_excluded_quarter that is not in var cmp_excluded_quarters_pinned (cik|report_date|accessions) fails, so one
-- quarter cannot leave the comparison while another re-enters. A pinned quarter that re-enters is fine.
with pinned as (
    select unnest([{% for q in var('cmp_excluded_quarters_pinned') %}'{{ q }}'{% if not loop.last %}, {% endif %}{% endfor %}]) as quarter_key
)
select e.cik, e.report_date, e.accessions
from {{ ref('cmp_excluded_quarter') }} e
anti join pinned p
    on p.quarter_key = coalesce(e.cik, '') || '|' || coalesce(strftime(e.report_date, '%Y-%m-%d'), '') || '|' || coalesce(e.accessions, '')
