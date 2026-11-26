-- Decides, for each PROPOSED rule of the rate-text agent run, what the checks say about it (text slice R phase 2,
-- 2026-11-26). A measurement the owner reads: no acceptance is recorded anywhere else, nothing reads this model, and
-- nothing is published from it. One row per proposal: proposal_kind column (unit_key), shape (unit_key, shape) or code
-- (unit_key, code).
--
-- stable: the proposal is the same in both option orders (column: text_proposed_column; shape: every number's role
-- and both role lists fit the shape; code: the normalised rate names agree).
-- Checks (thresholds are vars: confirm = at least text_verdict_confirm_min_rows (5) compared rows and at least
-- text_verdict_confirm_min_share (0.90) agreeing; contradict = at least text_verdict_contradict_min_rows (5) rows AND
-- at least text_verdict_contradict_min_share (0.10) of the compared rows disagreeing):
--   column  tag check (int_text_check_column_tags): the column's dominant tagged field is consistent with the proposed
--           content (all_in_rate <- interest_rate_tag; cash_rate <- interest_rate_cash_tag; spread <- spread;
--           pik_spread_or_rate <- pik_rate; pct_of_net_assets <- pct_of_net_assets; rate_terms <- spread,
--           interest_rate_tag, interest_rate_cash_tag or pik_rate). Confirms: tagged_rows >= 5, dominant share >= 0.90,
--           consistent. Contradicts: tagged_rows >= 5, dominant share >= 0.50, not consistent; or a
--           reference_rate_code column with rate tags on 10%+ of its rows. A column with no tags: no check applies.
--   shape   number-tag (int_text_check_number_tag), per number of the shape: compared = equal + differs. A number
--           confirms or contradicts by the thresholds; the shape is confirmed when one number confirms, contradicted
--           when one contradicts. Leg arithmetic (int_text_check_leg_arithmetic), the identity rows whose shape_keys
--           hold the shape: confirms by the thresholds on a_cash_plus_pik, d_floor_spread and e_spread_split rows
--           (an equality or the floor test); contradicts by the thresholds on all its rows (b, c, f included).
--   code    legend (int_text_check_code_legend), over the positions of the filings judged (agrees, contradicts, mixed):
--           confirms when agreeing positions are >= 5 and >= 0.90 of them; contradicts when contradicting positions
--           are >= 5 and >= 0.10 of them. Base level (int_text_check_base_level_quarter): strong when some quarter is
--           confirmed and discriminating; weak (does not confirm) when quarters are confirmed but none discriminating;
--           contradicts when, over all quarters, outside rows are >= 5 and >= 0.10 of the tested rows.
-- verdict, the first that applies:
--   unstable           not stable.
--   nothing_to_read    a shape with no number (a code or word only: "SOFR (Q)", "N/A"); its code is judged as a code.
--   contradicted       some check contradicts.
--   accepted_by_check  some strong check confirms (and none contradicts).
--   needs_owner        stable, and no check applies, or the only confirmation is a non-discriminating base level.
-- checks_confirming, checks_contradicting: the checks that did, comma-joined.
with column_tag_map as (
    select * from (values
        ('all_in_rate', 'interest_rate_tag'), ('cash_rate', 'interest_rate_cash_tag'), ('spread', 'spread'),
        ('pik_spread_or_rate', 'pik_rate'), ('pct_of_net_assets', 'pct_of_net_assets'), ('rate_terms', 'spread'),
        ('rate_terms', 'interest_rate_tag'), ('rate_terms', 'interest_rate_cash_tag'), ('rate_terms', 'pik_rate')
    ) t(column_holds, tag_field)
)

, column_judged as (
    select p.run_id, p.unit_key, u.cik, p.column_holds_fwd as column_holds, p.same_in_both_orders as stable
        , t.position_rows, t.tagged_rows, t.dominant_field, t.dominant_share
        , exists (select 1 from column_tag_map m where m.column_holds = p.column_holds_fwd
                                                  and m.tag_field = t.dominant_field) as consistent
    from {{ ref('text_proposed_column') }} p
    left join {{ ref('int_text_column_unit') }} u on u.unit_key = p.unit_key
    left join {{ ref('int_text_check_column_tags') }} t on t.unit_key = p.unit_key
)

