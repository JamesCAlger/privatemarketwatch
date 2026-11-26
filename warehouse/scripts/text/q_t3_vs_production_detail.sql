-- Text slice R phase 3: the "differ" rows of q_t3_vs_production.sql (and new_only reference rates / rate types), grouped
-- by fund, field, the two values and the status; with one example cell text of the position's ruled cells. Read-only.
with j as (
    select r.*, nullif(h.reference_rate_type, '') as p_ref, h.basis_spread as p_spread, h.interest_rate as p_rate
        , h.pik_rate as p_pik, lower(nullif(h.coupon_type, '')) as p_type
    from int_text_rate_read r
    join cmp_row_set s on s.accession = r.accession and s.context_id = r.context_id and s.basis = 'published'
        and s.side = 'both'
    join stg_holdings h on h.accession_number = s.accession and h.src_context_id = coalesce(s.production_context_id, s.context_id)
    where r.is_published
)
, txt as (
    select accession, context_id, string_agg(distinct cell_text, ' | ') as cells
    from int_text_rate_read_cell group by 1, 2
)
, d as (
    select cik, 'reference_rate' as field, reference_rate as v_new, p_ref as v_prod, reference_rate_status as status
        , accession, context_id from j where reference_rate is not null and (p_ref is null or upper(reference_rate) <> upper(p_ref))
    union all select cik, 'spread', spread::varchar, p_spread::varchar, spread_status, accession, context_id from j
        where spread is not null and p_spread is not null and abs(spread - p_spread) > 0.005
    union all select cik, 'all_in_rate', all_in_rate::varchar, p_rate::varchar, all_in_rate_status, accession, context_id
        from j where all_in_rate is not null and p_rate is not null and abs(all_in_rate - p_rate) > 0.005
    union all select cik, 'rate_type', rate_type, p_type, null, accession, context_id from j
        where rate_type is not null and (p_type is null or rate_type <> p_type)
)
select d.cik, d.field, d.v_new, coalesce(d.v_prod, '(empty)') as v_prod, d.status, count(*) as positions
    , min(t.cells) as example_cells
from d left join txt t on t.accession = d.accession and t.context_id = d.context_id
group by 1, 2, 3, 4, 5
order by 1, 2, 6 desc
