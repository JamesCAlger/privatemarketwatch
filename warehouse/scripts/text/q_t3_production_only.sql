-- Text slice R phase 3: published positions where production holds a value and the rule-read model none, by fund and
-- field, split by the read model's status for that field and by an explaining condition where one is measurable:
-- pik_rate held by this layer as pik_spread (same number); all_in_rate where this layer reads a PIK rate only (a PIK-only
-- coupon, production reads the coupon as the rate); spread where this layer reads a PIK spread only. Read-only.
with j as (
    select r.*, nullif(h.reference_rate_type, '') as p_ref, h.basis_spread as p_spread, h.interest_rate as p_rate
        , h.pik_rate as p_pik, lower(nullif(h.coupon_type, '')) as p_type
    from int_text_rate_read r
    join cmp_row_set s on s.accession = r.accession and s.context_id = r.context_id and s.basis = 'published'
        and s.side = 'both'
    join stg_holdings h on h.accession_number = s.accession and h.src_context_id = coalesce(s.production_context_id, s.context_id)
    where r.is_published
)
select cik, 'pik_rate' as field, pik_rate_status as status
    , case when pik_spread is not null and abs(pik_spread - p_pik) <= 0.005 then 'held here as pik_spread' else 'other' end
        as why, count(*) as positions
from j where pik_rate is null and p_pik is not null group by all
union all
select cik, 'all_in_rate', all_in_rate_status
    , case when pik_rate is not null and abs(pik_rate - p_rate) <= 0.005 then 'PIK-only coupon read here as PIK rate'
           when all_in_source is null and all_in_rate_status = 'not_printed' and reference_rate is not null
                then 'floating row, no all-in printed'
           else 'other' end, count(*)
from j where all_in_rate is null and p_rate is not null group by all
union all
select cik, 'spread', spread_status
    , case when pik_spread is not null and abs(pik_spread - p_spread) <= 0.005 then 'held here as pik_spread'
           when spread_status like 'constraint%' then 'dropped by constraint 1'
           else 'other' end, count(*)
from j where spread is null and p_spread is not null group by all
union all
select cik, 'reference_rate', reference_rate_status, 'reference rate not read', count(*)
from j where reference_rate is null and p_ref is not null group by all
order by 1, 2, 5 desc
