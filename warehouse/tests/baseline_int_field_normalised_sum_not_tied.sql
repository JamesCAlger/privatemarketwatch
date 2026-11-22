-- Baseline (spec section 7, the sum check): per fund and report date, the published positions' normalised fair value
-- against the filed total investments (stg_fund_financials), on the published basis (cash rows in) and without the cash
-- rows. Both differences are listed, with the basis fact_fund_period would choose (step 1; owner ruling 2026-11-04,
-- check A04: without cash when the total with cash misses, the total without cash ties, and the cash rows equal the
-- filed cash equivalents within 0.5 pct of the filed investments). A fund-quarter does not tie when it ties on neither
-- basis (both differences above var reconcile_tolerance). Slice 3 Task 3 decision: the A04 cash test is not required,
-- because one fund publishes money-market rows that are only part of its filed cash-equivalents line (D13), so it ties
-- without cash but fails the A04 cash test. A published fair value that is not normalised counts as missing (and fails
-- its own test). Fund-quarters with no filed total are listed too (filed null). Ceiling int_field_normalised_sum_not_tied.
{{ config(severity='error', warn_if='>0', error_if='>' ~ var('baseline_max')['int_field_normalised_sum_not_tied']) }}
with published as (
    select
        s.cik
        , s.report_date
        , sum(n.value) as published_fair_value
        , coalesce(sum(n.value) filter (where s.is_cash), 0) as cash_fair_value
        , count(*) filter (where n.status <> 'normalised') as fair_value_not_normalised
    from {{ ref('int_source_row') }} s
    join {{ ref('int_field_normalised') }} n
        on n.accession = s.accession and n.context_id = s.context_id and n.field = 'fair_value'
    where s.is_published
    group by 1, 2
)

, compared as (
    select
        p.*
        , f.investments_at_fair_value as filed_total
        , f.cash_equivalents_at_fair_value as cash_equivalents_filed
        , p.published_fair_value - f.investments_at_fair_value as difference
        , p.published_fair_value - p.cash_fair_value - f.investments_at_fair_value as difference_ex_cash
    from published p
    left join {{ ref('stg_fund_financials') }} f on f.cik = p.cik and f.report_date = p.report_date
)

, based as (
    select
        *
        , coalesce(
            cash_fair_value <> 0
            and abs(difference) > {{ var('reconcile_tolerance') }}
            and abs(difference_ex_cash) <= {{ var('reconcile_tolerance') }}
            and cash_equivalents_filed > 0
            and abs(cash_fair_value - cash_equivalents_filed) <= 0.005 * filed_total,
            false
          ) as filed_total_excludes_cash
    from compared
)

select
    cik
    , report_date
    , filed_total
    , published_fair_value
    , cash_fair_value
    , difference
    , difference_ex_cash
    , filed_total_excludes_cash
    , case when filed_total_excludes_cash then difference_ex_cash else difference end as difference_on_basis
    , fair_value_not_normalised
from based
where filed_total is null
   or (abs(difference) > {{ var('reconcile_tolerance') }} and abs(difference_ex_cash) > {{ var('reconcile_tolerance') }})
   or fair_value_not_normalised > 0
