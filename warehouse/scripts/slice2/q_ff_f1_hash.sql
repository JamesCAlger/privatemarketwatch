-- Final fix wave F1: can DuckDB hash a file's bytes at query time? read_blob + sha256, against the loader's hashes
-- (the readings manifest inputs and wrappers/_source.json). Paths relative to warehouse/ (run_sql.py switches there).
select version() as duckdb_version, filename, size, sha256(content) as sha256_sql
from read_blob(['wrappers/0001287750.json', '../data/overrides/bdc_xbrl_wrappers/0001287750.json', 'wrappers/_source.json'])
