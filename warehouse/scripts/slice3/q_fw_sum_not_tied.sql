-- Slice 3 final fix wave F5: the fund-quarters the sum check lists today, from the stored failures of
-- baseline_int_field_normalised_sum_not_tied (read-only).
select cik || '|' || strftime(report_date, '%Y-%m-%d') as quarter_key, filed_total, difference_on_basis
from main_dbt_test__audit.baseline_int_field_normalised_sum_not_tied
order by 1
limit 100
