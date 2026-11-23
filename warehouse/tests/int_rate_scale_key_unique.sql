-- Owner ruling B (2026-11-23): int_rate_scale has one row per (accession, context_id, field). Two scale rules for one
-- fund, filing and field would duplicate a row (tests/rate_scale_rule_selectors.sql also refuses them).
select accession, context_id, field, count(*) as n
from {{ ref('int_rate_scale') }}
group by 1, 2, 3
having count(*) > 1
