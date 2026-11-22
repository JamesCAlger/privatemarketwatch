-- Every published position has a normalised fair value (ceiling 0; measured 0 in slice 3 Task 3). Lists the rows that
-- do not, with the status and reason.
select n.accession, n.context_id, n.cik, n.report_date, n.status, n.reason
from {{ ref('int_field_normalised') }} n
join {{ ref('int_source_row') }} s on s.accession = n.accession and s.context_id = n.context_id
where s.is_published and n.field = 'fair_value' and n.status <> 'normalised'
