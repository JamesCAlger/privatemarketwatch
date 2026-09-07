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
tie-break) would have picked the twin. Class C is Kaseya (7 lots of ~$1.01M, 0001772704)
and Diligent (4 x $100K, 0001287750): separate lots of the same loan with identical
terms. The matcher gets these right at chance (14 confirmed vs 13 wrong).

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

### E8 / E9 status

- **E8 registry determinism:** NOT re-run. `pipeline/position_id_registry.py` already
  persists ids on a drift-resistant natural key (795K keys, 82 retirements) and the
  twin-build gate covers rebuild determinism. The earlier session claim that ids
  renumber on every rebuild was wrong; what is missing is a quarter-append test (build N
  quarters, then N+1, diff ids), not the registry itself.
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
3. Class C identical lots need a policy decision: chain by filer ordinal / table order,
   or define the tranche grain as "same terms = same tranche" and aggregate lots. The
   data cannot separate them.
4. Completeness levers, in FV order: wrapper fixes for the 3 null-issuer filers
   ($9.8B), the 7.4% hard-key-present break pool ($206B, filer-concentrated), subtype
   extraction (resolves 24% of name-duplicate ambiguity; 45% coverage today).
5. The 10-K boundary is not a problem. Splits/merges are second-order.
