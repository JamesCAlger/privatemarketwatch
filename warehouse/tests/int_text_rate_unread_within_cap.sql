-- Slice R phase 3 fix round 1 (2026-11-26): unread printed rate cells may not grow inside a group. Each group (column
-- unit, shape, status) of int_text_rate_read_cell rows the accepted rules leave unread has a recorded cap on its
-- positions in seed text_rate_unread_cap (measured 2026-11-26; unit_key names no fund). Returns a group above its cap
-- or not in the seed. The listing with counts is tests/baseline_int_text_rate_unread.sql.
with g as (
    select unit_key, shape, status, count(distinct accession || '|' || context_id) as positions
    from {{ ref('int_text_rate_read_cell') }}
    where status not in ('read', 'no_value')
    group by 1, 2, 3
)
select g.unit_key, g.shape, g.status, g.positions, c.max_positions
from g
left join {{ ref('text_rate_unread_cap') }} c on c.unit_key = g.unit_key and c.shape = g.shape and c.status = g.status
where c.max_positions is null or g.positions > c.max_positions
