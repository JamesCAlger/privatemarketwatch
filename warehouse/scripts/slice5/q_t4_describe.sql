-- Slice 5 Task 4 diagnostic: columns of the models this task reads. Read-only.
select table_name, string_agg(column_name, ', ' order by ordinal_position) as cols
from information_schema.columns
where table_name in ('int_source_row', 'int_row_corrected', 'int_field_read', 'int_field_rule', 'int_rate_scale', 'int_rate_tag_cell', 'stg_reading_rule', 'int_correction_target', 'cmp_rate', 'stg_holdings')
group by 1 order by 1
