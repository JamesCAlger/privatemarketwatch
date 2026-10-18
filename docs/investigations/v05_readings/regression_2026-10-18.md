# Regression of the accepted funds, 2026-10-18

Code at `505a5bf` (branch `ensemble-fp-experiment`, pipeline tree clean). Covers the shared changes of
2026-10-17/18: D-202 F27 (non-cash WAC, skip under 0.5 rated share), NMY-R1 re-verifier scale,
opt-in wrapper keys, `nonaccrual_footnote` / `extracted_industry` correctable, `printed_page_declared`,
printed-page maturity precision, `interest_expense` fallback, and the five page rules
(`pipeline/candidate_rules.py`, wired in `scripts/shadow_identity_engine.py`, engine `identity`).

53 accepted funds rebuilt in six fund sandboxes (0002052152 excluded, not accepted). Sandbox-only
builds; nothing written to `data/output/` or `frontend/public/data/`; no network.

| New sandbox | Funds | 2026-06-30 | Composition matches |
|---|---|---|---|
| rgA1 | the rg1b ten | yes | rg1b and ao_rg1 |
| rgA2 | the rg2 seven + 0001899996 | no | ao_rg2b |
| rgA3 | 1278752 1572694 1702510 1786108 1825384 1901164 1901612 1916099 1920453 1930679 | yes | ao_rg3 |
| rgA4 | 1634452 1885968 1899017 1902649 1911066 1925531 1975736 1989817 2037804 2049733 | yes | ao_rg4 |
| rgA5 | 1772704 1919369 1950976 1959604 1976336 2012139 2083477 | yes | ao_rg5 |
| rgA6 | 2031750 1508655 1950803 1633336 1965934 1766037 2008748 1825265 | yes | none (accepted as singles) |

Quarter scope copied from each accepted sandbox's log: only rg2 and fcxe were built without 2026-06-30.
The groups reuse the compositions of the 2026-10-16 regression builds (`ao_rg*`, built before every
commit listed above), so a second comparison, new against `ao_rg*`, isolates the effect of the
2026-10-17/18 commits from older drift.

## Result

- **Holdings: none of the 2026-10-17/18 commits moved a published value.** New against `ao_rg1`, `ao_rg2b`,
  `ao_rg3`, `ao_rg4`, `ao_rg5` (45 funds): 0 rows added or removed, 100 of 100 columns identical.
  rgA6 has no matching earlier build; against the accepted sandboxes its only differences are listed below.
- `regression_check.py`: 51 of 53 MOVED, 2 UNCHANGED (brxb 0002049733, asxe 0002083477). Every move is
  either new page-rule findings, the F27 change, or holdings differences that were already present on
  2026-10-16 and are written up in `reports/0002052152_regression_*review.md`.
- No quarter stopped tying on any fund.

### Moves not explained by a commit (lead items)

1. **MidCap 0001278752, Asurion second lien `ROW-9c70279521a746a1`**: GICS null in mfxi, a label now. Already
   on record as unexplained on 2026-10-17 (`0002052152_regression_batch3_review.md`); identical in ao_rg3,
   so not caused by today's commits. Still unexplained.
2. **Raw-string differences, equal values** (`src_facts._financial_fair_value.raw` `"N"` to `"N.0"`, or signed
   zero `0.0` / `-0.0` in fair_value, cost, pct columns): 1572694 (2), 1825384 (3), 1916099 (3), 1930679 (3),
   1899017 (4), 1975736 (6), 1993402 (1), 1950976 (57 pct), 1976336 (44 FV / 12 cost / 53 facts), and in rgA6
   **1825265 t8zd (1 row, D&D Buyer 2023-12-31)** and **1950803 spxf (5 rows: AKAM, BBG, Vacation Rental
   Brands, Accelevation x2, 2026-03-31)**. Numerically equal in every row checked. The first group matches
   the 2026-10-17 reviews; t8zd and spxf were not compared before. The mechanism has not been isolated (the
   10-17 review did not isolate it either). It looks like a batch-dependent string or dtype representation,
   but that is not proven.
