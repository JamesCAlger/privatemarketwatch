# Outstanding ledger findings, v1 cohort

Generated 2026-11-12 16:04 at git 3d5da2a8 by `python scripts/v05_evidence/outstanding_status.py --refresh`. Do not edit by hand; re-run it.

- Ledgers: each fund's most recently BUILT sandbox. Ledger stage re-run now against today's stores.
- A refresh does not rebuild holdings: rules added and extraction fixes since a sandbox's build are not in it.
- Outstanding = state not in `RESOLVED_FINDING_STATES` (quarter_acceptance). `real_error_check_silent` is outstanding (owner 2026-11-10).
- Review scope (owner 2026-11-10): agents investigate only `unreviewed` findings plus finding ids a rebuild newly produces; reviewed findings carry their earlier investigation forward (`carried_from`); fixing confirmed errors stays in scope.
- Production column: data/output/quarter_pass/n1110_q1c/findings_ledger_pre.csv (2026-11-10 22:15).
- Zero outstanding is not data correct.

## By quarter

| Quarter | Outstanding | proposal | verdict | review_supported | investigated | narrative | unreviewed | Production |
|---|---|---|---|---|---|---|---|---|
| 2022-03-31 | 4 | 0 | 1 | 2 | 0 | 0 | 1 | 4 |
| 2022-06-30 | 2 | 0 | 0 | 0 | 0 | 1 | 1 | 1 |
| 2022-09-30 | 2 | 0 | 0 | 1 | 0 | 1 | 0 | 4 |
| 2022-12-31 | 3 | 0 | 0 | 2 | 0 | 1 | 0 | 6 |
| 2023-03-31 | 34 | 2 | 12 | 16 | 0 | 2 | 2 | 60 |
| 2023-06-30 | 35 | 2 | 12 | 16 | 0 | 3 | 2 | 67 |
| 2023-09-30 | 39 | 3 | 11 | 20 | 0 | 3 | 2 | 75 |
| 2023-12-31 | 40 | 3 | 14 | 20 | 0 | 2 | 1 | 74 |
| 2024-03-31 | 36 | 1 | 13 | 16 | 0 | 4 | 2 | 82 |
| 2024-06-30 | 54 | 5 | 21 | 22 | 0 | 3 | 3 | 104 |
| 2024-09-30 | 60 | 5 | 27 | 22 | 0 | 3 | 3 | 105 |
| 2024-12-31 | 57 | 3 | 25 | 22 | 0 | 4 | 3 | 117 |
| 2025-03-31 | 51 | 4 | 24 | 18 | 0 | 2 | 3 | 115 |
| 2025-06-30 | 46 | 3 | 11 | 26 | 0 | 3 | 3 | 98 |
| 2025-09-30 | 51 | 1 | 23 | 21 | 0 | 2 | 4 | 113 |
| 2025-12-31 | 255 | 26 | 206 | 22 | 0 | 1 | 0 | 300 |
| 2026-03-31 | 210 | 8 | 177 | 21 | 0 | 1 | 3 | 238 |
| 2026-06-30 | 34 | 0 | 0 | 31 | 0 | 1 | 2 | 112 |
| 2026-08-13 | 1 | 0 | 0 | 1 | 0 | 0 | 0 | 1 |
| **Total** | **1014** | **66** | **577** | **299** | **0** | **37** | **35** | 1677 |

## By fund

