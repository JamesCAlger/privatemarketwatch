# Proxy-cost evidence: a separate B1 contract

Updated 2026-10-04. This is an isolated research result, not a production change
or an expansion of Jev clearance eligibility.

The published `cost` field can be an intentional first-observed-fair-value proxy.
Giving Jev the entire current SOI would not explain that value: its evidence can
belong to another quarter, and the original field is fair value rather than cost.

## Six real cases

The pilot's six proxy-cost flags all reproduce the recorded donor policy. The
holdings, donor audit and financial-state audit hashes agree with the existing
identity contract and release. An independently written bounded query finds the
same unique earliest source-valid donor for each snapshot position.

| Flagged position | Published proxy cost | Donor observation | Raw donor FV coordinate |
|---|---:|---|---|
| GC Ferry, 2026-03-31 | -39,000 | 2025-09-30, earlier quarter | t11r22, Fortress filing |
| Accupac, 2023-06-30 | -14,000 | 2023-03-31, earlier quarter | t10r7, Varagon filing |
| AB Centers delayed draw, 2024-09-30 | -22,000 | Same observation | t15r2, unfunded-commitments table |
| AB Centers revolver, 2024-09-30 | -2,000 | Same observation | t15r3, unfunded-commitments table |
| AB Centers delayed draw, 2026-03-31 | -4,000 | Same observation | t19r3, unfunded-commitments table |
| SI Swan / Sapiens, 2026-03-31 | -103,000 | Same observation | t10r40, Goldman Sachs filing |

Manual inspection of the preserved donor rows finds matching negative FV facts,
USD units, scale 3 and matching context periods in all six. This confirms the
narrow donor-amount comparison. It does not certify the full position chain,
candidate recall, all source notes or the appropriateness of the proxy policy.
The three AB Centers rows explicitly come from unfunded-commitment disclosures;
they must not be silently substituted with similarly named funded SOI rows.

Artifacts are under `data/pilot/jev_screening/20261003_shadow/`:

- `proxy_lineage_19.json`: exact release/input hashes, target and donor rows,
  audit records and ten explicit internal consistency checks per flag.
- `proxy_donor_sources_19.json`: source hashes, raw donor contexts, table headers,
  neighbouring rows and tagged FV evidence.

All six remain B1 work and unscorable under the current reported-cost Jev contract.
No Jev call or new natural flag was added by this investigation.

## What a proxy bundle would need

1. **Output and field basis.** Published cost, absent reported cost, explicit
   proxy method, current flag and the exact holdings release. Do not relabel FV
   as reported cost.
2. **Donor provenance.** Donor row, report date, accession, source context,
   disclosed FV, currency, and the immutable donor audit and release hashes.
3. **Both source views.** Current position evidence plus the donor filing's
   evidence. A single current-quarter table cannot establish historical lineage.
4. **Position continuity.** Evidence that donor and target represent the same
   tranche/facility, including maturity, class, ownership and commitment scope.
   Matching a snapshot position ID only reproduces the pipeline's assertion.
5. **Earliest-donor validity.** Demonstrate the eligible observation set and
   uniqueness of its earliest donor; surface gaps, conflicts or future donors.
6. **A separate decision question.** Distinguish a bad source extraction, a bad
   donor/position link, and a correctly applied but unsuitable estimation policy.
   These require different remedies and cannot share a reported-cost comparison.

## Trade-off

The existing audit files make lineage retrieval relatively small and reusable.
They can save B1 time locating the donor and explain why a current-SOI comparison
fails. The expensive unresolved part is independent position-chain and policy
validation. Adding more raw current-table context does not solve it.

Keep proxy costs outside the initial Jev reported-cost mode. Preserve this richer
evidence for B1, measure its investigation benefit separately, and require a new
label set and validation contract before proposing automated proxy adjudication.

## Main-SOI versus supplemental presentation: unresolved overlap

Four already-selected rows coexist in the frozen Q3-2024 output for CIK 1959568.
All carry `parent_schedule` and the same parent accounting-scope ID, but their
source contexts and field provenance differ:

