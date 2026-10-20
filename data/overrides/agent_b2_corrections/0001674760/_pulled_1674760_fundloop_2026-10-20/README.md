# Pulled 2026-10-20: B2 column_remap of Silver Capital Holdings LLC (0001674760)

Fund-clearing loop, report `docs/investigations/v05_readings/reports/0001674760.json`. Nothing reads
this directory.

- `column_remap.json` (principal_amount -> shares_held, 2025-12-31, selector issuer 'Khoros, LLC (fka
  Lithium Technologies, Inc.)', table 38 row 11): meant for the Khoros preferred stock line ('Khoros,
  LLC (fka Lithium Technologies, Inc.) | Interactive Media & Services | 05/23/25 | 133,523 | 5,739 |
  5,728'), whose unit count the build already publishes from its share tag (133,523 in every quarter
  from 2025-06-30). The selector matched by issuer name, so the remap hit the Khoros first-lien loan
  instead: sandbox svcb publishes that loan at 2025-12-31 with no principal and shares_held 12,518,000
  (printed 'Khoros, LLC (fka Lithium Technologies, Inc.) Interactive Media & Services 10.00 % 10.00 %
  05/23/30 12,518 12,093 12,048'). It raised X11 (drawn loan with no principal) for 2025-12-31.
  Without it the loan publishes principal 12,518,000 as in the other quarters.
