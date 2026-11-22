-- Slice 3 Task 2: every published position has its fair value read, with a number (measured 2026-11-22: 0 rows
-- fail, so this is a plain test, ceiling 0).
select f.accession, f.context_id, f.cik, f.report_date, f.status, f.reason, f.is_nil
from {{ ref('int_field_read') }} f
join {{ ref('int_source_row') }} r on r.accession = f.accession and r.context_id = f.context_id
where r.is_published and f.field = 'fair_value' and (f.status <> 'read' or f.value_filed is null)
