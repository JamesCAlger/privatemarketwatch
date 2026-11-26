-- Decides, for each PROPOSED rule of the rate-text agent run, what the checks say about it (text slice R phase 2,
-- 2026-11-26; per number role since fix round 1). A measurement the owner reads: no acceptance is recorded anywhere
-- else, nothing reads this model, and nothing is published from it. One row per proposal: proposal_kind column
-- (unit_key), shape (unit_key, shape), role (unit_key, shape, number_index: the role of one number of a shape) or code
-- (unit_key, code).
--
-- stable: the proposal is the same in both option orders (column: text_proposed_column; shape and role: every number's
-- role of the shape and both role lists fit the shape; code: the rate names agree, CDOR, CORRA, BBSY and BBSW being four
-- names).
-- Thresholds (vars): a check CONFIRMS on at least text_verdict_confirm_min_rows (5) compared rows with at least
-- text_verdict_confirm_min_share (0.90) agreeing; it CONTRADICTS on at least text_verdict_contradict_min_rows (5)
-- disagreeing rows AND at least text_verdict_contradict_min_share (0.10) of its compared rows; it contradicts SMALL on at
-- least text_verdict_small_min_rows (2) disagreeing rows AND at least text_verdict_small_min_share (0.50) of its
-- compared rows (fix round 1: a total failure on few rows; large populations with a few outliers stay out of it).
-- Checks:
--   column  tag check (int_text_check_column_tags): the dominant tagged field is consistent with the proposed content
--           (all_in_rate <- interest_rate_tag; cash_rate <- interest_rate_cash_tag; spread <- spread;
--           pik_spread_or_rate <- pik_rate; pct_of_net_assets <- pct_of_net_assets; rate_terms <- spread,
--           interest_rate_tag, interest_rate_cash_tag or pik_rate). Confirms: tagged_rows >= 5, dominant share >= 0.90,
--           consistent. Contradicts: tagged_rows >= 5, dominant share >= 0.50, not consistent (or a reference_rate_code
--           column with rate tags on 10%+ of its rows); small: tagged_rows 2 to 4, dominant share >= 0.50, not
--           consistent.
--   role    the evidence of ONE number of one shape (fix round 1; a role is never accepted on its neighbour's evidence):
--           number-tag (int_text_check_number_tag rows of this shape and number_index: compared = equal + differs) for
--           roles with a tag counterpart (spread_bps, spread_pct, all_in_rate_pct, cash_rate_pct, pik_rate_pct,
--           pik_spread_pct, fixed_rate_pct); leg arithmetic (int_text_check_leg_arithmetic rows whose parts hold this
--           field printed from this shape): its counts_as_confirming rows (a independent, e) can confirm, every row can
--           contradict. A floor has no tag and only the inequality d tests it: it can be contradicted, never confirmed.
--   shape   a summary of its roles (below).
--   code    legend (int_text_check_code_legend), over the positions of the filings judged (agrees, contradicts, mixed):
--           confirms when agreeing positions are >= 5 and >= 0.90 of them; contradicts / small on contradicting
--           positions by the thresholds. Base level (int_text_check_base_level_quarter): strong when some quarter is
--           confirmed and discriminating; weak (does not confirm) when quarters are confirmed but none discriminating;
--           contradicts / small on outside rows summed over quarters by the thresholds. base_quarters_currency_bloc:
--           quarters that separate the currency bloc (reported, never an acceptance).
-- verdict for column, role and code, the first that applies:
--   unstable            not stable.
--   contradicted        some check contradicts.
--   contradicted_small  some check contradicts small (never accepted; the owner sees its rows).
--   accepted_by_check   some strong check confirms.
--   needs_owner         otherwise; reason (roles and codes): role_not_a_rate (pct_of_net_assets, other_number),
--                       role_cannot_tell, no_check_exists (no check can test it: a floor, a number whose field is never
--                       tagged on its rows, a code with no legend entry and no tested row), too_few_rows (a check
--                       applies but on fewer than 5 rows), weak_only (only a non-discriminating base level), below_bar
--                       (5+ rows compared, under 0.90 agreeing, not contradicted).
-- verdict for shape: unstable; nothing_to_read (no number: "SOFR (Q)", "N/A"; its code is judged as a code);
--   contradicted, contradicted_small (some role is); accepted_by_check (every role accepted); partly_accepted (some
--   roles accepted, some not: roles_accepted, roles_not_accepted list them as 'k:role'); needs_owner (none accepted).
-- checks_confirming, checks_weak, checks_contradicting: the checks that did, comma-joined.
{% set c_rows = var('text_verdict_confirm_min_rows') %}
{% set c_share = var('text_verdict_confirm_min_share') %}
{% set x_rows = var('text_verdict_contradict_min_rows') %}
{% set x_share = var('text_verdict_contradict_min_share') %}
{% set s_rows = var('text_verdict_small_min_rows') %}
{% set s_share = var('text_verdict_small_min_share') %}
with column_tag_map as (
    select * from (values
        ('all_in_rate', 'interest_rate_tag'), ('cash_rate', 'interest_rate_cash_tag'), ('spread', 'spread'),
        ('pik_spread_or_rate', 'pik_rate'), ('pct_of_net_assets', 'pct_of_net_assets'), ('rate_terms', 'spread'),
        ('rate_terms', 'interest_rate_tag'), ('rate_terms', 'interest_rate_cash_tag'), ('rate_terms', 'pik_rate')
    ) t(column_holds, tag_field)
)

, role_field(role, field, has_tag) as (
    values ('spread_bps', 'spread', true), ('spread_pct', 'spread', true), ('floor_pct', 'floor', false),
           ('all_in_rate_pct', 'all_in_rate', true), ('cash_rate_pct', 'cash_rate', true),
           ('pik_rate_pct', 'pik_rate', true), ('pik_spread_pct', 'pik_spread', true),
           ('fixed_rate_pct', 'fixed_rate', true)
)

-- columns ------------------------------------------------------------------------------------------------------------
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
    select run_id, 'column' as proposal_kind, unit_key, cik, null::varchar as shape, null::integer as number_index
        , null::varchar as code, column_holds as proposal, stable, position_rows as positions
        , case when coalesce(tagged_rows >= {{ c_rows }} and dominant_share >= {{ c_share }} and consistent, false)
               then 'column_tags' end as confirming
        , null::varchar as weak
        , case when coalesce(tagged_rows >= {{ x_rows }} and dominant_share >= 0.5 and not consistent
                             and column_holds <> 'reference_rate_code', false)
                    or coalesce(column_holds = 'reference_rate_code' and tagged_rows >= {{ x_rows }}
                                and tagged_rows / nullif(position_rows, 0) >= 0.1, false)
               then 'column_tags' end as contradicting
        , case when coalesce(tagged_rows between {{ s_rows }} and {{ x_rows }} - 1 and dominant_share >= 0.5
                             and not consistent and column_holds <> 'reference_rate_code', false)
               then 'column_tags' end as contradicting_small
        , case when coalesce(tagged_rows, 0) = 0 then 'no_check_exists'
               when tagged_rows < {{ c_rows }} then 'too_few_rows' else 'below_bar' end as reason_if_open
        , tagged_rows as tag_tagged_rows, dominant_field as tag_dominant_field, dominant_share as tag_dominant_share
    from column_judged
)

