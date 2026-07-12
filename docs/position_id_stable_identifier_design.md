# Stable, content-anchored `position_id` — design note

**Status:** proposal for review. No code or production data changed. All evidence below is from read-only probes over `data/output/private_markets_holdings.csv` and `data/snapshots/`.
**Author basis:** investigation 2026-06-16.
**Decision pending:** approve the registry approach + key tiering before implementation. This is a high-blast-radius change.

---

## 1. Problem

`position_id` must become a durable key: as the pipeline moves to incremental quarter-by-quarter operation (scope **Q4-2022 onward**), each new quarter must leave prior closed quarters' identifiers unchanged, because the index, frontend, and a forthcoming source-labelled gold set will key on `position_id` to re-find a position-quarter across rebuilds.

Today it is **not** durable. In `assign_position_ids` (`pipeline/position_matching.py:1920-2377`):

- `unified_df` is stable-mergesorted by `UNIFIED_SORT_COLUMNS`, then `_uid = range(len(unified_df))` — the uid **is** the row's ordinal in the sorted frame (`:1958`).
- Connected components (union-find over match-pair edges) are labelled `POS-{rank:08d}` where rank = order of the component's smallest uid (`:2248-2253`); singletons are numbered after all components.

So the label is a **global positional ordinal**. The underlying chain graph is content-derived and stable; only the *string naming it* is rank-derived and unstable. The `:1702` comment confirms it: "only the synthetic position_id label re-sequences."

### Merge complication
Supplementary B2 (`:2218-2233`, guarded by `_guarded_union`) adds cross-component edges that bridge two previously-separate chains into one. Today the merged chain takes one new rank; the other id simply ceases to exist, **with no retirement record** — the absorbed chain's old `POS-…` is unrecoverable.

---

## 2. Downstream blast surface

| Consumer | Use of `position_id` | Sensitive to label value across rebuilds? |
|---|---|---|
| `private_markets_holdings.csv` | the column itself | it is the key — yes |
| `index_returns.py` | carried onto `position_returns.csv` (`:299`); **never a group/join key** | **No** — index series aggregate by classification/quarter; index values are independent of the labelling |
| `pik_status.py` | groups `["source","cik","position_id"]` for PIK transitions (`:316-389`) | within a single rebuild only (internally consistent); breaks only across rebuilds |
| `match_reconciliation.py`, oracle `J04`, `_validate_unique_position_ids` | within-rebuild join / uniqueness assertion | invariant, not value |
| `db.py` | `TEXT` column + 3 indexes | only if long-lived DB rows reference it |
| **Frontend** (`frontend/src`, `frontend/public/data`) | **zero references** | **No — not consumed today** |
| **Forthcoming gold set** | store id in rebuild N, re-find in N+1 | **Yes — the entire reason for this work** |

**Takeaway:** the only true cross-rebuild consumer is the gold set (+ any persisted DB rows). Index and frontend are insulated. This lowers urgency but not the requirement.

---

## 3. Empirical evidence

Current artifact: 795,064 rows; **321,241** distinct `position_id` (141,531 chained up to 26 quarters; 179,710 singletons); 2 sources; 343 CIKs; report-dates 2019-09 .. 2026-03.

### 3.1 Blast radius of the current scheme
- **Value-only rebuild** (current vs Jun-12 snapshot), 664,682 matched closed-quarter positions: **0** `position_id` changes, 0 FV/issuer drift. The scheme is *stable by luck* when row order is preserved.
- **New-quarter ingestion** (current, max 2026-03-31, vs May-27 snapshot, max 2026-01-31), 577,756 matched pre-2025Q4 positions (closed in both): **`position_id` changed on 99.99%** (577,694). Confirms the worst case: ingesting new quarters globally re-sequences essentially every label on already-closed quarters.

