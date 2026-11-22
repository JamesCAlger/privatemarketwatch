-- cmp_amount: one row per (accession, context_id, field); seven fields for every row cmp_row_set has on both sides
-- (outside the excluded quarters); the outcome from its list; a cause from the closed list (with a detail) exactly on
-- the rows that are not equal and not both empty; numbers and currency in their own columns; is_published equal to
-- the basis being published.
with expected as (
    select c.accession, c.context_id
    from {{ ref('cmp_row_set') }} c
    where c.side = 'both'
      and not exists (
          select 1 from {{ ref('cmp_excluded_quarter') }} x where x.cik = c.cik and x.report_date = c.report_date
      )
)

select accession, context_id, field, 'duplicate key' as problem
from {{ ref('cmp_amount') }}
group by 1, 2, 3
having count(*) > 1
union all
select e.accession, e.context_id, null, 'row on both sides without seven fields'
from expected e
left join {{ ref('cmp_amount') }} a on a.accession = e.accession and a.context_id = e.context_id
group by 1, 2
having count(distinct a.field) <> 7
union all
select a.accession, a.context_id, a.field, 'row not on both sides of cmp_row_set'
from {{ ref('cmp_amount') }} a
anti join expected e on e.accession = a.accession and e.context_id = a.context_id
union all
select accession, context_id, field, 'unknown field or outcome'
from {{ ref('cmp_amount') }}
where field not in ('fair_value', 'cost', 'principal_amount', 'principal_amount_currency', 'principal_amount_usd',
                    'shares', 'pct_of_net_assets')
   or outcome is null
   or outcome not in ('equal', 'differs', 'new_empty', 'production_empty', 'both_empty')
union all
select accession, context_id, field, 'cause on an equal or both-empty row'
from {{ ref('cmp_amount') }}
where outcome in ('equal', 'both_empty') and (cause is not null or cause_detail is not null)
union all
select accession, context_id, field, 'open row without a cause from the list'
from {{ ref('cmp_amount') }}
where outcome in ('differs', 'new_empty', 'production_empty')
  and (cause is null or cause_detail is null
       or cause not in ('old_wrong', 'new_wrong', 'convention', 'needs_correction', 'needs_store_not_loaded',
                        'production_stale', 'owner_review', 'not_yet_explained'))
union all
select accession, context_id, field, 'number and currency columns mixed'
from {{ ref('cmp_amount') }}
where (field = 'principal_amount_currency' and (value_new is not null or value_production is not null))
   or (field <> 'principal_amount_currency' and (currency_new is not null or currency_production is not null))
union all
select accession, context_id, field, 'is_published disagrees with basis'
from {{ ref('cmp_amount') }}
where is_published is distinct from (basis = 'published')
