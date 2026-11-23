-- Slice 4 Task 3: the amount-field rows of int_field_rule, for the before/after guard (exported with
-- slice2/export_query.py). The before file is the full table at HEAD e44f990c, which had only these rows.
select * from int_field_rule
where field in ('fair_value', 'cost', 'principal_amount', 'shares', 'pct_of_net_assets', 'principal_amount_usd')
