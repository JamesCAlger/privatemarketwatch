-- Slice 4 Task 4: columns of the production holdings file whose name suggests rates, maturity, provenance or
-- transforms. Schema only, no rows.
select column_name, column_type
from (describe select * from read_parquet('../data/output/private_markets_holdings.parquet'))
where regexp_matches(column_name, 'rate|spread|pik|matur|src_|source|transform|coupon|kind|precision|corrected')
