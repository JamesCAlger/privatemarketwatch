-- Final fix wave F5: pins the SET of fund-quarters the sum check lists (macro sum_not_tied_rows), not only their count:
-- any fund-quarter that does not tie and is not in var sum_not_tied_pinned (cik|report_date) fails, so one quarter
-- cannot start missing its filed total while another starts tying. A pinned quarter that starts tying is fine (the list
-- may shrink freely). The count ceiling stays in tests/baseline_int_field_normalised_sum_not_tied.sql.
with not_tied as (
    {{ sum_not_tied_rows() }}
)

, pinned as (
    select unnest([{% for q in var('sum_not_tied_pinned') %}'{{ q }}'{% if not loop.last %}, {% endif %}{% endfor %}]::varchar[]) as quarter_key
)

select n.cik, n.report_date, n.filed_total, n.published_fair_value, n.difference_on_basis
from not_tied n
anti join pinned p on p.quarter_key = n.cik || '|' || strftime(n.report_date, '%Y-%m-%d')
