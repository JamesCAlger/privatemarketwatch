-- The printed rate terms of each position, read with the ACCEPTED rate-text rules (text slice R phase 3, 2026-11-26).
-- Publishes nowhere outside the warehouse: no spine, staging, cmp or mart model reads it (pytest
-- test_text_models_no_production.py). One row per position with at least one cell in a ruled column
-- (int_text_rate_read_cell): (accession, context_id).
--
-- Fields: reference_rate, spread, floor, all_in_rate, cash_rate, pik_rate, pik_spread; rate_type. For each field F:
--   F             the value after every step below (null when unread); F_rule_id, F_grade: the rule that gave it and
--                 its source grade (checked, matches_few_rows, owner, untested); F_status, the first that applies:
--     not_printed                       no read cell gives F.
--     conflict                          two read cells give values more than var text_number_tolerance apart (for
--                                       reference_rate: two rates).
--     constraint_spread_needs_reference_rate (spread, pik_spread)  owner addition A1: a spread with no reference rate
--                                       read on the position is not applied. F_detail: code_printed_unread when the row
--                                       prints a code no rule read, no_code otherwise.
--     constraint_floor_needs_reference_rate (floor)  A2.
--     constraint_fixed_with_floating_terms (all_in_rate from a fixed rate)  A3: a fixed-rate reading on a position
--                                       that also reads a reference rate, spread or floor is not applied.
--     differs_from_tag                  the printed value differs from the filer's tag of the same field by more than
--                                       var text_number_tolerance (the tag first: slice A ruling; the row is listed,
--                                       not read). Tags: int_field_normalised status normalised, before corrections:
--                                       spread -> spread; all_in_rate -> interest_rate (rate_kind all_in); pik_rate and
--                                       pik_spread -> pik_rate. reference_rate, floor and cash_rate have no compared tag
--                                       (the cash tag is derived by the spine for most filers).
--     printed_wins_over_tag             as differs_from_tag, but a rate_printed_wins rule covers the field, filing,
--                                       table and printed row: the printed value is kept (one filing's shifted rate tags, 2022-09-30).
--     read_equals_tag / read_no_tag     read; the tag equals it / no tag exists.
--   F_tag: the tag compared.
-- all_in_rate: the all-in reading (all_in_rate_pct) and the fixed reading (fixed_rate_pct) together: a fixed rate is the
-- all-in rate of a fixed-rate loan. all_in_source: all_in, fixed, or both (two readings that agree); pik_coupon (fix
-- round 1, owner item 9) when the only all-in reading is a whole-coupon PIK number (a rate_role rule with whole_coupon:
-- "10.00% PIK" in an all-in column), which is then the all-in rate and the PIK rate; no cash rate is written.
-- Fix round 1 item 1: constraints 1 and 2 count a printed code as a reference rate even when no rule resolves it
-- (code_printed); the reference rate is then unread with status code_undecided and reference_rate_detail giving the
-- cell status (legend_two_rates, code_no_rule, ...). Only a position with no code printed at all loses its spread or
-- floor. Item 5: a printed_wins_over_tag all-in rate takes the grade of the printed_wins rule (owner).
-- rate_type: fixed where the fixed reading is applied; floating where a reference rate and a spread (or PIK spread)
-- are applied; null otherwise (no type is invented from anything else).
-- Readings of number cells with no rule, and code cells no rule reads, stay unread here; int_text_rate_read_cell holds
-- them with their status and tests/baseline_int_text_rate_unread.sql lists them by shape.
{% set num_fields = ['spread', 'floor', 'all_in_rate', 'cash_rate', 'pik_rate', 'pik_spread', 'fixed_rate'] %}
{% set tol = var('text_number_tolerance') %}
with cell as (
    select * from {{ ref('int_text_rate_read_cell') }}
)

, position as (
    select accession, context_id, min(cik) as cik, min(report_date) as report_date, bool_or(is_published) as is_published
        , min(table_index) as table_index, min(row_index) as row_index
        , bool_or(field = 'reference_rate' and status <> 'read' and status <> 'not_a_code') as code_printed_unread
        , bool_or(field = 'reference_rate' and status <> 'not_a_code') as code_printed
        , string_agg(distinct status, ',') filter (where field = 'reference_rate' and status not in ('read', 'not_a_code'))
            as code_statuses
    from cell
    group by 1, 2
)

, num as (
    select accession, context_id
    {%- for f in num_fields %}
        {%- set cond = "(field = 'all_in_rate' or (field = 'pik_rate' and whole_coupon))" if f == 'all_in_rate' else "field = '" ~ f ~ "'" %}
        , min(value) filter (where {{ cond }} and status = 'read') as min_{{ f }}
        , max(value) filter (where {{ cond }} and status = 'read') as max_{{ f }}
        , arg_min(rule_id, grade_rank::varchar || rule_id) filter (where {{ cond }} and status = 'read') as rule_{{ f }}
        , min(grade_rank) filter (where {{ cond }} and status = 'read') as rank_{{ f }}
    {%- endfor %}
        , count(*) filter (where field = 'all_in_rate' and status = 'read') as n_all_in_printed
        , count(distinct reference_rate) filter (where field = 'reference_rate' and status = 'read') as n_rates
        , min(reference_rate) filter (where field = 'reference_rate' and status = 'read') as reference_rate
        , arg_min(rule_id, grade_rank::varchar || rule_id) filter (where field = 'reference_rate' and status = 'read') as rule_reference_rate
        , min(grade_rank) filter (where field = 'reference_rate' and status = 'read') as rank_reference_rate
    from cell
    group by 1, 2
)

, printed as (
    select n.accession, n.context_id
    {%- for f in num_fields %}
        , case when n.max_{{ f }} - n.min_{{ f }} <= {{ tol }} then n.min_{{ f }} end as p_{{ f }}
        , n.max_{{ f }} - n.min_{{ f }} > {{ tol }} as conflict_{{ f }}
        , n.rule_{{ f }}, n.rank_{{ f }}
    {%- endfor %}
        , case when n.n_rates = 1 then n.reference_rate end as p_reference_rate
        , n.n_rates > 1 as conflict_reference_rate
        , n.rule_reference_rate, n.rank_reference_rate, n.n_all_in_printed
    from num n
)

-- all-in and fixed together; constraints A1 to A3 on the rules' output
, constrained as (
    select p.*, pos.cik, pos.report_date, pos.is_published, pos.table_index, pos.row_index, pos.code_printed_unread
        , pos.code_printed, pos.code_statuses
        -- fix round 1 item 1: a printed code counts as a reference rate for constraints 1 and 2 even when no rule
        -- resolves it; the reference rate itself stays unread (status code_undecided)
        , p.p_reference_rate is not null or coalesce(pos.code_printed, false) as has_rate
        , p.p_fixed_rate is not null
            and (p.p_reference_rate is not null or coalesce(pos.code_printed, false) or p.p_spread is not null or p.p_floor is not null
                 or p.p_pik_spread is not null) as fixed_broken
    from printed p
    join position pos on pos.accession = p.accession and pos.context_id = p.context_id
)

, tag as (
    select accession, context_id
        , any_value(value) filter (where field = 'spread') as t_spread
        , any_value(value) filter (where field = 'interest_rate' and rate_kind = 'all_in') as t_all_in
        , any_value(value) filter (where field = 'pik_rate') as t_pik
    from {{ ref('int_field_normalised') }}
    where field in ('spread', 'interest_rate', 'pik_rate') and status = 'normalised' and value is not null
    group by 1, 2
)

, wins as (
    select c.accession, c.context_id, r.field, min(r.rule_id) as rule_id, min(r.grade_rank) as grade_rank
    from constrained c
    join {{ ref('int_text_rate_rule') }} r
        on r.action = 'rate_printed_wins' and r.cik = c.cik and r.accession = c.accession
        and r.table_index = c.table_index and c.row_index between r.first_row and r.last_row
    group by 1, 2, 3
)

, decided as (
    select c.*, t.t_spread, t.t_all_in, t.t_pik
        -- all-in: the all-in reading, else the applied fixed reading
        , case when c.p_all_in_rate is not null and c.p_fixed_rate is not null and not c.fixed_broken
                    and abs(c.p_all_in_rate - c.p_fixed_rate) > {{ tol }} then true else false end as conflict_all_in_fixed
        , coalesce(c.p_all_in_rate, case when not c.fixed_broken then c.p_fixed_rate end) as v_all_in
        , case when c.p_all_in_rate is not null and c.p_fixed_rate is not null and not c.fixed_broken then 'both'
               when c.p_all_in_rate is not null and c.n_all_in_printed = 0 then 'pik_coupon'
               when c.p_all_in_rate is not null then 'all_in'
               when c.p_fixed_rate is not null and not c.fixed_broken then 'fixed' end as all_in_source
        , case when c.p_all_in_rate is not null then c.rule_all_in_rate
               when not c.fixed_broken then c.rule_fixed_rate end as rule_all_in
        , case when c.p_all_in_rate is not null then least(c.rank_all_in_rate, coalesce(c.rank_fixed_rate, 9))
               when not c.fixed_broken then c.rank_fixed_rate end as rank_all_in
        , w_all.rule_id as wins_all_in_rule, w_all.grade_rank as wins_all_in_rank
    from constrained c
    left join tag t on t.accession = c.accession and t.context_id = c.context_id
    left join wins w_all on w_all.accession = c.accession and w_all.context_id = c.context_id
        and w_all.field = 'all_in_rate'
)

, statused as (
    select d.*
        , case when d.conflict_reference_rate then 'conflict'
               when d.p_reference_rate is null and d.code_printed_unread then 'code_undecided'
               when d.p_reference_rate is null then 'not_printed'
               else 'read_no_tag' end as reference_rate_status
        , case when d.conflict_spread then 'conflict' when d.p_spread is null then 'not_printed'
               when not d.has_rate then 'constraint_spread_needs_reference_rate'
               when d.t_spread is not null and abs(d.p_spread - d.t_spread) > {{ tol }} then 'differs_from_tag'
               when d.t_spread is not null then 'read_equals_tag' else 'read_no_tag' end as spread_status
        , case when d.conflict_pik_spread then 'conflict' when d.p_pik_spread is null then 'not_printed'
               when not d.has_rate then 'constraint_spread_needs_reference_rate'
               when d.t_pik is not null and abs(d.p_pik_spread - d.t_pik) > {{ tol }} then 'differs_from_tag'
               when d.t_pik is not null then 'read_equals_tag' else 'read_no_tag' end as pik_spread_status
        , case when d.conflict_floor then 'conflict' when d.p_floor is null then 'not_printed'
               when not d.has_rate then 'constraint_floor_needs_reference_rate'
               else 'read_no_tag' end as floor_status
        , case when d.conflict_all_in_rate or d.conflict_fixed_rate or d.conflict_all_in_fixed then 'conflict'
               when d.p_all_in_rate is null and d.p_fixed_rate is not null and d.fixed_broken
                    then 'constraint_fixed_with_floating_terms'
               when d.v_all_in is null then 'not_printed'
               when d.t_all_in is not null and abs(d.v_all_in - d.t_all_in) > {{ tol }} and d.wins_all_in_rule is not null
                    then 'printed_wins_over_tag'
               when d.t_all_in is not null and abs(d.v_all_in - d.t_all_in) > {{ tol }} then 'differs_from_tag'
               when d.t_all_in is not null then 'read_equals_tag' else 'read_no_tag' end as all_in_rate_status
        , case when d.conflict_cash_rate then 'conflict' when d.p_cash_rate is null then 'not_printed'
               else 'read_no_tag' end as cash_rate_status
        , case when d.conflict_pik_rate then 'conflict' when d.p_pik_rate is null then 'not_printed'
               when d.t_pik is not null and abs(d.p_pik_rate - d.t_pik) > {{ tol }} then 'differs_from_tag'
               when d.t_pik is not null then 'read_equals_tag' else 'read_no_tag' end as pik_rate_status
    from decided d
)

{% set grade_of = "case {} when 1 then 'checked' when 2 then 'matches_few_rows' when 3 then 'owner' when 4 then 'untested' end" %}
{% set applied = "in ('read_no_tag', 'read_equals_tag', 'printed_wins_over_tag')" %}
select
    accession
    , context_id
    , cik
    , report_date
    , is_published
    , table_index
    , row_index
    , case when reference_rate_status {{ applied }} then p_reference_rate end as reference_rate
    , case when reference_rate_status {{ applied }} then rule_reference_rate end as reference_rate_rule_id
    , case when reference_rate_status {{ applied }} then {{ grade_of.format('rank_reference_rate') }} end
        as reference_rate_grade
    , reference_rate_status
    , code_printed
    , case when reference_rate_status = 'code_undecided' then code_statuses end as reference_rate_detail
    , case when spread_status {{ applied }} then p_spread end as spread
    , case when spread_status {{ applied }} then rule_spread end as spread_rule_id
    , case when spread_status {{ applied }} then {{ grade_of.format('rank_spread') }} end as spread_grade
    , spread_status
    , case when spread_status like 'constraint%' then case when code_printed_unread then 'code_printed_unread'
                                                             else 'no_code' end end as spread_detail
    , t_spread as spread_tag
    , case when floor_status {{ applied }} then p_floor end as floor
    , case when floor_status {{ applied }} then rule_floor end as floor_rule_id
    , case when floor_status {{ applied }} then {{ grade_of.format('rank_floor') }} end as floor_grade
    , floor_status
    , case when all_in_rate_status {{ applied }} then v_all_in end as all_in_rate
    , case when all_in_rate_status = 'printed_wins_over_tag' then wins_all_in_rule
           when all_in_rate_status {{ applied }} then rule_all_in end as all_in_rate_rule_id
    , case when all_in_rate_status = 'printed_wins_over_tag' then {{ grade_of.format('wins_all_in_rank') }}
           when all_in_rate_status {{ applied }} then {{ grade_of.format('rank_all_in') }} end as all_in_rate_grade
    , all_in_rate_status
    , all_in_source
    , t_all_in as all_in_rate_tag
    , case when cash_rate_status {{ applied }} then p_cash_rate end as cash_rate
    , case when cash_rate_status {{ applied }} then rule_cash_rate end as cash_rate_rule_id
    , case when cash_rate_status {{ applied }} then {{ grade_of.format('rank_cash_rate') }} end as cash_rate_grade
    , cash_rate_status
    , case when pik_rate_status {{ applied }} then p_pik_rate end as pik_rate
    , case when pik_rate_status {{ applied }} then rule_pik_rate end as pik_rate_rule_id
    , case when pik_rate_status {{ applied }} then {{ grade_of.format('rank_pik_rate') }} end as pik_rate_grade
    , pik_rate_status
    , t_pik as pik_rate_tag
    , case when pik_spread_status {{ applied }} then p_pik_spread end as pik_spread
    , case when pik_spread_status {{ applied }} then rule_pik_spread end as pik_spread_rule_id
    , case when pik_spread_status {{ applied }} then {{ grade_of.format('rank_pik_spread') }} end as pik_spread_grade
    , pik_spread_status
    , case
        when all_in_rate_status {{ applied }} and all_in_source in ('fixed', 'both') then 'fixed'
        when reference_rate_status {{ applied }}
             and (spread_status {{ applied }} or pik_spread_status {{ applied }}) then 'floating'
      end as rate_type
    , case
        when all_in_rate_status {{ applied }} and all_in_source in ('fixed', 'both') then rule_fixed_rate
        when reference_rate_status {{ applied }} and spread_status {{ applied }} then rule_spread
        when reference_rate_status {{ applied }} and pik_spread_status {{ applied }} then rule_pik_spread
      end as rate_type_rule_id
from statused