| CIK | Sandbox used | Accepted sandbox | Holdings built | Ledger at | Outstanding | Unreviewed | 2025-12-31 | 2026-03-31 | 2026-06-30 | Production 2025-12-31 / 2026-03-31 / 2026-06-30 |
|---|---|---|---|---|---|---|---|---|---|---|
| 0001508655 | ssq0 | ssxf | 2026-11-10 | 2026-11-12 16:03 | 62 | 25 | 7 | 9 | 4 | 7 / 7 / 2 |
| 0001925309 | rgA1 | rg1b | 2026-10-18 | 2026-11-12 16:02 | 49 | 0 | 4 | 6 | 3 | 4 / 6 / 3 |
| 0001993402 | rgA2 | rg2 | 2026-10-18 | 2026-11-12 16:02 | 44 | 0 | 13 | 10 | 1 | 13 / 10 / 7 |
| 0001859919 | rgA2 | rg2 | 2026-10-18 | 2026-11-12 16:02 | 41 | 0 | 4 | 2 | 1 | 4 / 2 / 7 |
| 0001786108 | rgA3 | tcxe | 2026-10-18 | 2026-11-12 16:02 | 40 | 0 | 5 | 3 | 2 | 5 / 3 / 2 |
| 0001572694 | rgA3 | gsxf | 2026-10-18 | 2026-11-12 16:02 | 34 | 0 | 12 | 8 | 1 | 13 / 9 / 1 |
| 0001825384 | rgA3 | stxf | 2026-10-18 | 2026-11-12 16:02 | 33 | 4 | 5 | 3 | 1 | 5 / 3 / 1 |
| 0001715933 | t7af | same | 2026-10-19 | 2026-11-12 16:04 | 31 | 1 | 10 | 12 | 0 | 10 / 12 / 0 |
| 0001916099 | rgA3 | dixc | 2026-10-18 | 2026-11-12 16:02 | 31 | 0 | 9 | 6 | 1 | 9 / 6 / 1 |
| 0001646614 | splf | same | 2026-10-19 | 2026-11-12 16:03 | 27 | 0 | 7 | 4 | 0 | 7 / 4 / 0 |
| 0001920453 | rgA3 | fpxg | 2026-10-18 | 2026-11-12 16:02 | 27 | 0 | 8 | 7 | 1 | 8 / 8 / 1 |
| 0001930087 | rgA1 | rg1b | 2026-10-18 | 2026-11-12 16:02 | 27 | 0 | 5 | 6 | 2 | 5 / 6 / 2 |
| 0001851322 | rgA2 | rg2 | 2026-10-18 | 2026-11-12 16:02 | 25 | 0 | 8 | 6 | 1 | 10 / 6 / 20 |
| 0001902649 | rgA4 | bpxh | 2026-10-18 | 2026-11-12 16:02 | 24 | 0 | 8 | 2 | 1 | 8 / 3 / 1 |
| 0001633336 | rfcrf | same | 2026-10-26 | 2026-11-12 15:59 | 23 | 0 | 4 | 6 | 1 | 4 / 6 / 1 |
| 0001825265 | rftcc | same | 2026-10-26 | 2026-11-12 16:01 | 23 | 0 | 4 | 2 | 0 | 4 / 2 / 0 |
| 0001872371 | rgA1 | rg1b | 2026-10-18 | 2026-11-12 16:02 | 20 | 0 | 2 | 1 | 1 | 2 / 1 / 1 |
| 0001899017 | rfbne | same | 2026-10-25 | 2026-11-12 15:59 | 20 | 0 | 7 | 8 | 0 | 7 / 8 / 0 |
| 0001702510 | rgA3 | ccxd | 2026-10-18 | 2026-11-12 16:02 | 19 | 0 | 2 | 4 | 2 | 2 / 4 / 1 |
| 0001742313 | rgA2 | rg2 | 2026-10-18 | 2026-11-12 16:02 | 19 | 0 | 2 | 2 | 1 | 2 / 2 / 14 |
| 0001784700 | vgaf | same | 2026-10-19 | 2026-11-12 16:04 | 19 | 1 | 8 | 3 | 0 | 8 / 3 / 0 |
| 0001603480 | tdle | same | 2026-10-20 | 2026-11-12 16:04 | 16 | 0 | 2 | 10 | 0 | 2 / 10 / 0 |
| 0001959568 | scie | same | 2026-10-19 | 2026-11-12 16:03 | 16 | 0 | 4 | 5 | 0 | 4 / 5 / 0 |
| 0002031750 | rgA6 | acxb | 2026-10-18 | 2026-11-12 16:03 | 16 | 0 | 2 | 5 | 1 | 2 / 5 / 1 |
| 0001766037 | rfnsf | same | 2026-10-26 | 2026-11-12 16:01 | 15 | 0 | 3 | 3 | 1 | 3 / 3 / 1 |
| 0001925531 | rfngf | same | 2026-10-25 | 2026-11-12 16:01 | 15 | 0 | 4 | 4 | 1 | 4 / 4 / 1 |
| 0001287750 | nbare | same | 2026-11-11 | 2026-11-12 15:58 | 14 | 0 | 1 | 1 | 1 | 3 / 2 / 2 |
| 0001634452 | rfabf | same | 2026-10-25 | 2026-11-12 15:59 | 14 | 1 | 6 | 3 | 0 | 6 / 3 / 0 |
| 0001837532 | nbape | same | 2026-11-11 | 2026-11-12 15:57 | 14 | 0 | 1 | 1 | 1 | 7 / 4 / 2 |
| 0001959604 | rfjcd | same | 2026-10-25 | 2026-11-12 16:00 | 14 | 0 | 8 | 4 | 0 | 9 / 5 / 0 |
| 0001989817 | rfhcg | same | 2026-10-25 | 2026-11-12 16:00 | 14 | 0 | 4 | 3 | 0 | 4 / 3 / 0 |
| 0002052152 | aoyae | none | 2026-10-16 | 2026-11-12 15:57 | 14 | 1 | 4 | 6 | 0 | 4 / 6 / 0 |
| 0001772704 | rfgsf | same | 2026-10-26 | 2026-11-12 16:00 | 13 | 0 | 6 | 2 | 0 | 9 / 3 / 0 |
| 0001869453 | rgA2 | rg2 | 2026-10-18 | 2026-11-12 16:02 | 13 | 0 | 5 | 2 | 1 | 6 / 2 / 6 |
| 0001901164 | rgA3 | trxd | 2026-10-18 | 2026-11-12 16:02 | 13 | 0 | 5 | 0 | 0 | 5 / 0 / 0 |
| 0001954360 | cpig | same | 2026-10-19 | 2026-11-12 15:57 | 13 | 0 | 5 | 2 | 1 | 5 / 2 / 1 |
| 0001849894 | rgA2 | rg2 | 2026-10-18 | 2026-11-12 16:02 | 12 | 0 | 3 | 4 | 1 | 3 / 4 / 7 |
| 0001901612 | rgA3 | g4xc | 2026-10-18 | 2026-11-12 16:02 | 12 | 0 | 1 | 1 | 0 | 1 / 1 / 0 |
| 0001913724 | rgA2 | rg2 | 2026-10-18 | 2026-11-12 16:02 | 12 | 0 | 3 | 3 | 1 | 3 / 3 / 14 |
| 0001976336 | rfape | same | 2026-10-26 | 2026-11-12 15:59 | 12 | 0 | 9 | 3 | 0 | 9 / 3 / 0 |
| 0002012139 | rffpe | same | 2026-10-26 | 2026-11-12 16:00 | 12 | 0 | 6 | 6 | 0 | 6 / 6 / 0 |
| 0001885968 | rftsc | same | 2026-10-25 | 2026-11-12 16:01 | 11 | 0 | 4 | 4 | 0 | 5 / 5 / 0 |
| 0001899996 | rffcf | same | 2026-10-26 | 2026-11-12 16:00 | 11 | 0 | 5 | 4 | 0 | 5 / 4 / 0 |
| 0002006758 | maif | same | 2026-10-19 | 2026-11-12 15:57 | 11 | 0 | 2 | 4 | 0 | 2 / 4 / 0 |
| 0001950976 | rf26c | same | 2026-10-26 | 2026-11-12 15:59 | 10 | 0 | 7 | 3 | 0 | 7 / 3 / 0 |
| 0002011498 | aglf | same | 2026-10-19 | 2026-11-12 15:57 | 9 | 0 | 3 | 6 | 0 | 3 / 6 / 0 |
| 0001841514 | rgR1 | cwaf | 2026-10-26 | 2026-11-12 16:03 | 8 | 0 | 2 | 2 | 0 | 2 / 2 / 0 |
| 0001918712 | nbase | same | 2026-11-11 | 2026-11-12 15:58 | 8 | 0 | 1 | 1 | 1 | 5 / 4 / 1 |
| 0001948368 | psmf | same | 2026-10-19 | 2026-11-12 15:59 | 7 | 0 | 6 | 1 | 0 | 6 / 1 / 0 |
| 0001911066 | rgA4 | ncxf | 2026-10-18 | 2026-11-12 16:02 | 6 | 0 | 0 | 2 | 0 | 0 / 2 / 0 |
| 0001919369 | rfvsc | same | 2026-10-26 | 2026-11-12 16:01 | 5 | 0 | 2 | 0 | 0 | 2 / 0 / 0 |
| 0001965934 | rfovb | same | 2026-10-26 | 2026-11-12 16:01 | 5 | 0 | 4 | 0 | 0 | 4 / 0 / 0 |
| 0001803498 | nbbcc | same | 2026-11-10 | 2026-11-12 15:58 | 3 | 2 | 0 | 0 | 0 | 3 / 0 / 1 |
| 0001812554 | nbocf | same | 2026-11-11 | 2026-11-12 15:58 | 2 | 0 | 1 | 1 | 0 | 5 / 4 / 4 |
| 0002008748 | rflad | same | 2026-10-26 | 2026-11-12 16:00 | 2 | 0 | 1 | 1 | 0 | 1 / 1 / 0 |
| 0002049733 | rgA4 | brxb | 2026-10-18 | 2026-11-12 16:02 | 2 | 0 | 0 | 2 | 0 | 0 / 2 / 0 |
| 0001920145 | nbgpe | rg1b | 2026-11-11 | 2026-11-12 15:58 | 1 | 0 | 1 | 0 | 0 | 5 / 6 / 2 |
| 0002083477 | rgA5 | asxe | 2026-10-18 | 2026-11-12 16:02 | 1 | 0 | 0 | 1 | 0 | 0 / 1 / 0 |

