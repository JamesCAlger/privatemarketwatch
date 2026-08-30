# Row Provenance + Layer Exclusion: closing the "diagnosable but inexpressible" gap

Status: DRAFT for owner review (2026-08-30). No implementation until approved.
Author: operator session 2026-08-29/30 (q1w1 campaign).

## 1. Problem

B2 keeps producing correct diagnoses it cannot express as corrections. Every
recent escalation in the class has the same shape: a coherent SET of rows is
additively double-counted (or out-of-total), the set is identified precisely,
and no template selector can name it.

Measured instances (all grounded against filings; amounts are the escalations'
own reconciliations):

| CIK | Quarter | The set | Evidence quality | Blocked because |
|---|---|---|---|---|
| 0001838126 | 2026-03-31 | 23 bare-axis rows, $1.611B | matches fv gap $1.58B (6.3% overshoot vs companyfacts) | axis PROFILE is not a queryable field |
| 0001812554 | 2026-03-31 | 14 bare-axis JV-vehicle rows $1.365B + $0.394B exact dupes | matches fv gap $1.72B (4.85%) | same; JV layer carries no subsidiary dimension |
| 0001715933 | 2026-03-31 | controlled/non-controlled TRANSACTION-schedule rows ($246.7M + $109.2M) | equals filing layer totals exactly | source TABLE is not recorded on the row |
| 0001851322 | 2026-03-31 | table-79 consolidated-sub slice | fv diff exactly $294,975,000 | same (distinct-valued slice, not row dupes) |
| 0001899017 | 2026-03-31 | subsidiary schedule $406.5M | exact | resolved 2026-08-29 ONLY because is_subsidiary happened to be tagged |
| 0002011498 | 2026-03-31 | 71 subsidiary-dimension rows $231.5M | exact to the dollar | same |

The last two rows are the control group: where a structural tag existed
(`is_subsidiary`), the 2026-08-29 retain-and-flag change cleared them with
ZERO per-CIK corrections (64 CIK-quarters cohort-wide). Where the tag does not
exist, every lane fails in sequence: dedup (no equality key), spv_lookthrough
(no legalentityaxis), subtotal_filter (no aggregate label), and there is --
deliberately -- no arbitrary row-delete template.

Root cause: staging DISCARDS structural provenance. Each raw fact once knew
which filing table it came from and which axis-set presented it; extraction
flattens this to the unparsed `bdc_dimensions_raw` string. `is_subsidiary`
is one hand-carved exception, and it is the only member of this family that
has ever worked.

## 2. Design principle

Do not widen what agents may delete. Widen what rows KNOW about themselves,
then permit exclusion only by structural key + anchor-equality proof.

Two parts, matching the Layer-1/Layer-2 architecture in
`docs/agentic_data_quality.md`:

## 3. Part A -- row provenance at staging (Layer 1, global, deterministic)

Two derived columns on every BDC holdings row, populated in
`pipeline/staging_bdc.py` next to the existing `is_subsidiary` derivation:

- `axis_profile` (VARCHAR): the normalized, order-stable axis SET of
  `bdc_dimensions_raw` with member values stripped, e.g.
  `investmentidentifieraxis` or
  `investmentidentifieraxis|equitymethodinvestmentequitymethodinvesteenameaxis`.
  Computation is the regex already used operationally:
  `regexp_replace(lower(bdc_dimensions_raw), '=[^|]*', '', 'g')` plus
  axis-token sort. Cheap, vectorizable, derived-only.
- `source_table` (VARCHAR, nullable): identifier of the filing table/schedule
  the fact was parsed from (R-file/table ordinal or the wrapper's table key),
  taken from the raw cache at extraction time. Nullable where the extractor
  cannot attribute a table; NULL is never a selector match.

Propagation: `pipeline/unified_holdings.py` carries both columns through the
build (same path as `is_subsidiary`). They are DERIVED, never corrected;
`CORRECTED_TRACKED_FIELDS` must NOT include them, and
`check_provenance_integrity` should treat them like other provenance columns
(appliers may not write or drop them).

Row-id stability: `row_id = hash(accession + context)` -- adding columns does
not perturb identity. Verified requirement anyway (see section 7 gate).

What Part A alone buys, before any new template:
- The shadow conservation engine and diagnose battery can PROFILE layers
  cohort-wide (which filers have bare-axis buckets, transaction-schedule
  tables, off-total slices) -- turning this quarter's hand forensics into a
  deterministic report.
- Future global rules (retain-and-flag style) become possible per class once
  a class proves stable, without per-CIK leaves at all.

## 4. Part B -- one new correction class: `layer_exclusion` (Layer 2, per-CIK)

Template schema (correction-leaf v1, same envelope as other classes):

```json
{
  "cik": "0001838126",
  "fix_class": "layer_exclusion",
  "template": {
    "scope_quarters": ["2026-03-31"],
    "selector": {
      "axis_profile": "investmentidentifieraxis",
      "source_table": null,
      "is_subsidiary": null
    },
    "anchor_proof": {
      "kind": "companyfacts_fv_gap",
      "cited_value": 1580000000.0,
      "tolerance_pct": 2.0,
      "citation": "companyfacts InvestmentOwnedAtFairValue 2026-03-31 vs value_sum"
    }
  },
  "source_review_ids": ["..."],
  "evidence_citations": ["..."],
  "confidence": 0.0
}
```

Selector rules (hard, enforced by the applier AND the validator):
- Selector fields are a CLOSED whitelist: `axis_profile`, `source_table`,
  `is_subsidiary`. Exact-match only. No issuer names, no identifiers, no
  values, no regex, no row_id lists, no negation.
- At least one selector field non-null; NULL fields do not match NULL data.
- `scope_quarters` required and explicit (no open-ended scope).

Applier (`pipeline/agent_b2_appliers.py`, POST_STAGING flavor): drop rows
matching the selector within scope_quarters; audit `rows_dropped`,
`fv_dropped`, the selector, and the anchor-proof check result. Add
`layer_exclusion` to `_FV_TOUCHING` (row-dropping class -- conservation gate
owns the FV judgement; this is the family fixed on 2026-08-30).

## 5. The anchor-equality gate predicate (what keeps this fail-closed)

New B3 value-gate predicate `excluded_set_anchored`, required for
`layer_exclusion` (and available to dedup-with-row_selector):

- The excluded set's FV (and cost, when the leaf cites a cost quantity) must
  equal the leaf's `cited_value` within `tolerance_pct` (cap the leaf's
  tolerance at 2%; tighter is better -- five of six known cases reconcile to
  the dollar).
