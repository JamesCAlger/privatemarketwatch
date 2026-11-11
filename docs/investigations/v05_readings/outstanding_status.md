# Outstanding ledger findings, v1 cohort

Generated 2026-11-11 00:11 at git 4f63b995 by `python scripts/v05_evidence/outstanding_status.py --refresh`. Do not edit by hand; re-run it.

- Ledgers: each fund's most recently BUILT sandbox. Ledger stage re-run now against today's stores.
- A refresh does not rebuild holdings: rules added and extraction fixes since a sandbox's build are not in it.
- Outstanding = state not in `RESOLVED_FINDING_STATES` (quarter_acceptance). `real_error_check_silent` is outstanding (owner 2026-11-10).
- Review scope (owner 2026-11-10): agents investigate only `unreviewed` findings plus finding ids a rebuild newly produces; reviewed findings carry their earlier investigation forward (`carried_from`); fixing confirmed errors stays in scope.
- Production column: data/output/quarter_pass/n1110_q1c/findings_ledger_pre.csv (2026-11-10 22:15).
- Zero outstanding is not data correct.

## By quarter

| Quarter | Outstanding | proposal | verdict | review_supported | investigated | narrative | unreviewed | Production |
|---|---|---|---|---|---|---|---|---|
| 2022-03-31 | 4 | 1 | 1 | 2 | 0 | 0 | 0 | 4 |
| 2022-06-30 | 2 | 1 | 0 | 0 | 0 | 1 | 0 | 1 |
| 2022-09-30 | 4 | 1 | 1 | 1 | 0 | 1 | 0 | 4 |
| 2022-12-31 | 4 | 1 | 0 | 2 | 0 | 1 | 0 | 6 |
| 2023-03-31 | 41 | 7 | 15 | 17 | 0 | 2 | 0 | 60 |
| 2023-06-30 | 47 | 12 | 16 | 16 | 0 | 3 | 0 | 67 |
| 2023-09-30 | 55 | 16 | 15 | 20 | 0 | 3 | 1 | 75 |
| 2023-12-31 | 62 | 22 | 17 | 20 | 0 | 2 | 1 | 74 |
| 2024-03-31 | 55 | 14 | 17 | 18 | 0 | 5 | 1 | 82 |
| 2024-06-30 | 70 | 19 | 25 | 22 | 0 | 4 | 0 | 104 |
| 2024-09-30 | 79 | 21 | 29 | 25 | 0 | 3 | 1 | 105 |
| 2024-12-31 | 74 | 18 | 28 | 23 | 1 | 4 | 0 | 117 |
| 2025-03-31 | 71 | 20 | 29 | 19 | 1 | 2 | 0 | 115 |
| 2025-06-30 | 65 | 18 | 15 | 27 | 1 | 3 | 1 | 98 |
| 2025-09-30 | 71 | 17 | 28 | 23 | 1 | 2 | 0 | 113 |
| 2025-12-31 | 304 | 40 | 238 | 22 | 1 | 1 | 2 | 300 |
| 2026-03-31 | 243 | 20 | 198 | 22 | 1 | 1 | 1 | 238 |
| 2026-06-30 | 51 | 17 | 0 | 31 | 1 | 1 | 1 | 112 |
| 2026-08-13 | 1 | 0 | 0 | 1 | 0 | 0 | 0 | 1 |
| **Total** | **1303** | **265** | **672** | **311** | **7** | **39** | **9** | 1677 |

## By fund

