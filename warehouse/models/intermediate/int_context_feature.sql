-- Decides nothing: one row per filed context with the structural features later rules read (members, dates, which facts it carries).
--
-- Standard concepts: read from the seed concept_map (one definition, slice 3 Task 1). A fact belongs to a field when
-- its local name equals the row's concept_local and its namespace matches the row's namespace_pattern (a glob), never
-- on the prefix (filed_layer.md section 7 ruling 12). Fair value and cost: us-gaap only. The term facts (principal,
-- shares, rate, spread, PIK rate, maturity, ownership percent) also accept the FASB supplement namespace; the seed
-- says so row by row. Share of net assets is in the seed but is not read here.
-- fair_value_rule_id: the rule the fair value was read under, the concept_map row for the standard concept or the
-- fund rule for a filer concept (spec section 7: every value names its rule).
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

, concept_map as (
    select concept_map_id, field, concept_local, namespace_pattern from {{ ref('concept_map') }}
)

, facts as (
    -- the facts of a standard concept, each with the field and the concept_map row it was read under
    select
        f.accession
        , f.context_id
        , m.field
        , m.concept_map_id
        , f.value_numeric
    from {{ ref('stg_filed_fact') }} f
    join concept_map m on m.concept_local = f.concept_local and f.concept_namespace glob m.namespace_pattern
)

, fact_features as (
    select
        accession
        , context_id
        , count(*) filter (where field = 'fair_value') as fair_value_fact_count
        , count(distinct value_numeric) filter (where field = 'fair_value') as fair_value_distinct
        , min(value_numeric) filter (where field = 'fair_value') as fair_value_any
        , min(concept_map_id) filter (where field = 'fair_value') as fair_value_map_id
        , count(*) filter (where field = 'cost') as cost_fact_count
        , count(distinct value_numeric) filter (where field = 'cost') as cost_distinct
        , min(value_numeric) filter (where field = 'cost') as cost_any
        -- has_* flags: a nil fact counts as present (the filer tagged the term on the row); row roles rely on this.
        , bool_or(field = 'principal_amount') as has_principal
        , bool_or(field = 'shares') as has_shares
        , bool_or(field = 'rate') as has_rate
        , bool_or(field = 'spread') as has_spread
        , bool_or(field = 'pik_rate') as has_pik_rate
        , bool_or(field = 'maturity') as has_maturity
        , bool_or(field = 'ownership_percent') as has_ownership_percent
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
        -- a fund rule that reads the ownership-percent concept (by its local name in the seed) in the filer's namespace
        , bool_or(maps_to = 'term_fact' and concept_local in (
            select concept_local from concept_map where field = 'ownership_percent'
          )) as has_filer_ownership_percent
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
    -- the rule the fair value was read under: the concept_map row (standard) or the fund rule (filer concept)
    , case
        when coalesce(ff.fair_value_fact_count, 0) > 0 then ff.fair_value_map_id
        when coalesce(fl.filer_fair_value_fact_count, 0) > 0 then fl.fair_value_rule_id
      end as fair_value_rule_id
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