3. **Lord Abbett 0002008748, ComPsych `ROW-9bd31e3767507c3e` 2026-06-30**: GICS null in layf, now Health Care
   Services. The canonical name is now `ComPsych Investments Corp.` (layf had `ComPsych Investment Corp.`),
   because rgA6 batches layf with other funds. This is the canonical-name batch dependency recorded on 10-17,
   not a commit. Either label may be the right one: the dependency is the defect.

### Expected movers (F27, D-202)

| Fund | Accepted F27 outstanding | New | Holdings |
|---|---|---|---|
| MidCap 0001278752 | 8 | 0 | unchanged vs ao_rg3 (the 4 GICS rows vs mfxi are older drift, see above) |
| KKR FS Income Trust 0001930679 | 2 | 0 | unchanged vs ao_rg3 (3 raw strings vs kfxh are older drift) |
| Overland 0001965934 | 0 (accepted under D-202) | 0 | unchanged |
| Jefferies 0001959604, KKR Select 0001975736, Ares Core 0002083477 | 0 | 0 | ledger unaffected: only passing quarters became skips |

Consistent with b2bcf95's recorded intent (fail quarters to skip, cash rows out). kfxh also shows
+4 `financial_convention_unresolved` against kfxh, but the same count is in ao_rg3: this is the provenance-scope
change already described on 2026-10-17 (four KKR coupon rows), not from today.

## New page-rule findings

Ledger rows (one per fund, quarter and rule), outstanding, since 2022-01-01, across the 53 funds:

| Rule (ledger id) | Ledger rows | Funds |
|---|---:|---:|
| issuer_name_printed | 320 | 45 |
| units_printed | 126 | 21 |
| pik_printed | 81 | 22 |
| industry_coverage | 59 | 13 |
| preferred_printed | 30 | 8 |
| **total** | **616** | 49 |

Outstanding over all 53 funds: 1,226 accepted, 1,836 new (+616 page rules, -10 F27, +4 KKR older drift).
No page-rule finding has a proposal. Position rows behind them (`shadow/page_rule_findings.csv`, all
quarters): issuer_name not_the_printed_name 5,774, spacing_only 116, other name kinds 42;
industry no_industry_at_all 4,396, filer_industry_not_mapped 99; units proxy_count_not_on_row 384,
labelled 32; pik_printed_not_published 192, pik_value_mismatch 29; preferred 47.

## Quarter acceptance

- `promoted_rule_drift` and `promoted_rule_health` read `agent_fix_application_audit.csv` and
  `input_admission_audit.csv`, the application and load audits of promoted *corrections*. Ledger rules,
  page rules included, do not appear in either. In rgA1 neither audit mentions the five rule ids, and the
  readings match rg1b (drift 136, not_ok 123 in both). Those values come from the sandbox: the global
  rule store is applied to a 10-fund subset. They say nothing about production. **The new rules are not
  counted as drift or as unhealthy.**
- They do reach `outstanding_findings`. Sandbox-scoped run (`python -m pipeline.quarter_acceptance` with
  `PM_OUTPUT_DIR` set to the sandbox, `--findings-ledger` the sandbox ledger, outputs to scratch):
  rg1b 0 and 0; rgA1 **10 at 2026-03-31, 9 at 2026-06-30**, all page rules, state `open`, across the five
  scope funds (2026-03-31: units_printed 5, issuer_name_printed 4, pik_printed 1; 2026-06-30: units_printed 5,
  issuer_name_printed 2, pik_printed 1, industry_coverage 1). Under v4 the scope funds fail `outstanding_findings` until the
  findings are dispositioned or fixed.
  - 2026-03-31: Ares issuer_name + units; BCRED units; Blue Owl issuer_name + units; Apollo issuer_name + units; HPS issuer_name + pik + units.
  - 2026-06-30: Ares issuer_name + pik + units; BCRED units; Blue Owl units; Apollo industry_coverage + issuer_name + units; HPS units.

## Per fund

"Findings / outstanding / with a proposal" comes from `fund_gate.check_ledger`. Proposals are read from the
current `data/overrides/finding_dispositions_proposed/`, so the two columns use the same proposals.
"New-rule" is the number of outstanding page-rule ledger rows.

