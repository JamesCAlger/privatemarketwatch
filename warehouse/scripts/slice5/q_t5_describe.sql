-- Slice 5 Task 5: columns of the models the comparison reads. Read-only.
select table_name, string_agg(column_name, ', ' order by ordinal_position) as cols
from information_schema.columns
where table_name in ('int_row_corrected', 'int_field_corrected', 'int_correction_application', 'int_source_row',
                     'int_field_normalised', 'int_correction_target')
group by 1 order by 1
