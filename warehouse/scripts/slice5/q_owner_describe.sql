-- Owner questions 2026-11-25: column names of the relations used in the answers. Read-only.
select table_name, string_agg(column_name, ', ' order by ordinal_position) as cols
from information_schema.columns
where table_name in ('stg_filed_fact_placement', 'stg_filed_document_row', 'cmp_amount', 'int_context_feature')
group by 1