, column_out as (
    select run_id, 'column' as proposal_kind, unit_key, cik, null::varchar as shape, null::varchar as code
        , column_holds as proposal, stable, position_rows as positions
        , coalesce(tagged_rows >= {{ var('text_verdict_confirm_min_rows') }}
                   and dominant_share >= {{ var('text_verdict_confirm_min_share') }} and consistent, false)
            as tag_confirms
        , coalesce(tagged_rows >= {{ var('text_verdict_contradict_min_rows') }} and dominant_share >= 0.5
                   and not consistent and column_holds <> 'reference_rate_code', false)
          or coalesce(column_holds = 'reference_rate_code'
                      and tagged_rows >= {{ var('text_verdict_contradict_min_rows') }}
                      and tagged_rows / nullif(position_rows, 0) >= 0.1, false) as tag_contradicts
        , tagged_rows, dominant_field, dominant_share
    from column_judged
)

, shape_proposal as (
    select run_id, unit_key, shape, left(md5(unit_key || '|' || upper(shape)), 16) as shape_key
        , bool_and(same_in_both_orders and roles_fit_shape) as stable
        , length(shape) - length(replace(shape, '#', '')) as n_numbers
        , string_agg(case when number_index > 0 then role_fwd || case when role_fwd is distinct from role_rev
                                                                    then '|' || coalesce(role_rev, '') else '' end end,
                     ',' order by number_index) as proposal
    from {{ ref('text_proposed_shape_role') }}
    group by 1, 2, 3
)

, shape_positions as (
    select shape_key, count(distinct accession || '|' || context_id) as positions
    from {{ ref('int_text_rate_proposed') }}
    group by 1
)

, number_check as (
    select shape_key, number_index
        , count(*) filter (where verdict in ('equal', 'differs')) as compared
        , count(*) filter (where verdict = 'equal') as equal
        , count(*) filter (where verdict = 'differs') as differs
    from {{ ref('int_text_check_number_tag') }}
    group by 1, 2
)

, number_sum as (
    select shape_key
        , sum(compared) as nt_compared
        , sum(equal) as nt_equal
        , sum(differs) as nt_differs
        , count(*) filter (where compared >= {{ var('text_verdict_confirm_min_rows') }}
                             and equal / compared >= {{ var('text_verdict_confirm_min_share') }}) as numbers_confirmed
        , count(*) filter (where differs >= {{ var('text_verdict_contradict_min_rows') }}
                             and differs / compared >= {{ var('text_verdict_contradict_min_share') }})
            as numbers_contradicted
    from number_check
    group by 1
)

, leg_row as (
    select unnest(shape_keys) as shape_key, identity, verdict
    from {{ ref('int_text_check_leg_arithmetic') }}
)

, leg_sum as (
    select shape_key
        , count(*) as leg_rows
        , count(*) filter (where verdict = 'fail') as leg_fail
        , count(*) filter (where identity in ('a_cash_plus_pik', 'd_floor_spread', 'e_spread_split')) as leg_strong_rows
        , count(*) filter (where identity in ('a_cash_plus_pik', 'd_floor_spread', 'e_spread_split')
                             and verdict = 'pass') as leg_strong_pass
    from leg_row
    group by 1
)

, shape_out as (
    select sp.run_id, 'shape' as proposal_kind, sp.unit_key, u.cik, sp.shape, null::varchar as code, sp.proposal
        , sp.stable, coalesce(pos.positions, 0) as positions, sp.n_numbers
        , coalesce(ns.nt_compared, 0) as nt_compared, coalesce(ns.nt_equal, 0) as nt_equal
        , coalesce(ns.nt_differs, 0) as nt_differs
        , coalesce(ns.numbers_confirmed, 0) as numbers_confirmed
        , coalesce(ns.numbers_contradicted, 0) as numbers_contradicted
        , coalesce(ls.leg_rows, 0) as leg_rows, coalesce(ls.leg_fail, 0) as leg_fail
        , coalesce(ls.leg_strong_rows, 0) as leg_strong_rows, coalesce(ls.leg_strong_pass, 0) as leg_strong_pass
    from shape_proposal sp
    left join {{ ref('int_text_column_unit') }} u on u.unit_key = sp.unit_key
    left join shape_positions pos on pos.shape_key = sp.shape_key
    left join number_sum ns on ns.shape_key = sp.shape_key
    left join leg_sum ls on ls.shape_key = sp.shape_key
)

