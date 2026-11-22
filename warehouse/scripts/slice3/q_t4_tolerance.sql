-- Slice 3 Task 4: for shares and share of net assets on rows both sides have (both values present), how many pairs
-- differ by more than each candidate tolerance, per fund and basis. Picks the tolerance for cmp_amount.
with b as (
    select c.basis, c.accession, c.context_id, c.cik from cmp_row_set c where c.side = 'both'
)
, pairs as (
    select b.cik, b.basis, n.field, n.value as v_new
        , case n.field when 'shares' then h.shares_held else h.pct_of_net_assets end as v_prod
    from b
    join stg_holdings h on h.accession_number = b.accession and h.src_context_id = b.context_id
    join int_field_normalised n on n.accession = b.accession and n.context_id = b.context_id
    where n.field in ('shares', 'pct_of_net_assets')
)
select cik, basis, field, count(*) n_both
    , count(*) filter (where v_new <> v_prod) as ne_exact
    , count(*) filter (where abs(v_new - v_prod) > 1e-9) as gt_1e9
    , count(*) filter (where abs(v_new - v_prod) > 1e-6) as gt_1e6
    , count(*) filter (where abs(v_new - v_prod) > 0.005) as gt_0005
    , count(*) filter (where abs(v_new - v_prod) >= 1) as ge_1
    , max(abs(v_new - v_prod)) filter (where abs(v_new - v_prod) <= 1e-6) as max_small
from pairs where v_new is not null and v_prod is not null
group by all order by 1, 2, 3
