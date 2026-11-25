-- Slice 5 Task 4: published rate rows of int_field_corrected a correction changed (the count of the generic test
-- baseline_corrected_amount_changed), per field, status and reason. Read-only.
select f.field, f.status, f.reason, count(*) as n
from int_field_corrected f
join int_row_corrected r using (accession, context_id)
where r.is_published and f.field in ('interest_rate', 'interest_rate_cash', 'pik_rate', 'spread', 'maturity_date')
  and (f.value is distinct from f.value_normalised or f.status in ('corrected', 'withdrawn')
       or f.value_date is distinct from f.value_date_normalised or f.rate_kind is distinct from f.rate_kind_normalised)
group by rollup (f.field, f.status, f.reason)
order by 1, 2, 3
