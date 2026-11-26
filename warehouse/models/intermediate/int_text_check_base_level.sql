-- Tests the level of the base rate each position implies against the public series of the rate the PROPOSED code
-- mapping names, and against every other rate (text slice R phase 2, 2026-11-26). A measurement of the proposals; it
-- publishes nothing. One row per (accession, context_id, candidate_rate).
--
-- Positions: int_text_rate_proposed_position rows whose read code gives a rate_name (a proposed mapping, stable in both
-- orders, to a rate with a series). input_state, the first that applies:
--   pik            a PIK leg exists (tagged PIK rate above 0, a printed PIK rate above 0, or a printed PIK spread): the
--                  all-in rate holds a PIK part, and whether the spread includes it differs by filer, so no base is
--                  implied.
--   no_spread      neither a printed spread (proposal) nor a tagged spread.
--   no_all_in      neither a tagged all-in rate nor a printed all-in rate (proposal).
--   all_in_tag_is_leg  (phase 3 check fix 1a) the all-in TAG equals the spread or the printed floor alone (within
--                  var text_legs_tolerance): the tag holds another leg, so it implies a base of zero (or base =
--                  spread - floor) that tests nothing. The same mechanism as identity d of int_text_check_leg_arithmetic.
--                  Fix round 1 (phase 3): only where no printed all-in rate agrees with the tag; where the print
--                  agrees, the tag is the all-in rate and a zero base is a real reading (EURIBOR 2022, SARON 2025-26)
--                  or a real contradiction, so the row is tested.
--   usable
-- spread = printed (proposal) else tag; all_in = tag else printed (the tagged all-in is the filer's number; a printed
-- one is used where the filer tags none). spread_source, all_in_source say which. implied_base = all_in - spread.
-- Candidate rates: for a usable position, every rate of int_text_base_rate_window at its report date (the proposed one
-- and each alternative); for any other position, the proposed rate only, verdict not_tested.
-- Against a candidate's window (int_text_base_rate_window): distance = implied_base - range_min when below the range,
-- implied_base - range_max when above, 0 inside (before any tolerance: the measurement the tolerances are set from).
-- verdict, the first that applies:
--   not_tested     input_state is not usable.
--   no_series      the window has no value or is stale (window state).
--   admissible     admissible_low <= implied_base <= admissible_high (the window's range widened by its tolerance; SOFR
--                  also by the credit spread adjustment on the upper edge).
--   floor_binding  outside, and a printed floor exists with abs(implied_base - floor) <= var text_floor_match (0.05):
--                  the base the loan pays is its floor. Applied above and below the range: a floor above every value of
--                  the window (2022, rates near zero) puts the implied base above the range.
--   outside
-- proposed_series: the series rate the proposed rate is judged against. Mapping proxy_series (fix round 1), the only
-- place it exists: CDOR -> CORRA, BBSY -> BBSW (each pair has one public series, the same OECD proxy); every other
-- rate is its own series. Everywhere else CDOR, CORRA, BBSY and BBSW are four rates.
-- is_proposed: the candidate is the proposed rate's series. code_unit_key, code: the proposal (the column unit and the code)
-- int_text_check_base_level_quarter groups by.
with proxy_series(rate_name, series_rate) as (
    -- the only place CDOR and BBSY meet CORRA and BBSW: their one public series is the same OECD proxy
    values ('CDOR', 'CORRA'), ('BBSY', 'BBSW')
)

, pos as (
    select
        accession, context_id, cik, report_date, is_published, rate_name as proposed_rate
        , coalesce((select series_rate from proxy_series ps where ps.rate_name = p.rate_name), rate_name) as proposed_series
        , code, code_unit_key
        , code_shape_key, p_floor as floor
        , coalesce(p_spread, t_spread) as spread
        , case when p_spread is not null then 'printed' when t_spread is not null then 'tag' end as spread_source
        , coalesce(t_all_in, p_all_in_rate) as all_in
        , case when t_all_in is not null then 'tag' when p_all_in_rate is not null then 'printed' end as all_in_source
        , case
            when coalesce(t_pik, 0) > 0 or coalesce(p_pik_rate, 0) > 0 or p_pik_spread is not null then 'pik'
            when coalesce(p_spread, t_spread) is null then 'no_spread'
            when coalesce(t_all_in, p_all_in_rate) is null then 'no_all_in'
            when t_all_in is not null
                 and (p_all_in_rate is null or abs(p_all_in_rate - t_all_in) > {{ var('text_legs_tolerance') }})
                 and (abs(t_all_in - coalesce(p_spread, t_spread)) <= {{ var('text_legs_tolerance') }}
                      or abs(t_all_in - p_floor) <= {{ var('text_legs_tolerance') }}) then 'all_in_tag_is_leg'
            else 'usable'
          end as input_state
    from {{ ref('int_text_rate_proposed_position') }} p
    where rate_name is not null
)

, candidate as (
    select p.*, w.rate_name as candidate_rate
    from pos p
    join {{ ref('int_text_base_rate_window') }} w on w.report_date = p.report_date
    where p.input_state = 'usable' or w.rate_name = p.proposed_series
)

, measured as (
    select c.*
        , c.all_in - c.spread as implied_base
        , w.range_min, w.range_max, w.admissible_low, w.admissible_high, w.tolerance, w.upper_extra, w.kind
        , w.state as window_state
    from candidate c
    join {{ ref('int_text_base_rate_window') }} w on w.report_date = c.report_date and w.rate_name = c.candidate_rate
)

select
    accession
    , context_id
    , cik
    , report_date
    , is_published
    , code_unit_key
    , code_shape_key
    , code
    , proposed_rate
    , candidate_rate
    , proposed_series
    , candidate_rate = proposed_series as is_proposed
    , input_state
    , spread
    , spread_source
    , all_in
    , all_in_source
    , floor
    , case when input_state = 'usable' then implied_base end as implied_base
    , kind as series_kind
    , range_min
    , range_max
    , tolerance
    , upper_extra
    , case when input_state = 'usable' and window_state = 'ok' then
        case when implied_base < range_min then implied_base - range_min
             when implied_base > range_max then implied_base - range_max
             else 0 end
      end as distance
    , {{ base_level_verdict("input_state = 'usable'", 'window_state', 'implied_base', 'admissible_low',
                            'admissible_high', 'floor') }} as verdict
from measured
