{#- The sum check (spec section 7), one row per fund and report date that does not tie: the published positions'
    normalised fair value against the filed total investments (stg_fund_financials), on the basis step 1 uses
    (fact_fund_period.sql): the published basis (cash rows in), or without the cash rows when the A04 evidence holds
    (owner ruling 2026-11-04): the total with cash misses, the total without cash ties, and the cash rows equal the
    filed cash equivalents within 0.5 pct of the filed investments; or the fund's wrapper declares it (macro
    filed_total_excludes_cash_declared, owner decision D16, 2026-11-23). A fund-quarter does not tie when the difference on
    that basis (difference_on_basis) is above var reconcile_tolerance. A published fair value that is not normalised
    counts as missing. Fund-quarters with no filed total are listed too (filed null). Controller ruling, slice 3 Task 3
    fix round 1. Read by tests/baseline_int_field_normalised_sum_not_tied.sql (the count) and
    tests/int_field_normalised_sum_not_tied_set.sql (the pinned set, final fix wave F5).
    corrected=true (slice 5 Task 3): the same check on the corrected published basis, the position set after corrections
    (int_row_corrected) and the corrected fair value (int_field_corrected); a fair value counts as missing unless its
    status is normalised or corrected (a withdrawn one is missing). Read by tests/baseline_int_field_corrected_sum_not_
    tied.sql and tests/int_field_corrected_sum_not_tied_set.sql. -#}
{% macro sum_not_tied_rows(corrected=false) %}
with published as (
    select
        s.cik
        , s.report_date
        , sum(n.value) as published_fair_value
        , coalesce(sum(n.value) filter (where s.is_cash), 0) as cash_fair_value
        {%- if corrected %}
        , count(*) filter (where n.status not in ('normalised', 'corrected')) as fair_value_not_normalised
    from {{ ref('int_row_corrected') }} s
    join {{ ref('int_field_corrected') }} n
        on n.accession = s.accession and n.context_id = s.context_id and n.field = 'fair_value'
        {%- else %}
        , count(*) filter (where n.status <> 'normalised') as fair_value_not_normalised
    from {{ ref('int_source_row') }} s
    join {{ ref('int_field_normalised') }} n
        on n.accession = s.accession and n.context_id = s.context_id and n.field = 'fair_value'
        {%- endif %}
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
    -- the basis rule of fact_fund_period.sql (step 1), applied to this layer's figures
    select
        *
        , {{ filed_total_excludes_cash_declared('cik', 'report_date') }}
          or coalesce(
            cash_fair_value <> 0
            and abs(difference) > {{ var('reconcile_tolerance') }}
            and abs(difference_ex_cash) <= {{ var('reconcile_tolerance') }}
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
from on_basis
where filed_total is null
   or abs(difference_on_basis) > {{ var('reconcile_tolerance') }}
   or fair_value_not_normalised > 0
{% endmacro %}
