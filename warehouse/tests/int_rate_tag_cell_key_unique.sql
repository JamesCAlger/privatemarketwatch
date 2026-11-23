-- Controller ruling R1 (2026-11-23): int_rate_tag_cell has one row per (accession, context_id).
select accession, context_id, count(*) as n
from {{ ref('int_rate_tag_cell') }}
group by 1, 2
having count(*) > 1
