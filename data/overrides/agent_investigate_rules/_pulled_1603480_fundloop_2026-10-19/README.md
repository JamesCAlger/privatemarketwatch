# Pulled 2026-10-19: six promoted rules of TCW Direct Lending LLC (0001603480)

Fund-clearing loop, report `docs/investigations/v05_readings/reports/0001603480.json`. Nothing reads
this directory. The B2 correction `agent_b2_corrections/0001603480/dedup.json` is pulled the same way
(`agent_b2_corrections/0001603480/_pulled_1603480_fundloop_2026-10-19/`).

Cause they all worked around: from the 10-Q for 2025-06-30 the filer tags a second set of members on
the investment axis (the affiliate roll-forward note: short name, fair value, no cost, no percent of net
assets) beside the schedule members ('Debt Investments- United States ...', principal, cost, fair value,
percent). Replaced by the wrapper setting `source_encodings.schedule_row_tags: ["cost_or_percent_unrounded"]`
(as TCW Direct Lending VII), which drops every row without cost and without percent in every quarter.

- `1603480_exclude_heldout_short_form_duplicate_axes_2025.json` (row_exclusion, 2025-09-30 and
  2025-12-31 only): right rows, pinned to two quarters; left 2025-06-30 and 2026 published double.
- `1603480_recover_short_form_equity_facts_2025.json` (row_add, 2025-06-30): added short-form twins
  of rows already published (RT Holdings Class A 20,405,886; Cedar Ultimate Parent preferred units) with
  no context. A plug.
- `add_cash_and_treasury_investments_20260331.json` (row_add, 2026-03-31): added the money market fund
  1,906,618 and the Treasury bill 321,170,326 as positions with no context and no cash class, one
  quarter only. The filed investments figure ('Total Debt & Equity Investments', 249,694,433) excludes
  them. A plug.
- `dedup_parallel_position_facts_20260331.json`, `dedup_ssi_term_loan_rounding_20260331.json`
  (2026-03-31): collapsed schedule / short-form pairs by fair value but kept the short-form twin in six
  cases (schedule cost, percent and terms lost).
- `rt_holdings_warrant_cost_zero.json` (cost := 0 on the RT Holdings warrant, three quarters): the
  schedule row is tagged with cost 0 (printed '-'); the wrong cost came from the short-form twin.
