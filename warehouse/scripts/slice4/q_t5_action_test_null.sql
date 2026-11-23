-- Slice 4 Task 5 repair (f): the old and the new predicate of tests/int_field_normalised_interest_rate_action.sql on
-- hand-made rows. A row is listed (the test fails) when the predicate is true. Row n0 has a value and no action: the
-- old predicate passes it, the new one lists it. Rows a1 (a built rate action) and a2 (an action outside the list)
-- show the two agree otherwise. Reads no table.
with t(ctx, field, action, value) as (
    values ('n0', 'interest_rate', null, 9.5)
         , ('a1', 'interest_rate', 'rate_is_all_in', 9.5)
         , ('a2', 'interest_rate', 'derived_from_spread', 9.5)
)
select
    ctx
    , action
    , coalesce(field in ('interest_rate', 'interest_rate_cash') and value is not null
        and action is distinct from 'as_filed'
        and action not in ('fraction_to_percent', 'rate_is_all_in', 'rate_is_cash_leg', 'pik_only_is_coupon',
                           'pik_only_is_margin', 'printed_margin_cash_plus_pik'), false) as old_lists_row
    , coalesce(field in ('interest_rate', 'interest_rate_cash') and value is not null
        and coalesce(action, '') not in ('as_filed', 'fraction_to_percent', 'rate_is_all_in', 'rate_is_cash_leg',
                                         'pik_only_is_coupon', 'pik_only_is_margin', 'printed_margin_cash_plus_pik'),
        false) as new_lists_row
from t
order by ctx
