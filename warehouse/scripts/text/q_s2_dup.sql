-- Slice R phase 2: a field read twice from one cell. Read-only.
select r.accession, r.context_id, r.unit_key, r.field, r.cell_text, r.shape, list(r.role order by number_index) roles, list(r.value order by number_index) vals
from int_text_rate_proposed r
join (select accession, context_id, unit_key, field from int_text_rate_proposed where status='read' group by all having count(*)>1) d using (accession, context_id, unit_key, field)
group by all
