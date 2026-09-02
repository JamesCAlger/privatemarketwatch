with ranked as (
    select *,
        row_number() over (
            partition by cik, accession_number, report_date,
                norm_issuer, norm_instrument, fv_key, principal_key, shares_key
            order by
                length(coalesce(cast(issuer_name as varchar), '')),
                coalesce(cast(issuer_name as varchar), ''),
                coalesce(cast(bdc_investment_identifier as varchar), ''),
                coalesce(cast(accession_number as varchar), ''),
                coalesce(cast(src_context_id as varchar), '')
        ) as _dim_rank
    from {{ ref('stg_bdc_holdings') }}
)
select * exclude (_dim_rank)
from ranked
where _dim_rank = 1
