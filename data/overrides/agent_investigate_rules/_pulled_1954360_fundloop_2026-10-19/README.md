# Pulled 2026-10-19: three promoted rules of Crescent Private Credit Income Corp (0001954360)

Fund-clearing loop, report `docs/investigations/v05_readings/reports/0001954360.json`. Nothing reads
this directory.

- `05_..._mph_healthcare_term_loan_fair_value.json` set MPH Acquisition 2024-06-30 fair value to 930,000
  ("subtotal-implied"). A plug: the page prints 831 ("MPH Acquisition (7) Senior Secured First Lien Term
  Loan S + 425 ( 50 Floor) 9.86 % 09/2028 995 968 0.5 831", 0000950170-24-096155) and the tag is 831,000.
  The 99,000 gap in the Health Care block is the two MB2 Dental delayed-draw lines: the tagged one prints
  "- ( 18 ) - 38" but is tagged -38,000 (fixed by a context-keyed row correction to 38,000), and the second
  prints "- (22 ) - 23" and has no context in the filing (38 + 38 + 23 = 99).
- `04_..._pinnacle_term_loan_fair_value.json` set only the fair value (3,607,000) of the Pinnacle Purchaser
  term loan 2024-06-30, where the filing splits all three printed figures across tags ("3, 607 3, 575 2.3
  3, 607", tags 607 / 575 / 607). Replaced by context-keyed row corrections of fair value, cost and par.
- `02_..._anchor_packaging_missing_row.json` added the Anchor Packaging LLC 2024-03-31 term loan as a row
  with no accession, context or class. The tagged row exists (context C_5015f54c-...); staging dropped it as
  a duplicate because the member's industry label ('Materials') was not in the issuer pattern, so it had no
  issuer and collided with another unnamed row. The wrapper's issuer pattern now names it.
- `00_..._exclude_cash_equivalents_from_investments_anchor.json` (scope all quarters) removed every row whose
  member names 'Cash Equivalents' from the published data so the fair-value check against the filed
  investments figure would pass. The rows are printed holdings below 'Total Investments' (2023-09-30 to
  2025-03-31 the money funds are tagged; e.g. 2023-09-30 "Dreyfus Government Cash Management
  Institutional Fund ... 36,082"). The wrapper now declares `investments_total_excludes: cash_rows`, so
  the cash rows are published as cash and the check compares the non-cash rows with the filed figure.
