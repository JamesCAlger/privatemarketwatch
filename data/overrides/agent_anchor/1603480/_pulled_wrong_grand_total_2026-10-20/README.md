# Pulled anchors, TCW Direct Lending LLC (0001603480), 2026-10-20

Request TDL-R1 (verification_bug) in `docs/investigations/v05_readings/reports/0001603480.json`, implemented by the orchestrator under D-207, recorded in D-220.

- `2025-06-30.json` set a grand total of 628,526,565 = 26 schedule rows (327,832,328, which equals the filer's companyfacts investments at fair value 327,832,330) plus 28 cost-less rows (300,694,237) that are the affiliated-investments note repeating the same holdings. The schedule total is the 327.8M figure.
- `2026-03-31.json` set 572,771,377 = Total Investments including the money market fund and the Treasury bill; the printed Total Debt & Equity Investments is 249,694,433 and those cash items are not published as positions.

Neither file has a `basis` key, so the loader skipped both; pulling them changes no verdict today but removes two wrong targets.
