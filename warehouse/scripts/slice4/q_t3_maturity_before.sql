-- Slice 4 Task 3: maturity dates before the report date (listed, not changed).
select n.cik, n.report_date, n.accession, n.context_id, n.value_date, s.is_published, c.identifier_label
from int_field_normalised n
join int_source_row s on s.accession = n.accession and s.context_id = n.context_id
left join int_context_feature c on c.accession = n.accession and c.context_id = n.context_id
where n.field = 'maturity_date' and n.status = 'normalised' and n.value_date < n.report_date
order by 1, 2, 4
