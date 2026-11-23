-- Slice 4 Task 4: per fund at 2026-03-31, published position rows on both sides that production classes as a loan
-- (asset_category LOAN; the warehouse has no loan class of its own), with an all-in rate here, with one in production,
-- with a spread here but no all-in rate here (the rows spec section 10 would later fill), and the same for production.
with r as (
    select c.cik, c.accession, c.context_id
        , any_value(c.value_new) filter (where c.field = 'interest_rate') as rate_new
        , any_value(c.value_production) filter (where c.field = 'interest_rate') as rate_prod
        , any_value(c.value_new) filter (where c.field = 'spread') as spread_new
        , any_value(c.value_production) filter (where c.field = 'spread') as spread_prod
    from cmp_rate c
    where c.basis = 'published' and c.report_date = date '2026-03-31'
    group by 1, 2, 3
)
select r.cik
    , count(*) as published_loans
    , count(*) filter (where rate_new is not null) as rate_here
    , count(*) filter (where rate_prod is not null) as rate_production
    , count(*) filter (where spread_new is not null and rate_new is null) as spread_no_rate_here
    , count(*) filter (where spread_prod is not null and rate_prod is null) as spread_no_rate_production
from r
join stg_holdings h on h.accession_number = r.accession and h.src_context_id = r.context_id
where h.asset_category = 'LOAN'
group by 1
order by 1
