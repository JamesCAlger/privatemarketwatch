-- Spec section 10 is not built (slice 4 Task 3): no rate is derived from a base rate plus a spread. Every interest_rate
-- or interest_rate_cash value comes from one of the six rate actions or as_filed; any other action fails the build.
select accession, context_id, field, action, rule_id, value
from {{ ref('int_field_normalised') }}
where field in ('interest_rate', 'interest_rate_cash')
  and value is not null
  and action is distinct from 'as_filed'
  and action not in ('fraction_to_percent', 'rate_is_all_in', 'rate_is_cash_leg', 'pik_only_is_coupon',
                     'pik_only_is_margin', 'printed_margin_cash_plus_pik')
