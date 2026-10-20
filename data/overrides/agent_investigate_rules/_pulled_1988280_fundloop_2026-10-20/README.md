# Pulled 2026-10-20: two promoted rules of Manulife Private Credit Fund (0001988280)

Fund-clearing loop, report `docs/investigations/v05_readings/reports/0001988280.json`. Nothing reads
this directory. The emptied folder `agent_investigate_rules/1988280/` is left in place.

- `fill_missing_cost_from_fair_value.1988280.json` (value_expression, all quarters, cost := fair_value
  where cost is null). The filer prints and tags no cost per row: the schedule columns are
  'Rate (%) Maturity date Par value^ Value' and only the totals carry a cost
  ('Total investments (Cost $ 417,711,887 ) 245.7 % $ 416,616,523', 0001193125-26-219274). The rule
  therefore wrote cost = fair value on every published row of every quarter (invented data; the
  published cost total 405,735,162 at 2026-03-31 equals the fair value, not the printed cost). With it
  pulled, per-row cost is blank, as filed.
- `1988280_2025q4_restore_missing_fv_only_staging_rows.json` (row_add, 2025-12-31 only). Added four
  rows so that the quarter tied: the contra line 'Less unfunded loan commitments' (-105,643,990, not a
  position), the Dreyfus Government money fund (16,403,149) and the equity rows P.J. Fitzpatrick LLC
  (314,500) and Rapid Aggregator LLC (105,029), with no class. A plug pinned to one quarter: the same
  kinds of rows are missing in every other quarter. The money fund and the two equity rows are now
  published natively in all quarters by wrapper settings (`cash_identifiers` with
  `cash_identifier_rows`, `bare_entity_rows`); the contra line is not a position and is not published.
  The undrawn commitments it offset are published gross until per-row netting exists (orchestrator
  request MLF-R1 in the report).
