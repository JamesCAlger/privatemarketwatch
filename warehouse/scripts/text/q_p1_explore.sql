-- Slice P, 2026-11-26: inputs' columns, and the published positions with no placement of their fair-value fact by
-- fund and quarter. Read-only.
select 'col' as k, table_name as a, column_name as b, data_type as c, null::bigint as n
from information_schema.columns
where table_name in ('stg_filed_document_row', 'stg_filed_fact_placement', 'int_field_read')
union all
select 'not_placed', s.cik, cast(s.report_date as varchar), s.accession, count(*)
from int_source_row s
left join int_field_read fr on fr.accession = s.accession and fr.context_id = s.context_id and fr.field = 'fair_value'
where s.role = 'position' and s.is_published
  and not exists (
    select 1 from stg_filed_fact_placement pl
    where pl.accession = fr.accession and pl.fact_id = fr.fact_id and pl.row_index is not null and not pl.in_hidden)
group by all
order by 1, 2, 3
