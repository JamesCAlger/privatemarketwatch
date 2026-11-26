-- Slice R phase 2: key checks on the proposed read. Read-only.
select 'dup_key' k, count(*) from (select accession, context_id, unit_key, number_index from int_text_rate_proposed group by all having count(*)>1)
union all select 'dup_field_read', count(*) from (select accession, context_id, unit_key, field from int_text_rate_proposed where status='read' group by all having count(*)>1)
