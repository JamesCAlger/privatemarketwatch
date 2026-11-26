-- Slice 5 Task 4 diagnostic: the rate corrections held deferred|rate_reading_not_rerun at BASE, by field, store and
-- fund, with withdrawals and the target role. Read-only.
select a.field_row, a.value_column, a.store, a.cik, a.target_role, a.is_withdrawal, count(*) as n
     , count(distinct a.correction_id) as corrections
from int_correction_application a
where a.reason = 'rate_reading_not_rerun' or (a.field_row in ('interest_rate','interest_rate_cash','pik_rate','spread','maturity_date') and a.outcome <> 'deferred')
group by all
order by 1, 2, 3, 4, 5, 6
