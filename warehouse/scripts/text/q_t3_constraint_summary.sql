-- Text slice R phase 3: constraint 5 by fund: tested, failed, and not tested by input state / verdict.
select cik
    , count(*) filter (where verdict in ('pass', 'fail')) as tested
    , count(*) filter (where verdict = 'fail') as fail
    , count(*) filter (where input_state = 'pik') as pik
    , count(*) filter (where input_state = 'no_all_in') as no_all_in
    , count(*) filter (where input_state = 'no_spread') as no_spread
    , count(*) filter (where input_state = 'no_series_for_rate') as rate_without_series
    , count(*) filter (where input_state = 'all_in_tag_is_leg') as all_in_tag_is_leg
    , count(*) filter (where verdict = 'no_series') as window_no_series
    , string_agg(distinct reference_rate || ' ' || n_fail, ', ') filter (where n_fail > 0) as fail_by_rate
from (
    select *, count(*) filter (where verdict = 'fail') over (partition by cik, reference_rate) as n_fail
    from int_text_rate_constraint where constraint_name = 'c5_base_level'
)
group by 1
order by 1