-- roles and shapes ---------------------------------------------------------------------------------------------------
, shape_role_raw as (
    select run_id, unit_key, shape, left(md5(unit_key || '|' || upper(shape)), 16) as shape_key, number_index
        , role_fwd, role_rev
        , bool_and(same_in_both_orders and roles_fit_shape) over (partition by run_id, unit_key, shape) as stable
        , length(shape) - length(replace(shape, '#', '')) as n_numbers
    from {{ ref('text_proposed_shape_role') }}
)

-- Phase 3 check 1d (owner item 11): where int_text_check_fixed_rate finds the shape's one number is the all-in rate on
-- code-free positions (verdict fixed_rate), the role is fixed_rate_pct whatever either order said among spread and fixed
-- rate; the check settles the label the orders split on (fixed_rate_pct / spread_pct), so such a shape is stable. Its
-- evidence is the check's (compared, equal), not the number-tag rows of the old label.
, shape_role as (
    select sr.run_id, sr.unit_key, sr.shape, sr.shape_key, sr.number_index
        , case when fc.unit_key is not null then 'fixed_rate_pct' else sr.role_fwd end as role_fwd
        , case when fc.unit_key is not null then 'fixed_rate_pct' else sr.role_rev end as role_rev
        , sr.stable or fc.unit_key is not null as stable
        , sr.n_numbers
        , case when fc.label_changes then 'fixed_rate_no_code' end as label_changed_by
        , sr.role_fwd as proposed_role_fwd, sr.role_rev as proposed_role_rev
        , fc.compared as fixed_compared, fc.equal as fixed_equal
    from shape_role_raw sr
    left join {{ ref('int_text_check_fixed_rate') }} fc
        on fc.unit_key = sr.unit_key and fc.shape = sr.shape and sr.number_index = 1
        and fc.verdict in ('fixed_rate', 'fixed_rate_few_rows')
)

