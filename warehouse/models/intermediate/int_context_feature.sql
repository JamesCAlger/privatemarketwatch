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
--   ownership  : InvestmentOwnedBalancePercentOfShares            us-gaap or us-gaap-sup (fix round 2); a filer namespace
--                only through a fund rule (below).
-- The term facts also accept the FASB supplement namespace (http://fasb.org/us-gaap-sup/2022q3): nine filings
-- with period ends 2022-09-30 to 2023-03-31 tag spread, PIK rate and floor there and nowhere else.
-- Investment identifier: a member on an axis whose local name is InvestmentIdentifierAxis (any prefix).
-- Filer concepts: a concept a filer files in its own namespace, read through a fund rule in the rule table
-- (stg_reading_rule, from the wrapper's reading_rules; slice 2 Task 5). Matched on the filer's cik, the namespace
-- glob of the rule (the filer's own domain, any dated path) and the exact local name, inside the rule's dates.
-- concept_is_fair_value: the fair value of a context that has no us-gaap fair-value fact (fair_value_source names the
-- rule). concept_is_term_fact: counts toward has_term_fact (term_fact_source names the rule when no standard term
-- fact is present). No fund value is written here.
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
        , 'InvestmentOwnedBalancePercentOfShares'
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
        , bool_or(concept_local = 'InvestmentOwnedBalancePercentOfShares' and is_fasb) as has_ownership_percent
    from facts
    group by 1, 2
)

, concept_rule as (
    select
        rule_id
        , cik
        , valid_from
        , valid_to
        , sel_accession
        , sel_concept_namespace
        , sel_concept_local
        , case action when 'concept_is_fair_value' then 'fair_value' when 'concept_is_term_fact' then 'term_fact' end
            as maps_to
    from {{ ref('stg_reading_rule') }}
    where action in ('concept_is_fair_value', 'concept_is_term_fact')
)

, filer_facts as (
    select
        f.accession
        , f.context_id
        , r.rule_id
        , r.maps_to
        , f.concept_local
        , f.value_numeric
    from {{ ref('stg_filed_fact') }} f
    join filing fi on fi.accession = f.accession
    join concept_rule r
        on r.cik = fi.cik
        and f.concept_namespace glob r.sel_concept_namespace
        and r.sel_concept_local = f.concept_local
        and (r.sel_accession is null or r.sel_accession = f.accession)
        and (r.valid_from is null or r.valid_from <= fi.document_period_end_date)
        and (r.valid_to is null or r.valid_to >= fi.document_period_end_date)
)

, filer_features as (
    select
        accession
        , context_id
        , count(*) filter (where maps_to = 'fair_value') as filer_fair_value_fact_count
        , count(distinct value_numeric) filter (where maps_to = 'fair_value') as filer_fair_value_distinct
        , min(value_numeric) filter (where maps_to = 'fair_value') as filer_fair_value_any
        , min(rule_id) filter (where maps_to = 'fair_value') as fair_value_rule_id
        , bool_or(maps_to = 'term_fact') as has_filer_term_fact
        , bool_or(maps_to = 'term_fact' and concept_local = 'InvestmentOwnedBalancePercentOfShares') as has_filer_ownership_percent
        , min(rule_id) filter (where maps_to = 'term_fact') as term_fact_rule_id
    from filer_facts
    group by 1, 2
)

, standard_term as (
    select
        accession
        , context_id
        , has_principal or has_shares or has_rate or has_spread or has_pik_rate or has_maturity or has_ownership_percent
            as has_standard_term_fact
    from fact_features
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
    -- The us-gaap concept comes first; a filer concept is read only where the context has no us-gaap fact.
    , case
        when coalesce(ff.fair_value_fact_count, 0) > 0 then case when ff.fair_value_distinct = 1 then ff.fair_value_any end
        when coalesce(fl.filer_fair_value_fact_count, 0) > 0 then case when fl.filer_fair_value_distinct = 1 then fl.filer_fair_value_any end
      end as fair_value
    , case
        when coalesce(ff.fair_value_fact_count, 0) > 0 then 'standard'
        when coalesce(fl.filer_fair_value_fact_count, 0) > 0 then fl.fair_value_rule_id
      end as fair_value_source
    , coalesce(ff.fair_value_fact_count, 0) > 0 and coalesce(fl.filer_fair_value_fact_count, 0) > 0
        as fair_value_filer_concept_also_present
    , case when ff.cost_distinct = 1 then ff.cost_any end as cost
    -- Facts of the concept the fair value was read from (us-gaap, else the filer concept).
    , case
        when coalesce(ff.fair_value_fact_count, 0) > 0 then ff.fair_value_fact_count
        else coalesce(fl.filer_fair_value_fact_count, 0)
      end as fair_value_fact_count
    , coalesce(ff.cost_fact_count, 0) as cost_fact_count
    , coalesce(ff.has_principal, false) as has_principal
    , coalesce(ff.has_shares, false) as has_shares
    , coalesce(ff.has_rate, false) as has_rate
    , coalesce(ff.has_spread, false) as has_spread
    , coalesce(ff.has_pik_rate, false) as has_pik_rate
    , coalesce(ff.has_maturity, false) as has_maturity
    , coalesce(ff.has_ownership_percent or fl.has_filer_ownership_percent, ff.has_ownership_percent, fl.has_filer_ownership_percent, false)
        as has_ownership_percent
    , coalesce(st.has_standard_term_fact or fl.has_filer_term_fact, st.has_standard_term_fact, fl.has_filer_term_fact, false)
        as has_term_fact
    , case
        when coalesce(st.has_standard_term_fact, false) then 'standard'
        when coalesce(fl.has_filer_term_fact, false) then fl.term_fact_rule_id
      end as term_fact_source
from {{ ref('stg_filed_context') }} c
join filing f on f.accession = c.accession
left join members m on m.accession = c.accession and m.context_id = c.context_id
left join fact_features ff on ff.accession = c.accession and ff.context_id = c.context_id
left join filer_features fl on fl.accession = c.accession and fl.context_id = c.context_id
left join standard_term st on st.accession = c.accession and st.context_id = c.context_id
