<!-- Canonical investigations file (cutover 2026-08-20). Append new entries with a
     dated '## ' heading, the question asked, and the results found; then rebuild
     the index: python scripts/split_investigations.py --reindex -->
# Position matching & chain stability

## 2026-09-07 - Chain-stability experiments E1-E7 on the completed mg3 gold set

**Objective:** a chain follows one tranche across quarters (precise) and every
tranche that persists gets chained (complete). These experiments were run to decide
the shape of the chaining architecture and the veto/cost rules inside it.

**Basis:** mg3 gold set, 535/535 verdicts (769 CONFIRMED/WRONG edges, 27 UNCERTAIN
excluded); `private_markets_holdings.csv` restricted to the 70-CIK v2 wrapper cohort,
BDC source (266,198 rows, 69 CIKs with rows, through 2026-03-31). Scripts:
`scripts/match_gold/chain_experiments/{build_gold_edges.py,experiments.py}` (output
under `out/`, gitignored; run order build then experiments, ~5s total). The gold set is
still one adjudicator's verdicts, not the human-audited slice -- every rate below is a
proxy with that caveat.

### E1. Sub-coding WRONG edges: tranche hop vs wrong borrower

Deterministic sub-code: WRONG_TRANCHE when the two rows share `name_key` (ordinal /
comma / fka-stripped issuer name) or `entity_id`, else WRONG_BORROWER. Rationale keyword
cross-check agrees on 31/62 tranche and 5/13 borrower (the rest are silent, none
contradict).

| | n | share of WRONG |
|---|---|---|
| WRONG_TRANCHE (same borrower, other tranche/lot) | 62 | 83% |
| WRONG_BORROWER | 13 | 17% |

`tier_random` rates (denominator CONFIRMED+WRONG):

| tier | n | tranche-hop rate | wrong-borrower rate |
|---|---|---|---|
| C_normalized_name | 42 | 0.143 | 0.000 |
| A_within_filing | 73 | 0.096 | 0.000 |
| E_entity_fingerprint | 42 | 0.071 | 0.000 |
| B2_exact_name | 104 | 0.058 | 0.000 |
| B1b_position_key | 85 | 0.047 | 0.000 |
| SUPP_B2_unique_exact_name | 200 | 0.045 | 0.000 |
| D_fuzzy | 97 | 0.041 | 0.134 |
| **ALL** | **643** | **0.061** | **0.020** |

**Finding:** wrong-borrower links come from `D_fuzzy` only (13/13). Every other tier's
errors are tranche hops. The objective's failure mode is 3x the size of the entity
problem on random edges. On the 62 tranche hops, a hard field (maturity / spread /
subtype / lien) disagrees on only 34; the other 28 are same-borrower siblings that agree
on every extracted field and were separated by the adjudicator on principal, cost or
table ordinal.

### E2. Maturity: veto or cost

| | CONFIRMED (n=614 both known) | WRONG (n=73) |
|---|---|---|
| maturity differs | 16 (2.6%) | 25 (34.2%) |
| of which <=45 days | 3 | 6 |
| of which >1 year | 7 | 7 |

Production base rate on adjacent-quarter chain steps: 4.6% of 142,705 steps change
maturity. The 16 confirmed changes are amendments/extensions (Nouryon 2025->2028,
Sedgwick 2028->2031, Duraserv, Rodeo Dental) and extraction noise (BDO 2038 vs 2028 typo,
IXS +-16 days, Perficient 1 day). In 10 of the 16, principal is identical to the dollar.
**Decision:** maturity is a veto with an amendment escape (principal within 2% and
spread within 1bp) -- the escape keeps 11 of the 16 confirmed and still rejects 92% of
wrong-borrower and 21% of wrong-tranche edges (rule `mat_amend` below).

### E3. Principal band

|ln(principal ratio)| quantiles:

| verdict | group | n | p50 | p75 | p90 | p95 |
|---|---|---|---|---|---|---|
| CONFIRMED | term/other | 495 | 0.003 | 0.036 | 0.309 | 0.655 |
| WRONG | term/other | 67 | 0.817 | 2.226 | 3.193 | 3.330 |
| CONFIRMED | revolver/DDTL | 97 | 0.021 | 0.394 | 1.364 | 1.674 |
| WRONG | revolver/DDTL | 7 | 1.050 | 1.489 | 2.315 | 2.912 |

