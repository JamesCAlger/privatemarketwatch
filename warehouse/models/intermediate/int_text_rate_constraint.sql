-- Owner addition A, constraints 4 and 5 on the read model (text slice R phase 3, 2026-11-26): relationships between the
-- fields of int_text_rate_read and another source. Failures are reported (tests/baseline_int_text_rate_constraint_fail
-- lists them), never used to drop a value. Constraints 1 to 3 are applied inside int_text_rate_read (a reading that
-- breaks them is not applied) and tested on its output (tests/int_text_rate_read_constraints.sql).
-- One row per (accession, context_id, constraint_name) where the constraint applies.
--
--   c4_legs        all-in = cash + PIK, where the position reads all three (read values only), within var
--                  text_legs_tolerance (the leg check's tolerance). rule_ids: the three fields' rules.
--   c5_base_level  the reference rate has a series (seed reference_rate.series_id; the window is that series' rate in
--                  seed base_rate_series, so CDOR is judged on the CORRA proxy and BBSY on the BBSW one, by lookup)
--                  and the window at the report date is usable: implied base = all-in - spread is judged by macro
--                  base_level_verdict (the same verdict int_text_check_base_level uses; floor respected through
--                  floor_binding). all-in: the read all-in rate, else the all-in tag (all_in_source). Not tested
--                  (input_state): a PIK leg (read PIK rate or PIK spread, or a PIK tag above 0: whether the spread
--                  holds it differs by filer), no spread read, no all-in, the all-in TAG equals the spread or the
--                  floor alone (all_in_tag_is_leg: the phase 3 check fix 1a mechanism, the tag holds another leg), or
--                  no series for the rate.
-- verdict: pass / fail for c4; for c5 pass (admissible or floor_binding), fail (outside), not_tested, no_series.
with r as (
    select * from {{ ref('int_text_rate_read') }}
)

, pik_tag as (
    select accession, context_id, max(value) as t_pik
    from {{ ref('int_field_normalised') }}
    where field = 'pik_rate' and status = 'normalised' and value is not null
    group by 1, 2
)

, c4 as (
    select accession, context_id, cik, report_date, is_published, 'c4_legs' as constraint_name
        , reference_rate, cash_rate + pik_rate as lhs, all_in_rate as rhs
        , case when abs(cash_rate + pik_rate - all_in_rate) <= {{ var('text_legs_tolerance') }} then 'pass' else 'fail' end
            as verdict
        , 'read' as all_in_source, null::varchar as base_verdict, null::double as implied_base, null::double as range_min
        , null::double as range_max
        , [all_in_rate_rule_id, cash_rate_rule_id, pik_rate_rule_id] as rule_ids
        , null::varchar as input_state
    from r
    where all_in_rate is not null and cash_rate is not null and pik_rate is not null
)

, c5_in as (
    select r.*, s.rate_name as window_rate
        , coalesce(r.all_in_rate, r.all_in_rate_tag) as all_in
        , case when r.all_in_rate is not null then 'read' when r.all_in_rate_tag is not null then 'tag' end as all_in_src
        , case
            when r.pik_rate is not null or r.pik_spread is not null or coalesce(pt.t_pik, 0) > 0 then 'pik'
            when r.spread is null then 'no_spread'
            when coalesce(r.all_in_rate, r.all_in_rate_tag) is null then 'no_all_in'
            when r.all_in_rate is null
                 and (abs(r.all_in_rate_tag - r.spread) <= {{ var('text_legs_tolerance') }}
                      or abs(r.all_in_rate_tag - r.floor) <= {{ var('text_legs_tolerance') }}) then 'all_in_tag_is_leg'
            when s.rate_name is null then 'no_series_for_rate'
            else 'usable'
          end as input_state
    from r
    left join {{ ref('reference_rate') }} rr on rr.rate_name = r.reference_rate
    left join {{ ref('base_rate_series') }} s on s.series_id = rr.series_id
    left join pik_tag pt on pt.accession = r.accession and pt.context_id = r.context_id
    where r.reference_rate is not null
)

, c5 as (
    select c.accession, c.context_id, c.cik, c.report_date, c.is_published, 'c5_base_level' as constraint_name
        , c.reference_rate, c.all_in - c.spread as lhs, null::double as rhs
        , null::varchar as verdict
        , c.all_in_src as all_in_source
        , {{ base_level_verdict("c.input_state = 'usable'", 'w.state', 'c.all_in - c.spread', 'w.admissible_low',
                                'w.admissible_high', 'c.floor') }} as base_verdict
        , c.all_in - c.spread as implied_base, w.range_min, w.range_max
        , [c.reference_rate_rule_id, c.spread_rule_id, c.all_in_rate_rule_id, c.floor_rule_id] as rule_ids
        , c.input_state
    from c5_in c
    left join {{ ref('int_text_base_rate_window') }} w on w.report_date = c.report_date and w.rate_name = c.window_rate
)

select
    accession, context_id, cik, report_date, is_published, constraint_name, reference_rate, lhs, rhs
    , case
        when constraint_name = 'c4_legs' then verdict
        when base_verdict in ('admissible', 'floor_binding') then 'pass'
        when base_verdict = 'outside' then 'fail'
        else base_verdict
      end as verdict
    , base_verdict, implied_base, range_min, range_max, all_in_source, input_state
    , list_filter(rule_ids, x -> x is not null) as rule_ids
from (select * from c4 union all by name select * from c5)
