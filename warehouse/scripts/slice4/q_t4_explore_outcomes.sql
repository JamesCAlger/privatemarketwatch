-- Slice 4 Task 4 exploration: outcome counts per fund, basis and field, this layer against production, before
-- cmp_rate exists. Tolerance 1e-9 percentage points for the rates.
with both_rows as (
    select c.basis, c.accession, c.context_id, c.cik, c.report_date
    from cmp_row_set c
    where c.side = 'both'
      and not exists (select 1 from cmp_excluded_quarter x where x.cik = c.cik and x.report_date = c.report_date)
)
, prod as (
    select accession_number as accession, src_context_id as context_id, interest_rate, interest_rate_cash, pik_rate,
        basis_spread, maturity_date, interest_rate_kind
    from stg_holdings where src_context_id is not null
)
, n as (select * from int_field_normalised)
, pairs as (
    select b.basis, b.cik, f.field,
        case f.field when 'maturity_date' then null else nv.value end as vn,
        case f.field when 'interest_rate' then p.interest_rate when 'interest_rate_cash' then p.interest_rate_cash
            when 'pik_rate' then p.pik_rate when 'spread' then p.basis_spread end as vp,
        nv.value_date as dn, p.maturity_date as dp
    from both_rows b
    cross join (values ('interest_rate'), ('interest_rate_cash'), ('pik_rate'), ('spread'), ('maturity_date')) f(field)
    join prod p on p.accession = b.accession and p.context_id = b.context_id
    left join n nv on nv.accession = b.accession and nv.context_id = b.context_id and nv.field = f.field
)
select basis, cik, field,
    case
        when field = 'maturity_date' then
            case when dn is null and dp is null then 'both_empty' when dn is null then 'new_empty'
                 when dp is null then 'production_empty' when dn = dp then 'equal' else 'differs' end
        when vn is null and vp is null then 'both_empty' when vn is null then 'new_empty'
        when vp is null then 'production_empty' when abs(vn - vp) <= 1e-9 then 'equal' else 'differs' end as outcome,
    count(*) as n,
    max(case when field <> 'maturity_date' and vn is not null and vp is not null and abs(vn - vp) <= 1e-6 then abs(vn - vp) end) as max_small_diff
from pairs
group by all
order by basis, cik, field, outcome
