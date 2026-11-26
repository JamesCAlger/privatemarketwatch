-- Slice R fix round 1 (2026-11-26): rows per fund by cluster-input state (hypothesis basis: every position with a code),
-- and the largest usable group per fund. Read-only.
select cik, count(*) as rows, round(avg((state = 'pik_present')::int), 3) as share_pik
    , round(avg((state = 'inputs_missing')::int), 3) as share_missing, round(avg((state = 'usable')::int), 3) as share_usable
from int_text_measure_implied_base where basis = 'hypothesis' group by 1 order by 1
