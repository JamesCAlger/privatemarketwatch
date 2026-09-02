{{ config(store_failures = true) }}
with grouped as (
    select *,
        count(*) over (
            partition by cik, accession_number, report_date,
                norm_issuer, norm_instrument, fv_key, principal_key, shares_key
        ) as group_size,
        concat_ws('|', cik, accession_number, cast(report_date as varchar),
                  norm_issuer, norm_instrument,
                  cast(cast(fv_key as bigint) as varchar),
                  cast(cast(principal_key as bigint) as varchar),
                  cast(cast(shares_key as bigint) as varchar)) as key_sig
    from {{ ref('stg_bdc_holdings') }}
)
select cik, entity_name, accession_number, report_date, source_row_id,
       issuer_name, instrument_description, fair_value,
       key_sig, group_size
from grouped
where group_size > 1
