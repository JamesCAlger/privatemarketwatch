-- Text slice R phase 3: published positions the rules read as FIXED rate, and how production holds them (spread,
-- reference rate, coupon type, rate). Does production hold the fixed rate as a spread? Read-only.
with j as (
    select r.cik, r.all_in_rate, r.all_in_rate_grade, h.basis_spread, nullif(h.reference_rate_type, '') as p_ref
        , lower(nullif(h.coupon_type, '')) as p_type, h.interest_rate as p_rate
    from int_text_rate_read r
    join cmp_row_set s on s.accession = r.accession and s.context_id = r.context_id and s.basis = 'published'
        and s.side = 'both'
    join stg_holdings h on h.accession_number = s.accession and h.src_context_id = coalesce(s.production_context_id, s.context_id)
    where r.is_published and r.rate_type = 'fixed'
)
select cik, all_in_rate_grade
    , case when basis_spread is null then 'no spread'
           when abs(basis_spread - all_in_rate) <= 0.005 then 'spread = the fixed rate' else 'other spread' end as prod_spread
    , coalesce(p_ref, '(none)') as prod_reference_rate, coalesce(p_type, '(none)') as prod_coupon_type
    , case when p_rate is null then 'no rate' when abs(p_rate - all_in_rate) <= 0.005 then 'rate = fixed' else 'other rate' end
        as prod_rate
    , count(*) as positions
from j
group by all
order by 1, 7 desc