| CIK | Accepted | New | Holdings moved | Explanation | Accepted F/O/P | New F/O/P | New-rule outstanding |
|---|---|---|---|---|---|---|---:|
| 0001287750 Ares | rg1b | rgA1 | no | | 74/6/0 | 121/53/0 | 47 |
| 0001803498 BCRED | rg1b | rgA1 | no | | 26/0/0 | 54/28/0 | 28 |
| 0001812554 Blue Owl CI | rg1b | rgA1 | no | | 58/3/0 | 87/32/0 | 29 |
| 0001837532 Apollo DS | rg1b | rgA1 | no | | 64/0/0 | 89/25/0 | 25 |
| 0001838126 HPS | rg1b | rgA1 | no | | 71/0/0 | 96/25/0 | 25 |
| 0001872371 | rg1b | rgA1 | no | | 43/0/0 | 51/8/0 | 8 |
| 0001918712 | rg1b | rgA1 | no | | 32/1/0 | 55/24/0 | 23 |
| 0001920145 | rg1b | rgA1 | no | | 59/0/0 | 72/13/0 | 13 |
| 0001925309 | rg1b | rgA1 | no | | 47/3/0 | 76/32/0 | 29 |
| 0001930087 | rg1b | rgA1 | no | | 35/0/0 | 50/15/0 | 15 |
| 0001742313 | rg2 | rgA2 | yes, GICS 57 | c8cf047 (10-15), reviewed 10-16; = ao_rg2b | 57/33/32 | 69/45/32 | 12 |
| 0001849894 | rg2 | rgA2 | no | | 72/37/36 | 75/40/36 | 3 |
| 0001851322 | rg2 | rgA2 | no | | 62/24/23 | 73/35/23 | 11 |
| 0001859919 | rg2 | rgA2 | no | | 41/25/15 | 57/41/15 | 16 |
| 0001869453 | rg2 | rgA2 | yes, GICS 73 | c8cf047, reviewed 10-16; = ao_rg2b | 23/7/6 | 27/11/6 | 4 |
| 0001899996 | fcxe | rgA2 | no | | 50/21/21 | 51/22/21 | 1 |
| 0001913724 | rg2 | rgA2 | no | | 45/23/19 | 47/25/19 | 2 |
| 0001993402 | rg2 | rgA2 | yes, cost 1 (signed zero) | equal value, reviewed 10-17; = ao_rg2b | 63/39/30 | 77/53/30 | 14 |
| 0001278752 MidCap | mfxi | rgA3 | yes, GICS 4 | c8cf047 + canonical names; **Asurion row unexplained (10-17)**; = ao_rg3. F27 -8 (D-202) | 145/84/84 | 168/107/76 | 31 |
| 0001572694 | gsxf | rgA3 | yes, src_facts 2 | "N" to "N.0", equal; = ao_rg3 | 154/88/88 | 167/101/88 | 13 |
| 0001702510 | ccxd | rgA3 | no | | 55/26/26 | 64/35/26 | 9 |
| 0001786108 | tcxe | rgA3 | no | | 109/74/61 | 115/80/61 | 6 |
| 0001825384 | stxf | rgA3 | yes, GICS 164, src_facts 3 | c8cf047 (160) + canonical (4); .0 strings; = ao_rg3 | 31/15/15 | 51/35/15 | 20 |
| 0001901164 | trxd | rgA3 | no | | 41/6/6 | 49/14/6 | 8 |
| 0001901612 | g4xc | rgA3 | no | | 57/17/16 | 60/20/16 | 3 |
| 0001916099 | dixc | rgA3 | yes, src_facts 3 | .0 strings, equal; = ao_rg3 | 49/32/32 | 57/40/32 | 8 |
| 0001920453 | fpxg | rgA3 | no | | 41/11/10 | 52/22/10 | 11 |
| 0001930679 KKR FS IT | kfxh | rgA3 | yes, src_facts 3 | .0 strings; = ao_rg3. F27 -2 (D-202); +4 coupon_unresolved (older, 10-17) | 47/39/39 | 49/41/37 | 0 |
| 0001634452 | abxf | rgA4 | yes, GICS 27 | c8cf047 (Amercare), reviewed 10-17; = ao_rg4 | 90/43/43 | 111/64/43 | 21 |
| 0001885968 | tsxd | rgA4 | no | | 54/17/17 | 58/21/17 | 4 |
| 0001899017 | bnxd | rgA4 | yes, src_facts 4 | .0 strings, equal; = ao_rg4 | 74/42/39 | 86/54/39 | 12 |
| 0001902649 | bpxh | rgA4 | no | | 40/22/22 | 54/36/22 | 14 |
| 0001911066 | ncxf | rgA4 | no | | 34/7/6 | 35/8/6 | 1 |
| 0001925531 | ngxd | rgA4 | no | | 57/32/32 | 66/41/32 | 9 |
| 0001975736 KKR Select | ksxf | rgA4 | yes, src_facts 6 | .0 strings, equal; = ao_rg4 | 34/13/13 | 37/16/13 | 3 |
| 0001989817 | hcxe | rgA4 | no | | 37/9/8 | 50/22/8 | 13 |
| 0002037804 | npxd | rgA4 | no | | 55/32/32 | 62/39/32 | 7 |
| 0002049733 | brxb | rgA4 | no (UNCHANGED) | | 4/1/1 | 4/1/1 | 0 |
| 0001772704 | gpyf | rgA5 | no | | 102/38/27 | 108/44/27 | 6 |
| 0001919369 | viya | rgA5 | no | | 23/14/13 | 28/19/13 | 5 |
| 0001950976 | tnxc | rgA5 | yes, pct 57 (signed zero) | equal, reviewed 10-17; = ao_rg5 | 20/9/9 | 28/17/9 | 8 |
| 0001959604 Jefferies | jcxd | rgA5 | no | | 20/7/7 | 26/13/7 | 6 |
| 0001976336 | atxc | rgA5 | yes, FV 44 / cost 12 / facts 53 (signed zero) | equal, reviewed 10-17; = ao_rg5 | 36/18/18 | 45/27/18 | 9 |
| 0002012139 | foxd | rgA5 | no | | 19/14/14 | 22/17/14 | 3 |
| 0002083477 Ares Core | asxe | rgA5 | no (UNCHANGED) | | 5/1/1 | 5/1/1 | 0 |
| 0001508655 | ssxf | rgA6 | no | | 117/59/56 | 133/75/56 | 16 |
| 0001633336 Crescent | ccza | rgA6 | no | | 108/49/43 | 146/87/43 | 38 |
| 0001766037 NMF SLF I | nmyd | rgA6 | no | | 87/59/59 | 95/67/59 | 8 |
| 0001825265 TCW DL VIII | t8zd | rgA6 | yes, src_facts 1 | .0 strings, equal; cause not isolated | 20/10/10 | 23/13/10 | 3 |
| 0001950803 | spxf | rgA6 | yes, src_facts 5 | .0 strings, equal; cause not isolated (also differed vs ao_rg2) | 65/42/40 | 65/42/40 | 0 |
| 0001965934 Overland | ovye | rgA6 | no | | 30/19/19 | 36/25/19 | 6 |
| 0002008748 Lord Abbett | layf | rgA6 | yes, GICS 1 | ComPsych canonical name from batch composition | 29/19/18 | 37/27/18 | 8 |
| 0002031750 | acxb | rgA6 | no | | 38/36/35 | 40/38/35 | 2 |

Page-rule split per fund: `scratch/2026-10-18_regression/rgA*_summary.txt`.

## Not run

- Full pytest suite and targeted tests; `diff_outputs.py --semantic` (no production output was touched).
- Fund gates (`fund_gate.py check`) and page samples on the new sandboxes.
- Regression of fund-level financials (`fund_financials`, highlights, `interest_expense`): `regression_check`
  compares only holdings, the ledger and totals.
- No attribution of the raw-string / signed-zero mechanism, and no reconstruction of the MidCap Asurion row.
- Quarter acceptance run only on rgA1 vs rg1b. Every other check is meaningless in a sandbox
  (fund_coverage 10 of 60, no investigate dir).
- The accepted-sandbox record was not updated and nothing was committed.

Scripts and outputs: `scratch/2026-10-18_regression/` (summarize.py, vs_prior.py, f27.py, rowdiff.py,
rowshow.py, scope_q.py, totals.py; `rgA*_regression.txt`, `rgA*_summary.txt`, `qa_*.json`), build logs
`scratch/fund_runs/rgA*.log`.
