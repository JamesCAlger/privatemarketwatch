{{ config(store_failures = true) }}
select cik, accession_number, report_date, source_row_id
from (
    select *,
        count(*) over (
            partition by cik, accession_number, report_date,
                norm_issuer, norm_instrument, fv_key, principal_key, shares_key
        ) as group_size
    from {{ ref('bdc_dim_deduped') }}
)
where group_size > 1
