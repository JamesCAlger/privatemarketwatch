-- Slice R phase 1: columns of the inputs used. Read-only.
select table_name, string_agg(column_name || ':' || data_type, ', ' order by ordinal_position) as cols
from information_schema.columns
where table_name in ('int_field_normalised')
group by 1