, shape_positions as (
    -- per spelling (phase 3 check fix 1b): a case variant of the proposed shape is not the proposal's
    select shape_key, shape, count(distinct accession || '|' || context_id) as positions
    from {{ ref('int_text_rate_proposed') }}
    group by 1, 2
)

, number_check as (
    select shape_key, number_index
        , count(*) filter (where verdict in ('equal', 'differs')) as compared
        , count(*) filter (where verdict = 'equal') as equal
        , count(*) filter (where verdict = 'differs') as differs
    from {{ ref('int_text_check_number_tag') }}
    group by 1, 2
)

, leg_part as (
    select split_part(part, '|', 1) as field, split_part(part, '|', 2) as shape_key, verdict, counts_as_confirming
    from (select unnest(parts) as part, verdict, counts_as_confirming from {{ ref('int_text_check_leg_arithmetic') }})
)

, leg_sum as (
    select field, shape_key
        , count(*) filter (where verdict in ('pass', 'fail')) as leg_rows  -- not_testable rows count neither way
        , count(*) filter (where verdict = 'fail') as leg_fail
        , count(*) filter (where counts_as_confirming) as leg_confirm_rows
        , count(*) filter (where counts_as_confirming and verdict = 'pass') as leg_confirm_pass
    from leg_part
    group by 1, 2
)

, role_evidence as (
    select sr.*, rf.field, coalesce(rf.has_tag, false) as has_tag
        , coalesce(sr.fixed_compared, nc.compared, 0) as nt_compared
        , coalesce(sr.fixed_equal, nc.equal, 0) as nt_equal
        , coalesce(sr.fixed_compared - sr.fixed_equal, nc.differs, 0) as nt_differs
        , coalesce(ls.leg_rows, 0) as leg_rows, coalesce(ls.leg_fail, 0) as leg_fail
        , coalesce(ls.leg_confirm_rows, 0) as leg_confirm_rows, coalesce(ls.leg_confirm_pass, 0) as leg_confirm_pass
    from shape_role sr
    left join role_field rf on rf.role = sr.role_fwd
    left join number_check nc on nc.shape_key = sr.shape_key and nc.number_index = sr.number_index
    left join leg_sum ls on ls.shape_key = sr.shape_key and ls.field = rf.field
    where sr.number_index > 0
)

, role_judged as (
    select *
        , nullif(concat_ws(',',
            case when nt_compared >= {{ c_rows }} and nt_equal / nt_compared >= {{ c_share }}
                 then case when fixed_compared is not null then 'fixed_rate_no_code' else 'number_tag' end end,
            case when leg_confirm_rows >= {{ c_rows }} and leg_confirm_pass / leg_confirm_rows >= {{ c_share }}
                 then 'leg_arithmetic' end), '') as confirming
        , nullif(concat_ws(',',
            case when nt_differs >= {{ x_rows }} and nt_differs / nt_compared >= {{ x_share }} then 'number_tag' end,
            case when leg_fail >= {{ x_rows }} and leg_fail / leg_rows >= {{ x_share }} then 'leg_arithmetic' end), '')
            as contradicting
        , nullif(concat_ws(',',
            case when nt_differs >= {{ s_rows }} and nt_differs / nt_compared >= {{ s_share }} then 'number_tag' end,
            case when leg_fail >= {{ s_rows }} and leg_fail / leg_rows >= {{ s_share }} then 'leg_arithmetic' end), '')
            as contradicting_small
    from role_evidence
)

