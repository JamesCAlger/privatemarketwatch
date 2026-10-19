# Pulled 2026-10-19: ex-cash anchor compared with published rows that include the cash fund

`2026-03-31.json` (Varagon Capital Corp, CIK 0001784700) set the 2026-03-31 grand total to
825,525,000 with basis `investments_ex_cash`: the printed "Total Investments, March 31, 2026"
(accession 0001193125-26-219643). As a promoted override it outranks every deterministic anchor in
`fv_conservation`, so the published rows, which include the State Street Institutional U.S.
Government Money Market Fund as a CASH row, were compared with a figure that excludes it. The fund
is not declared under `investments_total_excludes`, so the engine does not split cash out and the
check fails by exactly the cash row (15,531 thousand, 1.88 pct).

Checked (scratch/2026-10-19_vgareq/q_r2.sql, q_r2b.sql against sandbox vgaf):

- Published rows 2026-03-31, non-cash: 825,525 thousand = the anchor. CASH row: 15,531 thousand.
- Printed: "Total Investments and Cash Equivalents $ 874,482 $ 841,056 224.18 %" (same accession).
- fund_financials 2026-03-31: investments_at_fair_value 825,525,000, cash_equivalents_at_fair_value
  15,531,000. The deterministic `companyfacts_fv_plus_cash` anchor is therefore 841,056,000, the
  printed figure, and it is what every other quarter of this fund is checked against.

Pulled rather than re-based to 841,056,000 (published_rows): a re-based override would repeat the
deterministic anchor's figure while hiding it behind an agent-authored one, and would keep outranking
it if the filed figures change. The anchor added nothing companyfacts did not already give.

Request VGA-R2, report `docs/investigations/v05_readings/reports/0001784700.json`. Nothing reads
this directory: the anchor loader globs `agent_anchor/*/*.json`.
