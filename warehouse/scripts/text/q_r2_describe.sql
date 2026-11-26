-- Slice R phase 1: columns of the inputs used. Read-only.
select table_name, string_agg(column_name || ':' || data_type, ', ' order by ordinal_position) as cols
from information_schema.columns
where table_name in ('int_text_cell', 'stg_reading_rule', 'int_page_column', 'int_page_column_filing', 'stg_filed_fact_placement', 'stg_filed_fact', 'int_page_position', 'int_page_schedule', 'int_page_cell_column', 'int_text_reference_rate_read', 'concept_map', 'int_text_check_legend')
group by 1
