-- Slice 5 Task 3: pins the SET of fund-quarters the corrected-basis sum check lists (macro sum_not_tied_rows,
-- corrected=true), as tests/int_field_normalised_sum_not_tied_set.sql does for the normalised basis: a fund-quarter
-- that does not tie and is not in var sum_not_tied_corrected_pinned (cik|report_date) fails. The list may shrink freely.
with not_tied as (
    {{ sum_not_tied_rows(corrected=true) }}
)

, pinned as (
    select unnest([{% for q in var('sum_not_tied_corrected_pinned') %}'{{ q }}'{% if not loop.last %}, {% endif %}{% endfor %}]::varchar[]) as quarter_key
)

select n.cik, n.report_date, n.filed_total, n.published_fair_value, n.difference_on_basis
from not_tied n
anti join pinned p on p.quarter_key = n.cik || '|' || strftime(n.report_date, '%Y-%m-%d')
