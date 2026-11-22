-- Slice 3 final fix wave: columns of stg_correction and stg_holdings (read-only).
select table_name, column_name, data_type
from information_schema.columns
where table_name in ('stg_correction')
order by table_name, ordinal_position
limit 80
