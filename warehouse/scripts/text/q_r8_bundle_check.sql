-- Slice R fix round 2 (2026-11-26): bundle sizes, legend entries left outside each column's dates, and the legs of one
-- parts-stating shape ("Cash plus" wording). Read-only.
select 'size' as block, cik as k, count(*)::varchar as v1, sum(bundle_chars)::varchar as v2
    , sum((bundle_json::json ->> 'legend_entries_outside')::int)::varchar as v3
from int_text_bundle group by 1, 2
union all
select 'legs', left(unit_key, 6), (s ->> 'shape'), (s -> 'legs')::varchar, null
from (select unit_key, unnest(from_json(bundle_json::json -> 'shapes', '["json"]')) as s from int_text_bundle)
where (s ->> 'shape') like 'S+%Cash plus%PIK, #% Floor'
order by 1 desc, 2
