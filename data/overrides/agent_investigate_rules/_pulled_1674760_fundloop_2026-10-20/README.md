# Pulled 2026-10-20: one promoted rule of Silver Capital Holdings LLC (0001674760)

Fund-clearing loop, report `docs/investigations/v05_readings/reports/0001674760.json`. Nothing reads
this directory.

- `add_2026q1_goldman_government_fund.json` (row_add, 2026-03-31 only): added the affiliated money
  market fund (Goldman Sachs Financial Square Government Fund, 157,671,000) as a position from the
  context C_ca1e2b91-605b-4bf7-a59f-4b3d988606f4 ('Non-Controlled Affiliated Investments Goldman Sachs
  Financial Square Government Fund', the affiliate note's member) so that holdings reached the printed
  'Total Investments and Investments in Affiliated Money Market Fund - 138.5 % $ 467,835 $ 447,150'.
  A plug against a total that includes the money fund. The build now publishes the money fund
  natively as a CASH row from its schedule context (C_50ead9b2-20b3-4c59-8e45-170bfe78cb93, 157,671,000,
  'Goldman Sachs Financial Square Government Fund - Institutional Shares'), as it does at 2025-06-30
  to 2026-06-30; with the rule present the build added nothing (sandbox svca shows one CASH row at
  2026-03-31), so pulling it changes no published row. The filed investments figure (289,479,000,
  printed 'Total Investments - 89.7 % $ 310,164 $ 289,479') excludes the money fund.
