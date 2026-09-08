# Chain completeness: plan for the five next steps after mg5_recall

Date: 2026-09-08
Objective (unchanged): a position chains to the same position in the next quarter,
every quarter it exists, and never to a different one. Precision AND completeness.

Status going in: the contested-assignment promotion (56ef506) took cohort singletons from
27.2% to 15.2% and cut the likely-missed pool from $206B to $31B. mg5_recall then measured
that 61% of decidable interior singletons were still matcher misses, and the replay showed
the residue fails on issuer-name drift (38 of 66 pairs) and gap quarters (12), not on
assignment order.

## What the E13-E15 diagnostics found (2026-09-08, current production build)

Run: `e13_name_drift.py`, `e14_fingerprint_precision.py`, `e15_guards.py`,
`replay_verdicts.py --pairs-csv`.

**Finding 1 -- 44% of remaining singletons cannot chain by design.**

| cohort BDC rows | 266,198 |
|---|---|
| fair value exactly 0 (excluded from the match universe) | 17,655 (6.6%) |
| singleton rows | 40,539 (15.2%) |
| singletons that are unchainable by construction | 17,717 (43.7% of singletons) |
| singleton rate actually attributable to the matcher | 8.6% |

`match_positions` builds its universe with `fair_value IS NOT NULL AND fair_value != 0`.
A row carrying zero fair value therefore can never be chained. 5,943 of those rows have a
same-name, non-zero-FV row in the very next quarter, across 53 CIKs -- undrawn revolvers and
delayed-draw commitments that get funded. `index_returns.py` already filters
`begin_fair_value != 0` independently (line 239), so the universe exclusion is redundant
with the returns filter: removing it changes chaining without changing index returns.

**Finding 2 -- the terms fingerprint is accurate but only where it agrees with the name.**

E13 finds 11,323 adjacent-quarter break/new row pairs, unique on both sides, that agree on
maturity + classification + principal band + spread ($77.1B). E14 replays that rule against
a control of 160,384 pairs the matcher chained by exact name:

| fingerprint outcome on the control | n | share |
|---|---|---|
| fires with exactly one candidate | 84,611 | 52.8% |
| of those, picks the exact-name answer | 83,652 | 0.989 |
| of those, picks a different row | 959 | 0.011 |

Every one of the 772 different-name picks is a false positive. The control's truth is a
same-name pair by construction, so it cannot certify the fingerprint on drifted names --
and an availability gate ("fire only where no same-name row exists next quarter") removes
100% of the control's false positives but also the entire control. **The drift population
cannot be certified offline. It needs adjudication.**

**Finding 3 -- the candidate pool splits cleanly into safe and unsafe halves.**
Corroboration is on fields the fingerprint does not key on. Interest rate agreement is low
everywhere because SOFR resets quarterly; it is not a discriminator.

| class | pairs | FV | lien | instr type | industry | blocking guard |
|---|---|---|---|---|---|---|
| same name, zero/negative begin FV | 3,053 | $1.7B | 0.998 | 0.996 | 0.996 | `fv_nonpositive`, sole cause |
| null issuer name | 1,472 | $6.6B | 1.000 | 0.984 | 1.000 | name multiplicity (all nulls collide) |
| same name, other | 658 | $1.4B | 0.994 | 0.798 | 0.988 | `fv_nonpositive`, `inst_subtype` |
| wrapper containment | 2,326 | $21.5B | 0.995 | 0.936 | 0.917 | `name_differs`; 1,012 already admitted by D/E |
| unrelated names | 3,814 | $46.0B | 0.946 | 0.955 | 0.928 | `name_differs`; 1,613 already admitted by D/E |

The first three are mechanically explained and corroborate at 0.98-1.00 on unused fields.
The last two carry the FV and are exactly the drift population Finding 2 cannot certify.

**Finding 4 -- gap quarters are real but small.** 496 span-2 pairs, $4.7B, 44 CIKs, on the
strict definition (same name, same maturity, principal band, nothing with that name in the
intervening filing). None of the mg5 gap pairs are caught, because those drifted in name too.

