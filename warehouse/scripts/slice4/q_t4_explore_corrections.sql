-- Slice 4 Task 4 exploration: for open rate pairs (not equal, not both empty; maturity left out), what production's
-- corrected_fields and src_field_overrides say about rate fields, whether a loaded correction (stg_correction) names a
-- rate field on the row, production's asset_category and interest_rate_kind.
with both_rows as (
    select c.basis, c.accession, c.context_id, c.cik, c.report_date
    from cmp_row_set c
    where c.side = 'both'
      and not exists (select 1 from cmp_excluded_quarter x where x.cik = c.cik and x.report_date = c.report_date)
)
, prod as (
    select accession_number as accession, src_context_id as context_id, interest_rate, interest_rate_cash, pik_rate,
        basis_spread, interest_rate_kind, asset_category, bdc_investment_identifier,
        list_sort(list_filter(string_split(coalesce(corrected_fields, ''), ';'),
            x -> regexp_matches(x, 'rate|spread|matur|kind'))) as corr_rate,
        src_field_overrides
    from read_parquet('../data/output/private_markets_holdings.parquet')
    where source = 'bdc' and src_context_id is not null and src_context_id <> ''
)
, loaded as (
    select o.accession, o.context_id, list_sort(list_distinct(list(c.field))) as loaded_fields
    from both_rows o
    join prod p on p.accession = o.accession and p.context_id = o.context_id
    join stg_correction c on c.kind = 'value' and c.accession = o.accession
        and (c.context_id = o.context_id or (c.context_id is null and c.identifier = p.bdc_investment_identifier))
    where regexp_matches(c.field, 'rate|spread|matur|kind')
    group by 1, 2
)
, n as (select * from int_field_normalised)
, pairs as (
    select b.basis, b.cik, f.field, nv.value as vn,
        case f.field when 'interest_rate' then p.interest_rate when 'interest_rate_cash' then p.interest_rate_cash
            when 'pik_rate' then p.pik_rate when 'spread' then p.basis_spread end as vp,
        nv.status, nv.reason, p.corr_rate, p.src_field_overrides, l.loaded_fields, p.asset_category, p.interest_rate_kind
    from both_rows b
    cross join (values ('interest_rate'), ('interest_rate_cash'), ('pik_rate'), ('spread')) f(field)
    join prod p on p.accession = b.accession and p.context_id = b.context_id
    left join n nv on nv.accession = b.accession and nv.context_id = b.context_id and nv.field = f.field
    left join loaded l on l.accession = b.accession and l.context_id = b.context_id
)
select cik, field,
    case when vn is null and vp is null then 'both_empty' when vn is null then 'new_empty'
         when vp is null then 'production_empty' when abs(vn - vp) <= 1e-9 then 'equal' else 'differs' end as outcome,
    reason, array_to_string(corr_rate, ';') as corr_rate, nullif(src_field_overrides, '') as ovr,
    array_to_string(loaded_fields, ';') as loaded, asset_category, interest_rate_kind, count(*) as n
from pairs
where not (vn is null and vp is null) and not coalesce(abs(vn - vp) <= 1e-9, false)
  and (len(corr_rate) > 0 or loaded_fields is not null or nullif(src_field_overrides, '') is not null
       or (field = 'interest_rate' and cik = '0001287750'))
group by all
order by field, cik, outcome, n desc
