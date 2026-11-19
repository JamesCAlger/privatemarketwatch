-- Task 4 (CI fixture): column names and types of the production holdings file, for the schema-only fixture
-- warehouse/ci/fixture/output/private_markets_holdings.columns.csv. Reads the schema only, no rows.
select column_name, column_type from (describe select * from read_parquet('../data/output/private_markets_holdings.parquet'))