Band sweep, term/other: 1.25x retains 88.5% of confirmed / rejects 66% of wrong; 2x
95% / 55%; 4x 97% / 36%. The confirmed tail is real (paydowns IQN 23.5M->0.5M, Hootsuite
1.2M->240K, add-ons OneDigital 224K->1.07M, Numerix 2.3M->10.1M -- all adjudicated as the
same position). **Decision:** principal is an assignment cost, never a filter; a
sanity veto only at >=4x (term) / >=10x (revolver, DDTL).

### E4. Tranche-key completeness per CIK

Cohort-wide (262,673 rows with a name): maturity coverage 85.9%, spread 80.1%,
principal 77.7%, instrument subtype 44.7%. Within CIK-quarter uniqueness:

| key | unique share |
|---|---|
| name_key | 0.414 |
| + maturity | 0.512 |
| + spread | 0.580 |
| + subtype | 0.721 |
| + principal | 0.961 |

Of the 154,020 name-duplicate rows, maturity resolves 16.8%, spread a further 11.6%,
subtype 24.1%, principal 41.0%; 6.6% remain identical on every field (duplicate lots).
Per-CIK at 2026-03-31 the Goldman filers (0001948368, 0001572694) have 87-88% of rows
non-unique on the hard key because instrument subtype is not extracted and each
borrower carries 5-9 lots; only principal separates them.

