# Decisions for the owner, collected during the run of 2026-10-12

Nothing below was decided by the agent. Each item names where the evidence is.

| # | Question | Agent's recommendation | Evidence |
|---|---|---|---|
| 1 | Should a filed share count ever be replaced by another row's of the same issuer name? 1,653 rows in 92 funds in the published build; rises as names are cleaned (Barings 12 to 52, Sixth Street Specialty Lending 8 to 17). | No: publish the filed count. | D-111 |
| 2 | Loans printed with a PIK part and a spread, and no plain rate (Monroe 204, Twin Brook 5 to 18 a quarter, first five funds): publish the PIK figure as the rate where it exceeds the spread? | Yes for that case; leave a PIK margin alone. | D-092 |
| 3 | Stepstone, Puma Buyer 2025-09-30: the page prints fair value 3,829 for a loan of 13,829 par (percent 0.92 implies 13,829). Publish as filed, or correct to 13,829,000? | Correct; the percent and the industry subtotal both give 13,829. | D-112 |
| 4 | The 215 proposed dispositions for the nine funds of D-099 to D-110, plus those added below. | Accept by reason, not by fund. | `data/overrides/finding_dispositions_proposed/fund_*.json` |
| 5 | The 34 proposals for the next five funds (unchanged). | - | `docs/investigations/next5_proposed_dispositions.md` |
