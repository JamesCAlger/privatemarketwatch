-- Slice 3 Task 3: rows the row modes would take on value size alone but that int_field_rule leaves alone, by reason:
-- no debt term fact (the stand-in for production's text test "is a loan"), or a label that names an equity instrument.
-- Per fund and mode. Shows how much the stand-in matters.
with r as (
    select cik, parameter as mode from stg_reading_rule
    where action = 'par_tagged_as_units' and parameter in ('rows_near_cost', 'rated_rows_near_cost', 'rows_within_twice_cost')
)
, sh as (select accession, context_id, cik, value_filed as sh from int_field_read where field = 'shares' and status = 'read' and value_filed > 0)
, pa as (select accession, context_id from int_field_read where field = 'principal_amount' and status = 'read' and not is_nil)
, co as (select accession, context_id, value_filed as cost from int_field_read where field = 'cost' and status = 'read')
, x as (
    select r.mode, sh.*, co.cost, cf.has_rate or cf.has_spread or cf.has_pik_rate or cf.has_maturity as has_debt_term
        , cf.has_rate or cf.has_spread as is_rated
        , regexp_matches(lower(coalesce(cf.identifier_label, '')), '(^|[^a-z])(units?|shares?|stock|membership|warrants?)([^a-z]|$)') as names_equity
        , case when r.mode = 'rows_within_twice_cost'
               then exists (select 1 from (values (1.0), (1000.0), (1000000.0)) k(k) where sh.sh * k.k between 0.5 * co.cost and 2.0 * co.cost)
               else exists (select 1 from (values (1.0), (1000.0), (1000000.0)) k(k) where sh.sh * k.k between 0.8 * co.cost and 1.25 * co.cost)
          end as in_band
    from sh
    join r on r.cik = sh.cik
    anti join pa on pa.accession = sh.accession and pa.context_id = sh.context_id
    join co on co.accession = sh.accession and co.context_id = sh.context_id and co.cost > 0
    join int_context_feature cf on cf.accession = sh.accession and cf.context_id = sh.context_id
)
select cik, mode
    , count(*) filter (where in_band) as in_band
    , count(*) filter (where in_band and not names_equity and (case when mode = 'rated_rows_near_cost' then is_rated else has_debt_term end)) as taken
    , count(*) filter (where in_band and names_equity) as left_names_equity
    , count(*) filter (where in_band and not names_equity and not (case when mode = 'rated_rows_near_cost' then is_rated else has_debt_term end)) as left_no_debt_term
from x group by all order by all
limit 20