, role_out as (
    select run_id, 'role' as proposal_kind, rj.unit_key, u.cik, rj.shape, rj.number_index, null::varchar as code
        , rj.role_fwd || case when rj.role_fwd is distinct from rj.role_rev then '|' || coalesce(rj.role_rev, '') else ''
                           end as proposal
        , rj.stable, coalesce(sp.positions, 0) as positions
        , rj.confirming, null::varchar as weak, rj.contradicting, rj.contradicting_small
        , case
            when rj.role_fwd in ('pct_of_net_assets', 'other_number') then 'role_not_a_rate'
            when rj.role_fwd = 'cannot_tell' then 'role_cannot_tell'
            when rj.nt_compared = 0 and rj.leg_confirm_rows = 0 then 'no_check_exists'
            when greatest(rj.nt_compared, rj.leg_confirm_rows) < {{ c_rows }} then 'too_few_rows'
            else 'below_bar'
          end as reason_if_open
        , rj.role_fwd as role, rj.field, rj.nt_compared, rj.nt_equal, rj.nt_differs, rj.leg_rows, rj.leg_fail
        , rj.leg_confirm_rows, rj.leg_confirm_pass, rj.shape_key, rj.label_changed_by
    from role_judged rj
    left join {{ ref('int_text_column_unit') }} u on u.unit_key = rj.unit_key
    left join shape_positions sp on sp.shape_key = rj.shape_key and sp.shape = rj.shape
)

, role_verdict as (
    select *
        , case
            when not stable then 'unstable'
            when contradicting is not null then 'contradicted'
            when contradicting_small is not null then 'contradicted_small'
            when confirming is not null then 'accepted_by_check'
            else 'needs_owner'
          end as verdict
    from role_out
)

, shape_sum as (
    select sr.run_id, sr.unit_key, sr.shape, sr.shape_key, any_value(sr.stable) as stable
        , any_value(sr.n_numbers) as n_numbers
        , string_agg(case when sr.number_index > 0 then sr.role_fwd || case when sr.role_fwd is distinct from sr.role_rev
                                                                      then '|' || coalesce(sr.role_rev, '') else '' end
                     end, ',' order by sr.number_index) as proposal
        , count(rv.number_index) as roles
        , count(*) filter (where rv.verdict = 'accepted_by_check') as roles_accepted_n
        , count(*) filter (where rv.verdict = 'contradicted') as roles_contradicted
        , count(*) filter (where rv.verdict = 'contradicted_small') as roles_contradicted_small
        , string_agg(rv.number_index || ':' || rv.role, ',' order by rv.number_index)
            filter (where rv.verdict = 'accepted_by_check') as roles_accepted
        , string_agg(rv.number_index || ':' || rv.role || ' (' || case when rv.verdict = 'needs_owner' then rv.reason_if_open else rv.verdict end || ')', ','
                     order by rv.number_index) filter (where rv.verdict <> 'accepted_by_check') as roles_not_accepted
        , nullif(string_agg(distinct rv.confirming, ','), '') as confirming
        , nullif(string_agg(distinct rv.contradicting, ','), '') as contradicting
        , nullif(string_agg(distinct rv.contradicting_small, ','), '') as contradicting_small
        , sum(rv.nt_compared) as nt_compared, sum(rv.nt_equal) as nt_equal, sum(rv.nt_differs) as nt_differs
        , sum(rv.leg_rows) as leg_rows, sum(rv.leg_fail) as leg_fail
        , string_agg(distinct rv.label_changed_by, ',') as label_changed_by
    from shape_role sr
    left join role_verdict rv
        on rv.unit_key = sr.unit_key and rv.shape = sr.shape and rv.number_index = sr.number_index
    group by 1, 2, 3, 4
)