| CIK | Sandbox used | Accepted sandbox | Holdings built | Ledger at | Outstanding | Unreviewed | 2025-12-31 | 2026-03-31 | 2026-06-30 | Production 2025-12-31 / 2026-03-31 / 2026-06-30 |
|---|---|---|---|---|---|---|---|---|---|---|
| 0001925309 | rgA1 | rg1b | 2026-10-18 | 2026-11-11 00:08 | 49 | 0 | 4 | 6 | 3 | 4 / 6 / 3 |
| 0001993402 | rgA2 | rg2 | 2026-10-18 | 2026-11-11 00:08 | 48 | 0 | 14 | 10 | 1 | 13 / 10 / 7 |
| 0001646614 | splf | same | 2026-10-19 | 2026-11-11 00:10 | 46 | 0 | 7 | 4 | 0 | 7 / 4 / 0 |
| 0001715933 | t7af | same | 2026-10-19 | 2026-11-11 00:10 | 42 | 0 | 10 | 12 | 0 | 10 / 12 / 0 |
| 0001859919 | rgA2 | rg2 | 2026-10-18 | 2026-11-11 00:08 | 41 | 0 | 4 | 2 | 1 | 4 / 2 / 7 |
| 0001786108 | rgA3 | tcxe | 2026-10-18 | 2026-11-11 00:09 | 40 | 0 | 5 | 3 | 2 | 5 / 3 / 2 |
| 0001508655 | ssq0 | ssxf | 2026-11-10 | 2026-11-11 00:10 | 37 | 0 | 7 | 7 | 2 | 7 / 7 / 2 |
| 0001702510 | rgA3 | ccxd | 2026-10-18 | 2026-11-11 00:09 | 35 | 0 | 2 | 4 | 3 | 2 / 4 / 1 |
| 0001572694 | rgA3 | gsxf | 2026-10-18 | 2026-11-11 00:09 | 34 | 0 | 12 | 8 | 1 | 13 / 9 / 1 |
| 0001899017 | rfbne | same | 2026-10-25 | 2026-11-11 00:05 | 33 | 0 | 9 | 9 | 2 | 7 / 8 / 0 |
| 0001633336 | rfcrf | same | 2026-10-26 | 2026-11-11 00:06 | 32 | 0 | 4 | 6 | 1 | 4 / 6 / 1 |
| 0001674760 | rgR1 | svce | 2026-10-26 | 2026-11-11 00:10 | 31 | 1 | 8 | 6 | 4 | 4 / 2 / 0 |
| 0001916099 | rgA3 | dixc | 2026-10-18 | 2026-11-11 00:09 | 31 | 0 | 9 | 6 | 1 | 9 / 6 / 1 |
| 0001837532 | apx5 | nvapf | 2026-11-10 | 2026-11-11 00:03 | 30 | 0 | 7 | 4 | 1 | 7 / 4 / 2 |
| 0001902649 | rgA4 | bpxh | 2026-10-18 | 2026-11-11 00:09 | 30 | 0 | 8 | 2 | 1 | 8 / 3 / 1 |
| 0001918712 | nvasf | same | 2026-10-20 | 2026-11-11 00:04 | 30 | 0 | 5 | 4 | 1 | 5 / 4 / 1 |
| 0001825384 | rgA3 | stxf | 2026-10-18 | 2026-11-11 00:09 | 29 | 0 | 5 | 3 | 1 | 5 / 3 / 1 |
| 0001950803 | rgA6 | spxf | 2026-10-18 | 2026-11-11 00:09 | 28 | 1 | 5 | 4 | 2 | 3 / 2 / 0 |
| 0001287750 | nvard | same | 2026-10-20 | 2026-11-11 00:04 | 27 | 0 | 3 | 2 | 1 | 3 / 2 / 2 |
| 0001920453 | rgA3 | fpxg | 2026-10-18 | 2026-11-11 00:09 | 27 | 0 | 8 | 7 | 1 | 8 / 8 / 1 |
| 0001930087 | rgA1 | rg1b | 2026-10-18 | 2026-11-11 00:08 | 27 | 0 | 5 | 6 | 2 | 5 / 6 / 2 |
| 0001851322 | rgA2 | rg2 | 2026-10-18 | 2026-11-11 00:08 | 26 | 0 | 8 | 6 | 1 | 10 / 6 / 20 |
| 0001772704 | rfgsf | same | 2026-10-26 | 2026-11-11 00:06 | 25 | 0 | 9 | 5 | 3 | 9 / 3 / 0 |
| 0001920145 | gspc1104b | rg1b | 2026-11-04 | 2026-11-11 00:03 | 25 | 7 | 5 | 6 | 2 | 5 / 6 / 2 |
| 0001825265 | rftcc | same | 2026-10-26 | 2026-11-11 00:08 | 23 | 0 | 4 | 2 | 0 | 4 / 2 / 0 |
| 0001954360 | cpig | same | 2026-10-19 | 2026-11-11 00:03 | 23 | 0 | 5 | 2 | 1 | 5 / 2 / 1 |
| 0001742313 | rgA2 | rg2 | 2026-10-18 | 2026-11-11 00:08 | 22 | 0 | 2 | 2 | 1 | 2 / 2 / 14 |
| 0001959568 | scie | same | 2026-10-19 | 2026-11-11 00:10 | 21 | 0 | 4 | 6 | 2 | 4 / 5 / 0 |
| 0001784700 | vgaf | same | 2026-10-19 | 2026-11-11 00:11 | 20 | 0 | 8 | 3 | 0 | 8 / 3 / 0 |
| 0001838126 | nvhpg | same | 2026-10-20 | 2026-11-11 00:05 | 20 | 0 | 6 | 4 | 0 | 6 / 4 / 4 |
| 0001872371 | rgA1 | rg1b | 2026-10-18 | 2026-11-11 00:08 | 20 | 0 | 2 | 1 | 1 | 2 / 1 / 1 |
| 0001948368 | psmf | same | 2026-10-19 | 2026-11-11 00:05 | 19 | 0 | 6 | 1 | 0 | 6 / 1 / 0 |
| 0001634452 | rfabf | same | 2026-10-25 | 2026-11-11 00:05 | 17 | 0 | 6 | 3 | 0 | 6 / 3 / 0 |
| 0001603480 | tdle | same | 2026-10-20 | 2026-11-11 00:10 | 16 | 0 | 2 | 10 | 0 | 2 / 10 / 0 |
| 0001959604 | rfjcd | same | 2026-10-25 | 2026-11-11 00:07 | 16 | 0 | 8 | 4 | 0 | 9 / 5 / 0 |
| 0002031750 | rgA6 | acxb | 2026-10-18 | 2026-11-11 00:09 | 16 | 0 | 2 | 5 | 1 | 2 / 5 / 1 |
| 0002052152 | aoyae | none | 2026-10-16 | 2026-11-11 00:03 | 16 | 0 | 6 | 5 | 0 | 4 / 6 / 0 |
| 0001766037 | rfnsf | same | 2026-10-26 | 2026-11-11 00:07 | 15 | 0 | 3 | 3 | 1 | 3 / 3 / 1 |
| 0001925531 | rfngf | same | 2026-10-25 | 2026-11-11 00:07 | 15 | 0 | 4 | 4 | 1 | 4 / 4 / 1 |
| 0001950976 | rf26c | same | 2026-10-26 | 2026-11-11 00:05 | 14 | 0 | 8 | 3 | 0 | 7 / 3 / 0 |
| 0001989817 | rfhcg | same | 2026-10-25 | 2026-11-11 00:06 | 14 | 0 | 4 | 3 | 0 | 4 / 3 / 0 |
| 0001849894 | rgA2 | rg2 | 2026-10-18 | 2026-11-11 00:08 | 13 | 0 | 3 | 4 | 1 | 3 / 4 / 7 |
| 0001869453 | rgA2 | rg2 | 2026-10-18 | 2026-11-11 00:08 | 13 | 0 | 5 | 2 | 1 | 6 / 2 / 6 |
| 0001899996 | rffcf | same | 2026-10-26 | 2026-11-11 00:06 | 13 | 0 | 5 | 4 | 0 | 5 / 4 / 0 |
| 0001901164 | rgA3 | trxd | 2026-10-18 | 2026-11-11 00:09 | 13 | 0 | 5 | 0 | 0 | 5 / 0 / 0 |
| 0002012139 | rffpe | same | 2026-10-26 | 2026-11-11 00:06 | 13 | 0 | 6 | 6 | 1 | 6 / 6 / 0 |
| 0001812554 | nvboe | same | 2026-10-20 | 2026-11-11 00:04 | 12 | 0 | 5 | 4 | 0 | 5 / 4 / 4 |
| 0001885968 | rftsc | same | 2026-10-25 | 2026-11-11 00:08 | 12 | 0 | 4 | 4 | 0 | 5 / 5 / 0 |
| 0001901612 | rgA3 | g4xc | 2026-10-18 | 2026-11-11 00:09 | 12 | 0 | 1 | 1 | 0 | 1 / 1 / 0 |
| 0001913724 | rgA2 | rg2 | 2026-10-18 | 2026-11-11 00:08 | 12 | 0 | 3 | 3 | 1 | 3 / 3 / 14 |
| 0001976336 | rfape | same | 2026-10-26 | 2026-11-11 00:05 | 12 | 0 | 9 | 3 | 0 | 9 / 3 / 0 |
| 0001965934 | rfovb | same | 2026-10-26 | 2026-11-11 00:07 | 11 | 0 | 5 | 0 | 1 | 4 / 0 / 0 |
| 0002006758 | maif | same | 2026-10-19 | 2026-11-11 00:04 | 11 | 0 | 2 | 4 | 0 | 2 / 4 / 0 |
| 0002011498 | aglf | same | 2026-10-19 | 2026-11-11 00:03 | 11 | 0 | 3 | 7 | 1 | 3 / 6 / 0 |
| 0001841514 | rgR1 | cwaf | 2026-10-26 | 2026-11-11 00:10 | 10 | 0 | 2 | 2 | 0 | 2 / 2 / 0 |
| 0001919369 | rfvsc | same | 2026-10-26 | 2026-11-11 00:08 | 10 | 0 | 2 | 0 | 0 | 2 / 0 / 0 |
| 0001911066 | rgA4 | ncxf | 2026-10-18 | 2026-11-11 00:09 | 9 | 0 | 0 | 2 | 0 | 0 / 2 / 0 |
| 0002008748 | rflad | same | 2026-10-26 | 2026-11-11 00:07 | 2 | 0 | 1 | 1 | 0 | 1 / 1 / 0 |
| 0002049733 | rgA4 | brxb | 2026-10-18 | 2026-11-11 00:09 | 2 | 0 | 0 | 2 | 0 | 0 / 2 / 0 |
| 0001803498 | nbbcc | same | 2026-11-10 | 2026-11-11 00:04 | 1 | 0 | 0 | 0 | 0 | 3 / 0 / 1 |
| 0002083477 | rgA5 | asxe | 2026-10-18 | 2026-11-11 00:09 | 1 | 0 | 0 | 1 | 0 | 0 / 1 / 0 |

