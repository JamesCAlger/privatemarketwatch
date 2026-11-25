-- Slice 5 Task 4: positions whose rate corrections fail (int_rate_corrected row_failure), with the interest_rate rows
-- before and after and the inputs. Read-only.
with f as (select distinct accession, context_id, row_failure from int_rate_corrected where run = 'corrected' and row_failure is not null)
select f.row_failure, r.run, r.accession, r.context_id, r.field, r.value, r.value_filed, r.action, r.status, r.reason, r.rate_kind
    , i.it_state, i.it_why, i.it_pct, i.pk_state, i.pk_pct, i.sp_state, i.ir_resolution, i.ir_action, i.it_correction_id, i.it_number
from f join int_rate_corrected r using (accession, context_id)
join int_rate_corrected_input i on i.run = r.run and i.accession = r.accession and i.context_id = r.context_id
where r.field in ('interest_rate', 'interest_rate_cash')
order by r.context_id, r.field, r.run