**Null issuer names (E4b):** 3,499 cohort rows have no `issuer_name` at all and are
unchainable by any name tier: 0001954360 (1,229 rows, $2.5B FV), 0001633336 (924,
$2.2B), 0001572694 GSBD (886, $5.1B; 139 in 2026-03-31). GSBD's are the `Debt
Investments <mojibake en-dash> 233.2% United States - 220.5% ...` header rows the
wrapper regex does not strip when the dash is mis-encoded. Verified identical in the
2026-09-05 baseline (886/139) -- pre-existing, NOT a regression from the 2026-09-06 GSBD
fix. All three are wrapper work items with direct completeness payoff.

### E5. Veto rules and combinations on the gold edges

Single rules (CONFIRMED retained / WRONG_TRANCHE rejected / WRONG_BORROWER rejected):

| rule | conf retained | tranche rej | borrower rej |
|---|---|---|---|
| mat_strict | 0.977 | 0.210 | 0.923 |
| mat_amend | 0.991 | 0.210 | 0.923 |
| spread exact (1bp) | 0.851 | 0.468 | 0.923 |
| spread 50bp | 0.964 | 0.113 | 0.692 |
| subtype | 0.999 | 0.000 | 0.000 |
| lien | 0.993 | 0.000 | 0.077 |
| principal 4x/10x | 0.846 | 0.403 | 0.000 |

Combinations:

| combo | conf retained | wrong survive | tranche rej | borrower rej | precision after |
|---|---|---|---|---|---|
| A: mat_amend | 0.991 | 50 | 0.21 | 0.92 | 0.932 |
| B: A + spread 50bp | 0.957 | 45 | 0.27 | 1.00 | 0.936 |
| C: B + subtype + lien | 0.948 | 45 | 0.27 | 1.00 | 0.936 |
| D: C + principal 4x/10x | 0.795 | 24 | 0.60 | 1.00 | 0.958 |
| any 2 of 4 hard fields | 0.999 | 63 | 0.05 | 0.69 | -- |

Spread cannot be a hard veto either: 25 of the 29 confirmed edges lost under B are
repricings (Panda 6.85->7.60->9.35, Mallinckrodt 5.25->7.25) or scale defects
(0001837532 `325.0` vs `3.25`; 0001950803 `6.65` vs `0.0`). **Decision:** vetoes are
maturity-with-amendment-escape plus wrong-borrower guards; spread, subtype, lien and
principal are assignment costs.

**E5b lot-ambiguity classes** (begin-side block on cik, quarter, name_key, maturity,
spread+-50bp, subtype):

| class | WRONG_TRANCHE | CONFIRMED |
|---|---|---|
| A: unique on hard key -- veto fixes | 11 | 482 |
| B: hard-key siblings, principal separates >5% -- assignment cost fixes | 38 | 197 |
| C: identical lots (hard key + principal within 5%) -- undecidable from fields | 13 | 14 |

Class B is the target: 38 of 62 hops sit in blocks where principal (with cost as
tie-break) would have picked the twin. The 50bp / 5% tolerances above overstate class
C. **E5c strict recount** (exact spread; principal within 0.5%; then cost and FV
identical):

| strict class | WRONG_TRANCHE |
|---|---|
| A: unique on name + maturity + subtype + exact spread | 18 |
| B: siblings separable by principal (>0.5%) | 35 |
| C1: principal within 0.5% but cost / FV differ | 5 |
| C2: identical on name, maturity, subtype, spread, principal, cost, FV | 4 |

Kaseya (0001772704) is separable by exact spread and cost/FV, not an identical-lot
case. Only Diligent (0001287750, two $100K lots) and one Apex (0001851322) edge are
identical on every field. **Those 4 do not matter:** when two lots are identical on
every field at both ends, any pairing yields the same per-position and aggregate
returns, FV and counts; and if they later diverge, the two possible labelings produce
the same pair of series. The gold rubric should score any pairing inside an
all-fields-identical block as correct (or its own code, excluded from the tranche-hop
rate). No grain or policy decision is needed for them. 58 of 62 hops are therefore
fixable by veto (18) or assignment cost with exact spread, principal, cost, FV (40).

### E6. Block shapes (adjacent quarters, excluding each CIK's last quarter)

| shape | begin rows | share |
|---|---|---|
| 1:1 | 118,543 | 50.9% |
| N:N equal | 51,232 | 22.0% |
| exit / key change | 50,443 | 21.7% |
| N:M unequal | 6,623 | 2.8% |
| N:1 | 3,312 | 1.4% |
| 1:N | 2,839 | 1.2% |

Inside the 6,918 ambiguous blocks (13,952 rows) principals are all distinct in 99.1%
of blocks, >5% apart in 73.9%, >50% apart in 63.4%. Splits and merges are ~2.6% of
rows; the registry needs those events but they are not the first-order problem.

### E7. Continuation and the 10-K boundary

Chain continuation for a live (FV>0) row whose CIK filed the next quarter: 10-Q begin
77.3%, 10-K begin 80.9%. **No 10-K boundary penalty** in aggregate; one filer
(0001925309: 64% vs 87%) has one.

**E7b completeness decomposition** (194,631 live rows with a name, next quarter filed):

| outcome | rows | share | FV |
|---|---|---|---|
| continued | 154,289 | 79.3% | $2,552B |
| exit: name absent next quarter | 20,289 | 10.4% | $235B |
| BREAK: same name + maturity + spread present next quarter | 14,453 | 7.4% | $206B |
| BREAK: same name present, hard key differs | 5,600 | 2.9% | $56B |

The 7.4% "hard key present next quarter but not chained" is the likely-missed-link
pool -- an upper bound on the recall gap, since some are genuine tranche swaps. It is
concentrated: 0001959568 16.1%, 0001993402 15.7%, 0001885968 15.7%, 0001772704 14.8%.
Interior singletons (chain length 1, not the CIK's first quarter): 11,133 rows, $122B,
of which 36% have a hard-key twin in the next quarter. The mg3 interior_singleton
stratum adjudicated 26 MISSED_LINK / 8 CONFIRMED-singleton / 6 insufficient, i.e. ~76%
[Wilson ~0.60-0.88] of interior singletons are matcher misses at n=34.

### E10. The static-ambiguous group and rank-order pairing

Question (owner): two lots identical on every static field, differing only in a
time-varying one (FV 90/100 -> 100/110 next quarter). How to pair, and how big is the
group? Script `e10_static_ambiguous.py`.

**Rule:** pair by rank on the time-varying field (sorted matching = minimum total
displacement). 90->100, 100->110 (returns 11% / 10%) rather than 90->110, 100->100
(22% / 0%). Aggregates are invariant either way; rank pairing is the one consistent
with lots of one instrument sharing a mark.

**Size** (rows whose CIK-quarter block shares name_key, maturity, subtype and EXACT
spread with another row):

| scope | rows | static-ambiguous | share | FV | FV share | still ambiguous after principal | identical on all fields |
|---|---|---|---|---|---|---|---|
| all quarters | 262,673 | 73,216 | 27.9% | $821B | 23.9% | 10,135 (3.9%) | 1,463 (0.6%) |
| 2026-03-31 | 29,681 | 9,454 | 31.9% | $107B | 28.2% | 1,600 | 145 |

Block sizes: 51% pairs, 40% of 3-4 lots, 9% of 5+. So a quarter of cohort FV sits in
blocks where the pairing is decided by principal, cost or FV alone.

**What production does inside them:** on the 2,532 static-ambiguous blocks that are
fully chained block-to-block (5,843 pairs), the production pairing violates FV rank
order on 10.7% of pairs and principal rank order on 10.6%. In the 274 violating
blocks, the dispersion of log FV returns across the lots is 0.70 under the production
pairing and 0.002 under rank pairing. Rank pairing minimises dispersion partly by
construction, but 0.002 means the lots move together to within a fraction of a
percent -- the "one instrument, one mark" prior holds, and the production pairing is
manufacturing +100% / -50% lot returns out of it. This is the mechanism behind the
class-B tranche hops (35 of 62) and is a direct, testable assignment rule: inside a
static-identical block, assign by sorted principal, then cost, then FV.

### E11. Borrower ids without external identifiers

Question (owner): how to get unique company ids. Script `e11_borrower_ids.py`; cohort
BDC rows, 2026-03-31 unless stated.

**No external identifier exists in the cohort.** CUSIP, ISIN, LEI and ticker coverage
on BDC schedule rows is 0.0% across all 69 filers. The spec's CUSIP6 -> LEI -> name
cascade is name-only for v1. `entity_id` (fuzzy clustering) covers 97%.

**E11a key cardinalities:** 14,646 raw names -> 12,006 `name_key` (ordinal/comma/fka
stripped) -> 11,453 legal keys (legal-form suffix + punctuation stripped, structure
words KEPT) -> 7,253 entity_ids. Under the legal key there are 17 "collision suspects"
(>=2 name_keys and >1 entity_id) and every one is a punctuation variant the entity
layer split (G-3 vs G 3 Chickadee; SCHP L.P. vs L.P; Ascend Buyer split across 4
entities). The legal key has no observed true collisions; the entity layer splits 48
legal keys and merges 2,019 into others. Stripping structure words (holdings, buyer,
bidco, topco, parent, intermediate) collapses only 171 families (165 of 2 legal keys,
5 of 3, 1 of 4) -- 1.5% of keys -- but those are exactly the deal-family merges
(Denali Bidco/Holdco/Intermediate = Dun & Bradstreet). **Decision:** `borrower_id` =
legal key; structure-word collapse is a `borrower_group_id` rule, never applied at the
strict level.

**E11b aliases:** 5.1% of rows carry a dba/fka/formerly parenthetical (4.4% dba, 0.7%
fka); 1,239 legal keys have one across all quarters, 418 at 2026-03-31. Alias-only
cross-fund bridges at 2026-03-31: 75 name pairs, 454 fund-pair links (Denali
Intermediate -> Dun & Bradstreet; Edition Holdings -> Enverus; GS AcquisitionCo ->
insightsoftware; Romulus Intermediate -> PetVet). Small but deterministic and free.

**E11c cross-fund term agreement** (2,454 legal keys held by >=2 funds, $218B; 10,068
fund pairs with maturities):

| agreement test | share of fund pairs |
|---|---|
| exact maturity + spread | 59.5% |
| exact maturity | 62.9% |
| same month + spread | 88.1% |
| maturity within 45 days | 94.4% |
| no overlap within 45 days | 5.6% |

The 30pp gap between exact and 45-day agreement is filer day-convention drift on the
same loan (2029-06-18 vs 2029-06-30; 2031-09-10 vs 2031-09-30; 2030-12-20 vs
2030-12-31). Per name, only 46 of 2,216 checkable multi-fund names (2.1%, $1.4B) have
no fund pair agreeing within 45 days, and those are refinancings or genuinely different
deals sharing a stem (Ranger Intermediate II 2030 vs 2031; Tiger Acquisition = Sabre
Industries vs another Tiger; Dcert 2029/7.0 vs 2030/5.75). **Two consequences:** (1)
cross-fund term agreement is a working independent validator for the name key -- 98%
of multi-fund names pass it; (2) any maturity equality test that spans filers must be
month-level or +-45 days. Within one filer E2 showed drift is rare (3 of 16 confirmed
maturity changes were <=45 days), so the within-CIK veto can stay exact with the
amendment escape, but the cross-fund layer cannot.

**Not run:** GLEIF name-match hit rate (external download, awaiting owner go).

**E12 cross-quarter stability** (`e12_key_stability.py`; 164,646 adjacent-quarter
chain steps on production position_ids): raw name unchanged 93.1%, name_key 94.8%,
legal key 96.4%, structure-stripped key 96.4%. The 3.6% legal-key changes are not
alias or structure variants (0.01%); they are wrapper parse drift -- the same position
carries ", First lien senior secured loan" in one quarter's issuer_name and not the
next (0001812554 at 2025q3 alone accounts for most of the largest-FV cases). Per-CIK
change rate: 0001899017 35.5%, 0001901164 22.3%, 0001930087 18.4%, 0001899996 16.1%,
0001901612 15.9%; most filers <5%. 10-K boundary change rate 1.9% vs 10-Q 4.4%, so the
10-K is not the driver. **Reading:** the key is stable where the wrapper is stable;
per-CIK key-drift rate is the metric to gate wrapper changes on. Caveats: the
cross-fund validator covers only multi-fund names (~21% of keys); 3,499 null-issuer
rows have no key; the strict key is a legal entity, so "all loans to X" needs the
group layer, which is unbuilt.

### E8 / E9 status

- **E8 registry determinism:** NOT re-run. `pipeline/position_id_registry.py` exists
  (795K natural keys, 82 retirements, last written 2026-07-01) but **is not on the
  production path**: `assign_position_ids(use_registry=False)` is the default and both
  `scripts/rebuild_outputs.py --returns` and `pipeline.main` (without
  `--stable-position-ids`) call it that way, so production ids are still ordinal
  labels that renumber per rebuild (correction 2026-09-07 evening; the earlier note in
  this file overstated it). Turning the registry on is a one-flag change with a
  parity check already written; the quarter-append test is still the missing gate.
- **E9 recall stratum:** not enlarged. The existing 40-packet interior_singleton stratum
  gives the estimate above; a 100-150 packet random interior-singleton batch would
  tighten it to +-8pp and is the right next fleet after `mg4_contested`.

### What the experiments decide

1. The objective's dominant failure is same-borrower tranche/lot hopping (6.1% of random
   edges), not borrower confusion (2.0%, D_fuzzy only). Fix order follows that.
2. Vetoes: maturity with amendment escape; instrument class / lien only as wrong-borrower
   guards. Everything else (spread, principal, cost, ordinal) is an assignment cost
   inside a (cik, borrower, quarter-pair) block -- exactly the `contested_assignment`
   shape, which is why its A/B moved WRONG 58->29.
3. All-fields-identical lots (4 edges) are not an error: any pairing is observationally
   equivalent. Score them as correct in the rubric; no grain or policy change needed.
   Assignment costs must use exact spread and cost/FV, which separate the rest.
4. Completeness levers, in FV order: wrapper fixes for the 3 null-issuer filers
   ($9.8B), the 7.4% hard-key-present break pool ($206B, filer-concentrated), subtype
   extraction (resolves 24% of name-duplicate ambiguity; 45% coverage today).
5. The 10-K boundary is not a problem. Splits/merges are second-order.
6. **mg4_contested gate (2026-09-07 evening, see agent_campaigns.md):** the contested
   name-key contest scores 0.98 on 499 random edges and is promoted; the leftover
   rounds score 0.56 / 0.71 and stay off. Flag-on precision 0.960 excluding leftovers
   vs 0.919 production. Next: fold the E5/E10 rules into the contest, replay mg3+mg4,
   rebuild behind the semantic diff and twin-build gates.

## 2026-09-07 (evening) - Production result of the contested promotion

Rebuild `--returns` with `CONTESTED_ASSIGNMENT_DEFAULT = True`, leftover rounds off,
maturity veto with amendment escape (code in `pipeline/position_matching.py`, gold
A/B in agent_campaigns.md "mg4_contested" addendum). Cohort BDC rows, current build vs
the 2026-09-05 baseline (`prod_chain_metrics.py`, `e10_static_ambiguous.py`,
`experiments.py` E7b):

| metric | baseline | now |
|---|---|---|
| singleton share (rows) | 27.2% | 15.2% |
| singleton share (FV) | 9.5% | 3.8% |
| cohort chain edges | 144,663 | 178,355 |
| D_fuzzy / C_normalized_name edges | 4,277 / 824 | 1,423 / 390 |
| rank-order violations in static-ambiguous blocks (E10c) | 10.7% | 3.7% |
| live-row continuation to next quarter (E7b) | 79.3% | 84.3% |
| likely-missed pool: hard key present next quarter, not chained | 7.4% / $206B | 2.6% / $31B |
| cohort FV | $3,440.7B | $3,440.7B |

The approximate tiers shrink because the name-key contest claims their rows first;
the likely-missed pool falls by a factor of three without any wrapper work. What this
does NOT show: per-edge precision of the new production build (the gold A/B is the
proxy: mg3 WRONG linked 52 -> 24, CONFIRMED 669 -> 660), and recall on the remaining
singletons (mg5_recall, running). Baseline not refreshed; frontend not exported.

## 2026-09-07 (night) - What still blocks the mg5 missed links

`replay_verdicts.py` on the 66 adjudicated missed pairs from mg5_recall, current
production build (post-promotion): 27 are admitted by at least one tier today (the 26
now chained plus one lost in the 1:1 contest). The 39 that no tier admits fail on:

| blocker | pairs |
|---|---|
| issuer name differs between the two quarters (`name_differs`, `jw<0.88`) | 38 |
| the two rows are not in adjacent quarters (a gap quarter in between) | 12 |
| name multiplicity cap / not unique | 13 |

(Overlapping counts; most pairs fail two or three predicates.) The name-differs
group is E12's parse drift plus genuine filer renames: the position is the same but
the wrapper produced a different issuer name in one quarter, so no name-keyed tier
can see it. The gap-quarter group needs a span-2 link (position absent for one filing,
present again after), which no current tier attempts. Together these are the
remaining completeness mechanism, and both are outside the assignment contest: one is
extraction, the other is a new tier.

## 2026-09-08 - E13-E16: where the remaining completeness gap actually is

Diagnostics after mg5_recall, on the post-promotion production build. Scripts:
`chain_experiments/e13_name_drift.py`, `e14_fingerprint_precision.py`,
`e15_guards.py`, `e16_null_issuer.py`, and `replay_verdicts.py --pairs-csv`
(new flag: replays the tier vetoes over any pair list, not just a gold batch).

### E15. The match universe, not the matcher, owns 44% of the singletons

`match_positions` built its universe with `fair_value IS NOT NULL AND != 0`, and
every name tier additionally required `b.fv > 0 AND e.fv > 0` before its FV-ratio
guard. So a row carrying a zero mark could not chain at all.

| cohort BDC rows | 266,198 |
|---|---|
| fair value exactly 0 | 17,655 (6.6%) |
| fair value negative (in the universe, but sign-flip pairs vetoed) | 26,737 |
| singleton rows | 40,539 (15.2%) |
| singletons that cannot chain by construction | 17,717 (43.7% of singletons) |
| singleton rate attributable to the matcher | 8.6% |

5,943 zero-FV rows have a same-name, non-zero-FV row in the very next quarter,
across 53 CIKs: undrawn revolvers and delayed-draw commitments being funded.
`index_returns.py` filters `begin_fair_value != 0` independently (line 239), so
chaining them cannot move any index.

### E13/E14. The terms fingerprint: accurate where it agrees with the name, unproven where it does not

E13 finds 11,323 adjacent-quarter break/new pairs, unique on both sides, agreeing
on maturity + classification + principal band + spread ($77.1B). E14 replays that
rule against 160,384 pairs the build chained by exact name:

| fingerprint on the control | n |
|---|---|
| fires with exactly one candidate | 84,611 (52.8%) |
| picks the exact-name answer | 83,652 (0.989) |
| picks a different row | 959 (0.011), of which 772 have a different name |

Every different-name pick is wrong **by construction** -- the control's truth is a
same-name pair. An availability gate ("fire only where the begin row has no
same-name row next quarter") suppresses all 959, and also the entire control, so
it certifies nothing about drift. **The drift population cannot be validated
offline.** Adjudication is the only instrument for it.

Replaying the pool through the tier vetoes splits it cleanly:

| class | pairs | FV | lien | instr | industry | what blocks it |
|---|---|---|---|---|---|---|
| same name, zero/neg begin FV | 3,053 | $1.7B | 0.998 | 0.996 | 0.996 | `fv_nonpositive`, sole cause, 0 admitted |
| null issuer name | 1,472 | $6.6B | 1.000 | 0.984 | 1.000 | name multiplicity, 0 admitted |
| same name, other | 658 | $1.4B | 0.994 | 0.798 | 0.988 | `fv_nonpositive`, `inst_subtype` |
| wrapper containment | 2,326 | $21.5B | 0.995 | 0.936 | 0.917 | `name_differs`; 1,012 already admitted by D/E |
| unrelated names | 3,814 | $46.0B | 0.946 | 0.955 | 0.928 | `name_differs`; 1,613 already admitted by D/E |

Corroboration columns are fields the fingerprint does not key on. Interest-rate
agreement runs 0.35-0.49 everywhere because SOFR resets quarterly; it is not a
discriminator. The first three classes are mechanically explained; the last two
carry the FV and are the drift population above.

### E13(b). Gap quarters

496 span-2 pairs, $4.7B, 44 CIKs, on the strict definition (same name, same
maturity, principal band, and that name absent from the intervening filing).
None of the mg5 gap pairs are among them: those drifted in name as well.

### E15(2). What the contested promotion cost, and why

The 17 CONFIRMED gold pairs lost to the promotion have two causes. Seven hit the
maturity veto: five also moved principal beyond 2%, three moved spread, so the
escape (which demanded principal AND spread stability) could not fire. Columbia
Helicopters (principal within 2%, spread 10.51 -> 11.51, maturity +380d) and
Nouryon Finance (principal identical, spread 4.00 -> 3.50, +912d) are textbook
repricings the rule was written to keep. The other ten lost the 1:1 contest with
principal ratios a revolver produces legitimately: 3.94, 2.52, 0.24, 0.13, 0.04,
0.001. Their names say "revolving loan" but `instrument_description` is empty, so
`_inst_subtype` was NULL and `CONTESTED_PA_BAND_REVOLVER` never applied.

### E16. Null issuer names are a wrapper defect

3,525 cohort rows, $11.12B, and 94% sit in four filers: Crescent Private Credit
(1,229), Crescent Capital BDC (924), Goldman Sachs BDC (886), Audax (259). Every
one retains a raw identifier that still contains the borrower, e.g.
`Investment Debt Investments - 216.4% United States - 205.6% 1st Lien/Senior
Secured Debt - 195.3% Xactly Corporation IT Services Interest Rate 10.55%`.
The wrapper's `prefix_rules` match with `str.startswith` on fixed strings, and
these prefixes embed percentages that change every quarter, so no rule fires.
`fallback_family_patterns` already accepts regexes, which is the mechanism a fix
would use. Not attempted here: it renames $11.1B of rows and would flow into
investee concentration, top constituents and entity resolution, so it deserves
its own gated pass rather than riding along with a matcher rebuild.

### What shipped (commit 8c4b68e)

1. Zero-FV rows join the match universe.
2. `_fv_scale_ok_sql`: magnitude comparison plus a principal-agreement escape,
   replacing the signed ratio at all eight tier call sites.
3. `_inst_subtype_name` widens the contested principal band for filers who name
   the instrument in `issuer_name`; never used as a veto.
4. The amendment escape takes principal OR spread, with the spread-only leg gated
   on the principal not contradicting (band 1.5, fitted to the lost gold pairs).
5. Tier F gap-quarter links, and the continuation metric, both off by default.
## 2026-09-14 - Refactor identity comparison and cached-name representative regression

Question: did the v8 deterministic entity-input choice preserve available cached-name evidence, and which measured changes are software defects versus unresolved legacy identity evidence?

The immutable v8/v7 comparison scored all535validated mg3 packets and the exposed pair table. Pair results are1regression/0improvements/0unassessable; the complete packet table additionally flags7confirmedentitysplits and1negativecluster collapse. These are development-reference measures, not population accuracy. Negative-cluster separation means only that at least two IDs exist in the cluster; it does not certify all assignments.

Evidence is under scratch/2026-09-12_programme_e0/identity-v8-versus-v7-v1/, v8-v7-delta-diagnosis-v1/ and v8-entity-input-review-v1/. The latter binds frozen holdings/cache hashes and covers12changed packets and393issuer/sourcevariants. Several regressions share one implementation mechanism: MIN(bdc_investment_identifier) chose an uncached identifier, discarding populated names attached to other identifiers for the exact same issuer/source. The affected examples include Artifact Bidco, Wealth Enhancement, Jeppesen, Kaseya, GC Waves, Azurite and Southern Veterinary. Clarience/Truck-Lite also has conflicting cached names and requires a separate ambiguity caveat.

The root implementation now prefers a populated cached identifier, then observed identifier frequency and a lexical tie-break. This preserves deterministic selection and existing cache availability; frequency remains a representative heuristic, not source adjudication. The focused entity/durable-ID suite passed152tests in62.41seconds, with237627protectedfiles unchanged. A read-only full-input aggregation of135084variants followed by393selected extractions recovered the expected cached names for the eight examples. It did not run fuzzy clustering, position matching or durable allocation. A replacement immutable candidate and full comparison are still required; v8 was not edited.

Two important residuals must not be hidden. Coupa's negative-cluster flag follows a punctuation variant of the single LLC joining a cluster that already combines single and joint borrowers; the stored verdict distinguishes Coupa Holdings, LLC from the joint Coupa Holdings/Coupa Software label. Cloud Software likewise has cached names that both retain and drop Picard Parent from an explicitly joint label. Deterministic selection does not resolve those contradictory legacy name decisions. Keep actual reference outcomes and source-review needs visible; do not add example-specific overrides or call a cache preference a verified legal-entity conclusion.

No new LLM calls, agent campaign, source download, accepted-registry mutation or production adoption occurred. The repair's complete integration and semantic backstop remain pending at this checkpoint.

## 2026-09-16 - V11b named identity regressions and source-defined scope

Question: why do the exposed development packets change after reviewed source recovery and financial/scope migration?

- Midwest MGP-e2d2fd83b520: June 2025 ROW-ebff28dde0fbb417 and September ROW-b596bd59a3e1b6c2 lose their E-tier link when September gains an outgoing B2 link to December. One global used-row set incorrectly occupies both incoming and outgoing slots. Separate direction sets restore eligibility without allowing two uses in the same direction. Candidate counts must also be per accounting scope: another portfolio cannot make one within-scope position ambiguous. Nine direction controls and a six-row scope probe passed; same-scope ambiguity still prevents the unsupported links. The first scope probe's principal-bucket fixture was wrong and its failed evidence is retained; no tolerance was widened.
- Coupa MGP-28ee21d4522d and Higginbotham MGP-25948b5c52ac: cached single-company extraction can truncate a disclosed legal co-borrower list. The repair restores the complete list before exact/fuzzy linking and prevents shared loan identifiers from merging the joint set with one member. Positive list controls and ordinary names containing and/& are separated. Fourteen actual variants passed the bounded source-name probe. Exact conservative list agreement can retain false splits; broad identity accuracy is not established.
- Coding Solutions/NeoGov MGP-f5a2604249d8, CIK 0001772704 Q1-2023: the flat identifier format was interpreted as a percentage hierarchy, causing both issuers to become Reference Rate and Spread S + 5.50. Source0000950170-23-019617 SHA256 ea28f2e9b947aa945412e21ffb982f61003fbd40a6ca1bdbf7081013d31821c5. The flat-layout profile contains 81 raw rows/80 identifiers. The revised wrapper extracts the borrower before the structural Industry field; a borrower named Alpha Industry Systems LLC remains intact, and subtotals do not match. Seven pattern controls and four staged observations passed. Wrapper v2 is applied; final identity effects require V12.
- MH Sub I MGP-742cafc01ca0: ROW-e83972fbeb8d1ba0 in 0001803498-24-000007/c-4761/Q4-2023 names MH Sub I, LLC 1 Verdelite JV LP; ROW-4cb1d31c8c5ba003 in 0001803498-24-000022/c-4323/Q1-2024 uses MH Sub I, LLC, Verdelite JV LP. XML hashes 097ea2806299ca7908b0d8dca775661d341319cb03b7482e8cb5b0d47bd4fd1d and 776637174cd41ca0610c03fbfa957714b134c0b673a96f3b2a5f12475a938e86. Both source formats identify the Verdelite portfolio. The two-row staging probe retains FV 3.920m/2.462m and cost 3.893m/2.423m with that same scope; it does not remove position ordinals.
- Nouryon MGP-59b7640cd792 links an underlying ORCIC observation to a parent record in the old reference; D08 does not permit that inferred continuation. Payroc, UKG, two HelpSystems packets and Staples retain financial/tranche evidence limitations after unsupported rates and false exact-day precision are removed. Pavement's V11b improvement must survive the final repair. These are named review obligations, not blanket acceptance of every lost link.

Evidence lives under scratch/2026-09-16_refactor_continuation/, including joint-resolution-probe-v1, matching-scope-counts-v2, legacy-scope-staging-v1 and v12-identity-review-plan.json. Confidence is high in the diagnosed mechanisms; integrated test failures are still being investigated. Review every new final-candidate transition, including packets outside this list. The 535 exposed mg3 packets are development references, not independent population-accuracy evidence; no labels or accepted registry have been promoted. Identical-input cold-build equality remains required.
