# Pulled 2026-10-19: anchor total includes cash equivalents that are published in no quarter

`2026-03-31.json` (MidCap Apollo Institutional Private Lending, CIK 0002006758) set the 2026-03-31
grand total to 945,613,000, the printed "Total Investment after Cash Equivalents" (accession
0001193125-26-214580). It was promoted alongside the SEKO row_add plug rule, which added
11,188,000 to the published rows; that rule was pulled on 2026-10-10
(`data/overrides/agent_investigate_rules/2006758/_pulled_plug_seko_equity_2026-10-10/`).

With the plug gone the anchor compares the published rows with a total that includes the two
money-market funds (Goldman Sachs Financial Square Government Institutional 7,665 and State Street
Institutional U.S. Government Money Market 3,523, thousands; sum 11,188). Those funds have no
fair-value fact on the investment axis and no published row in any quarter:

- Printed: "Total Investments before Cash Equivalents $ 968,958 $ 934,425" (0001193125-26-214580).
- companyfacts investments_ex_cash at 2026-03-31: 934,425,000.
- maic sandbox holdings, published basis, 2026-03-31: 301 rows, 934,425 thousand; money-market or
  cash rows in quarters 2024-06-30 to 2026-06-30: 0
  (`scratch/2026-10-19_mair/verify_r1_r3.py`).

Every other quarter of this fund is checked against investments_ex_cash and passes; without this
anchor fv_conservation 2026-03-31 falls back to companyfacts 934,425,000.

Request MAI-R3, report `docs/investigations/v05_readings/reports/0002006758.json`. Nothing reads
this directory: the anchor loaders glob `agent_anchor/*/*.json` and `agent_anchor/<cik>/*.json`.