### 3.2 Natural-key collisions (within-quarter uniqueness of a candidate key)
Q4-2022 scope, key = `rawid | issuer_name | fair_value` within (cik, source, report_date): **44 collided groups / 88 rows** (0.012%). All 44 already get distinct `position_id` today; they collide only because the key omits `principal_amount` (27 groups) / `shares_held` (17 groups). Pattern: unfunded / zero-FV sibling tranches of the same borrower. (Full-history was 105 groups / 3,354 rows — the Q4-2022 scope removes ~97%.)

### 3.3 Cross-rebuild field drift (current vs May-27), 577,756 closed positions
| field | drift | implication |
|---|---|---|
| `fair_value` | **0.000%** | stable here, but exclude (restatement hazard) |
| `rawid` | **1.60%** (9,584) | best anchor, not immune |
| `issuer_name` | **12.1%** (72,383) | **exclude from any key** |
| `position_id` (today) | 99.99% | the defect |

`rawid` drift cause is **code, not data**: pipe-suffix tail edits + the MidCap flattened-identifier parsing fix (commit `2368845`).

### 3.4 Wrapper cohort split
78 wrapper files (77 schema v3). `canonical_strip_re` present in **54/77 (70%)**; position-stability edge case in **32/77 (42%)** — coverage is partial, not uniform.

- `rawid` drift (BDC closed quarters, current vs May-27): **unwrapped 1.72%**, **wrapped 2.71%**. Wrapping does *not* reduce raw drift — the wrapped cohort is under active development, so its identifiers churn *more*; the wrapper relocates the drift into a stabilised `position_key`.
- Within-quarter single-field collision rate (current BDC): `position_key` **40.8% unwrapped / 21.8% wrapped**; `rawid` **33.1% / 18.1%**. `position_key` collides *more* than `rawid` (normalisation merges siblings); wrapping roughly halves both.

### 3.5 Does `position_key` follow a position across quarters? (ground truth = current `position_id` chains, 2025-09-30 → 2025-12-31, the pipe-suffix boundary)
| cohort | chained pairs | `rawid` changed | `position_key` changed | raw drifted but key held |
|---|---|---|---|---|
| wrapped | 15,963 | 56.3% | **15.0%** | 6,593 (73% absorbed) |
| unwrapped | 10,072 | 61.2% | **22.7%** | 3,874 (63% absorbed) |

`position_key` follows a position far better than `rawid` (15% vs 56% drift, wrapped) and `canonical_strip_re` measurably absorbs raw drift — but it still breaks on ~1-in-7 wrapped positions per quarter. **No single field follows a position;** the `position_id` chain (UF over `position_key` + FV-proximity + name tiers) is the actual follower.

### 3.6 Source has no native follower
`bdc_investment_identifier` is the filer-authored typed-dimension member on the XBRL SOI axis (`staging_bdc.py:1757-1773`); XBRL `contextRef` is per-filing. CUSIP/ISIN/LEI persist but are ~absent for private credit. **Cross-quarter identity must be reconstructed.**

### What I ran / didn't run
Ran: six read-only DuckDB probes over the current artifact + snapshots; wrapper-file scan; git history of `canonical_strip_re`. Did **not** run: a double full-rebuild diff (write-prohibited / expensive); `position_key` cross-build drift (snapshots predate the column). All temp scripts removed.

---

## 4. Options assessed

### (a) Deterministic content-anchored hash — rejected
Derive the id from chain-invariant content (earliest `cik+source+issuer+report_date`, hashed). Fails on three independent axes, all evidenced above:
- **Issuer drift 12.1%** (§3.3) — any key containing `issuer_name` changes value with no data change.
- **Merges** — the absorbed chain's id vanishes with no alias; a gold-set row keyed on it is unrecoverable.
- **Chain-head drift** — re-extracting an old filing can change the "earliest member" and thus the hash.

Its only advantage (no stateful artifact) is exactly what the incremental model must give up to be merge-safe.

### (b) Persisted component→id registry — recommended
A governed, baseline-diffable artifact maps a per-row natural key → `position_id`. New quarters look up and extend existing ids; merges resolve to a surviving id with an audited retirement record. Robust to merges; the only design where a retired id stays resolvable.

---

## 5. Recommended architecture — incorporate, don't rebuild