## Review scope: unreviewed and investigated-without-review (16)

| CIK | Quarter | Engine | Rule | State | Category | review_id |
|---|---|---|---|---|---|---|
| 0001674760 | 2025-12-31 | oracle | B01 | open | unreviewed | RVQ_REV_aefca8faf0b4 |
| 0001920145 | 2023-09-30 | identity | issuer_name_printed | open | unreviewed | RVQ_BLK_0467314ce4d0 |
| 0001920145 | 2023-12-31 | identity | issuer_name_printed | open | unreviewed | RVQ_BLK_e31aba290714 |
| 0001920145 | 2024-03-31 | identity | issuer_name_printed | open | unreviewed | RVQ_BLK_6cf2c651130c |
| 0001920145 | 2024-09-30 | identity | issuer_name_printed | open | unreviewed | RVQ_BLK_9a7cf62497e6 |
| 0001920145 | 2024-12-31 | identity | issuer_name_printed | open | investigated | RVQ_BLK_fe670b845316 |
| 0001920145 | 2025-03-31 | identity | issuer_name_printed | open | investigated | RVQ_BLK_71891d1539d4 |
| 0001920145 | 2025-06-30 | identity | issuer_name_printed | open | investigated | RVQ_BLK_4b5f344ec376 |
| 0001920145 | 2025-06-30 | oracle | B01 | open | unreviewed | RVQ_REV_a3e52bf808b2 |
| 0001920145 | 2025-09-30 | identity | issuer_name_printed | open | investigated | RVQ_BLK_6521069052a0 |
| 0001920145 | 2025-12-31 | identity | issuer_name_printed | open | investigated | RVQ_BLK_fc7e2604552d |
| 0001920145 | 2026-03-31 | identity | units_printed | open | unreviewed | RVQ_BLK_2848a6b63e4d |
| 0001920145 | 2026-03-31 | identity | issuer_name_printed | open | investigated | RVQ_BLK_5e3c93599309 |
| 0001920145 | 2026-06-30 | identity | units_printed | open | unreviewed | RVQ_BLK_e4d63aaad35a |
| 0001920145 | 2026-06-30 | identity | issuer_name_printed | open | investigated | RVQ_BLK_f894fdafc604 |
| 0001950803 | 2025-12-31 | oracle | B02 | open | unreviewed | RVQ_REV_66eeb8c7f2ab |