, code_proposal as (
    select run_id, unit_key, code, upper(replace(code, ' ', '')) as code_key, same_in_both_orders as stable
        , coalesce(nullif(rate_name, ''), reference_rate_fwd, '(not a code)')
          || case when not same_in_both_orders then '|' || coalesce(reference_rate_rev, '') else '' end as proposal
    from {{ ref('text_proposed_code') }}
)

, code_positions as (
    select unit_key, upper(replace(reference_rate_code, ' ', '')) as code_key
        , count(distinct accession || '|' || context_id) as positions
    from {{ ref('int_text_rate_proposed') }}
    where field = 'reference_rate_code'
    group by 1, 2
)

, legend_sum as (
    select unit_key, code_key
        , count(*) filter (where verdict = 'agrees') as legend_filings_agree
        , count(*) filter (where verdict = 'contradicts') as legend_filings_contradict
        , count(*) filter (where verdict = 'mixed') as legend_filings_mixed
        , count(*) filter (where verdict = 'no_legend_in_filing') as legend_filings_none
        , count(*) filter (where verdict = 'unclear') as legend_filings_unclear
        , coalesce(sum(positions) filter (where verdict = 'agrees'), 0) as legend_positions_agree
        , coalesce(sum(positions) filter (where verdict = 'contradicts'), 0) as legend_positions_contradict
        , coalesce(sum(positions) filter (where verdict in ('agrees', 'contradicts', 'mixed')), 0)
            as legend_positions_judged
    from {{ ref('int_text_check_code_legend') }}
    group by 1, 2
)

, base_sum as (
    select code_unit_key as unit_key, code_key
        , count(*) filter (where tested > 0) as base_quarters_tested
        , count(*) filter (where confirmed) as base_quarters_confirmed
        , count(*) filter (where discriminating) as base_quarters_discriminating
        , count(*) filter (where contradicted) as base_quarters_contradicted
        , sum(tested) as base_tested
        , sum(admissible) as base_admissible
        , sum(outside) as base_outside
    from {{ ref('int_text_check_base_level_quarter') }}
    group by 1, 2
)

, code_out as (
    select cp.run_id, 'code' as proposal_kind, cp.unit_key, u.cik, null::varchar as shape, cp.code, cp.proposal
        , cp.stable, coalesce(pos.positions, 0) as positions
        , coalesce(l.legend_filings_agree, 0) as legend_filings_agree
        , coalesce(l.legend_filings_contradict, 0) as legend_filings_contradict
        , coalesce(l.legend_filings_mixed, 0) as legend_filings_mixed
        , coalesce(l.legend_filings_none, 0) as legend_filings_none
        , coalesce(l.legend_filings_unclear, 0) as legend_filings_unclear
        , coalesce(l.legend_positions_agree, 0) as legend_positions_agree
        , coalesce(l.legend_positions_contradict, 0) as legend_positions_contradict
        , coalesce(l.legend_positions_judged, 0) as legend_positions_judged
        , coalesce(b.base_quarters_tested, 0) as base_quarters_tested
        , coalesce(b.base_quarters_confirmed, 0) as base_quarters_confirmed
        , coalesce(b.base_quarters_discriminating, 0) as base_quarters_discriminating
        , coalesce(b.base_quarters_contradicted, 0) as base_quarters_contradicted
        , coalesce(b.base_tested, 0) as base_tested
        , coalesce(b.base_admissible, 0) as base_admissible
        , coalesce(b.base_outside, 0) as base_outside
    from code_proposal cp
    left join {{ ref('int_text_column_unit') }} u on u.unit_key = cp.unit_key
    left join code_positions pos on pos.unit_key = cp.unit_key and pos.code_key = cp.code_key
    left join legend_sum l on l.unit_key = cp.unit_key and l.code_key = cp.code_key
    left join base_sum b on b.unit_key = cp.unit_key and b.code_key = cp.code_key
)

