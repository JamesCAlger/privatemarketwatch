select
    lpad(cik, 10, '0')                                   as cik,
    try_cast(report_date as date)                        as report_date,
    entity_name                                          as fund_name_raw,
    try_cast(total_assets as double)                     as total_assets,
    try_cast(net_assets as double)                       as net_assets,
    try_cast(investments_at_fair_value as double)        as investments_at_fair_value
from {{ source('pipeline', 'fund_financials') }}
where lpad(cik, 10, '0') in (select cik from {{ ref('stg_v05_scope') }})
