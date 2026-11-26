-- Slice 5 Task 3 proof: the sum check on both bases, per fund-quarter that does not tie on either (normalised: the
-- stored test failures of baseline_int_field_normalised_sum_not_tied; corrected: baseline_int_field_corrected_sum_not_tied).
select coalesce(n.cik, c.cik) as cik, coalesce(n.report_date, c.report_date) as report_date
    , n.filed_total, n.published_fair_value as normalised_fair_value, n.difference_on_basis as normalised_difference
    , c.published_fair_value as corrected_fair_value, c.difference_on_basis as corrected_difference
    , c.fair_value_not_normalised as corrected_not_normalised
from main_dbt_test__audit.baseline_int_field_normalised_sum_not_tied n
full join main_dbt_test__audit.baseline_int_field_corrected_sum_not_tied c on c.cik = n.cik and c.report_date = n.report_date
order by 1, 2
