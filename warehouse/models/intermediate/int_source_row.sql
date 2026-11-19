-- Decides the role of every context of every parsed filing of the five funds (spec intermediate_spine.md 6.2): rules 0
-- to 9 in order, the first that fires decides, then the cross-check.
--
--   0-3  int_role_structure (superseded, not_schedule, comparative; unresolved where fair-value facts disagree)
--   4-5  int_role_text      (label reads total, net assets, an affiliation heading, or the cash bucket) -> aggregate
--   6    int_role_subtotal  (label starts other rows' labels and its fair value, and cost, equal their sum) -> aggregate
--   7    int_role_scope     (a JV or entity member or label from the rule table) -> position, scope = that entity
--   8    a cash context (cash and cash equivalents axis, no identifier, others only on rule 8 seed axes) -> position, is_cash
--   9    anything left -> position
-- Cross-check (spec 6.2): a position should carry at least one term fact (principal, shares, rate, spread, PIK rate,
-- maturity; a nil fact counts, see int_context_feature). Where it disagrees with rules 4 to 6 the role is unresolved:
-- a row rules 4 to 6 call an aggregate that carries a term fact, or a row that reaches rule 7 or 9 without one. A cash
-- row (is_cash) is exempt: cash carries no loan or share terms (D7). Two different scopes on one row are unresolved.
-- concept_rule_id names the fund rule (stg_reading_rule, concept_is_fair_value or concept_is_term_fact) a role was
-- decided through. rule_id on a rule 6 row names the fund rule subtotal_on_fair_value where the row is a subtotal only
-- through it (its fair value ties and its cost does not).
-- Fund rule position_without_term_fact (int_role_fund_position, D15): a row at rule 7 or 9 with no term fact that one
-- such rule of its fund matches is a position, not unresolved; position_rule_id names the rule. It changes nothing
-- else: rules 0 to 6, cash rows and two scopes are decided as before, and cross_check_agrees stays false on the row
-- (the cross-check still disagrees; the fund rule overrides it). Two rules matching one row leave it unresolved.
-- is_published is false for a JV's own schedule rows (scope other than 'fund'), matching production's published basis.
with base as (
    select
        s.accession
        , s.context_id
        , s.cik
        , s.report_date
        , s.role as structure_role
        , s.role_rule as structure_rule
        , s.reason as structure_reason
        , s.is_cash_axis
        , cf.has_term_fact
        , cf.fair_value_source
        , cf.term_fact_source
        , t.text_rule
        , t.pattern_id
        , t.cash_pattern_id
        , st.is_subtotal
        , st.child_count
        , st.subtotal_rule_id
        , sc.scope_count
        , sc.scope
        , sc.scopes
        , sc.scope_rule_id
        , sc.scope_how
        , sc.cash_rule_id
        , fp.position_rule_id
        , coalesce(fp.match_count, 0) as position_rule_count
    from {{ ref('int_role_structure') }} s
    join {{ ref('int_context_feature') }} cf on cf.accession = s.accession and cf.context_id = s.context_id
    left join {{ ref('int_role_text') }} t on t.accession = s.accession and t.context_id = s.context_id
    left join {{ ref('int_role_subtotal') }} st on st.accession = s.accession and st.context_id = s.context_id
    left join {{ ref('int_role_scope') }} sc on sc.accession = s.accession and sc.context_id = s.context_id
    left join {{ ref('int_role_fund_position') }} fp on fp.accession = s.accession and fp.context_id = s.context_id
)

, ruled as (
    select
        *
        , case
            when structure_role is not null then structure_rule
            when text_rule is not null then text_rule
            when coalesce(is_subtotal, false) then 6
            when scope_count > 0 then 7
            when is_cash_axis then 8
            else 9
          end as role_rule
        , structure_role is null and (is_cash_axis or cash_rule_id is not null or cash_pattern_id is not null) as is_cash_row
    from base
)

, released as (
    -- a row the cross-check would hold for want of a term fact, and exactly one fund rule declares a position
    -- Cash rows are left out: the cross-check exempts them (D7, cash carries no loan or share terms), so they are never held for want of a term fact and need no release.
    select
        *
        , role_rule in (7, 9) and not (role_rule = 7 and scope_count > 1) and not has_term_fact and not is_cash_row
            as lacks_term_fact
        , role_rule in (7, 9) and not (role_rule = 7 and scope_count > 1) and not has_term_fact and not is_cash_row
            and position_rule_count = 1 as is_released
    from ruled
)

, decided as (
select
    accession
    , context_id
    , cik
    , report_date
    , case
        when role_rule <= 3 then structure_role
        when role_rule in (4, 5, 6) and has_term_fact then 'unresolved'
        when role_rule in (4, 5, 6) then 'aggregate'
        when role_rule = 7 and scope_count > 1 then 'unresolved'
        when lacks_term_fact and not is_released then 'unresolved'
        else 'position'
      end as role
    , role_rule
    , case
        when role_rule in (4, 5) then pattern_id
        when role_rule = 6 then subtotal_rule_id
        when role_rule = 7 then scope_rule_id
        when role_rule in (8, 9) then cash_rule_id
      end as rule_id
    , case
        when role_rule <= 3 then structure_reason
        when role_rule in (4, 5) and has_term_fact then 'label pattern ' || pattern_id || ' reads as an aggregate but the row carries a term fact'
        when role_rule in (4, 5) then 'label pattern ' || pattern_id
        when role_rule = 6 and has_term_fact then 'sum of ' || child_count || ' rows below it, but the row carries a term fact'
        when role_rule = 6 and subtotal_rule_id is not null
            then 'fair value equals the sum of ' || child_count || ' rows below it; cost does not (fund rule subtotal_on_fair_value)'
        when role_rule = 6 then 'fair value (and cost) equal the sum of ' || child_count || ' rows below it'
        when role_rule = 7 and scope_count > 1 then 'two scopes: ' || scopes
        when lacks_term_fact and position_rule_count > 1
            then 'no term fact, and ' || position_rule_count || ' fund rules position_without_term_fact match'
        when role_rule = 7 and is_released
            then 'scope ' || scope || ' by ' || scope_how || '; no term fact, position by fund rule position_without_term_fact'
        when role_rule = 7 and lacks_term_fact then 'scope ' || scope || ' by ' || scope_how || ', but no term fact'
        when role_rule = 7 then 'scope ' || scope || ' by ' || scope_how
        when role_rule = 8 then 'fair value on the cash and cash equivalents axis'
        when is_released then 'no term fact; position by fund rule position_without_term_fact'
        when lacks_term_fact then 'no rule removes it, but no term fact'
        when cash_rule_id is not null then 'position; cash identifier from the rule table'
        when cash_pattern_id is not null then 'position; label names a money-market fund (' || cash_pattern_id || ')'
        else 'position'
      end as reason
    , case when role_rule = 7 and scope_count = 1 then scope when role_rule = 7 then scopes else 'fund' end as scope
    , coalesce(is_cash_row, false) as is_cash
    , case
        when role_rule <= 3 then null
        when role_rule in (4, 5, 6) then not has_term_fact
        when role_rule = 7 and scope_count > 1 then null
        else has_term_fact or is_cash_row
      end as cross_check_agrees
    , cash_rule_id
    -- The seed pattern (seeds/role_pattern.csv, a rule 5 exception) that flagged the row as cash: its label names a
    -- money-market fund. A cash row names its source: cash_rule_id (a fund rule), cash_pattern_id, or role_rule 8
    -- (the filed cash and cash equivalents axis); tested by cash_row_names_its_source.
    , case when is_cash_row then cash_pattern_id end as cash_pattern_id
    -- The fund concept rule a role was decided through: the fair value that let the row past
    -- rule 3, else the only term fact the cross-check read (on a row that reached rules 4 to 9).
    , case
        when role_rule >= 4 and fair_value_source <> 'standard' then fair_value_source
        when role_rule >= 4 and term_fact_source <> 'standard' then term_fact_source
      end as concept_rule_id
    , case when is_released then position_rule_id end as position_rule_id
from released
)

select
    accession
    , context_id
    , cik
    , report_date
    , role
    , role_rule
    , rule_id
    , reason
    , scope
    , is_cash
    , role = 'position' and scope = 'fund' as is_published
    , cross_check_agrees
    , cash_rule_id
    , cash_pattern_id
    , concept_rule_id
    , position_rule_id
from decided
