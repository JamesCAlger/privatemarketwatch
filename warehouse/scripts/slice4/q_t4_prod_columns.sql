-- Slice 4 Task 4: what production's second rate columns hold on the five funds (all rows of stg scope, bdc source).
-- interest_rate_reported against the filed tag, basis_spread_kind values, maturity_precision values, rate source
-- labels (identifier_text_override = a SOFR-reconciled spread override), src_filled_fields naming a rate field.
with p as (
    select h.*
    from read_parquet('../data/output/private_markets_holdings.parquet') h
    where h.source = 'bdc' and h.cik in (select cik from stg_v05_scope)
)
select 'basis_spread_kind' as what, coalesce(basis_spread_kind, '<null>') as value, count(*) as n from p group by all
union all
select 'maturity_precision', coalesce(maturity_precision, '<null>') || ' / date ' || (maturity_date is not null)::varchar, count(*) from p group by all
union all
select 'interest_rate_kind', coalesce(interest_rate_kind, '<null>'), count(*) from p group by all
union all
select 'reported_vs_rate', interest_rate_kind || ' reported ' || (interest_rate_reported is not null)::varchar
    || ' rate ' || (interest_rate is not null)::varchar
    || ' equal ' || coalesce((abs(interest_rate_reported - interest_rate) <= 1e-9)::varchar, '-'), count(*) from p group by all
union all
select 'rate_source', 'ir ' || coalesce(interest_rate_source, '') || ' | bs ' || coalesce(basis_spread_source, '')
    || ' | pik ' || coalesce(pik_rate_source, ''), count(*) from p group by all
union all
select 'filled_rate_fields', src_filled_fields, count(*) from p
where regexp_matches(coalesce(src_filled_fields, ''), 'rate|spread|matur') group by all
order by 1, 3 desc
