# Apollo regression batch 3: independent bounded diagnosis

2026-10-16. Reviewer `/root/apollo_investigation_reviewer`. Read-only diagnostics; no builds, tests, network, corrections, dispositions, or gate changes. This is attribution evidence, not acceptance of legacy classifications or unresolved findings.

## GICS: 168 changed rows

| CIK / historical sandbox | Changed subindustry | Lost labels | Changed sectors | Historical function with current canonical input | Historical function with historical canonical input | Current replay |
|---|---:|---:|---:|---:|---:|---:|
| 0001278752 / mfxi | 4 | 2 | 4 | 0/4 | 3/4 | 4/4 |
| 0001825384 / stxf | 164 | 18 | 101 | 160/164 | 164/164 | 164/164 |
| Total | 168 | 20 | 105 | 160/168 | 167/168 | 168/168 |

Selected all 566 rows in affected issuer families, joined raw source rows by CIK/accession/context, and reconstructed pre-cleaning filed names with bounded in-memory staging. No missing joins. Replayed only the historical `_apply_gics_to_holdings` function from `c8cf047^` and current function with equivalent cache inputs. All three caches are byte-identical: SHA256 `465fb2fdd6e9a5aff88394860603bde53df1804f4ef6c5d4a7eb89ef87f67097`, 32,270,986 bytes. Every old/new sector equals the corresponding subindustry's hierarchy sector.

160 differences reproduce the c8cf047 filed-name/cleaned-name precedence change alone. Seven additional historical labels reproduce when restoring historical canonical names: four GraphPAD typo rows, two Golub CLO rows, and one Asurion first-lien row. Entity resolution uses the whole build population; differing canonical inputs are an additional batch-context dependency, not proof that either canonical assignment is correct. In particular, issuer `Golub Capital Partners CLO, LTD 2021-55` now has canonical `Golub Capital Partners CLO 43B Ltd.`; this deserves separate entity-quality investigation. Twenty lost labels are not approved by this diagnosis.

One historical label remains unreproduced: MidCap `ROW-9c70279521a746a1`, Asurion second-lien, accession `0000950170-24-122744`, context `C_6ce92d70-99a6-4da7-9703-d6ec1984a014`. Historical published label is null; historical-function replay yields Diversified Financial Services even with historical canonical `Asurion, LLC (fka Asurion Corporation)`. Current canonical is `Asurion LLC`, and current published label is reproduced. Historical/current raw BDC rows compare identically after JSON normalization. Thus neither raw extraction drift nor the restored canonical input explains the residual. The exact historical intermediate frame at GICS entry (including the pre-strip filed name and ordering of correction/cleaning stages) was not preserved/recovered here. Next action is a separately bounded reconstruction of that historical entry frame and stage order; do not label this row explained or clean before then.

Evidence: `apollo_gics_rg3.py`, `apollo_gics_rg3.log`, `apollo_gics_rg3_rows.json`, `apollo_rg3_canonical_replay.py`, and `apollo_rg3_final_probe.py/.log` in this directory. The Apollo four-line allowance for `extracted_industry` is not exercised by these isolated GICS replays. Confidence is high for the 160 direct precedence reproductions and seven historical-canonical reproductions; causal attribution remains incomplete for one row.

## KKR: four newly visible unresolved convention findings

All four concern Auxilior Capital Partners Inc preferred equity, field `interest_rate`, pathway `xbrl_field`. Published rate is blank and kind is unresolved in both kfxh and ao_rg3. Holdings and source facts for these rows did not change.

| Quarter | Row ID | Accession | Context | Raw rate |
|---|---|---|---|---:|
| 2024-06-30 | ROW-0d31861c4b735cb5 | 0001930679-24-000012 | c-179 | 0.05 |
| 2024-09-30 | ROW-b117fabfe718ea37 | 0001628280-24-047584 | c-229 | 0.05 |
| 2024-12-31 | ROW-b6605821a6e48828 | 0001628280-25-012549 | c-256 | 0.05 |
| 2025-03-31 | ROW-7126fbce531de316 | 0001628280-25-025410 | c-283 | 0.145 |

The historical kfxh provenance ledger has zero data rows. Its Oct 15 04:43 provenance log used `ciks=70`, the default public cohort. Commit `2bdab56` at Oct 15 07:52 changed `scripts/fund_ledger_trial.py` to pass requested `--ciks` to provenance instead of default `--cohort`. The current ao_rg3 provenance run uses the requested ten funds. This previously omitted population is now checked: it is not a new numeric regression or a harmless string-format alert.

The declared events include `interest_rate:coupon_unresolved`; the published rate is null. `pipeline/provenance_reverify.py` deterministically assigns `unresolved_coupon`, mapped to `financial_convention_unresolved`. Current full status is `not_checked`, so do not imply full source re-verification passed.

Independently inspected cached source rows in `data/raw/filings/bdc_html/1930679/` for the four accessions. June/September/December print 5.0% cash and 9.5% PIK (9.5% max PIK); March prints 14.5% with 9.5% PIK. This is material coupon-convention evidence requiring investigation/disposition. It does not justify filling all four rates with the raw percentages or suppressing the findings. Confidence is high that detection scope explains their newly outstanding status; correctness of the final resolved coupon treatment remains open.

Evidence: `apollo_rg3_provenance.py/.log`, historical/current provenance ledgers/logs, commit 2bdab56, and cached HTML. The four findings must remain outstanding pending fund-level resolution.

## Eleven source-fact string differences

Independently compared parsed source-fact JSON. All eleven differences are confined to `_financial_fair_value.raw` integer versus decimal string representations, with equal numeric values and other JSON keys unchanged:

- 0001825384/stxf: Helpsystems 8182000; MRI 1888000 and 494000.
- 0001572694/gsxf: AI Titan Parent (Prometheus) 294000 and 7024000.
- 0001916099/dixc: CWC Fund II (Cresset) 9949000; Quantum Leap 5000; L2 Brands 13835000.
- 0001930679/kfxh: Florida Food Products 0; Opendoor 0; Curia Receivables 104000.

Each changed from the integer string to that same string with `.0`. These are distinct from the four Auxilior rows and do not explain away their findings. Full row identifiers and differences are in `apollo_rg3_provenance.log`. Parent's all-ten-fund monetary equality comparison was not repeated as a full regression here.

## Batch 2 signed-zero follow-up

CIK 0001993402, Alert Media Inc, `ROW-7d79eed5e832f3e1`: rg2 cost +0.0 versus ao_rg2b -0.0; numeric difference is zero. The sole parsed source-fact difference is `_financial_cost.raw` `"0.0"` to `"-0.0"`; state remains `present`. This comparison proves numeric equality, without changing provenance or accepting unrelated findings. Evidence: `apollo_rg3_final_probe.log`.

## Handoff

Do not claim a clean regression: one historical classification remains unexplained and four genuine unresolved-convention findings are newly visible. No diagnostic repairs or acceptance were performed. All diagnostic commands exited; writes stopped after this note.