, judged as (
    select run_id, proposal_kind, unit_key, cik, shape, code, proposal, stable, positions
        , false as is_empty_shape
        , case when tag_confirms then 'column_tags' end as confirming
        , null::varchar as weak
        , case when tag_contradicts then 'column_tags' end as contradicting
        , tagged_rows as tag_tagged_rows, dominant_field as tag_dominant_field, dominant_share as tag_dominant_share
        , null::bigint as nt_compared, null::bigint as nt_equal, null::bigint as nt_differs
        , null::bigint as leg_rows, null::bigint as leg_fail
        , null::bigint as legend_filings_agree, null::bigint as legend_filings_contradict
        , null::bigint as legend_filings_mixed, null::bigint as legend_filings_none
        , null::bigint as base_quarters_tested, null::bigint as base_quarters_confirmed
        , null::bigint as base_quarters_discriminating, null::bigint as base_tested, null::bigint as base_outside
    from column_out
    union all
    select run_id, proposal_kind, unit_key, cik, shape, code, proposal, stable, positions
        , n_numbers = 0
        , concat_ws(',',
            case when numbers_confirmed > 0 then 'number_tag' end,
            case when leg_strong_rows >= {{ var('text_verdict_confirm_min_rows') }}
                      and leg_strong_pass / leg_strong_rows >= {{ var('text_verdict_confirm_min_share') }}
                 then 'leg_arithmetic' end)
        , null
        , concat_ws(',',
            case when numbers_contradicted > 0 then 'number_tag' end,
            case when leg_fail >= {{ var('text_verdict_contradict_min_rows') }}
                      and leg_fail / leg_rows >= {{ var('text_verdict_contradict_min_share') }}
                 then 'leg_arithmetic' end)
        , null, null, null
        , nt_compared, nt_equal, nt_differs, leg_rows, leg_fail
        , null, null, null, null, null, null, null, null, null
    from shape_out
    union all
    select run_id, proposal_kind, unit_key, cik, shape, code, proposal, stable, positions
        , false
        , concat_ws(',',
            case when legend_positions_agree >= {{ var('text_verdict_confirm_min_rows') }}
                      and legend_positions_agree / legend_positions_judged >= {{ var('text_verdict_confirm_min_share') }}
                 then 'legend' end,
            case when base_quarters_discriminating > 0 then 'base_level' end)
        , case when base_quarters_confirmed > 0 and base_quarters_discriminating = 0 then 'base_level_not_discriminating'
          end
        , concat_ws(',',
            case when legend_positions_contradict >= {{ var('text_verdict_contradict_min_rows') }}
                      and legend_positions_contradict / legend_positions_judged
                          >= {{ var('text_verdict_contradict_min_share') }}
                 then 'legend' end,
            case when base_outside >= {{ var('text_verdict_contradict_min_rows') }}
                      and base_outside / base_tested >= {{ var('text_verdict_contradict_min_share') }}
                 then 'base_level' end)
        , null, null, null
        , null, null, null, null, null
        , legend_filings_agree, legend_filings_contradict, legend_filings_mixed, legend_filings_none
        , base_quarters_tested, base_quarters_confirmed, base_quarters_discriminating, base_tested, base_outside
    from code_out
)

select
    run_id
    , proposal_kind
    , unit_key
    , cik
    , shape
    , code
    , proposal
    , stable
    , positions
    , nullif(confirming, '') as checks_confirming
    , weak as checks_weak
    , nullif(contradicting, '') as checks_contradicting
    , case
        when not stable then 'unstable'
        when is_empty_shape then 'nothing_to_read'
        when nullif(contradicting, '') is not null then 'contradicted'
        when nullif(confirming, '') is not null then 'accepted_by_check'
        else 'needs_owner'
      end as verdict
    , tag_tagged_rows
    , tag_dominant_field
    , tag_dominant_share
    , nt_compared
    , nt_equal
    , nt_differs
    , leg_rows
    , leg_fail
    , legend_filings_agree
    , legend_filings_contradict
    , legend_filings_mixed
    , legend_filings_none
    , base_quarters_tested
    , base_quarters_confirmed
    , base_quarters_discriminating
    , base_tested
    , base_outside
from judged
