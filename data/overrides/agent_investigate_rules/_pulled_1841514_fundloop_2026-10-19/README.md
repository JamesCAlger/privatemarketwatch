# Pulled 2026-10-19: two promoted rules of Commonwealth Credit Partners BDC I (0001841514)

Fund-clearing loop, report `docs/investigations/v05_readings/reports/0001841514.json`. Nothing reads
this directory.

- `exclude_duplicate_kent_affiliate_rows.json` (row_exclusion, all quarters) required
  `src_transforms = 'cost:cost_proxy_fv'`, which the build no longer sets on these rows, so it matched
  nothing: the two Kent Water Sports rows of the affiliated-investments roll-forward note were published
  in 2024-03-31 to 2024-12-31 (fv_conservation 11.5M, 10.9M, 9.9M, 9.6M over the filed total).
- `exclude_kent_water_affiliated_duplicate_rows.json` (row_exclusion, all quarters) removed the same note
  rows from 2025-03-31 on by naming one issuer (`LIKE 'Non-controlled, Affiliated investments, Kent Water
  Sports Holdings, LLC - Delayed Draw Loan%'`); a second affiliate in the note would leak.

Both are replaced by `1841514/exclude_affiliate_rollforward_note_rows.json`, which matches the note's own
member headings ('Affiliate company investment,', 'Affiliated investments,', 'Non-controlled, Affiliated
investments,') in every quarter. Printed (10-Q 2024-06-30, 0000950170-24-096491): "Affiliated investments:
Kent Water Sports Holdings, LLC - Delayed Draw Loan Last-Out First Lien Senior Secured $ - $ 8,176 $ 92 $ -
$ - $ ( 3,044 ) $ 5,224".
