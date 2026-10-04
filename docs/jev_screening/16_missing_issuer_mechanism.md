# Missing issuer: upstream extraction, not a Jev bundle repair

Date: 2026-10-04. Read-only investigation of three existing blocked C107 flags.
No production code, wrappers, holdings or issue dispositions changed.

## Source evidence

All three are Crescent Private Credit Income Corp., CIK 1954360. Published issuer
names are null, but cached source rows and their exact inline contexts name the
positions explicitly:

| Frozen row | Period | Source position | Source coordinates | Published / source cost |
|---|---|---|---|---:|
| ROW-22507c1f1f37f884 | 2026-03-31 | LTC Ally Inc, first-lien revolver, 04/2031 | table 15 row 32 | -$1,000 / -$1,000 |
| ROW-abe6a29b7b31623f | 2026-03-31 | Angels of Care, first-lien revolver, 02/2030 | table 14 row 27 | -$3,000 / -$3,000 |
| ROW-e53e1f373c7311c4 | 2025-12-31 | Numera, unitranche first-lien delayed-draw loan, 08/2032 | table 40 row 9 | -$1,000 / -$1,000 |

Source amounts use inline USD facts, scale 3 and negative signs, consistent with
the printed parentheses. Each exact context locates one cost row. Nearby rows
include distinct term loans or revolvers, so borrower-level aggregation would be
wrong. This investigation is not a completed independent notes/scope/recall audit.

## Reproduced mechanism

The active wrapper uses a hierarchy issuer regex expanded with
`_CRESCENT_HIERARCHY_INDUSTRIES` from `pipeline/bdc_identifier.py`.
`pipeline/staging_bdc.py` chooses that CIK-specific extraction branch when its
condition matches, and extracts the issuer after a recognised industry label.

| Observed identifier label | Configured label |
|---|---|
| Health Care Equipment and Services | Health Care Equipment & Services |
| Financial Service | Financial Services |

A bounded DuckDB reproduction of the active wrapper branch confirms its condition
is true and issuer extraction returns an empty string for all three identifiers.
Changing only the industry label to the configured spelling extracts LTC Ally
Inc, Angels of Care and Numera, respectively; each matches the visible row prefix.
The active production files were read and hashed, not imported for execution or
modified. This reproduces the specific extraction branch, not the full historical
pipeline build; downstream provenance still needs checking before any correction.

## Implication for the hybrid workflow

Each of these exact row IDs has three existing issues in the canonical validation
artifact: C107 negative cost (REVIEW), C201 missing issuer (BLOCK_VERIFIED), and
X02 missing credit rate/spread (REVIEW). The source-supported negative costs do
not resolve the identity failure or the separate rate question.

Do not fill an issuer only inside a Jev packet to make it ready. That would hide
the fact that the published position is missing identity. Retain B1 routing and
repair the upstream mechanism through the normal independently validated process.
The reusable source locator can still help B1 find evidence from the exact context
when visible-name search is unavailable.

A later correction should validate a CIK-scoped industry-label vocabulary across
quarters and instrument types, including real companies whose names resemble
industry labels. It must preserve separate revolver/term-loan/DDTL positions and
show before/after source reconciliation. Do not add a global free-text name
extraction rule or treat three matching counterfactuals as rollout validation.

This is an example of the required drift test: an industry-label spelling change
can break identity extraction even when the schedule remains visually familiar.
It is not evidence that Jev needs a bespoke whole-filer bundle builder.

## Aggregate period check

A bounded read-only holdings query stays within this same reserved filer and
does not select additional source-review cases:

| Period | Published BDC positions | Missing issuer names | Missing names in health-care `and` variant | Missing names in singular financial-service variant |
|---|---:|---:|---:|---:|
| 2023-09-30 | 55 | 37 | 7 | 0 |
| 2025-12-31 | 371 | 192 | 49 | 34 |
| 2026-03-31 | 357 | 153 | 49 | 0 |

The health-care variant appears from the earliest quarter in this current-snapshot
projection, Q3 2023. The singular financial-service pattern is detected only in
Q4 2025. This dates the observed identifier patterns, not a source-template change
or the time when the pipeline first failed. The three-case mechanism must not be
described as a newly introduced Q1-2026 defect.

Q1 2026 contains 55 positions with the health-care variant: 49 lack names and six
already have names. Other corrections, bridges or processing paths may explain
the six; that provenance has not been established here. Another 104 missing names
are outside the two narrowly matched label patterns. Do not claim a two-label fix
would repair all 153 positions or overwrite existing valid identities.

The direct data-quality priority is source-backed upstream identity remediation,
with validation across periods and preserved correction precedence. Jev can help
screen supported weak questions, but cannot make these published identities
correct by clearing their negative-cost flags. No production remediation was
performed under the owner's no-production instruction.

## Pilot tooling and artifacts

The existing source-review helper initially crashed on null issuer names. The
isolated fix skips name search for absent/non-string values while retaining exact
context lookup. Five new checks cover null/blank/non-string names and a valid
name; all 14 source-review tests passed at that checkpoint, with readiness then
37/67. Later unrelated note repairs brought the current replay to 39/67; these
three missing-issuer cases remain blocked. The source-review helper now has 18
passing focused tests, including later custom-context evidence preservation.

Under `data/pilot/jev_screening/20261003_shadow/`:

- `missing_identity_source_review_45.json`: three raw-source extracts from two
  cached filings, without automatic truth labels or audit stamps.
- `missing_issuer_mechanism_562617aca4f814f5.json`: active-code/config hashes,
  branch reproduction, controlled label variants, source coordinates and existing
  C107/C201/X02 issues.
- `issuer_coverage_f1bab34c176c8ca7.json`: aggregate label and missing-name counts
  across 11 periods from the same holdings snapshot; no new source-reviewed cases.

Original filing hashes:

- Q1 2026: `fcc112450873f19d032e6872db3e353049519881d4b4eed154d7b3121665c40f`.
- Q4 2025: `e664da7f3ab77c13ade79bb999f287293c03a11684275206b37485654842d6d6`.

No new funds, selected natural cases, API calls, published corrections or
independent clearances were added. Existing frozen reference labels remain intact.