- `cited_value` must itself be verifiable: either a filing-table quantity the
  evidence CLI can re-read (table/row citation) or the deterministic gap
  vs a named anchor (companyfacts/ff value already in
  `conservation_gate_results.csv`). An uncited number FAILS.
- All existing predicates still run: conservation gate (target cleared,
  held-out quarters not regressed), magnitude, provenance-invariant,
  replay-equivalence.

This is the containment: the mechanism names a structural cause (selector),
the amount is proven against an independent quantity (anchor proof), the
blast radius is scoped (quarters + selector), and the exclusion replays
identically on re-runs. An agent cannot use it to delete arbitrary rows,
because arbitrary rows do not share a whitelisted structural key AND sum to a
cited anchor quantity.

## 6. Explicit non-goals

- Does NOT address extraction gaps (1905824/1950976 missing contexts,
  1702510's absent Structured Credit section, 1899017's collapsed parent ATS
  row). Those need wrapper/extractor work; no exclusion vocabulary may add
  rows, and the missing_position_add fabrication guard stays as-is.
- Does NOT change public FV/export semantics. Whether excluded layers also
  leave `private_markets_holdings.csv` headline sums is the standing open
  decision (AGL/Bain double-count note, 2026-07-22); this spec only affects
  correction vocabulary + gates. Until that decision, layer_exclusion leaves
  change holdings the same way dedup already does (post-staging drop), so the
  headline convention is unchanged in kind.
- No free-form row_selector widening for dedup. Bounded dedup keeps its
  equality-group contract.

## 7. Migration order (each step gated before the next)

1. Staging columns (`axis_profile`, `source_table`) + tests; full unified
   rebuild; REQUIRED CHECK: zero row_id changes vs pre-migration baseline
   (anchor-hashed ids; diff the id sets), zero value deltas
   (`scripts/diff_outputs.py --semantic`).
2. Reproduce this spec's section-1 table deterministically from the new
   columns (a small report script); the six known funds must match the
   hand-measured numbers. This validates the enrichment before any
   correction exists.
3. Applier + validator + gate predicate (TDD; include a false-positive test:
   a selector matching legitimate dimensioned rows must FAIL the anchor
   proof).
4. Author leaves for the known six (B2 workers or operator-authored with
   worker evidence), gate each through B3, promote PASSes one at a time,
   post-battery after the large-FV pair (1812554, 1838126).
5. Only after >=2 quarters of stable behavior: consider promoting stable
   per-CIK exclusions into a global Layer-1 rule per class (the
   is_subsidiary/retain-and-flag path), retiring the leaves.

## 8. Expected impact (measured basis, 2026-03-31)

The six known funds carry a combined ~$4.4B of layer-excludable FV overshoot;
1812554 + 1838126 alone are $63.8B of the $118.3B flagged-FV pool (their
flags clear if their ~$1.7B/$1.6B gaps close). With the mid-tail mechanisms
already measured (aggregate rows: 1572694, 1742313) this plausibly moves
flagged_fv_share from 30.9% toward the ~10% bar and reconcile_rate toward
90 -- but numbers above are the CEILING assuming every diagnosis gates PASS;
gate refusals remain valid outcomes.

## 9. Open questions for the owner

1. Approve the closed selector whitelist as specified (axis_profile,
   source_table, is_subsidiary)? Anything to remove/add?
2. Anchor-proof tolerance cap: 2% proposed; five of six known cases are
   exact. Tighter (0.5%)?
3. Should step-5 globalization be in scope at all, or stay per-CIK forever?
4. source_table derivation cost: if the raw cache lacks a usable table key
   for some filers, Part A ships axis_profile-only first and source_table
   follows -- acceptable to split? (1715933/1851322 then wait for the second
   tranche.)
