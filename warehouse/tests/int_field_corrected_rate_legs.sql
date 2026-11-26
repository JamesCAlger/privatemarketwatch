-- Slice 5 Task 4, spec section 7 on the corrected values: where the all-in rate, the cash leg and the PIK rate of a
-- position all hold a value in int_field_corrected, the cash leg plus the PIK rate equals the all-in rate within var
-- rate_legs_tolerance. A corrected reading that fails the check is failed (int_rate_corrected row_failure) and never
-- stored, so this cannot fail on today's code: a regression guard, not evidence about the data.
with leg as (
    select
        accession
        , context_id
        , any_value(value) filter (where field = 'interest_rate') as all_in
        , any_value(value) filter (where field = 'interest_rate_cash') as cash
        , any_value(value) filter (where field = 'pik_rate') as pik
    from {{ ref('int_field_corrected') }}
    where field in ('interest_rate', 'interest_rate_cash', 'pik_rate')
    group by 1, 2
)

select *, cash + pik - all_in as difference
from leg
where all_in is not null and cash is not null and pik is not null
  and abs(cash + pik - all_in) > {{ var('rate_legs_tolerance') }}
