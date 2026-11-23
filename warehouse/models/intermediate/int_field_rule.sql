-- Decides which rule converts each amount field of each position row (spec intermediate_spine.md sections 5 and 6.4).
-- Resolution only: no value is computed here. One row per (accession, context_id, field), for the five amount fields
-- of int_field_read plus principal_amount_usd.
--
-- Rules come from two places, and both are rows, never an else branch:
--   global defaults  seeds/field_rule_default.csv (origin global_default, priority 10), for example as_filed for an
--                    amount tagged in US dollars;
--   fund rules       stg_reading_rule (the wrapper copies), for the slice 3 actions listed in seeds/action_field.csv,
--                    which says which fields each action governs and on which rows (applies_to).
-- A rule matches a row when its fund, accession (if it names one), dates (against the report date) and applies_to
-- all hold. The most specific match wins, in two steps:
--   1. higher priority wins (10 global default, 20 fund rule, 30 a rule naming a filing or a row feature);
--   2. at the same priority, a rule that names a filing (sel_accession) outranks one that names only a row feature:
--      a filing is the narrower scope, and production's par_scale gives the listed filing precedence over the row
--      modes (pipeline/staging_bdc.py). Controller ruling, slice 3 Task 3 fix round 1.
-- Two rules still equal after both steps (two filing rules, or two feature rules) are a conflict: no rule is chosen
-- (rule_id null, resolution rule_conflict). tie_break_losers counts the rules a row's winner beat by step 2 alone, and
-- tie_break_same_effect says whether every one of them that can be decided would have given the same action and scale
-- (an undecidable loser is left out; null when none can be decided).
-- tests/baseline_int_field_rule_tie_break_different_effect.sql fails when a tie-break is decided between rules of
-- different effect (ceiling 0); tests/baseline_int_field_rule_tie_break_undecidable_loser.sql fails when every beaten
-- rule is undecidable (ceiling 0).
-- A row no rule matches has resolution no_rule.
-- Spec section 5 rule 2, a missing row feature is an error, never "no match": where a rule's other tests let a row
-- through but a feature it needs is null (the label for the equity-word tests, the read cost for a band, a printed
-- placement for the sign test), the rule counts as a candidate it cannot decide. If such a candidate is among the
-- top-ranked, the field gets resolution feature_missing and no rule.
--
-- applies_to, the rows each kind of rule can act on (unit kind is read from the unit as filed: iso4217:USD is usd,
-- another iso4217 code is foreign, shares, pure, anything else other):
--   unit_usd / unit_foreign / unit_shares / unit_pure  the field was read with a number in that unit kind
--   two_unit_cost                    cost unresolved because it is tagged once in USD and once in another currency
--                                    with two numbers (macro two_unit_cost_facts)
--   two_unit_cost_principal_absent   principal absent on such a context
--   shares_as_par                    principal absent or nil, a share count above zero, and the row mode of the rule
--                                    (value_scale is the power of a thousand chosen; see below)
--   principal_as_units               shares absent or nil, a principal above zero, and no debt term fact
--   sign_differs_from_print          fair value or cost read, not zero, and its printed brackets disagree with its sign
--   principal_usd / principal_foreign  principal_amount_usd: the currency of the principal as resolved above
--
-- par_tagged_as_units row modes, ported from pipeline/staging_bdc.py (par_scale) and pipeline/source_encodings.py.
-- Production tests "the row is a loan" from text (asset_category_final = LOAN); text is not read in this slice, so a
-- debt term fact (rate, spread, PIK rate or maturity) stands in for it. A row whose label names an equity instrument
-- keeps its count (production's _names_equity guard).
--   rows_near_cost          debt row; count times 1, 1000 or 1,000,000 within 0.8 to 1.25 times cost (first that fits)
--   rated_rows_near_cost    the same, and the row carries a rate or a spread
--   rows_within_twice_cost  debt row; the band is 0.5 to 2 times cost
--   whole_filing            (names an accession) every debt row of the filing, scale 1, no band and no equity guard
--   listed_rows_without_instrument  in a filing a whole_filing rule of the same fund lists, a row with no debt term
--                           fact whose label names no equity word, scale 1
-- These decide from the size of a number; each is listed for review in docs/owner_review_value_size_rules_2026-11-22.md.
with read as (
    -- the five amount fields only: int_field_read also reads the rate fields and the maturity date since slice 4 Task 2;
    -- their rules are slice 4 Task 3, which extends this list
    select *
        , case
            when status <> 'read' or is_nil or value_filed is null then null
            when unit = 'iso4217:USD' then 'usd'
            when regexp_full_match(unit, 'iso4217:[A-Z]{3}') then 'foreign'
            when unit = 'shares' then 'shares'
            when unit = 'pure' then 'pure'
            else 'other'
          end as unit_kind
    from {{ ref('int_field_read') }}
    where field in ('fair_value', 'cost', 'principal_amount', 'shares', 'pct_of_net_assets')
)

, unresolved_cost as (
    select accession, context_id from read where field = 'cost' and status = 'unresolved'
)

, two_unit_cost as (
    {{ two_unit_cost_facts('unresolved_cost') }}
)

, listed_sign_filing as (
    select distinct cik, sel_accession as accession
    from {{ ref('stg_reading_rule') }}
    where action = 'bracketed_unsigned' and sel_accession is not null
)

, sign_placement as (
    -- every printing of the fair value and cost facts on positions of a listed filing, with its printed brackets
    select
        r.accession
        , r.context_id
        , r.field
        , r.value_filed
        -- bracketed: the number's own cell is wholly "(...)"; or "(" ends the cell before it and ")" starts the cell
        -- after it; or (slice 3 Task 4 fix round 1, a general layout rule) the number's own cell opens with "(" and
        -- holds no ")" and the very next cell starts with ")": "(282" then ")"
        , regexp_full_match(coalesce(dr.cells[coalesce(pl.cell_index, pl.shown_cell_index) + 1], ''),
                            '\s*\$?\s*\(.*\)\s*%?\s*')
          or (rtrim(coalesce(dr.cells[coalesce(pl.cell_index, pl.shown_cell_index)], '')) like '%('
              and ltrim(coalesce(dr.cells[coalesce(pl.cell_index, pl.shown_cell_index) + 2], '')) like ')%')
          or (regexp_full_match(coalesce(dr.cells[coalesce(pl.cell_index, pl.shown_cell_index) + 1], ''),
                                '\s*\$?\s*\([^)]*')
              and ltrim(coalesce(dr.cells[coalesce(pl.cell_index, pl.shown_cell_index) + 2], '')) like ')%') as is_bracketed
    from read r
    semi join listed_sign_filing l on l.accession = r.accession and l.cik = r.cik
    join {{ ref('stg_filed_fact_placement') }} pl on pl.accession = r.accession and pl.fact_id = r.fact_id
    join {{ ref('stg_filed_document_row') }} dr
        on dr.accession = pl.accession and dr.row_index = coalesce(pl.row_index, pl.shown_row_index)
    where r.field in ('fair_value', 'cost') and r.unit_kind is not null and r.value_filed <> 0
)

, sign_differs as (
    -- every printing agrees, and it disagrees with the tagged sign (pipeline/printed_sign.py apply_printed_signs)
    select accession, context_id, field
    from sign_placement
    group by 1, 2, 3
    having count(distinct is_bracketed) = 1 and bool_and(is_bracketed <> (value_filed < 0))
)

, sign_unplaced as (
    -- fair value or cost of a listed filing that the sign test would read but that has no printed placement: the
    -- feature (its printed brackets) is missing
    select r.accession, r.context_id, r.field
    from read r
    semi join listed_sign_filing l on l.accession = r.accession and l.cik = r.cik
    anti join sign_placement p on p.accession = r.accession and p.context_id = r.context_id and p.field = r.field
    where r.field in ('fair_value', 'cost') and r.unit_kind is not null and r.value_filed <> 0
)

, whole_filing as (
    select distinct cik, sel_accession as accession
    from {{ ref('stg_reading_rule') }}
    where action = 'par_tagged_as_units' and parameter = 'whole_filing' and sel_accession is not null
)

, row_feature as (
    -- one row per position with what the domain tests read
    select
        r.accession
        , r.context_id
        , any_value(r.cik) as cik
        , any_value(r.report_date) as report_date
        , bool_or(r.field = 'principal_amount' and (r.status = 'absent' or r.is_nil)) as no_principal
        , bool_or(r.field = 'principal_amount' and r.status = 'read' and r.value_filed > 0) as principal_positive
        , any_value(r.unit_kind) filter (where r.field = 'principal_amount') as principal_unit_kind
        , bool_or(r.field = 'shares' and (r.status = 'absent' or r.is_nil)) as no_shares
        , max(r.value_filed) filter (where r.field = 'shares' and r.unit_kind is not null) as shares_value
        , max(r.value_filed) filter (where r.field = 'cost' and r.unit_kind is not null) as cost_value
    from read r
    group by 1, 2
)

, par_feature as (
    select
        rf.*
        , cf.has_rate or cf.has_spread or cf.has_pik_rate or cf.has_maturity as has_debt_term
        , cf.has_rate or cf.has_spread as is_rated
        -- null when the label is null: the feature is missing, not "names no equity word"
        , regexp_matches(lower(cf.identifier_label),
                         '(^|[^a-z])(units?|shares?|stock|membership|warrants?)([^a-z]|$)') as names_equity
        , regexp_matches(lower(cf.identifier_label),
                         '(^|[^a-z])(units?|shares?|stock|membership|warrants?|interests?|preferred|equity)([^a-z]|$)')
          as names_equity_wide
        , cf.identifier_label is null as label_missing
        , rf.cost_value is null as cost_missing
        , wf.accession is not null as in_whole_filing
        , rf.no_principal and rf.shares_value > 0 as par_candidate
        , case
            when rf.cost_value > 0 and rf.shares_value between 0.8 * rf.cost_value and 1.25 * rf.cost_value then 1.0
            when rf.cost_value > 0 and rf.shares_value * 1000 between 0.8 * rf.cost_value and 1.25 * rf.cost_value then 1000.0
            when rf.cost_value > 0 and rf.shares_value * 1000000 between 0.8 * rf.cost_value and 1.25 * rf.cost_value
                then 1000000.0
          end as near_scale
        , case
            when rf.cost_value > 0 and rf.shares_value between 0.5 * rf.cost_value and 2.0 * rf.cost_value then 1.0
            when rf.cost_value > 0 and rf.shares_value * 1000 between 0.5 * rf.cost_value and 2.0 * rf.cost_value then 1000.0
            when rf.cost_value > 0 and rf.shares_value * 1000000 between 0.5 * rf.cost_value and 2.0 * rf.cost_value
                then 1000000.0
          end as wide_scale
    from row_feature rf
    join {{ ref('int_context_feature') }} cf on cf.accession = rf.accession and cf.context_id = rf.context_id
    left join whole_filing wf on wf.cik = rf.cik and wf.accession = rf.accession
)

, field_row as (
    -- the five read fields with every domain flag
    select
        r.accession
        , r.context_id
        , r.field
        , r.cik
        , r.report_date
        , r.unit_kind
        , t.context_id is not null as is_two_unit_cost
        , p.no_principal
        , p.par_candidate
        , p.has_debt_term
        , p.is_rated
        , p.names_equity
        , p.names_equity_wide
        , p.in_whole_filing
        , p.near_scale
        , p.wide_scale
        , p.label_missing
        , p.cost_missing
        , p.no_shares and p.principal_positive and not p.has_debt_term as principal_as_units
        , s.context_id is not null as sign_differs
        , su.context_id is not null as sign_unplaced
    from read r
    join par_feature p on p.accession = r.accession and p.context_id = r.context_id
    left join two_unit_cost t on t.accession = r.accession and t.context_id = r.context_id
    left join sign_differs s on s.accession = r.accession and s.context_id = r.context_id and s.field = r.field
    left join sign_unplaced su on su.accession = r.accession and su.context_id = r.context_id and su.field = r.field
)

, fund_rule as (
    select
        r.rule_id
        , r.cik
        , r.action
        , r.parameter
        , r.sel_accession
        , r.valid_from
        , r.valid_to
        , r.priority
        , r.origin
        , af.field
        , af.applies_to
    from {{ ref('stg_reading_rule') }} r
    join {{ ref('action_field') }} af on af.action = r.action
)

, default_rule as (
    select
        rule_id
        , cast(null as varchar) as cik
        , action
        , nullif(cast(parameter as varchar), '') as parameter
        , cast(null as varchar) as sel_accession
        , cast(null as date) as valid_from
        , cast(null as date) as valid_to
        , priority
        , 'global_default' as origin
        , field
        , applies_to
    from {{ ref('field_rule_default') }}
)

, rule_set as (
    select * from fund_rule
    union all
    select * from default_rule
)

, matched as (
    -- every rule that matches a row of the five read fields, with the scale a value-size rule chose
    select
        f.accession
        , f.context_id
        , f.field
        , f.cik
        , f.report_date
        , r.rule_id
        , r.action
        , r.parameter
        , r.origin
        , r.priority
        -- step 2 of the ranking: at the same priority a rule naming a filing outranks one naming only a row feature
        , r.priority + case when r.sel_accession is not null then 1 else 0 end as specificity
        , case when r.applies_to = 'shares_as_par' then
            case r.parameter
                when 'whole_filing' then case when f.has_debt_term then 1.0 end
                when 'listed_rows_without_instrument' then
                    case when f.in_whole_filing and not f.has_debt_term and not f.names_equity_wide then 1.0 end
                when 'rows_near_cost' then case when f.has_debt_term and not f.names_equity then f.near_scale end
                when 'rated_rows_near_cost' then case when f.is_rated and not f.names_equity then f.near_scale end
                when 'rows_within_twice_cost' then case when f.has_debt_term and not f.names_equity then f.wide_scale end
            end
          end as value_scale
        -- the rule's other tests let the row through, but a feature it needs is null (spec section 5 rule 2)
        , coalesce(case r.applies_to
            when 'shares_as_par' then f.par_candidate and case r.parameter
                when 'listed_rows_without_instrument' then f.in_whole_filing and not f.has_debt_term and f.label_missing
                when 'rows_near_cost' then f.has_debt_term and (f.label_missing or f.cost_missing)
                when 'rated_rows_near_cost' then f.is_rated and (f.label_missing or f.cost_missing)
                when 'rows_within_twice_cost' then f.has_debt_term and (f.label_missing or f.cost_missing)
                else false
              end
            when 'sign_differs_from_print' then f.sign_unplaced
            else false
          end, false) as is_undecidable
        , r.applies_to
        , f.par_candidate
        , f.unit_kind
        , f.is_two_unit_cost
        , f.no_principal
        , f.principal_as_units
        , f.sign_differs
    from field_row f
    join rule_set r
        on r.field = f.field
        and (r.cik is null or r.cik = f.cik)
        and (r.sel_accession is null or r.sel_accession = f.accession)
        and (r.valid_from is null or r.valid_from <= f.report_date)
        and (r.valid_to is null or r.valid_to >= f.report_date)
)

, applicable as (
    select *
    from matched
    where is_undecidable
       or case applies_to
            when 'unit_usd' then unit_kind = 'usd'
            when 'unit_foreign' then unit_kind = 'foreign'
            when 'unit_shares' then unit_kind = 'shares'
            when 'unit_pure' then unit_kind = 'pure'
            when 'two_unit_cost' then is_two_unit_cost
            when 'two_unit_cost_principal_absent' then is_two_unit_cost and no_principal
            when 'shares_as_par' then par_candidate and value_scale is not null
            when 'principal_as_units' then principal_as_units
            when 'sign_differs_from_print' then sign_differs
            else false
          end
)

, ranked as (
    select
        *
        , count(*) over (partition by accession, context_id, field) as candidate_count
        , count(*) over (partition by accession, context_id, field, specificity) as same_rank_count
        , bool_or(is_undecidable) over (partition by accession, context_id, field, specificity) as rank_undecidable
        , rank() over (partition by accession, context_id, field order by specificity desc) as rank_at
    from applicable
)

, top as (
    -- the winning rule; a conflict when two remain at the top; feature_missing when a top candidate cannot be decided
    select
        accession
        , context_id
        , field
        , case
            when rank_undecidable then 'feature_missing'
            when same_rank_count = 1 then 'rule'
            else 'rule_conflict'
          end as resolution
        , rule_id
        , action
        , parameter
        , origin
        , priority
        , specificity
        , value_scale
        , candidate_count
    from ranked
    where rank_at = 1
    qualify row_number() over (partition by accession, context_id, field order by rule_id) = 1
)

, tie_break as (
    -- rules the winner beat only by step 2 (same priority, it names a filing and they do not)
    select
        t.accession
        , t.context_id
        , t.field
        , count(*) as tie_break_losers
        -- final fix wave F3: a loser that cannot be decided (a feature it needs is missing, so no scale) is left out
        -- of the comparison, not counted as a different effect; null when no loser can be decided
        , bool_and(l.action = t.action and l.value_scale is not distinct from t.value_scale)
            filter (where not l.is_undecidable) as tie_break_same_effect
    from top t
    join ranked l
        on l.accession = t.accession and l.context_id = t.context_id and l.field = t.field
        and l.priority = t.priority and l.specificity < t.specificity
    where t.resolution = 'rule'
    group by 1, 2, 3
)

, five as (
    select
        r.accession
        , r.context_id
        , r.field
        , r.cik
        , r.report_date
        , case when t.resolution = 'rule' then t.rule_id end as rule_id
        , case when t.resolution = 'rule' then t.action end as action
        , case when t.resolution = 'rule' then t.parameter end as parameter
        , case when t.resolution = 'rule' then t.origin end as origin
        , t.priority
        , coalesce(t.candidate_count, 0) as candidate_count
        , coalesce(t.resolution, 'no_rule') as resolution
        , case when t.resolution = 'rule' then t.value_scale end as value_scale
        , coalesce(tb.tie_break_losers, 0) as tie_break_losers
        , tb.tie_break_same_effect
    from read r
    left join top t on t.accession = r.accession and t.context_id = r.context_id and t.field = r.field
    left join tie_break tb on tb.accession = r.accession and tb.context_id = r.context_id and tb.field = r.field
)

, principal_usd_row as (
    -- principal_amount_usd reads the currency of the principal as resolved: a principal taken from the shares tag is
    -- in dollars (production reads an empty principal unit as USD), one taken from the foreign cost fact is foreign
    select
        f.accession
        , f.context_id
        , f.cik
        , f.report_date
        , case
            when f.resolution <> 'rule' then null
            when f.action = 'par_tagged_as_units' then 'usd'
            when f.action = 'cost_foreign_is_par' then 'foreign'
            when f.action = 'as_filed' then p.principal_unit_kind
          end as principal_kind
    from five f
    join row_feature p on p.accession = f.accession and p.context_id = f.context_id
    where f.field = 'principal_amount'
)

, usd_matched as (
    select
        u.accession
        , u.context_id
        , r.rule_id
        , r.action
        , r.parameter
        , r.origin
        , r.priority
        , r.priority + case when r.sel_accession is not null then 1 else 0 end as specificity
    from principal_usd_row u
    join rule_set r
        on r.field = 'principal_amount_usd'
        and (r.cik is null or r.cik = u.cik)
        and (r.sel_accession is null or r.sel_accession = u.accession)
        and (r.valid_from is null or r.valid_from <= u.report_date)
        and (r.valid_to is null or r.valid_to >= u.report_date)
        and ((r.applies_to = 'principal_usd' and u.principal_kind = 'usd')
             or (r.applies_to = 'principal_foreign' and u.principal_kind = 'foreign'))
)

, usd_top as (
    select
        accession
        , context_id
        , case when same_rank_count = 1 then rule_id end as rule_id
        , case when same_rank_count = 1 then action end as action
        , case when same_rank_count = 1 then parameter end as parameter
        , case when same_rank_count = 1 then origin end as origin
        , priority
        , candidate_count
        , case when same_rank_count = 1 then 'rule' else 'rule_conflict' end as resolution
    from (
        select
            *
            , count(*) over (partition by accession, context_id) as candidate_count
            , count(*) over (partition by accession, context_id, specificity) as same_rank_count
            , rank() over (partition by accession, context_id order by specificity desc) as rank_at
        from usd_matched
    )
    where rank_at = 1
    qualify row_number() over (partition by accession, context_id order by rule_id) = 1
)

select * from five
union all
select
    u.accession
    , u.context_id
    , 'principal_amount_usd' as field
    , u.cik
    , u.report_date
    , t.rule_id
    , t.action
    , t.parameter
    , t.origin
    , t.priority
    , coalesce(t.candidate_count, 0) as candidate_count
    , coalesce(t.resolution, 'no_rule') as resolution
    , cast(null as double) as value_scale
    -- no rule for principal_amount_usd names a filing today; tests/int_field_rule_tie_break_usd.sql keeps it so
    , 0 as tie_break_losers
    , cast(null as boolean) as tie_break_same_effect
from principal_usd_row u
left join usd_top t on t.accession = u.accession and t.context_id = u.context_id
