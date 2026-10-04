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
