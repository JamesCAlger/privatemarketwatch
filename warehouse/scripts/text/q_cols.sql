-- 2026-11-26: column lists of the tables slice A reads. Read-only.
select table_name, string_agg(column_name, ', ' order by ordinal_position) as cols
from information_schema.columns
where table_name in ('int_rate_corrected', 'cmp_rate', 'int_field_corrected', 'stg_correction', 'int_correction_application', 'int_correction_screen', 'stg_production_holding', 'int_rate_normalised', 'int_source_row')
group by 1 order by 1
