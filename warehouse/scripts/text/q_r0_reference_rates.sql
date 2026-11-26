-- Slice R, 2026-11-26 (owner question): production's reference rate by fund on published rows, to size how much of
-- the "spread plus base rate" check a SOFR-only table covers. Production's values, not checked. Read-only.
select s.cik, coalesce(upper(h.reference_rate_type), '(none)') as ref, count(*) as n
    , round(100.0 * count(*) / sum(count(*)) over (partition by s.cik), 1) as pct
from cmp_row_set s
join stg_holdings h on h.accession_number = s.accession and h.src_context_id = coalesce(s.production_context_id, s.context_id)
where s.basis = 'published' and s.side = 'both'
group by 1, 2 qualify row_number() over (partition by s.cik order by count(*) desc) <= 6
order by 1, 3 desc
