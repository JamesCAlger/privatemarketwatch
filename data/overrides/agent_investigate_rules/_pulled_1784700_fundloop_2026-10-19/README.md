# Pulled 2026-10-19: three promoted row_add rules of Varagon Capital Corporation (0001784700)

Fund-clearing loop, report `docs/investigations/v05_readings/reports/0001784700.json`. Nothing reads
this directory.

All three added rows with no issuer, class, accession or source context (findings C201, C006, C301,
C303, C304, no_provenance), pinned to single quarters:

- `1784700_heldout_missing_position_add.json` (32 rows, 2025-06-30 and 2025-09-30),
- `1784700_2025q4_missing_position_add.json` (11 rows, 2025-12-31, 4.47M),
- `restore_dropped_2026q1_positions.json` (13 rows, 2026-03-31, 4.40M).

The rows are real printed lines, but they exist as tagged contexts in the filings: staging dropped them
as affiliation-axis duplicates because two printed lines of one issuer and facility with equal figures
(e.g. 10-Q 2026-03-31, 0001193125-26-219643: "NS and Associates LLC Term Loan SOFR + 5.25 % (Q) 8.90 %
9/9/2025 8/6/2030 3,498 3,451 3,455 (1)(6) NS and Associates LLC Term Loan SOFR + 5.25 % (Q) 8.92 %
9/9/2025 8/6/2030 3,498 3,451 3,455 (1)(6)") collapsed into one key. The wrapper now sets
`staging.distinct_member_suffix_re` to the member tail from 'Type of', so the twins are published from
their own contexts in every quarter (not only the four the rules covered), with name, class and provenance.
