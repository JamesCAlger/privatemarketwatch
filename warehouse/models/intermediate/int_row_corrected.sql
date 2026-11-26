-- Decides the position set after corrections (slice 5 Task 3): every position of int_source_row, plus each context a
-- correction makes a position. One row per (accession, context_id). No role in int_source_row changes: role_filed is
-- the role there, role is 'position' on every row here.
--
-- Row rule (mirrors cmp_row_set's needs_correction rule, the measured evidence; spec 6.5). A context that is not a
-- position becomes one when a correction that passes int_correction_screen (screen_outcome null) supplies what its role
-- lacked:
--   correction_adds_row             (iii) an agent add_row group (kind add_row) that supplies a fair value on the
--                                   context (owner decision 1). Measured: the 8 row_add positions of one fund, all on contexts
--                                   rule 1 left out (no investment identifier member: the issuer-axis context that
--                                   carries cost and fair value)
--   correction_supplies_fair_value  (i) the role is not_schedule by rule 3 for want of a fair-value fact (no fact at
--                                   all) and a correction supplies fair_value (a value, not a withdrawal). Measured: the
--                                   wrapper zero fair values (untagged_values) whose printed cell prints a dash
--                                   or a zero (owner answer 2026-11-24 on decision 4, int_correction_fair_value_cell)
--   correction_supplies_term        (ii) the role is unresolved by rule 7 or 9 for want of a term fact (no term fact,
--                                   not held for two scopes) and a correction supplies a term field (principal_amount,
--                                   shares, interest_rate, spread, pik_rate, maturity_date). Measured: 2 rows of one
--                                   fund (2022-09-30) and 6, each through a wrapper principal. Since slice 5 Task 4
--                                   the rate corrections pass the screen too: they promote no further context, but
--                                   the two 2022-09-30 rows now also list their rate corrections in row_correction_ids
-- The first that holds, in that order, names row_reason; a filed position has row_reason 'filed'. scope is the
-- context's scope in int_source_row ('fund' unless a scope rule names an entity); is_published follows the existing
-- rule (scope 'fund'); is_cash is int_source_row's. row_correction_ids lists the corrections that supplied what the
-- role lacked (comma separated, sorted); null on a filed position. Any promotion beyond the measured counts fails the
-- build (generic test baseline_correction_count, var row_corrected_promoted_max, one ceiling per row reason), as does a promotion whose role rule
-- is not 1 (add_row), 3, 7 or 9 (tests/int_row_corrected_promotion_rules.sql).
with source_row as (
    select s.*, cf.has_term_fact, cf.fair_value_fact_count
    from {{ ref('int_source_row') }} s
    join {{ ref('int_context_feature') }} cf on cf.accession = s.accession and cf.context_id = s.context_id
)

, passing as (
    -- corrections that pass the screen and set a value on a context that is not a position
    select sc.*
    from {{ ref('int_correction_screen') }} sc
    where sc.screen_outcome is null and sc.target_role <> 'position'
      and sc.value_column = 'value' and not sc.is_withdrawal
)

, supply as (
    select
        p.accession
        , p.context_id
        , case
            when p.kind = 'add_row' and p.field_row = 'fair_value' then 1
            when p.field_row = 'fair_value' and s.role = 'not_schedule' and s.role_rule = 3
                 and s.fair_value_fact_count = 0 then 2
            when p.field_row in ('principal_amount', 'shares', 'interest_rate', 'spread', 'pik_rate', 'maturity_date')
                 and s.role = 'unresolved' and s.role_rule in (7, 9) and not s.has_term_fact
                 and not s.held_for_two_scopes then 3
          end as rule_rank
        , p.correction_id
    from passing p
    join source_row s on s.accession = p.accession and s.context_id = p.context_id
)

, promoted as (
    select
        accession
        , context_id
        , min(rule_rank) as rule_rank
    from supply
    where rule_rank is not null
    group by 1, 2
)

, promoted_ids as (
    select
        p.accession
        , p.context_id
        , p.rule_rank
        , string_agg(s.correction_id, ',' order by s.correction_id) as row_correction_ids
    from promoted p
    join supply s on s.accession = p.accession and s.context_id = p.context_id and s.rule_rank = p.rule_rank
    group by 1, 2, 3
)

select
    s.accession
    , s.context_id
    , s.cik
    , s.report_date
    , s.role as role_filed
    , s.role_rule as role_rule_filed
    , 'position' as role
    , s.scope = 'fund' as is_published
    , s.scope
    , s.is_cash
    , cast(null as varchar) as row_correction_ids
    , 'filed' as row_reason
from source_row s
where s.role = 'position'
union all
select
    s.accession
    , s.context_id
    , s.cik
    , s.report_date
    , s.role as role_filed
    , s.role_rule as role_rule_filed
    , 'position' as role
    , s.scope = 'fund' as is_published
    , s.scope
    , s.is_cash
    , p.row_correction_ids
    , case p.rule_rank
        when 1 then 'correction_adds_row'
        when 2 then 'correction_supplies_fair_value'
        when 3 then 'correction_supplies_term'
      end as row_reason
from promoted_ids p
join source_row s on s.accession = p.accession and s.context_id = p.context_id
