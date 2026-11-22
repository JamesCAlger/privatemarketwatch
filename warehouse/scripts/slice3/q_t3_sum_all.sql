-- Slice 3 Task 3: the sum check for every fund-quarter, generated from tests/baseline_int_field_normalised_sum_not_tied.sql
-- (tolerance 500000). A fund-quarter does not tie when abs(difference_on_basis) is above the tolerance, the basis
-- chosen by the step 1 rule (filed_total_excludes_cash). does_not_tie is the test's condition; all rows are shown.
with published as (
    select
        s.cik
        , s.report_date
        , sum(n.value) as published_fair_value
        , coalesce(sum(n.value) filter (where s.is_cash), 0) as cash_fair_value
        , count(*) filter (where n.status <> 'normalised') as fair_value_not_normalised
    from int_source_row s
    join int_field_normalised n
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
    left join stg_fund_financials f on f.cik = p.cik and f.report_date = p.report_date
)

, based as (
    -- the basis rule of fact_fund_period.sql (step 1), applied to this layer's figures
    select
        *
        , coalesce(
            cash_fair_value <> 0
            and abs(difference) > 500000
            and abs(difference_ex_cash) <= 500000
            and cash_equivalents_filed > 0
            and abs(cash_fair_value - cash_equivalents_filed) <= 0.005 * filed_total,
            false
          ) as filed_total_excludes_cash
    from compared
)

, on_basis as (
    select
        *
        , case when filed_total_excludes_cash then difference_ex_cash else difference end as difference_on_basis
    from based
)

select
    cik
    , report_date
    , filed_total
    , published_fair_value
    , cash_fair_value
    , cash_equivalents_filed
    , difference
    , difference_ex_cash
    , filed_total_excludes_cash
    , difference_on_basis
    , fair_value_not_normalised
    , filed_total is null or abs(difference_on_basis) > 500000 or fair_value_not_normalised > 0 as does_not_tie
from on_basis
order by 1, 2
limit 200
