-- Slice 4 Task 3: the amount-field rows of int_field_normalised, for the before/after guard (exported with
-- slice2/export_query.py). The before file is the full table at HEAD e44f990c, which had only these rows; the new
-- columns value_date and rate_kind are not in it, so the comparison ignores them.
select * from int_field_normalised
where field in ('fair_value', 'cost', 'principal_amount', 'shares', 'pct_of_net_assets', 'principal_amount_usd')