The registry is a **thin naming/persistence layer on top of the existing matching**. Nothing in component formation changes.

| Layer | Status |
|---|---|
| Component formation: UF, Tiers A-E, `B1b_position_key`, supplementary B2, lot suffixes (`utils.UnionFind`, `position_matching.py`) | **Unchanged — fully reused** |
| Per-CIK corrections: wrapper `position_key`, `canonical_strip_re`, tranche/comparative/JV edge-case dispositions | **Unchanged — these *are* the Layer-2 matching corrections** |
| Within-quarter natural key | **New definition** (below) |
| Naming / persistence | **New — registry + retirement/remap log** replacing `POS-{rank}` |

### 5.1 Natural key (corrected by evidence)
Not `position_key` alone (collides 22-41% within quarter, §3.4) and not `rawid` alone (drifts, collides 18-33%). Use a **composite within-quarter anchor**:

```
(cik, source, report_date, rawid, principal_amount, shares_held)
```

measured at **0.012% residual collision** when combined with issuer/FV historically (§3.2), with the residual handled by a documented deterministic ordinal tiebreak. **Exclude `issuer_name` (12.1% drift) and `fair_value` (restatement hazard) from the key.** Wrapper `canonical_strip_re` improves the `rawid` input for the wrapped cohort but does not replace the composite.

### 5.2 Cross-quarter linking
Comes entirely from the **existing chain** (`position_id` component), not from any field. The registry persists the chain↔id binding; the wrappers' `position_key` + UF tiers remain the follower (§3.5).

### 5.3 Registry algorithm (sketch)
1. Form components exactly as today.
2. For each component, compute the composite natural key of its members.
3. Match each component to the registry by **member-key overlap**: ≥1 shared member-key → inherit id (extend). Multiple existing ids matched → **merge**: keep oldest (lowest id / earliest `first_seen`), write `position_id_retirements` rows (`retired_id → surviving_id`, quarter, mechanism, build id) for the rest. No match → mint next id from a persisted monotonic counter (never reuse).
4. Seed the registry from current labels (no flag-day renumber). Re-scope to Q4-2022-onward at seed time.

### 5.4 `rawid` drift as a governed migration (mandatory)
`rawid` drifts 1.6% overall and **2.7% for the wrapped cohort** (§3.4) — driven by extraction-code fixes. When a build changes `rawid` for already-closed quarters, emit an audited `rawid_remap` record (old → new, cik, quarter, mechanism, build id) and carry the existing id forward via the §5.3 fallback (FV+principal overlap). This converts the 9,584-row event from silent re-mint into a reviewable artifact. **This is most needed for the wrapped cohort**, where raw churn is highest.

---

## 6. Uniqueness invariants
`_validate_unique_position_ids` (`:150-196`) and oracle `J04`: at most one `position_id` per (cik, source, report_date). Preserved — the registry only *names* components; membership (and thus per-quarter uniqueness) is unchanged from today's guarded UF. Cross-quarter analytics (`pik_status`) become correct **across** rebuilds, not just within one.

---

## 7. Agentic validation integration
The wrapper system (`docs/wrapper/WRAPPER_SYSTEM.md`) is already the agentic-data-quality backbone: deterministic frozen hot path, LLM only at edges, commit only when `reconciliation ∧ content_signatures ∧ remainder≈0`, "the agent is never its own judge." Position-matching validation slots in directly:
- **Drift trigger:** the `rawid`/key-drift detector becomes the deterministic "detected drift" signal that flags a CIK for agent wrapper repair (it would auto-flag the 2025-12-31 pipe change → agent adds `canonical_strip_re` → oracle accepts).
- **Stability gate:** the wrapper `position_count_qoq` invariant + the registry's chain-continuity diff are oracles a proposed match correction must pass before commit.
- **Audit:** registry retirement/remap logs reuse the wrappers' versioned-diff governance.

---