## Refresh log

- aglf exit 0 10s
- aoyae exit 0 10s
- apx5 exit 0 11s
- cpig exit 0 11s
- gspc1104b exit 0 11s
- maif exit 0 10s
- nbbcc exit 0 12s
- nvard exit 0 13s
- nvasf exit 0 11s
- nvboe exit 0 12s
- nvhpg exit 0 12s
- psmf exit 0 11s
- rf26c exit 0 11s
- rfabf exit 0 12s
- rfape exit 0 12s
- rfbne exit 0 11s
- rfcrf exit 0 13s
- rffcf exit 0 11s
- rffpe exit 0 10s
- rfgsf exit 0 11s
- rfhcg exit 0 10s
- rfjcd exit 0 11s
- rflad exit 0 12s
- rfngf exit 0 12s
- rfnsf exit 0 12s
- rfovb exit 0 10s
- rftcc exit 0 10s
- rftsc exit 0 12s
- rfvsc exit 0 10s
- rgA1 exit 0 17s
- rgA2 exit 0 14s
- rgA3 exit 0 14s
- rgA4 exit 0 14s
- rgA5 exit 0 13s
- rgA6 exit 0 14s
- rgR1 exit 0 11s
- scie exit 0 11s
- splf exit 0 12s
- ssq0 exit 0 11s
- t7af exit 0 11s
- tdle exit 0 10s
- vgaf exit 0 12s