## Review scope: unreviewed and investigated-without-review (35)

| CIK | Quarter | Engine | Rule | State | Category | review_id |
|---|---|---|---|---|---|---|
| 0001508655 | 2023-03-31 | source_recon | blocking_source_position_like_parser_mismatch | open | unreviewed | BDCSRC_0001508655_2023-03-31_BLOCKING_SOURCE_POSITION_LIKE_PARSER_MISMATCH_6a71a8ee9b |
| 0001508655 | 2023-03-31 | row_validation | SRC_BDC01 | open | unreviewed | RVQ_BLK_3b4fb3ab83dd |
| 0001508655 | 2023-06-30 | source_recon | blocking_source_position_like_parser_mismatch | open | unreviewed | BDCSRC_0001508655_2023-06-30_BLOCKING_SOURCE_POSITION_LIKE_PARSER_MISMATCH_015ff56e8a |
| 0001508655 | 2023-09-30 | source_recon | blocking_source_position_like_parser_mismatch | open | unreviewed | BDCSRC_0001508655_2023-09-30_BLOCKING_SOURCE_POSITION_LIKE_PARSER_MISMATCH_c8b47b08f9 |
| 0001508655 | 2023-12-31 | source_recon | blocking_source_position_like_parser_mismatch | open | unreviewed | BDCSRC_0001508655_2023-12-31_BLOCKING_SOURCE_POSITION_LIKE_PARSER_MISMATCH_d9c656e5f9 |
| 0001508655 | 2024-03-31 | source_recon | blocking_source_pct_leaf_parser_mismatch | open | unreviewed | BDCSRC_0001508655_2024-03-31_BLOCKING_SOURCE_PCT_LEAF_PARSER_MISMATCH_dd0a0d4e62 |
| 0001508655 | 2024-03-31 | source_recon | blocking_source_position_like_parser_mismatch | open | unreviewed | BDCSRC_0001508655_2024-03-31_BLOCKING_SOURCE_POSITION_LIKE_PARSER_MISMATCH_5eef4e3544 |
| 0001508655 | 2024-06-30 | source_recon | blocking_source_pct_leaf_parser_mismatch | open | unreviewed | BDCSRC_0001508655_2024-06-30_BLOCKING_SOURCE_PCT_LEAF_PARSER_MISMATCH_2603f5855c |
| 0001508655 | 2024-06-30 | source_recon | blocking_source_position_like_parser_mismatch | open | unreviewed | BDCSRC_0001508655_2024-06-30_BLOCKING_SOURCE_POSITION_LIKE_PARSER_MISMATCH_f7af411216 |
| 0001508655 | 2024-09-30 | source_recon | blocking_source_pct_leaf_parser_mismatch | open | unreviewed | BDCSRC_0001508655_2024-09-30_BLOCKING_SOURCE_PCT_LEAF_PARSER_MISMATCH_20748c9fca |
| 0001508655 | 2024-09-30 | source_recon | blocking_source_position_like_parser_mismatch | open | unreviewed | BDCSRC_0001508655_2024-09-30_BLOCKING_SOURCE_POSITION_LIKE_PARSER_MISMATCH_07c1a9b3a2 |
| 0001508655 | 2024-12-31 | source_recon | blocking_source_pct_leaf_parser_mismatch | open | unreviewed | BDCSRC_0001508655_2024-12-31_BLOCKING_SOURCE_PCT_LEAF_PARSER_MISMATCH_320abd6a72 |
| 0001508655 | 2024-12-31 | source_recon | blocking_source_position_like_parser_mismatch | open | unreviewed | BDCSRC_0001508655_2024-12-31_BLOCKING_SOURCE_POSITION_LIKE_PARSER_MISMATCH_fc532a624b |
| 0001508655 | 2025-03-31 | source_recon | blocking_source_pct_leaf_parser_mismatch | open | unreviewed | BDCSRC_0001508655_2025-03-31_BLOCKING_SOURCE_PCT_LEAF_PARSER_MISMATCH_ff811d0f17 |
| 0001508655 | 2025-03-31 | source_recon | blocking_source_position_like_parser_mismatch | open | unreviewed | BDCSRC_0001508655_2025-03-31_BLOCKING_SOURCE_POSITION_LIKE_PARSER_MISMATCH_037d8122b0 |
| 0001508655 | 2025-06-30 | source_recon | blocking_source_pct_leaf_parser_mismatch | open | unreviewed | BDCSRC_0001508655_2025-06-30_BLOCKING_SOURCE_PCT_LEAF_PARSER_MISMATCH_b583f36138 |
| 0001508655 | 2025-06-30 | source_recon | blocking_source_position_like_parser_mismatch | open | unreviewed | BDCSRC_0001508655_2025-06-30_BLOCKING_SOURCE_POSITION_LIKE_PARSER_MISMATCH_99194e4bd2 |
| 0001508655 | 2025-06-30 | row_validation | SRC_BDC01 | open | unreviewed | RVQ_BLK_43f1dff48b9c |
| 0001508655 | 2025-09-30 | source_recon | blocking_source_pct_leaf_parser_mismatch | open | unreviewed | BDCSRC_0001508655_2025-09-30_BLOCKING_SOURCE_PCT_LEAF_PARSER_MISMATCH_49544ece6b |
| 0001508655 | 2025-09-30 | source_recon | blocking_source_position_like_parser_mismatch | open | unreviewed | BDCSRC_0001508655_2025-09-30_BLOCKING_SOURCE_POSITION_LIKE_PARSER_MISMATCH_e51dbfb939 |
| 0001508655 | 2025-09-30 | row_validation | SRC_BDC01 | open | unreviewed | RVQ_BLK_4b3eeb81893d |
| 0001508655 | 2026-03-31 | source_recon | blocking_source_position_like_parser_mismatch | open | unreviewed | BDCSRC_0001508655_2026-03-31_BLOCKING_SOURCE_POSITION_LIKE_PARSER_MISMATCH_1e4ab0f33c |
| 0001508655 | 2026-03-31 | row_validation | SRC_BDC01 | open | unreviewed | RVQ_BLK_a333e99aeaff |
| 0001508655 | 2026-06-30 | source_recon | blocking_source_position_like_parser_mismatch | open | unreviewed | BDCSRC_0001508655_2026-06-30_BLOCKING_SOURCE_POSITION_LIKE_PARSER_MISMATCH_96639effd1 |
| 0001508655 | 2026-06-30 | row_validation | SRC_BDC01 | open | unreviewed | RVQ_BLK_1bc5d78ee8b7 |
| 0001634452 | 2023-09-30 | oracle | B01 | open | unreviewed | RVQ_REV_81f1981e1f51 |
| 0001715933 | 2024-06-30 | oracle | B01 | open | unreviewed | RVQ_REV_73e5e22898e6 |
| 0001784700 | 2023-06-30 | oracle | B01 | open | unreviewed | RVQ_REV_ced40819edfb |
| 0001803498 | 2022-03-31 | fund_financials | F28 | open | unreviewed | RVQ_REV_e89d777120f0 |
| 0001803498 | 2022-06-30 | fund_financials | F28 | open | unreviewed | RVQ_REV_8788b4b75ff1 |
| 0001825384 | 2024-09-30 | oracle | B01 | open | unreviewed | RVQ_REV_6264b1d5cb79 |
| 0001825384 | 2024-12-31 | oracle | B01 | open | unreviewed | RVQ_REV_e576ef15aee3 |
| 0001825384 | 2025-03-31 | oracle | B01 | open | unreviewed | RVQ_REV_4c7618f7b77a |
| 0001825384 | 2025-09-30 | oracle | B01 | open | unreviewed | RVQ_REV_791e66a95963 |
| 0002052152 | 2026-03-31 | identity | issuer_name_printed | open | unreviewed | RVQ_BLK_c1f5972c9e0d |

