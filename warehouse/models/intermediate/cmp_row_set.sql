-- Decides which position rows sit on one side only when this layer is compared with production, and why
-- (spec intermediate_spine.md section 8, D1). Joined on accession and context id, never on a position id.
--
-- Two bases, one row per (basis, accession, context_id):
--   published   : this layer's role = position and is_published, against production rows whose
--                 accounting_record_class is not 'underlying_schedule' (the published basis).
--   unpublished : this layer's role = position and not is_published (a JV's own schedule), against production rows
--                 whose accounting_record_class is 'underlying_schedule'.
-- A production row with no context id cannot be joined; it is counted by tests/baseline_cmp_row_set_no_context.sql.
--
-- cause is set by rules on row features, first match wins, never by a list of accession or context ids. The
-- evidence behind each rule (what was opened and how many rows) is in docs/baseline_roles_2026-11-19.md.
-- Agreement between the two sides shows they agree. It does not show either is right.
with prod as (
    select
        cik
        , report_date
        , accession_number as accession
        , src_context_id as context_id
        , case when accounting_record_class = 'underlying_schedule' then 'unpublished' else 'published' end as basis
        , accounting_record_class
        , fair_value
        , corrected_fields
    from {{ ref('stg_holdings') }}
    where src_context_id is not null
)

, new_side as (
    select
        r.accession
        , r.context_id
        , r.cik
        , r.report_date
        , case when r.is_published then 'published' else 'unpublished' end as basis
    from {{ ref('int_source_row') }} r
    where r.role = 'position'
)

, joined as (
    select
        coalesce(n.basis, p.basis) as basis
        , coalesce(n.accession, p.accession) as accession
        , coalesce(n.context_id, p.context_id) as context_id
        , coalesce(n.cik, p.cik) as cik
        , coalesce(n.report_date, p.report_date) as report_date
        , case
            when n.accession is not null and p.accession is not null then 'both'
            when n.accession is not null then 'new_only'
            else 'production_only'
          end as side
        , p.accounting_record_class
        , p.fair_value
        , p.corrected_fields
    from new_side n
    full join prod p
        on p.accession = n.accession and p.context_id = n.context_id and p.basis = n.basis
)

-- Row features, read only for one-sided rows.
, one_sided as (
    select * from joined where side <> 'both'
)

