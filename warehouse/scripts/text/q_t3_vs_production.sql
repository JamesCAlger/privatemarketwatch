-- Text slice R phase 3 (2026-11-26): MEASUREMENT ONLY. The rule-read fields of int_text_rate_read against production's
-- holdings on published positions both sides hold (cmp_row_set basis published, side both; production row joined as in
-- q_r5_vs_production.sql). Fields: reference_rate / reference_rate_type, spread / basis_spread, all_in_rate /
-- interest_rate, pik_rate / pik_rate, rate_type / coupon_type. Tolerance 0.005. Agreement with production is not
-- correctness. Read-only.
with j as (
    select r.*, nullif(h.reference_rate_type, '') as p_ref, h.basis_spread as p_spread, h.interest_rate as p_rate
        , h.pik_rate as p_pik, lower(nullif(h.coupon_type, '')) as p_type
    from int_text_rate_read r
    join cmp_row_set s on s.accession = r.accession and s.context_id = r.context_id and s.basis = 'published'
        and s.side = 'both'
    join stg_holdings h on h.accession_number = s.accession and h.src_context_id = coalesce(s.production_context_id, s.context_id)
    where r.is_published
)
, long as (
    select cik, 'reference_rate' as field, reference_rate_status as status, null::double as n_new, null::double as n_prod
        , reference_rate as t_new, p_ref as t_prod from j
    union all select cik, 'spread', spread_status, spread, p_spread, null, null from j
    union all select cik, 'all_in_rate', all_in_rate_status, all_in_rate, p_rate, null, null from j
    union all select cik, 'pik_rate', pik_rate_status, pik_rate, p_pik, null, null from j
    union all select cik, 'rate_type', null, null, null, rate_type, p_type from j
)
select cik, field
    , case
        when coalesce(n_new::varchar, t_new) is null and coalesce(n_prod::varchar, t_prod) is null then 'both_empty'
        when coalesce(n_new::varchar, t_new) is null then 'production_only'
        when coalesce(n_prod::varchar, t_prod) is null then 'new_only'
        when n_new is not null and abs(n_new - n_prod) <= 0.005 then 'same'
        when t_new is not null and upper(t_new) = upper(t_prod) then 'same'
        else 'differ'
      end as outcome
    , count(*) as positions
from long
group by all
order by 1, 2, 3
