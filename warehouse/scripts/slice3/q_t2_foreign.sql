-- Slice 3 Task 2: fair value and cost read in a unit other than USD, with the printed text and the other amounts.
select r.cik, r.report_date, r.context_id, r.field, r.unit, r.value_filed, r.printed_text
    , cf.identifier_label
from int_field_read r
join int_context_feature cf on cf.accession = r.accession and cf.context_id = r.context_id
where r.status = 'read' and r.field in ('fair_value', 'cost') and r.unit <> 'iso4217:USD'
order by r.unit, r.cik, r.report_date, r.field
limit 60
