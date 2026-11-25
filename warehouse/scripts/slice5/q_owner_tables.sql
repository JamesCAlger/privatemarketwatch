-- Owner questions 2026-11-25: filed-layer relation names. Read-only.
select table_name from information_schema.tables where table_name like 'stg_filed%' or table_name like 'stg_hold%' order by 1