, fact_flags as (
    select
        f.accession
        , f.context_id
        -- a fair value tagged with a concept outside the us-gaap namespaces (a filer's own concept)
        , bool_or(f.concept_local ilike '%FairValue%' and f.concept_namespace not like 'http://fasb.org/us-gaap/%')
            as has_filer_fair_value_fact
        , bool_or(f.concept_local = 'InvestmentOwnedBalancePercentOfShares') as has_ownership_pct
        , bool_or(f.concept_local in ('InvestmentInterestRate', 'InvestmentBasisSpreadVariableRate', 'InvestmentInterestRatePaidInKind'))
            as has_rate_fact
    from {{ ref('stg_filed_fact') }} f
    semi join one_sided o on o.accession = f.accession and o.context_id = f.context_id
    group by 1, 2
)

, term_correction as (
    -- a loaded context-keyed correction that supplies the fair value or a term field (not applied in this slice)
    select distinct accession, context_id
    from {{ ref('stg_correction') }}
    where kind = 'value'
      and context_id is not null
      and field in ('fair_value', 'principal_amount', 'shares_held', 'interest_rate', 'basis_spread', 'pik_rate', 'maturity_date')
)

, filer_not_loaded as (
    select distinct cik, wrapper_key from {{ ref('stg_reading_not_loaded') }}
)

, featured as (
    select
        o.*
        , r.role
        , r.role_rule
        , r.rule_id
        , r.reason
        , r.scope
        , r.is_cash
        , r.is_published
        , cf.identifier_label
        , cf.fair_value as new_fair_value
        , cf.fair_value_fact_count
        , list_contains(cf.other_axes, 'us-gaap:CashAndCashEquivalentsAxis') as on_cash_axis
        , coalesce(ff.has_filer_fair_value_fact, false) as has_filer_fair_value_fact
        , coalesce(ff.has_ownership_pct, false) as has_ownership_pct
        , coalesce(ff.has_rate_fact, false) as has_rate_fact
        , tc.accession is not null as has_term_correction
        , coalesce(o.corrected_fields like '%_row:added%', false) as production_row_added
        -- names a cash-equivalent fund: the keywords production uses (pipeline/classification.py
        -- _MONEY_MARKET_KEYWORDS and pipeline/bdc_xbrl_wrapper.py non_private_markers), plus cash management
        , regexp_matches(lower(coalesce(cf.identifier_label, '')),
            '\b(money market|treasury obligations|government obligations|liquidity fund|financial square|cash management|government fund)\b')
            as names_cash_fund
        -- production has rows for this fund and report date at all
        , exists (
            select 1 from {{ ref('stg_holdings') }} h where h.cik = o.cik and h.report_date = o.report_date
          ) as production_has_quarter
        , s.accession is not null as is_selected_filing
        , nl.cik is not null as filer_has_rate_only_declaration
    from one_sided o
    left join {{ ref('int_source_row') }} r on r.accession = o.accession and r.context_id = o.context_id
    left join {{ ref('int_context_feature') }} cf on cf.accession = o.accession and cf.context_id = o.context_id
    left join fact_flags ff on ff.accession = o.accession and ff.context_id = o.context_id
    left join term_correction tc on tc.accession = o.accession and tc.context_id = o.context_id
    left join {{ ref('int_filing_selected') }} s on s.accession = o.accession
    left join filer_not_loaded nl on nl.cik = o.cik and nl.wrapper_key = 'rate_only_contexts'
)

, paired as (
    -- A one-sided row whose twin (same basis, accession and identifier label) is one-sided on the other side, where
    -- the production row's context carries rate facts and no fair value: the rate-only / value-only context pair a
    -- filer's unloaded rate_only_contexts declaration joins.
    select
        f.*
        , exists (
            select 1 from featured t
            where t.basis = f.basis and t.accession = f.accession and t.identifier_label = f.identifier_label
              and t.side <> f.side
              and (case when f.side = 'production_only' then f.fair_value_fact_count = 0 and f.has_rate_fact
                        else t.fair_value_fact_count = 0 and t.has_rate_fact end)
          ) as has_rate_only_twin
    from featured f
)

, caused as (
    select
        *
        , case
            -- production_only
            when side = 'production_only' and production_row_added
                then 'needs_store_not_loaded|production_row_added'
            when side = 'production_only' and has_rate_only_twin and filer_has_rate_only_declaration
                then 'needs_store_not_loaded|rate_only_context_pair'
            when side = 'production_only' and has_term_correction
                then 'needs_correction|correction_supplies_value_or_term'
            when side = 'production_only' and role = 'not_schedule' and role_rule = 3 and has_filer_fair_value_fact
                then 'new_wrong|fair_value_in_filer_concept'
            when side = 'production_only' and role = 'not_schedule' and role_rule = 1 and on_cash_axis
                then 'new_wrong|cash_axis_with_other_axis'
            when side = 'production_only' and role = 'unresolved' and has_ownership_pct
                then 'new_wrong|ownership_pct_not_a_term_fact'
            when side = 'production_only' and role = 'unresolved' and names_cash_fund
                then 'new_wrong|cash_fund_not_recognised'
            when side = 'production_only' and role = 'unresolved' and reason like '%no term fact%'
                then 'new_wrong|no_term_fact_but_position'
            -- new_only
            when side = 'new_only' and is_selected_filing and not production_has_quarter
                then 'old_wrong|production_build_lacks_filing'
            when side = 'new_only' and has_rate_only_twin and filer_has_rate_only_declaration
                then 'needs_store_not_loaded|rate_only_context_pair'
            when side = 'new_only' and (is_cash or names_cash_fund)
                then 'convention|cash_published_d7'
            else 'not_yet_explained|none'
          end as cause_key
    from paired
)

select
    j.basis
    , j.accession
    , j.context_id
    , j.cik
    , j.report_date
    , j.side
    , r.role
    , r.role_rule
    , r.rule_id
    , r.reason
    , r.is_published
    , j.accounting_record_class
    , j.fair_value
    , cf.fair_value as new_fair_value
    , split_part(c.cause_key, '|', 1) as cause
    , nullif(split_part(c.cause_key, '|', 2), '') as cause_detail
from joined j
left join {{ ref('int_source_row') }} r on r.accession = j.accession and r.context_id = j.context_id
left join {{ ref('int_context_feature') }} cf on cf.accession = j.accession and cf.context_id = j.context_id
left join caused c on c.basis = j.basis and c.accession = j.accession and c.context_id = j.context_id
