-- Slice 4 Task 2 (input to Task 3): per fund, how many position rows carry which rate tags. A tag is "carried" when
-- int_field_read has a fact for it (status read, nil included, or unresolved: status <> 'absent'). All position rows,
-- published or not, all report dates; published counts beside. Every row falls in exactly one combination.
with tags as (
    select r.cik, r.accession, r.context_id
        , bool_or(r.field = 'interest_rate_tag' and r.status <> 'absent') as ir
        , bool_or(r.field = 'interest_rate_cash_tag' and r.status <> 'absent') as cash
        , bool_or(r.field = 'pik_rate' and r.status <> 'absent') as pik
        , bool_or(r.field = 'spread' and r.status <> 'absent') as spread
    from int_field_read r
    group by 1, 2, 3
)

select t.cik
    , case
        when not t.ir and not t.cash and not t.pik then 'none'
        when t.ir and not t.cash and not t.pik then 'interest_rate_tag only'
        when not t.ir and t.cash and not t.pik then 'cash_tag only'
        when t.ir and t.cash and not t.pik then 'interest_rate_tag and cash_tag'
        when not t.ir and not t.cash and t.pik then 'pik only'
        when t.ir and not t.cash and t.pik then 'pik with interest_rate_tag'
        when not t.ir and t.cash and t.pik then 'pik with cash_tag'
        else 'pik with both'
      end as combination
    , count(*) as positions
    , count(*) filter (where s.is_published) as published
    , count(*) filter (where t.spread) as with_spread
    , count(*) filter (where s.is_published and t.spread) as published_with_spread
from tags t
join int_source_row s on s.accession = t.accession and s.context_id = t.context_id
group by all
order by 1, 2
