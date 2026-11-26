-- Decides, per PROPOSED code mapping and quarter, whether the base-rate level check confirms the mapping and whether it
-- tells the proposed rate from the others (text slice R phase 2, 2026-11-26). A measurement of the proposals; it
-- publishes nothing. One row per (code_unit_key, code_key, report_date) with at least one position of
-- int_text_check_base_level.
--
-- code_key: the code upper case, spaces removed (as text_proposed_code is matched). proposed_rate: the proposal's rate.
-- positions: positions carrying the code with a proposed rate; not_tested: of them, input_state not usable (PIK, no
-- spread, no all-in rate); no_series: usable but the proposed rate's window has no current value.
-- tested: usable positions whose proposed-rate verdict is admissible, floor_binding or outside. admissible counts
-- admissible and floor_binding; floor_binding, outside apart. share_admissible = admissible / tested.
-- Alternatives: for each other rate with a current window, the share of the tested positions admissible under it
-- (admissible or floor_binding) among those it could test; alt_shares: a map rate -> share (rounded to 3 places);
-- best_alt_rate, best_alt_share: the alternative with the largest share (ties to the smaller rate name);
-- alt_admissible_rates: the alternatives above var text_base_alt_max_share, comma-joined.
-- confirmed: tested >= var text_base_confirm_min_rows (10) and share_admissible >= var text_base_confirm_min_share
-- (0.90). discriminating: confirmed and no alternative's share is above var text_base_alt_max_share (0.50).
-- contradicted: outside >= var text_verdict_contradict_min_rows (5) and the share outside (not admissible, not floor
-- binding) is at least var text_verdict_contradict_min_share. Reported per quarter; int_text_proposal_verdict counts
-- base_quarters_contradicted from it but judges a code on its rows summed over quarters.
with level as (
    select *, upper(replace(code, ' ', '')) as code_key
    from {{ ref('int_text_check_base_level') }}
)

, proposed as (
    select code_unit_key, code_key, report_date
        , min(cik) as cik
        , min(proposed_rate) as proposed_rate
        , count(*) as positions
        , count(*) filter (where verdict = 'not_tested') as not_tested
        , count(*) filter (where verdict = 'no_series') as no_series
        , count(*) filter (where verdict in ('admissible', 'floor_binding', 'outside')) as tested
        , count(*) filter (where verdict in ('admissible', 'floor_binding')) as admissible
        , count(*) filter (where verdict = 'floor_binding') as floor_binding
        , count(*) filter (where verdict = 'outside') as outside
    from level
    where is_proposed
    group by 1, 2, 3
)

, tested_position as (
    select accession, context_id
    from level
    where is_proposed and verdict in ('admissible', 'floor_binding', 'outside')
)

, alternative as (
    select l.code_unit_key, l.code_key, l.report_date, l.candidate_rate
        , count(*) filter (where l.verdict in ('admissible', 'floor_binding')) / count(*) as share
    from level l
    join tested_position t on t.accession = l.accession and t.context_id = l.context_id
    where not l.is_proposed and l.verdict in ('admissible', 'floor_binding', 'outside')
    group by 1, 2, 3, 4
)

, alternative_sum as (
    select code_unit_key, code_key, report_date
        , map_from_entries(list(struct_pack(k := candidate_rate, v := round(share, 3)) order by candidate_rate))
            as alt_shares
        , arg_max(candidate_rate, share * 1000 - rank_name) as best_alt_rate
        , max(share) as best_alt_share
        , string_agg(candidate_rate, ',' order by candidate_rate)
            filter (where share > {{ var('text_base_alt_max_share') }}) as alt_admissible_rates
    from (select *, dense_rank() over (partition by code_unit_key, code_key, report_date order by candidate_rate) * 1e-6
                     as rank_name
          from alternative)
    group by 1, 2, 3
)

select
    p.code_unit_key
    , p.code_key
    , p.report_date
    , p.cik
    , p.proposed_rate
    , p.positions
    , p.not_tested
    , p.no_series
    , p.tested
    , p.admissible
    , p.floor_binding
    , p.outside
    , p.admissible / nullif(p.tested, 0) as share_admissible
    , a.alt_shares
    , a.best_alt_rate
    , a.best_alt_share
    , a.alt_admissible_rates
    , coalesce(p.tested >= {{ var('text_base_confirm_min_rows') }}
        and p.admissible / nullif(p.tested, 0) >= {{ var('text_base_confirm_min_share') }}, false) as confirmed
    , coalesce(p.tested >= {{ var('text_base_confirm_min_rows') }}
        and p.admissible / nullif(p.tested, 0) >= {{ var('text_base_confirm_min_share') }}
        and coalesce(a.best_alt_share, 0) <= {{ var('text_base_alt_max_share') }}, false) as discriminating
    , coalesce(p.outside >= {{ var('text_verdict_contradict_min_rows') }}
        and p.outside / nullif(p.tested, 0) >= {{ var('text_verdict_contradict_min_share') }}, false) as contradicted
from proposed p
left join alternative_sum a
    on a.code_unit_key = p.code_unit_key and a.code_key = p.code_key and a.report_date = p.report_date
