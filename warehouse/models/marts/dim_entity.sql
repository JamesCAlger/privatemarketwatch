select
    h.entity_id,
    l.canonical_name,
    l.alias_count,
    min(h.report_date) as first_seen_date,
    max(h.report_date) as last_seen_date
from {{ ref('stg_holdings') }} h
left join {{ ref('stg_entity_lookup') }} l on l.entity_id = h.entity_id
group by 1, 2, 3