## Refresh log

- aglf exit 0 10s
- aoyae exit 0 9s
- cpig exit 0 10s
- maif exit 0 9s
- nbape exit 0 10s
- nbare exit 0 11s
- nbase exit 0 10s
- nbbcc exit 0 10s
- nbgpe exit 0 10s
- nbhpe exit 0 10s
- nbocf exit 0 10s
- psmf exit 0 10s
- rf26c exit 0 10s
- rfabf exit 0 11s
- rfape exit 0 11s
- rfbne exit 0 10s
- rfcrf exit 0 10s
- rffcf exit 0 10s
- rffpe exit 0 9s
- rfgsf exit 0 10s
- rfhcg exit 0 10s
- rfjcd exit 0 10s
- rflad exit 0 9s
- rfngf exit 0 10s
- rfnsf exit 0 10s
- rfovb exit 0 9s
- rftcc exit 0 9s
- rftsc exit 0 10s
- rfvsc exit 0 9s
- rgA1 exit 0 15s
- rgA2 exit 0 12s
- rgA3 exit 0 13s
- rgA4 exit 0 12s
- rgA5 exit 0 11s
- rgA6 exit 0 12s
- rgR1 exit 0 10s
- scie exit 0 10s
- splf exit 0 10s
- spyg exit 0 12s
- ssq0 exit 0 9s
- svda exit 0 10s
- t7af exit 0 10s
- tdle exit 0 9s
- vgaf exit 0 10s