, shape_out as (
    select ss.run_id, 'shape' as proposal_kind, ss.unit_key, u.cik, ss.shape, null::integer as number_index
        , null::varchar as code, ss.proposal, ss.stable, coalesce(sp.positions, 0) as positions
        , ss.confirming, null::varchar as weak, ss.contradicting, ss.contradicting_small
        , case
            when not ss.stable then 'unstable'
            when ss.n_numbers = 0 then 'nothing_to_read'
            when ss.roles_contradicted > 0 then 'contradicted'
            when ss.roles_contradicted_small > 0 then 'contradicted_small'
            when ss.roles > 0 and ss.roles_accepted_n = ss.roles then 'accepted_by_check'
            when ss.roles_accepted_n > 0 then 'partly_accepted'
            else 'needs_owner'
          end as verdict
        , ss.roles_accepted, ss.roles_not_accepted
        , ss.nt_compared, ss.nt_equal, ss.nt_differs, ss.leg_rows, ss.leg_fail, ss.label_changed_by
    from shape_sum ss
    left join {{ ref('int_text_column_unit') }} u on u.unit_key = ss.unit_key
    left join shape_positions sp on sp.shape_key = ss.shape_key and sp.shape = ss.shape
)

-- codes ----------------------------------------------------------------------------------------------------------------
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
        , count(*) filter (where separates_currency_bloc) as base_quarters_currency_bloc
        , sum(tested) as base_tested
        , sum(outside) as base_outside
    from {{ ref('int_text_check_base_level_quarter') }}
    group by 1, 2
)

, code_judged as (
    select cp.run_id, cp.unit_key, u.cik, cp.code, cp.proposal, cp.stable, coalesce(pos.positions, 0) as positions
        , coalesce(l.legend_filings_agree, 0) as legend_filings_agree
        , coalesce(l.legend_filings_contradict, 0) as legend_filings_contradict
        , coalesce(l.legend_filings_mixed, 0) as legend_filings_mixed
        , coalesce(l.legend_filings_none, 0) as legend_filings_none
        , coalesce(l.legend_positions_agree, 0) as lpa
        , coalesce(l.legend_positions_contradict, 0) as lpc
        , coalesce(l.legend_positions_judged, 0) as lpj
        , coalesce(b.base_quarters_tested, 0) as base_quarters_tested
        , coalesce(b.base_quarters_confirmed, 0) as base_quarters_confirmed
        , coalesce(b.base_quarters_discriminating, 0) as base_quarters_discriminating
        , coalesce(b.base_quarters_currency_bloc, 0) as base_quarters_currency_bloc
        , coalesce(b.base_tested, 0) as base_tested
        , coalesce(b.base_outside, 0) as base_outside
    from code_proposal cp
    left join {{ ref('int_text_column_unit') }} u on u.unit_key = cp.unit_key
    left join code_positions pos on pos.unit_key = cp.unit_key and pos.code_key = cp.code_key
    left join legend_sum l on l.unit_key = cp.unit_key and l.code_key = cp.code_key
    left join base_sum b on b.unit_key = cp.unit_key and b.code_key = cp.code_key
)

, code_out as (
    select run_id, 'code' as proposal_kind, unit_key, cik, null::varchar as shape, null::integer as number_index, code
        , proposal, stable, positions
        , nullif(concat_ws(',',
            case when lpa >= {{ c_rows }} and lpa / lpj >= {{ c_share }} then 'legend' end,
            case when base_quarters_discriminating > 0 then 'base_level' end), '') as confirming
        , case when base_quarters_confirmed > 0 and base_quarters_discriminating = 0
               then 'base_level_not_discriminating' end as weak
        , nullif(concat_ws(',',
            case when lpc >= {{ x_rows }} and lpc / lpj >= {{ x_share }} then 'legend' end,
            case when base_outside >= {{ x_rows }} and base_outside / base_tested >= {{ x_share }} then 'base_level' end),
            '') as contradicting
        , nullif(concat_ws(',',
            case when lpc >= {{ s_rows }} and lpc / lpj >= {{ s_share }} then 'legend' end,
            case when base_outside >= {{ s_rows }} and base_outside / base_tested >= {{ s_share }} then 'base_level' end),
            '') as contradicting_small
        , case
            when proposal = '(not a code)' then 'role_not_a_rate'
            when base_quarters_confirmed > 0 and base_quarters_discriminating = 0 then 'weak_only'
            when lpj = 0 and base_tested = 0 then 'no_check_exists'
            else 'too_few_rows'
          end as reason_if_open
        , legend_filings_agree, legend_filings_contradict, legend_filings_mixed, legend_filings_none
        , base_quarters_tested, base_quarters_confirmed, base_quarters_discriminating, base_quarters_currency_bloc
        , base_tested, base_outside
    from code_judged
)

