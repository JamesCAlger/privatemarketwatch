-- Tests the arithmetic between the rate legs on each position, with the numbers the PROPOSED rules read first and the
-- filer's tags where a part is not printed (text slice R phase 2, 2026-11-26; owner: "rules comparing all-in vs PIK vs
-- cash leg"). A measurement of the proposals; it publishes nothing. One row per (accession, context_id, identity) where
-- the identity applies; a position where it does not apply has no row for it.
--
-- Input: int_text_rate_proposed_position. Each part is the printed value (p_<field>) when the proposals read one, else
-- the tag (t_*): all_in = p_all_in_rate else t_all_in; cash = p_cash_rate else t_cash; pik = p_pik_rate else t_pik;
-- spread = p_spread else t_spread. floor and pik_spread exist only printed (no filer tags them). An identity applies
-- only when every part it needs exists and at least one of them is printed: on tags alone it would test the filer's
-- tags (and, for cash, the spine's own derivation, int_rate_legs_check), not the proposals.
-- Tolerance: var text_legs_tolerance, 0.011 percentage points: printed rates carry two decimals, so two printed parts
-- can be 0.01 apart after rounding; the spine's int_rate_legs_check uses 1e-9 because tags are exact. The leg
-- definitions are the spine's (rate_reading: the cash leg plus the PIK rate equals the all-in rate; a PIK rate above
-- the all-in rate is a fault, pik_above_rate).
-- Identities:
--   a_cash_plus_pik     cash + pik = all_in, within the tolerance.
--   b_pik_le_all_in     pik <= all_in + tolerance.
--   c_cash_le_all_in    cash <= all_in + tolerance.
--   d_floor_spread      floating row (a printed floor): all_in >= margin + floor - tolerance. margin = spread; where the
--                       row has no spread but a printed PIK spread ("S+5.00% PIK"), margin = the PIK spread. A fixed
--                       PIK rate leg is not added to the margin (the all-in rate holds it, so leaving it out only
--                       weakens the test, never fails a right row); a PIK spread next to a cash spread is not added
--                       either, because whether a tagged spread already holds it differs by filer.
--   e_spread_split      a printed spread and a printed PIK spread and a tagged spread: pass when the tag equals spread
--                       + PIK spread (detail equals_total) or the spread alone (equals_cash_spread), fail when neither.
--   f_printed_agree     the position's field is read from two columns (or twice from one cell) and the values differ
--                       by more than var text_number_tolerance: always fail (detail names the fields). Applies only
--                       where some field is read twice.
-- lhs, rhs: the two sides compared (null for f); difference = lhs - rhs. sources: which parts were printed or tagged.
-- shape_keys: the shapes that printed a part used by the identity (for f, the shapes of the disagreeing field); a
-- failure counts against each of them in int_text_proposal_verdict.
with pos as (
    select *
        , coalesce(p_all_in_rate, t_all_in) as all_in
        , coalesce(p_cash_rate, t_cash) as cash
        , coalesce(p_pik_rate, t_pik) as pik
        , coalesce(p_spread, t_spread) as spread
    from (
        select * replace (
            {%- for f in ['spread', 'floor', 'all_in_rate', 'cash_rate', 'pik_rate', 'pik_spread', 'fixed_rate'] %}
            coalesce(conflict_{{ f }}, false) as conflict_{{ f }},
            coalesce(n_{{ f }}, 0) as n_{{ f }},
            coalesce(shapes_{{ f }}, []::varchar[]) as shapes_{{ f }}{{ ',' if not loop.last }}
            {%- endfor %})
        from {{ ref('int_text_rate_proposed_position') }}
    )
)

, a as (
    select accession, context_id, cik, report_date, is_published, 'a_cash_plus_pik' as identity
        , cash + pik as lhs, all_in as rhs
        , abs(cash + pik - all_in) <= {{ var('text_legs_tolerance') }} as passed, null::varchar as detail
        , 'cash=' || case when p_cash_rate is not null then 'printed' else 'tag' end
          || ',pik=' || case when p_pik_rate is not null then 'printed' else 'tag' end
          || ',all_in=' || case when p_all_in_rate is not null then 'printed' else 'tag' end as sources
        , list_distinct(list_concat(case when p_cash_rate is not null then shapes_cash_rate else [] end,
                                    case when p_pik_rate is not null then shapes_pik_rate else [] end,
                                    case when p_all_in_rate is not null then shapes_all_in_rate else [] end)) as shape_keys
    from pos
    where cash is not null and pik is not null and all_in is not null
        and (p_cash_rate is not null or p_pik_rate is not null or p_all_in_rate is not null)
)

, b as (
    select accession, context_id, cik, report_date, is_published, 'b_pik_le_all_in', pik, all_in
        , pik <= all_in + {{ var('text_legs_tolerance') }}, null
        , 'pik=' || case when p_pik_rate is not null then 'printed' else 'tag' end
          || ',all_in=' || case when p_all_in_rate is not null then 'printed' else 'tag' end
        , list_distinct(list_concat(case when p_pik_rate is not null then shapes_pik_rate else [] end,
                                    case when p_all_in_rate is not null then shapes_all_in_rate else [] end))
    from pos
    where pik is not null and all_in is not null and (p_pik_rate is not null or p_all_in_rate is not null)
)

