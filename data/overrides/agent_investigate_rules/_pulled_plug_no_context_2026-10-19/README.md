# Pulled 2026-10-19: a row_add rule that added cash rows with no context

`1715933_2025q2_add_cash_short_term_investments.json` (TCW Direct Lending VII, 2025-06-30) added
the money market fund (7,095,586) and a Treasury bill (394,466,500) as CASH rows with no source
context, to close the gap to the printed "Total Investments ( 226.1 %) $ 1,246,113,181 $ 1,093,518,278",
which includes cash equivalents and short-term investments.

The filed investments figure for the quarter (InvestmentOwnedAtFairValue 691,956,192) is the printed
"Total Debt & Equity Investments", which leaves both out, and the published non-cash rows equal it.
In 13 of the fund's 16 quarters no cash row is published; the rule made 2025-06-30 one of three
exceptions, with rows that the source reconciliation and the provenance re-verifier cannot trace
(SRC_BDC02, no_provenance). The wrapper now declares `investments_total_excludes: cash_rows`.

Fund-clearing loop, report `docs/investigations/v05_readings/reports/0001715933.json`. Nothing reads
this directory.
