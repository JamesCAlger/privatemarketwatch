-- Fund name: the same source and rule as the website. The financials file's name at the fund's
-- latest quarter with total assets, with any "(CIK 0001234567)" suffix removed.
with latest_name as (
    select
        cik,
        arg_max(fund_name_raw, report_date) as fund_name_raw
    from {{ ref('stg_fund_financials') }}
    where total_assets > 0
    group by 1
)
select
    s.cik,
    trim(regexp_replace(regexp_replace(n.fund_name_raw, '\s*\(CIK\s+\d+\)\s*', ' ', 'g'), '\s+', ' ', 'g')) as fund_name,
    lower(replace(b.manager_brand, ' ', '_')) as adviser_id,
    u.vehicle_type,
    u.status,
    u.bdc_election_date,
    u.first_filing_date,
    c.cohort_status,
    true as is_v05
from {{ ref('stg_v05_scope') }} s
left join latest_name n                on n.cik = s.cik
left join {{ ref('manager_brand') }} b on b.cik = s.cik
left join {{ ref('stg_bdc_universe') }} u on u.cik = s.cik
left join {{ ref('stg_cohort') }} c    on c.cik = s.cik
