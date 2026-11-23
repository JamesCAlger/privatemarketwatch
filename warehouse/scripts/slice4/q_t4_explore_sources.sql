-- Slice 4 Task 4 exploration: open pairs (not equal, not both empty) per fund, field and outcome, with production's
-- per-field source column, the rate-related src_transforms tokens, corrected_fields naming the field, and this
-- layer's status and reason. Published and unpublished together (basis column).
with both_rows as (
    select c.basis, c.accession, c.context_id, c.cik, c.report_date
    from cmp_row_set c
    where c.side = 'both'
      and not exists (select 1 from cmp_excluded_quarter x where x.cik = c.cik and x.report_date = c.report_date)
)
, prod as (
    select accession_number as accession, src_context_id as context_id, interest_rate, interest_rate_cash, pik_rate,
        basis_spread, maturity_date, interest_rate_kind, interest_rate_source, basis_spread_source, pik_rate_source,
        maturity_date_source, src_transforms, corrected_fields, src_field_overrides, src_filled_fields
    from read_parquet('../data/output/private_markets_holdings.parquet')
    where source = 'bdc' and src_context_id is not null and src_context_id <> ''
)
, n as (select * from int_field_normalised)
, pairs as (
    select b.basis, b.cik, f.field,
        case f.field when 'maturity_date' then null else nv.value end as vn,
        case f.field when 'interest_rate' then p.interest_rate when 'interest_rate_cash' then p.interest_rate_cash
            when 'pik_rate' then p.pik_rate when 'spread' then p.basis_spread end as vp,
        nv.value_date as dn, p.maturity_date as dp, nv.status, nv.reason,
        case f.field when 'interest_rate' then p.interest_rate_source when 'interest_rate_cash' then p.interest_rate_source
            when 'pik_rate' then p.pik_rate_source when 'spread' then p.basis_spread_source
            else p.maturity_date_source end as psrc,
        array_to_string(list_sort(list_filter(string_split(coalesce(p.src_transforms, ''), ';'),
            x -> regexp_matches(x, 'rate|spread|pik|matur'))), ';') as ptr,
        regexp_matches(coalesce(p.corrected_fields, '') || ';' || coalesce(p.src_field_overrides, ''),
            'interest_rate|pik_rate|basis_spread|maturity') as pcorr
    from both_rows b
    cross join (values ('interest_rate'), ('interest_rate_cash'), ('pik_rate'), ('spread'), ('maturity_date')) f(field)
    join prod p on p.accession = b.accession and p.context_id = b.context_id
    left join n nv on nv.accession = b.accession and nv.context_id = b.context_id and nv.field = f.field
)
, o as (
    select *,
        case
            when field = 'maturity_date' then
                case when dn is null and dp is null then 'both_empty' when dn is null then 'new_empty'
                     when dp is null then 'production_empty' when dn = dp then 'equal' else 'differs' end
            when vn is null and vp is null then 'both_empty' when vn is null then 'new_empty'
            when vp is null then 'production_empty' when abs(vn - vp) <= 1e-9 then 'equal' else 'differs' end as outcome
    from pairs
)
select cik, field, outcome, status, reason, psrc, ptr, pcorr, count(*) as n
from o
where outcome not in ('equal', 'both_empty')
group by all
order by field, cik, outcome, n desc
