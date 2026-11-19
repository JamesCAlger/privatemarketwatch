-- Decides nothing: one row per filed context with the structural features later rules read (members, dates, which facts it carries).
--
-- Concepts read (matched on local name plus namespace, never on the prefix; filed_layer.md section 7 ruling 12):
--   fair value : InvestmentOwnedAtFairValue                      namespace http://fasb.org/us-gaap/*
--   cost       : InvestmentOwnedAtCost                           namespace http://fasb.org/us-gaap/*
--   principal  : InvestmentOwnedBalancePrincipalAmount           us-gaap or us-gaap-sup
--   shares     : InvestmentOwnedBalanceShares                    us-gaap or us-gaap-sup
--   rate       : InvestmentInterestRate, InvestmentInterestRatePaidInCash   us-gaap or us-gaap-sup
--   spread     : InvestmentBasisSpreadVariableRate               us-gaap or us-gaap-sup
--   PIK rate   : InvestmentInterestRatePaidInKind                us-gaap or us-gaap-sup
--   maturity   : InvestmentMaturityDate                          us-gaap or us-gaap-sup
-- The term facts also accept the FASB supplement namespace (http://fasb.org/us-gaap-sup/2022q3): nine filings
-- with period ends 2022-09-30 to 2023-03-31 tag spread, PIK rate and floor there and nowhere else.
-- Investment identifier: a member on an axis whose local name is InvestmentIdentifierAxis (any prefix).
with filing as (
    select accession, cik, document_period_end_date
    from {{ ref('stg_filed_filing') }}
)

, members as (
    select
        accession
        , context_id
        , count(*) filter (where axis like '%:InvestmentIdentifierAxis') as identifier_axis_count
        , min(member) filter (where axis like '%:InvestmentIdentifierAxis') as identifier_label
        , list(axis order by member_index) filter (where axis not like '%:InvestmentIdentifierAxis') as other_axes
        , list(member order by member_index) filter (where axis not like '%:InvestmentIdentifierAxis') as other_members
    from {{ ref('stg_filed_context_member') }}
    group by 1, 2
)

, facts as (
    select
        accession
        , context_id
        , concept_local
        , concept_namespace like 'http://fasb.org/us-gaap/%' as is_us_gaap
        , concept_namespace like 'http://fasb.org/us-gaap/%' or concept_namespace like 'http://fasb.org/us-gaap-sup/%' as is_fasb
        , value_numeric
    from {{ ref('stg_filed_fact') }}
    where concept_local in (
        'InvestmentOwnedAtFairValue', 'InvestmentOwnedAtCost', 'InvestmentOwnedBalancePrincipalAmount'
        , 'InvestmentOwnedBalanceShares', 'InvestmentInterestRate', 'InvestmentInterestRatePaidInCash'
        , 'InvestmentBasisSpreadVariableRate', 'InvestmentInterestRatePaidInKind', 'InvestmentMaturityDate'
    )
)

, fact_features as (
    select
        accession
        , context_id
        , count(*) filter (where concept_local = 'InvestmentOwnedAtFairValue' and is_us_gaap) as fair_value_fact_count
        , count(distinct value_numeric) filter (where concept_local = 'InvestmentOwnedAtFairValue' and is_us_gaap) as fair_value_distinct
        , min(value_numeric) filter (where concept_local = 'InvestmentOwnedAtFairValue' and is_us_gaap) as fair_value_any
        , count(*) filter (where concept_local = 'InvestmentOwnedAtCost' and is_us_gaap) as cost_fact_count
        , count(distinct value_numeric) filter (where concept_local = 'InvestmentOwnedAtCost' and is_us_gaap) as cost_distinct
        , min(value_numeric) filter (where concept_local = 'InvestmentOwnedAtCost' and is_us_gaap) as cost_any
        -- has_* flags: a nil fact counts as present (the filer tagged the term on the row); row roles rely on this.
        , bool_or(concept_local = 'InvestmentOwnedBalancePrincipalAmount' and is_fasb) as has_principal
        , bool_or(concept_local = 'InvestmentOwnedBalanceShares' and is_fasb) as has_shares
        , bool_or(concept_local in ('InvestmentInterestRate', 'InvestmentInterestRatePaidInCash') and is_fasb) as has_rate
        , bool_or(concept_local = 'InvestmentBasisSpreadVariableRate' and is_fasb) as has_spread
        , bool_or(concept_local = 'InvestmentInterestRatePaidInKind' and is_fasb) as has_pik_rate
        , bool_or(concept_local = 'InvestmentMaturityDate' and is_fasb) as has_maturity
    from facts
    group by 1, 2
)

select
    c.accession
    , c.context_id
    , f.cik
    , c.instant_date
    , c.period_type
    , c.member_count
    , coalesce(m.identifier_axis_count, 0) > 0 as has_identifier_member
    -- A context with two identifier axes (two prefixes) would have no single label; none exists today.
    , case when m.identifier_axis_count = 1 then m.identifier_label end as identifier_label
    , coalesce(m.other_axes, []) as other_axes
    , coalesce(m.other_members, []) as other_members
    , coalesce(c.instant_date = f.document_period_end_date, false) as is_filing_period_end
    -- One value only when the facts of the concept on the context carry exactly one distinct number
    -- (repeated equal facts agree; a nil fact carries no number). Two different numbers give null.
    , case when ff.fair_value_distinct = 1 then ff.fair_value_any end as fair_value
    , case when ff.cost_distinct = 1 then ff.cost_any end as cost
    , coalesce(ff.fair_value_fact_count, 0) as fair_value_fact_count
    , coalesce(ff.cost_fact_count, 0) as cost_fact_count
    , coalesce(ff.has_principal, false) as has_principal
    , coalesce(ff.has_shares, false) as has_shares
    , coalesce(ff.has_rate, false) as has_rate
    , coalesce(ff.has_spread, false) as has_spread
    , coalesce(ff.has_pik_rate, false) as has_pik_rate
    , coalesce(ff.has_maturity, false) as has_maturity
    , coalesce(ff.has_principal or ff.has_shares or ff.has_rate or ff.has_spread or ff.has_pik_rate or ff.has_maturity, false) as has_term_fact
from {{ ref('stg_filed_context') }} c
join filing f on f.accession = c.accession
left join members m on m.accession = c.accession and m.context_id = c.context_id
left join fact_features ff on ff.accession = c.accession and ff.context_id = c.context_id
