-- Slice 4 Task 1, item d: the rows of cmp_amount with cause detail correction_loaded_value_not_matched, any basis and
-- field. Read-only.
select basis, cik, report_date, accession, context_id, field, value_new, value_production, outcome, cause, cause_detail
from cmp_amount
where cause_detail = 'correction_loaded_value_not_matched'
order by all
