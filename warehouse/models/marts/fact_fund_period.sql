-- One row per fund and report date that has positions, or has a financials row at a report date
-- that appears in the holdings in scope. A fund-quarter with financials and no positions is kept
-- on purpose: a build that lost a whole quarter of holdings must show here.
-- The filed total comes from the SEC companyfacts record via the pipeline's financials file. It
-- covers the fund's own schedule only, so it is compared with the published basis (rows from a
-- JV's own schedule are excluded).
with published as (
    select
        cik,
        report_date,
        min(accession_number)                                   as accession_number,
        sum(case when is_published then fair_value else 0 end)  as published_fair_value
    from {{ ref('fact_observation') }}
    group by 1, 2
),
filed as (
    select *
    from {{ ref('stg_fund_financials') }}
    where report_date in (select report_date from {{ ref('dim_date') }})
)
select
    coalesce(p.cik, f.cik)                                               as cik,
    coalesce(p.report_date, f.report_date)                               as report_date,
    p.accession_number,
    p.cik is not null                                                    as has_positions,
    f.net_assets,
    f.total_assets,
    f.investments_at_fair_value                                          as investments_at_fair_value_filed,
    coalesce(p.published_fair_value, 0)                                  as published_fair_value,
    coalesce(p.published_fair_value, 0) - f.investments_at_fair_value    as difference_to_filed
from published p
full outer join filed f
       on f.cik = p.cik and f.report_date = p.report_date