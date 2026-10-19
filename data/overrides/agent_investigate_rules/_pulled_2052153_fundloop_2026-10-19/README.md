# Pulled 2026-10-19: two promoted rules of Apollo Origination II (UL) Capital Trust (0002052153)

Fund-clearing loop, report `docs/investigations/v05_readings/reports/0002052153.json`. Nothing reads
this directory.

- `recover_de_minimis_revolver_rows_from_staging.json` (row_add, 2025-06-30 and 2025-09-30) added four
  undrawn revolver rows at fair value 1,000 with no class, accession or source context (findings C006,
  C301, C303, C304, SRC_BDC02, no_provenance) "to close" residuals of -1,000 and -2,000 that were
  rounding. The page prints a dash for their fair value (10-Q 2025-09-30, 0001193125-25-278012:
  "First Lien Secured Debt - Revolver S + 500 , 0.75 % Floor 7/2/2031 - 1 - (7)(10)(14)(16)", Everbridge).
  The rows are tagged contexts with a cost or principal and no fair-value fact; staging dropped them as
  excluded_no_fair_value together with 18 other dash lines. The wrapper now declares fair value 0 from the
  page for all 22 (`source_encodings.untagged_values`), so they publish from their own contexts.
- `exclude_co_investment_axis_subtotal.json` (row_exclusion, all quarters) removed the member
  "Co-investment", the footnote total of co-investments (ctx carries fair value, cost and percent of net
  assets only; 10-Q 2026-03-31 footnote "(12) These are co-investments made with the Company's affiliates
  in accordance with the terms of the exemptive order"). The result was right but the wrapper had
  dispatched it as a 'fund' leaf first (source findings blocking_source_short_plain_unresolved and
  SRC_BDC01 in every quarter). The wrapper no longer has the 'fund' family; the member is an aggregate,
  so staging never publishes it and the rule matches nothing.