| Frozen row suffix | Source | Disclosed position | Published cost | Published FV |
|---|---|---|---:|---:|
| 54bec5b9be81ee4d | Main SOI t12r6 | AB Centers delayed-draw loan | -10,000 reported | -21,000 |
| 96818d4e9b1777d0 | Main SOI t12r7 | AB Centers revolver | -2,000 reported | -2,000 |
| 1e319095e85a0c34 | Commitments t15r2 | AB Centers delayed-draw loan | -22,000 FV proxy | -22,000 |
| 24cf5e7b72e10c93 | Commitments t15r3 | AB Centers revolver | -2,000 FV proxy | -2,000 |

Row identifiers above have the `ROW-` prefix and are valid only in the frozen
holdings snapshot. Source file: `1959568/000095017024126452.html`, SHA-256
`5fc8a8adf1d45724378996b3554af55de250ad17e84f3bc96088f932f552535f`.
The primary rows have explicit instrument descriptions and 2031-07-02 maturity.
The proxy rows retain instrument text inside the issuer/identifier but have null
instrument-description and maturity fields. Their absence does not establish a
different facility.

This is **possible presentation overlap, not a proven duplicate finding**. Note 9
says positions may be wholly or partly unfunded, with commitment expiration
preceding loan maturity. The supplemental delayed-draw commitment expires in
2026, while the main position matures in 2031; those dates therefore cannot alone
prove that the facilities differ. Conversely, similar names and matching revolver
FV do not prove equivalence. The delayed-draw FV differs between the two source
presentations (-21,000 versus -22,000), requiring further reconciliation.

The four published FVs sum to -47,000; the two main-SOI rows sum to -23,000 and the
two supplemental rows to -24,000. These are descriptive sums, **not a correction
proposal or an independently established target**. Do not deduplicate by issuer,
value or maturity, and do not remove all supplemental/JV rows globally.

B1 needs to establish the contractual position link, funded versus unfunded
exposure treatment, the source schedule's totals, and why both observations enter
the unified holdings. Then an independent position-level reconciliation can test
any proposed extraction/correction mechanism. The frozen C107 reference labels
are unchanged: source-value agreement on one row does not settle whether both
rows belong in published holdings. This is a concrete limit on what cheap
per-flag screening can certify.

### Existing checks do not settle this overlap

The frozen main rows each have C107 REVIEW. The supplemental proxy rows each
have C107 and X02 REVIEW. Existing `source_reconciliation_detail.csv` matches
all four by exact dimensions: the main rows are reconciled; supplemental rows
have a nonblocking cost diagnostic because the source lacks cost and output uses
an FV proxy. These records do not certify unique economic exposure across the
two source presentations. The query rechecked their output cost/FV against the
four frozen bundles and recorded hashes of both input artifacts.

The two supplemental diagnostics also contain a misleading explanation:
`principal_amount differs on equity position; tracked as diagnostic`. Their
recorded category is LOAN, mismatched field is cost, and both principal amounts
are absent. Read-only inspection of the current SQL builder shows an unparenthesized
OR expression followed by equity/principal AND conditions. A bounded four-case
SQL probe reproduces how a cost mismatch selects that explanation despite the
failed equity/principal conditions. Parenthesizing the OR group selects the
generic secondary-field explanation in that counterfactual.

This identifies an explanation-branch mechanism, not a full historical rebuild
or a demonstrated change to blocking status. Production code remains untouched.
The reason text is carried into column-validation evidence and reconciliation
summaries, so it should not be treated as source truth in a B1/Jev reference label.
Any later fix needs a targeted regression covering loan cost-only, loan principal,
equity principal and share-count mismatches, plus confirmation of unchanged
status/amount outputs except intended explanatory text.

Artifact: `overlap_routing_f9d3f6a9fd99796e.json`. The source-reconciliation input
is the existing artifact dated 2026-09-30; its four amounts match the frozen pilot
snapshot. No new flags, corrected amounts, promoted fixes or API calls resulted.

## 2026-10-04 checkpoint: explicit disclosure roles

