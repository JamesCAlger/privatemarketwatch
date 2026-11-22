-- Slice 3 Task 3 fix round 1, item 4: rows where a slice 3 rule could apply but a feature it needs is null.
-- par modes: label null (all modes but whole_filing) or cost not read (band modes), on a candidate row the rule's other
-- tests let through. bracketed_unsigned: fair value or cost in a listed filing with no printed placement.
with sh as (select accession, context_id, cik, value_filed from int_field_read where field = 'shares' and status = 'read' and value_filed > 0)
, pa as (select accession, context_id from int_field_read where field = 'principal_amount' and status = 'read' and not is_nil)
, co as (select accession, context_id, value_filed from int_field_read where field = 'cost' and status = 'read' and not is_nil)
, cand as (
    select sh.*, co.value_filed as cost, cf.identifier_label
        , cf.has_rate or cf.has_spread or cf.has_pik_rate or cf.has_maturity as has_debt_term
        , cf.has_rate or cf.has_spread as is_rated
    from sh
    anti join pa on pa.accession = sh.accession and pa.context_id = sh.context_id
    left join co on co.accession = sh.accession and co.context_id = sh.context_id
    join int_context_feature cf on cf.accession = sh.accession and cf.context_id = sh.context_id
)
, par as (
    select r.cik, r.parameter as mode
        , count(*) filter (where c.identifier_label is null) as label_null
        , count(*) filter (where c.cost is null and r.parameter in ('rows_near_cost', 'rated_rows_near_cost', 'rows_within_twice_cost')) as cost_null
    from stg_reading_rule r
    join cand c on c.cik = r.cik and (r.sel_accession is null or r.sel_accession = c.accession)
    where r.action = 'par_tagged_as_units'
      and case r.parameter
            when 'rated_rows_near_cost' then c.is_rated
            when 'listed_rows_without_instrument' then not c.has_debt_term
                 and c.accession in (select sel_accession from stg_reading_rule w where w.cik = r.cik and w.parameter = 'whole_filing')
            else c.has_debt_term end
    group by 1, 2
)
, sign as (
    select r.cik, 'bracketed_unsigned' as mode, count(*) filter (where pl.fact_id is null) as no_placement, 0 as cost_null
    from stg_reading_rule r
    join int_field_read f on f.cik = r.cik and f.accession = r.sel_accession
    left join stg_filed_fact_placement pl on pl.accession = f.accession and pl.fact_id = f.fact_id
    where r.action = 'bracketed_unsigned' and f.field in ('fair_value', 'cost') and f.status = 'read' and f.value_filed <> 0
    group by 1, 2
)
select * from par union all select * from sign order by 1, 2
limit 50
