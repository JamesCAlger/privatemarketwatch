-- Slice R fix round 1 (2026-11-26): shape units per fund (after the spacing and case key), the largest column, and
-- bundle counts and sizes per fund and state. Read-only.
select 'shapes' as block, cik, null as state, count(*) as n, max(per_unit) as max_in_column, null::bigint as chars
from (select cik, unit_key, count(*) over (partition by unit_key) as per_unit from int_text_shape_unit) group by 1, 2, 3
union all
select 'bundles', cik, worklist_state, count(*), max(bundle_chars), sum(bundle_chars) from int_text_bundle group by 1, 2, 3
order by 1 desc, 2, 3