- Added an optional offline header-role helper. It requires complete headers in one band, preserves original coordinates and abstains on conflicting/unsupported layouts. It does not infer economic identity, ownership or row inclusion.
- Applied it to the four frozen AB Centers rows: t12r6/r7 identify position-value disclosures; t15r2/r3 identify unfunded-commitment disclosures. Exact output context IDs are present at all four source coordinates. Artifact: disclosure_roles_08568f715a21154d.json.
- Thirteen focused role tests pass, including ambiguous headers, split bands and narrative unfunded references. This is one-filing validation, not evidence of transfer across filers.
- Builder remains unchanged at 39 evidence-ready / 28 blocked. No API calls, independent clearance, production changes or deduplication decision.

## 2026-10-04: exploratory TCW survivor defect outside the frozen experiment

While checking historical C104 references, one additional current position was investigated separately: TCW Direct Lending VIII, CIK 0001825265, Q3-2025, ROW-ecc8c78a0d433f52. This is not a new Jev call or an addition to the frozen 67-case experiment. It adds one exploratory source investigation in an already included fund, using a filing outside the prior 26-file frozen set.

The published issuer includes the affiliation prefix and instrument text; instrument_description is `%`, cost is 12,115,467 with first_observed_fv_proxy provenance, and rate/principal are missing. Its existing X02 flag requests review for missing rate data. The source context C_e7164d57-af08-45d5-bb0f-37f8d69a00cc is table 10 row 3, an affiliate rollforward. It contains current FV 12,115,467 and a 10.00% rate, but no cost fact.

The same filing's main schedule, table 5 row 7, has context C_f1dd68ce-9df4-4ad8-9279-784ba8aaf308 and explicitly reports the Superior term loan's cost 20,376,019, FV 12,115,467, principal 21,367,666, maturity 2028-12-15 and displayed rate 11.66% including PIK. Those cost/FV/principal facts are present in raw bdc_holdings.csv. The main context is absent from current unified holdings; the only current equal-FV/context candidate is the rollforward row. Different stated rates across the two disclosures are preserved as evidence, not reconciled by assumption.

The existing promoted rule superior-affiliation-axis-dedup-2025q3 groups by report_date/fair_value and keeps first. Its rationale says this preserves the detailed row. The current applier instead sorts by a source anchor before choosing first; row_id is not assigned until after the correction stage, so accession/context provide the tie-break. The rollforward context sorts before the detailed term-loan context. An in-memory six-row reproduction using the unmodified applier retains the rollforward term loan in both original and reversed input order, while preserving the detailed delayed-draw and common-stock rows. Main/worktree module text is identical after newline normalization; raw hashes are recorded separately.

Current application audit reports status ok, three rows removed and FV 15,046,605, exactly matching authored counts/amounts with no drift. Those metrics cannot distinguish the wrong surviving term-loan representation: its FV is identical. The main-schedule cost exceeds the published proxy by 8,260,552. This is a source-backed field-retention discrepancy, not a completed correction or full pipeline replay; no production changes were made.

Implications for screening: a missing-rate question can expose a wrong source representation rather than a legitimate missing disclosure. A role-aware bundle must locate the primary schedule and relevant rollforward, preserve conflicting terms, and route the suspected extraction/correction issue to B1. A matched FV, valid donor proxy, deterministic output or high-confidence weak-flag answer would not establish audited holdings. Before any future repair, verify position identity, correction precedence, all three surviving instruments and field-level source reconciliation; do not simply flip keep to last or drop all affiliate disclosures.

Artifacts: exploratory_context_089f24a29d1a0ec6.json and survivor_rule_probe_b725defdd3b05c9b.json. Original source: data/raw/filings/bdc_html/1825265/000119312525276913.html, SHA-256 e2346b7f6529af80f91b369ca6c6f34a1c43d2245a0e9a051551d976f69b8fd7. Earlier source-only extracts are retained. The probe records source/output/rule/module/audit hashes and makes no API calls. This finding was discovered by source investigation, not by Jev, and does not establish Jev's incremental benefit.
