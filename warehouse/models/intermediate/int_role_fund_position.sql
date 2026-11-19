-- Decides which open contexts a fund rule declares positions although they carry no term fact (owner decision D15:
-- a fund's own JV or fund interest, equity with no units tagged, a zero-value undrawn revolver). int_source_row uses
-- the match only where a row would otherwise be unresolved for want of a term fact (rules 7 and 9); it never overrides
-- rules 0 to 6, a cash row, or two scopes.
--
-- Rules come from stg_reading_rule, action position_without_term_fact, never copied here. A rule applies to its own
-- filer inside its dates (on the report date) and selects on row features only:
--   sel_label_pattern  a regular expression matched in full (case ignored) against the first '|'-segment of the
--                      identifier label, lowercased with white space collapsed (the form int_role_scope compares)
--   sel_feature        optional, from a closed list: fair_value_zero (the context's fair value is 0). Any other
--                      value matches nothing here and fails tests/fund_rule_selectors_supported.sql.
-- A context matched by two rules carries match_count 2 and is left unresolved (spec section 5: two equal matches are
-- an error, not a tie-break; tests/fund_rule_position_one_match.sql).
with open_context as (
    select
        s.accession
        , s.context_id
        , s.cik
        , s.report_date
        , cf.fair_value
        , {{ label_first_segment('cf.identifier_label') }} as first_segment
    from {{ ref('int_role_structure') }} s
    join {{ ref('int_context_feature') }} cf on cf.accession = s.accession and cf.context_id = s.context_id
    where s.role is null
)

, rule as (
    select rule_id, cik, valid_from, valid_to, sel_label_pattern, sel_feature
    from {{ ref('stg_reading_rule') }}
    where action = 'position_without_term_fact'
)

, matched as (
    select o.accession, o.context_id, r.rule_id
    from open_context o
    join rule r on r.cik = o.cik
        and (r.valid_from is null or r.valid_from <= o.report_date)
        and (r.valid_to is null or r.valid_to >= o.report_date)
        and regexp_full_match(o.first_segment, r.sel_label_pattern, 'i')
        and (
            r.sel_feature is null
            or (r.sel_feature = 'fair_value_zero' and o.fair_value = 0)
        )
)

select
    accession
    , context_id
    , min(rule_id) as position_rule_id
    , count(*) as match_count
from matched
group by 1, 2