, c as (
    select accession, context_id, cik, report_date, is_published, 'c_cash_le_all_in', cash, all_in
        , cash <= all_in + {{ var('text_legs_tolerance') }}, null
        , 'cash=' || case when p_cash_rate is not null then 'printed' else 'tag' end
          || ',all_in=' || case when p_all_in_rate is not null then 'printed' else 'tag' end
        , list_distinct(list_concat(case when p_cash_rate is not null then shapes_cash_rate else [] end,
                                    case when p_all_in_rate is not null then shapes_all_in_rate else [] end))
    from pos
    where cash is not null and all_in is not null and (p_cash_rate is not null or p_all_in_rate is not null)
)

, d as (
    select accession, context_id, cik, report_date, is_published, 'd_floor_spread', all_in
        , coalesce(spread, p_pik_spread) + p_floor
        , all_in >= coalesce(spread, p_pik_spread) + p_floor - {{ var('text_legs_tolerance') }}
        , case when spread is null then 'margin_is_pik_spread' end
        , 'margin=' || case when p_spread is not null then 'printed' when spread is not null then 'tag'
                            else 'printed_pik_spread' end
          || ',floor=printed,all_in=' || case when p_all_in_rate is not null then 'printed' else 'tag' end
        , list_distinct(list_concat(shapes_floor,
                                    case when p_spread is not null then shapes_spread
                                         when spread is null then shapes_pik_spread else [] end,
                                    case when p_all_in_rate is not null then shapes_all_in_rate else [] end))
    from pos
    where p_floor is not null and all_in is not null and coalesce(spread, p_pik_spread) is not null
)

, e as (
    select accession, context_id, cik, report_date, is_published, 'e_spread_split', t_spread, p_spread + p_pik_spread
        , abs(t_spread - (p_spread + p_pik_spread)) <= {{ var('text_legs_tolerance') }}
            or abs(t_spread - p_spread) <= {{ var('text_legs_tolerance') }}
        , case when abs(t_spread - (p_spread + p_pik_spread)) <= {{ var('text_legs_tolerance') }} then 'equals_total'
               when abs(t_spread - p_spread) <= {{ var('text_legs_tolerance') }} then 'equals_cash_spread'
               else 'equals_neither' end
        , 'spread=printed,pik_spread=printed,total=tag'
        , list_distinct(list_concat(shapes_spread, shapes_pik_spread))
    from pos
    where p_spread is not null and p_pik_spread is not null and t_spread is not null
)

, f as (
    select accession, context_id, cik, report_date, is_published, 'f_printed_agree', null::double, null::double, false
        , concat_ws(',', case when conflict_spread then 'spread' end, case when conflict_floor then 'floor' end,
                    case when conflict_all_in_rate then 'all_in_rate' end, case when conflict_cash_rate then 'cash_rate' end,
                    case when conflict_pik_rate then 'pik_rate' end, case when conflict_pik_spread then 'pik_spread' end,
                    case when conflict_fixed_rate then 'fixed_rate' end)
        , 'printed'
        , list_distinct(list_concat(
            case when conflict_spread then shapes_spread else [] end,
            case when conflict_floor then shapes_floor else [] end,
            case when conflict_all_in_rate then shapes_all_in_rate else [] end,
            case when conflict_cash_rate then shapes_cash_rate else [] end,
            case when conflict_pik_rate then shapes_pik_rate else [] end,
            case when conflict_pik_spread then shapes_pik_spread else [] end,
            case when conflict_fixed_rate then shapes_fixed_rate else [] end))
    from pos
    where conflict_spread or conflict_floor or conflict_all_in_rate or conflict_cash_rate or conflict_pik_rate
        or conflict_pik_spread or conflict_fixed_rate
)

, f_pass as (
    -- positions where some field is read twice and every such field agrees: the identity applies and passes
    select accession, context_id, cik, report_date, is_published, 'f_printed_agree', null::double, null::double, true
        , null, 'printed'
        , list_distinct(list_concat(
            case when n_spread > 1 then shapes_spread else [] end, case when n_floor > 1 then shapes_floor else [] end,
            case when n_all_in_rate > 1 then shapes_all_in_rate else [] end,
            case when n_cash_rate > 1 then shapes_cash_rate else [] end,
            case when n_pik_rate > 1 then shapes_pik_rate else [] end,
            case when n_pik_spread > 1 then shapes_pik_spread else [] end,
            case when n_fixed_rate > 1 then shapes_fixed_rate else [] end))
    from pos
    where (n_spread > 1 or n_floor > 1 or n_all_in_rate > 1 or n_cash_rate > 1 or n_pik_rate > 1 or n_pik_spread > 1
           or n_fixed_rate > 1)
        and not (conflict_spread or conflict_floor or conflict_all_in_rate or conflict_cash_rate or conflict_pik_rate
                 or conflict_pik_spread or conflict_fixed_rate)
)

, unioned as (
    select * from a
    union all select * from b
    union all select * from c
    union all select * from d
    union all select * from e
    union all select * from f
    union all select * from f_pass
)

select
    accession
    , context_id
    , cik
    , report_date
    , is_published
    , identity
    , case when passed then 'pass' else 'fail' end as verdict
    , lhs
    , rhs
    , lhs - rhs as difference
    , detail
    , sources
    , shape_keys
from unioned
