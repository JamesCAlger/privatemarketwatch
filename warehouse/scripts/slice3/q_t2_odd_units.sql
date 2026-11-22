-- Slice 3 Task 2: principal read in a currency that looks out of place, and negative amounts.
select r.cik, r.report_date, r.context_id, r.field, r.unit, r.value_filed, r.printed_text, left(cf.identifier_label, 90) as label
from int_field_read r
join int_context_feature cf on cf.accession = r.accession and cf.context_id = r.context_id
where r.status = 'read' and r.unit in ('iso4217:KPW', 'iso4217:AFN', 'iso4217:RSD', 'iso4217:KRW')
order by 1, 2, 4