, unioned as (
    select run_id, proposal_kind, unit_key, cik, shape, number_index, code, proposal, stable, positions
        , confirming, weak, contradicting, contradicting_small, reason_if_open
        , case when not stable then 'unstable' when contradicting is not null then 'contradicted'
               when contradicting_small is not null then 'contradicted_small'
               when confirming is not null then 'accepted_by_check' else 'needs_owner' end as verdict
        , null::varchar as role, null::varchar as roles_accepted, null::varchar as roles_not_accepted
        , tag_tagged_rows, tag_dominant_field, tag_dominant_share
        , null::bigint as nt_compared, null::bigint as nt_equal, null::bigint as nt_differs
        , null::bigint as leg_rows, null::bigint as leg_fail
        , null::bigint as legend_filings_agree, null::bigint as legend_filings_contradict
        , null::bigint as legend_filings_mixed, null::bigint as legend_filings_none
        , null::bigint as base_quarters_tested, null::bigint as base_quarters_confirmed
        , null::bigint as base_quarters_discriminating, null::bigint as base_quarters_currency_bloc
        , null::bigint as base_tested, null::bigint as base_outside, null::varchar as label_changed_by
    from column_out
    union all
    select run_id, proposal_kind, unit_key, cik, shape, number_index, code, proposal, stable, positions
        , confirming, weak, contradicting, contradicting_small, reason_if_open, verdict
        , role, null, null
        , null, null, null
        , nt_compared, nt_equal, nt_differs, leg_rows, leg_fail
        , null, null, null, null, null, null, null, null, null, null, label_changed_by
    from role_verdict
    union all
    select run_id, proposal_kind, unit_key, cik, shape, number_index, code, proposal, stable, positions
        , confirming, weak, contradicting, contradicting_small, null, verdict
        , null, roles_accepted, roles_not_accepted
        , null, null, null
        , nt_compared, nt_equal, nt_differs, leg_rows, leg_fail
        , null, null, null, null, null, null, null, null, null, null, label_changed_by
    from shape_out
    union all
    select run_id, proposal_kind, unit_key, cik, shape, number_index, code, proposal, stable, positions
        , confirming, weak, contradicting, contradicting_small, reason_if_open
        , case when not stable then 'unstable' when contradicting is not null then 'contradicted'
               when contradicting_small is not null then 'contradicted_small'
               when confirming is not null then 'accepted_by_check' else 'needs_owner' end
        , null, null, null
        , null, null, null
        , null, null, null, null, null
        , legend_filings_agree, legend_filings_contradict, legend_filings_mixed, legend_filings_none
        , base_quarters_tested, base_quarters_confirmed, base_quarters_discriminating, base_quarters_currency_bloc
        , base_tested, base_outside, null
    from code_out
)

select
    run_id
    , proposal_kind
    , unit_key
    , cik
    , shape
    , number_index
    , role
    , code
    , proposal
    , stable
    , positions
    , confirming as checks_confirming
    , weak as checks_weak
    , contradicting as checks_contradicting
    , contradicting_small as checks_contradicting_small
    , verdict
    , case when verdict = 'needs_owner' then reason_if_open end as reason
    , roles_accepted
    , roles_not_accepted
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
    , base_quarters_currency_bloc
    , base_tested
    , base_outside
    , label_changed_by
from unioned
