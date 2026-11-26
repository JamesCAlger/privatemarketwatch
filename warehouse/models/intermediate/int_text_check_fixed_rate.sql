-- Decides, per proposed single-number shape with no rate code, whether its number is a FIXED rate rather than a spread
-- (text slice R phase 3 check 1d, owner item 11, 2026-11-26). A measurement of the proposals; it publishes nothing.
-- One row per (unit_key, shape): the proposed shapes of text_proposed_shape_role that hold exactly one number, whose
-- text has no leading rate code (macro rate_code null on the shape: "#%", "#"), and whose number either option order
-- proposes as spread_bps, spread_pct or fixed_rate_pct.
--
-- Rows compared: the shape's number rows in int_text_rate_proposed (any status: an unstable shape's number is still the
-- number) on positions that (1) read no rate code in any column unit (a code printed in another column, such as a separate
-- "Reference" column, makes the loan floating) and (2) carry an all-in rate tag (int_field_normalised interest_rate, rate_kind
-- all_in, status normalised). equal: the printed number (spread_bps read as number / 100) equals the tag within var
-- text_number_tolerance.
-- verdict:
--   fixed_rate   compared >= var text_verdict_confirm_min_rows and equal / compared >= var text_verdict_confirm_min_share:
--                a number with no reference rate that equals the all-in rate is the rate itself, not a spread over a
--                base. int_text_proposal_verdict then labels the role fixed_rate_pct.
--   not_fixed    compared >= the minimum rows and the share is below the bar (the number is not the all-in rate).
--   fixed_rate_few_rows (fix round 1 item 8) 1 to 4 compared rows, every one equal: below the bar, so not accepted by
--                the check, but the spread label is not kept either (owner item 11: no code and the number equals
--                the all-in rate is a fixed rate). The hole it closes: before, a code-free number equal to the all-in
--                tag on 4 of 4 rows kept its spread label, accepted by the spread tag that the filer files too.
--   too_few_rows 1 to 4 compared rows, not all equal.
--   no_check     no compared row (no all-in tag on any code-free position: a filer that tags none).
-- label_changes: the verdict is fixed_rate and some order proposed a spread.
-- The check never turns a cell with a code into a fixed rate: such cells are not in its scope (false-positive test in
-- _text_proposed.yml).
with shape as (
    select unit_key, shape
        , any_value(role_fwd) as role_fwd, any_value(role_rev) as role_rev
    from {{ ref('text_proposed_shape_role') }}
    where number_index = 1
    group by 1, 2
    having length(shape) - length(replace(shape, '#', '')) = 1
        and {{ rate_code('shape') }} is null
        and (bool_or(role_fwd in ('spread_bps', 'spread_pct', 'fixed_rate_pct'))
             or bool_or(role_rev in ('spread_bps', 'spread_pct', 'fixed_rate_pct')))
)

, coded_position as (
    select distinct accession, context_id
    from {{ ref('int_text_rate_proposed') }}
    where field = 'reference_rate_code' and status = 'read'
)

, all_in_tag as (
    select accession, context_id, any_value(value) as t_all_in
    from {{ ref('int_field_normalised') }}
    where field = 'interest_rate' and rate_kind = 'all_in' and status = 'normalised' and value is not null
    group by 1, 2
)

, number_row as (
    select s.unit_key, s.shape, s.role_fwd, s.role_rev, p.accession, p.context_id
        , case when s.role_fwd = 'spread_bps' and s.role_rev = 'spread_bps' then p.number_value / 100
               else p.number_value end as value
        , cp.accession is not null as has_code
        , t.t_all_in
    from shape s
    join {{ ref('int_text_rate_proposed') }} p
        on p.unit_key = s.unit_key and p.shape = s.shape and p.number_index = 1
    left join coded_position cp on cp.accession = p.accession and cp.context_id = p.context_id
    left join all_in_tag t on t.accession = p.accession and t.context_id = p.context_id
)

, summed as (
    select unit_key, shape, any_value(role_fwd) as role_fwd, any_value(role_rev) as role_rev
        , count(*) as number_rows
        , count(*) filter (where has_code) as rows_with_code
        , count(*) filter (where not has_code and t_all_in is not null) as compared
        , count(*) filter (where not has_code and abs(value - t_all_in) <= {{ var('text_number_tolerance') }}) as equal
    from number_row
    group by 1, 2
)

select
    s.unit_key
    , u.cik
    , s.shape
    , s.role_fwd
    , s.role_rev
    , s.number_rows
    , s.rows_with_code
    , s.compared
    , s.equal
    , case
        when s.compared = 0 then 'no_check'
        when s.compared < {{ var('text_verdict_confirm_min_rows') }} and s.equal = s.compared then 'fixed_rate_few_rows'
        when s.compared < {{ var('text_verdict_confirm_min_rows') }} then 'too_few_rows'
        when s.equal / s.compared >= {{ var('text_verdict_confirm_min_share') }} then 'fixed_rate'
        else 'not_fixed'
      end as verdict
    , ((s.compared >= {{ var('text_verdict_confirm_min_rows') }}
        and s.equal / s.compared >= {{ var('text_verdict_confirm_min_share') }})
       or (s.compared between 1 and {{ var('text_verdict_confirm_min_rows') }} - 1 and s.equal = s.compared))
        and (s.role_fwd in ('spread_bps', 'spread_pct') or s.role_rev in ('spread_bps', 'spread_pct')) as label_changes
from summed s
left join {{ ref('int_text_column_unit') }} u on u.unit_key = s.unit_key