**Finding 5 -- the 17 lost CONFIRMED pairs have two causes, not one.** 7 had a maturity
change the veto rejected (5 also moved principal >2%, 3 moved spread, so the amendment
escape could not fire). The other 10 lost the 1:1 contest, and their signature is a
principal ratio that a revolver legitimately produces: 3.94, 2.52, 0.24, 0.13, 0.04, 0.001.
Names like "First lien senior secured revolving loan 1" lose their ordinal in the name key
and are then assigned by principal band, which is the wrong cost for a revolver.

## The plan

Ordered by evidence strength, not by size. Each step states its own gate.

### Step 1 -- one joint metric, sampled once, reusable for every build

Precision and completeness are currently measured by different instruments on different
builds, so no single number says whether a change helped. Fix the instrument first.

Design: sample position-quarters (not edges). For each sampled row ask the adjudicator the
build-independent question "which row in a later quarter is this position's continuation, or
none". Truth is then a property of the filings, not of the matcher, so **any** build can be
scored against the same adjudicated sample without re-adjudication.

- Two strata: uniform over rows, and FV-weighted. Exclude each CIK's last quarter.
- Scores per build: linked-correct, linked-wrong, missing-link, correctly-ended.
- New: `scripts/match_gold/build_continuation_packets.py`, `scripts/match_gold/score_continuation.py`.
- Gate: this becomes the acceptance metric for steps 2-4. Ship it before the Q2 fleet.

### Step 2 -- the guards that block mechanically-explained links

2a. **Zero-FV rows join the match universe.** Remove `fair_value != 0` from the universe in
`match_positions`; keep cash/derivative exclusion. Returns are unaffected (Finding 1).
Gate: `index_returns.csv` and `position_returns.csv` byte-identical apart from position_id
labels; singleton rate falls by roughly the 17.7K forced singletons.

2b. **Sign-safe FV ratio guard.** `b.fv / e.fv BETWEEN 1/50 AND 50` rejects every sign flip.
Replace with a magnitude comparison, and skip the guard when both principal amounts are
present, positive and within 2% -- the principal then carries the scale check the guard
exists for. Gate: the 3,053 same-name zero/negative pairs link; no new WRONG in the A/B.

2c. **Null issuer names are a wrapper defect, not a matcher one.** 1,472 pairs, $6.6B, and
every null name collides into one multiplicity bucket so no name tier can ever fire. Fix in
`data/overrides/bdc_xbrl_wrappers/` per CIK. Gate: null-name row count falls; no FV change.

2d. **Drift classes go to the fleet, not into the matcher.** wrapper containment ($21.5B)
and unrelated names ($46B) are adjudicated as their own gold batch before any tier ships.
Nothing in this plan enables a name-free tier on unadjudicated evidence.

### Step 3 -- gap-quarter tier

A span-2 link, admitted only when the intervening filing contains no candidate for that
position at all, plus the same maturity veto and 1:1 contest as the adjacent tiers. Test set:
the 496 pairs from E13(b) and the 12 mg5 gap pairs. Off by default until step 1 scores it.

### Step 4 -- the two regressions the promotion introduced

4a. Widen the amendment escape so a repriced-and-extended loan survives: allow the maturity
veto to be escaped on principal-within-2% OR spread-equal, rather than requiring both.
4b. Give revolvers their own assignment cost: when either side is a revolver by subtype,
rank on spread and maturity before principal. Gate: the 17 lost CONFIRMED pairs recover
without the WRONG count rising in the mg3+mg4 A/B.

### Step 5 -- position id persistence

Deferred deliberately. `use_registry` is still False in production and ids renumber on every
rebuild. That is an identity-persistence question, not a chain-correctness one, and turning
it on before the joint metric is stable would confound the two. Revisit after step 1 has
scored two consecutive builds.

## Verification

- Targeted `pytest tests/test_position_matching.py` per change; full suite before handoff.
- `ab_gold_percik.py` on mg3 + mg4_contested for every matcher change (WRONG must not rise).
- `prod_chain_metrics.py`, `e13`, `e15` before/after on the cohort.
- `scripts/diff_outputs.py --semantic` against the active baseline, with deltas explained.
- Frontend export stays blocked while another session holds uncommitted frontend edits.
