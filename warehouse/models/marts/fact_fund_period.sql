-- One row per fund and report date that has positions, or has a financials row at a report date
-- that appears in the holdings in scope. A fund-quarter with financials and no positions is kept
-- on purpose: a build that lost a whole quarter of holdings must show here.
-- The filed total comes from the SEC companyfacts record via the pipeline's financials file. It
-- covers the fund's own schedule only, so it is compared with the published basis (rows from a
-- JV's own schedule are excluded).
--
-- Cash rows (is_cash) are published and counted in published_fair_value. Some funds' filed
-- investments line leaves them out. filed_total_excludes_cash follows the evidence half of the
-- owner's ruling of 2026-11-04 (check A04 in pipeline/oracle_checks.py): the total with cash rows
-- misses the filed line, the total without them ties, and the cash rows equal the filed
-- cash-equivalents figure within 0.5 pct of the investments line. The other half of the ruling, a
-- wrapper that declares the basis, is not read here: none of the five funds in scope declares one.
with published as (
    select
        cik,
        report_date,
        min(accession_number)                                               as accession_number,
        sum(case when is_published then fair_value else 0 end)              as published_fair_value,
        sum(case when is_published and is_cash then fair_value else 0 end)  as cash_fair_value
    from {{ ref('fact_observation') }}
    group by 1, 2
),
filed as (
    select *
    from {{ ref('stg_fund_financials') }}
    where report_date in (select report_date from {{ ref('dim_date') }})
),
joined as (
    select
        coalesce(p.cik, f.cik)                                               as cik,
        coalesce(p.report_date, f.report_date)                               as report_date,
        p.accession_number,
        p.cik is not null                                                    as has_positions,
        f.net_assets,
        f.total_assets,
        f.investments_at_fair_value                                          as investments_at_fair_value_filed,
        f.cash_equivalents_at_fair_value                                     as cash_equivalents_filed,
        coalesce(p.published_fair_value, 0)                                  as published_fair_value,
        coalesce(p.cash_fair_value, 0)                                       as cash_fair_value,
        coalesce(p.published_fair_value, 0) - coalesce(p.cash_fair_value, 0) as published_fair_value_ex_cash
    from published p
    full outer join filed f
           on f.cik = p.cik and f.report_date = p.report_date
),
compared as (
    select
        *,
        published_fair_value - investments_at_fair_value_filed               as difference_to_filed,
        published_fair_value_ex_cash - investments_at_fair_value_filed       as difference_to_filed_ex_cash
    from joined
),
based as (
    select
        *,
        coalesce(
            cash_fair_value <> 0
            and abs(difference_to_filed) > {{ var('reconcile_tolerance') }}
            and abs(difference_to_filed_ex_cash) <= {{ var('reconcile_tolerance') }}
            and cash_equivalents_filed > 0
            and abs(cash_fair_value - cash_equivalents_filed) <= 0.005 * investments_at_fair_value_filed,
            false
        )                                                                    as filed_total_excludes_cash
    from compared
)
select
    cik,
    report_date,
    accession_number,
    has_positions,
    net_assets,
    total_assets,
    investments_at_fair_value_filed,
    cash_equivalents_filed,
    published_fair_value,
    cash_fair_value,
    published_fair_value_ex_cash,
    difference_to_filed,
    difference_to_filed_ex_cash,
    filed_total_excludes_cash,
    case when filed_total_excludes_cash then difference_to_filed_ex_cash
         else difference_to_filed end                                        as difference_to_filed_on_basis
from based