## 8. Test plan
1. **Churn baseline:** rebuild twice from frozen cache into named `data/snapshots/` (not the official baseline); diff `position_id`. Confirm no-new-data ≈ 0 and incremental ≈ 100% today; ≈ 0 closed-quarter churn under the registry.
2. **Registry replay determinism:** same cache + same registry → byte-identical ids.
3. **Closed-quarter stability:** add a synthetic new quarter; assert 0 closed-quarter id changes.
4. **Merge audit:** force a B2 bridge; assert exactly one survivor + one retirement row; retired id resolves to survivor.
5. **`rawid` remap:** simulate a `canonical_strip_re` / parsing change on a closed quarter; assert ids carry forward via FV+principal fallback and a `rawid_remap` row is written.
6. **Invariant:** `_validate_unique_position_ids` + `J04` pass on registry-assigned frame.
7. **Collision tiebreak:** the residual composite-key collisions resolve deterministically across runs.
8. **Index parity:** `index_returns` output byte-identical (it must be — `position_id` is non-keying there).

---

## 9. Open questions — resolved

### Q1 (RESOLVED) — composite-key residual
The natural key now disambiguates base-key collisions with **`bdc_dimensions_raw`**
(the full XBRL dimension path).  XBRL guarantees distinct positions in one
filing have distinct dimension contexts, so it is a per-filing-unique,
cache-deterministic anchor — no new extraction plumbing required (the column
already flows to `private_markets_holdings.csv`, 0% blank for BDC).  Measured:
residual within-quarter collisions **175 → 12 → 0** rows on the full Q4-2022
dataset (733,240 rows, 733,240 distinct keys).  The final dozen share an
identical XBRL context (interchangeable) and are separated by a deterministic
ordinal over stable structural fields (`issuer_name`/`fair_value` excluded).
Implemented in `position_id_registry.compute_natural_keys`.

### Q2 (MEASURED) — `position_key` cross-build drift
Closed via the offline pure-function harness `scripts/measure_position_key_drift.py`
(no rebuild, no snapshot): `canonical_strip_re` is the only rule that rewrites
the identifier feeding `position_key`, so the count of current rows it moves is
the exact `position_key` churn a wrapper edit would cause.  **Result: 88,384
rows — 15.7% of all BDC, 52.7% of the cohort under such a rule.**  Material.

Interpretation and decision:
- The registry's natural key **excludes `position_key`**, so closed-quarter ids
  are unaffected by this drift.  The exposure is forward continuity: a new
  quarter that fails to chain mints a fresh id instead of inheriting.
- For **wrapped** CIKs `position_key` is held stable by `canonical_strip_re`, so
  the chain carries continuity and the registry inherits (tested:
  `test_rawid_drift_carry_forward_via_chain`).
- For **unwrapped** CIKs with the suffix, the fix is **adding a wrapper** (the
  agentic drift loop the harness feeds), NOT a registry-side rebind.  A generic
  suffix-strip / fuzzy rebind would over-link distinct tranches (`Acme | First
  Lien` vs `Acme | Second Lien` → `Acme`) — the over-merge the uniqueness guards
  exist to prevent.  Deliberately not implemented.

Remaining gate before seeding in production: run the harness after any wrapper
batch and confirm the unwrapped-with-suffix tail is acceptable (or wrappered).

## 10. Implementation status (2026-06-16)

- Registry implemented (`pipeline/position_id_registry.py`), wired into
  `assign_position_ids(use_registry=...)` and the `--stable-position-ids` flag.
- Natural key uses `bdc_dimensions_raw` (Q1) -> 0 residual collisions on 733k rows.
- Merges AND splits are audited in `retirements.csv` (`reason` =
  `chain_merge` / `chain_split`); a chain_split keeps the source id alive (the
  keeper) and records the evicted component's new id.
- **Stateful artifacts live under `data/overrides/position_id_registry/`**
  (`registry.csv`, `retirements.csv`) -- NOT in `data/output/`, so clean
  rebuilds/snapshots never wipe them.
- Seeded from the last fully-labelled build and activated via one
  `--returns --stable-position-ids` run: position_id 100% repopulated; 99.15%
  of Q4-2022+ closed labels preserved across the rebuild (vs ~0% before).
