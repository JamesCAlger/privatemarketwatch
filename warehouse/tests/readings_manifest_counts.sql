-- The row counts the loader recorded equal the tables dbt reads. Fails on a missing or partial file.
with counted as (
    select 'reading_rule' as table_name, count(*) as table_rows from {{ ref('stg_reading_rule') }}
    union all
    select 'correction', count(*) from {{ ref('stg_correction') }}
    union all
    select 'not_loaded', count(*) from {{ ref('stg_reading_not_loaded') }}
    union all
    -- the loader's own table; stg_wrapper_drift hashes the files at build time and no longer reads it
    select 'wrapper_drift', count(*) from {{ source('readings', 'wrapper_drift') }}
    union all
    select 'rule_label_example', count(*) from {{ ref('stg_rule_label_example') }}
)
select m.table_name, m.manifest_rows, c.table_rows
from {{ ref('stg_readings_manifest') }} as m
left join counted as c using (table_name)
where c.table_rows is null or c.table_rows <> m.manifest_rows
