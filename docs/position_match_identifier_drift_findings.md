# Identifier-drift position-match findings (overhaul-proof evidence)

**Purpose.** Durable, engine-agnostic record of position-matching defects whose
root cause is cross-quarter identifier drift in under-wrapped BDC CIKs. Captured
as *facts + a measured behavioral contract* so they survive the planned wrapper
overhaul/split — the new system must satisfy the contract regardless of how
extraction/normalization is implemented.

**Source.** Spot-check of the J06 fuzzy-match oracle flags (2026-06-16). J06
warns when Tier-D/E (fuzzy / entity-fingerprint) matches have diverging raw IDs
or a classification flip. The flag is working: it surfaced both real mis-matches
and drift-driven false positives.

**Companion gate:** `tests/test_identifier_tranche_identity_gate.py`
(two strict-xfail tests; flip green when fixed).

---

## Confirmed defect 1 — tranche ordinal stripped (matching identity)

The aggressive matching normalizer (`_normalize_name_sql`) strips a trailing
ordinal (`\s+\d+$`), so distinct tranches collapse:

```
"LeadsOnline, LLC, One stop 2" -> "leadsonline, llc, one stop"
"LeadsOnline, LLC, One stop 3" -> "leadsonline, llc, one stop"   (identical)
```

Consequence: in the fuzzy tier, tranche 2 and tranche 3 are indistinguishable,
so the matcher pairs by FV/order and can cross tranches.

**Contract:** distinct tranche ordinals of the same borrower are distinct index
constituents and MUST retain distinct matching identities. (Position-level index
semantics, AGENTS.md.)

**Note / migration care:** ordinal stripping was added to absorb noise-suffix
variants ("Company 2"). The fix is to make stripping *tranche-aware* (preserve
the ordinal when it denotes a loan tranche / "one stop N"), not to remove
stripping globally — a blanket change risks regressing the noise-suffix cases it
was added for. This is a wrapper/normalization-layer decision, not a registry
one.

## Confirmed defect 2 — doubled entity suffix not collapsed

Extraction emitted a doubled suffix in one quarter only:

```
2024-06-30: "LeadsOnline, LLC, LLC, One stop N"   (doubled)
2024-09-30: "LeadsOnline, LLC, One stop N"         (single)
```

The doubling breaks the exact-name tier across the quarter boundary, forcing the
fuzzy tier (which then mis-pairs per defect 1).

**Contract:** a repeated entity suffix (`X, LLC, LLC`) is the same borrower as
`X, LLC` and MUST share a matching identity. Best fixed at extraction (don't
emit the doubling) or in canonical normalization.

## Net production symptom (CIK 1930087, LeadsOnline, 2024-06→09)

| begin | FV | produced match | correct match |
|---|---|---|---|
| One stop 2 | 2,259k | -> One stop 3 (780k) **WRONG** | One stop 2 (2,253k) |

Correct FV-aligned mapping is unambiguous (1->1, 2->2, 3->3, 4->4); the matcher
crossed tranches only because of defects 1+2.

---

## Triage of the J06 sample (so the new system inherits the labels)

Real mis-match (true positive, actionable):
- **CIK 1930087** LeadsOnline `One stop 2 -> 3` (defects 1+2 above).

Suspect (FV jump + suffix collapse — review):
- CIK 1901612 Zarya `Senior secured (6,667) -> One stop 2 (20,000)`.
- CIK 1930087 Brown Group `Senior secured (11,978k) -> bare (3,008k)`.

Defensible relabel (flag appropriate, match likely correct):
- CIKs 1901612 & 1930087 Zullas `LP units (564k/1,726k) -> Warrant (same FV)`:
  the LP-units row vanishes exactly as a Warrant appears at identical FV — same
  co-invest re-characterized.

False positives (same position; flagged only on JW dip from drift):
- `UKG Inc.` vs `UKG Inc` (period), `Aptive Environmental One stop -> Aptive`
  (12,441k->12,567k stable), `SDC Holdco One stop 2 -> SDC Holdco`.

---

## Why this is overhaul-proof

- The **facts** (doubled-LLC, tranche-ordinal collapse, the specific source
  strings) are observations about the filings and survive any rewrite.
- The **contract** is encoded as strict-xfail gates on the matching identity, not
  on a wrapper-schema field — they bind whatever engine the split produces.
- The **registry** layer is unaffected: it consumes `position_key` /
  `bdc_dimensions_raw` from the unified output, independent of wrapper internals.

CIK candidates for the agentic wrapper loop to absorb these: **1930087**
(suffix doubling + tranche handling), **1901612** (`One stop N` suffix collapse).
Re-run `scripts/measure_position_key_drift.py` and J06 after wrappering to
confirm the suspect rate drops.
