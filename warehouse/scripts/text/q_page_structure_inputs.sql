-- 2026-11-26: what the filed layer holds for page structure (columns of the printed-row and placement tables). Read-only.
select table_name, string_agg(column_name || ':' || data_type, ', ' order by ordinal_position) as cols
from information_schema.columns
where table_name in ('stg_filed_document_row', 'stg_filed_fact_placement', 'stg_filed_table', 'stg_filed_document', 'stg_reading_rule')
   or table_name like 'stg_filed%'
group by 1 order by 1
