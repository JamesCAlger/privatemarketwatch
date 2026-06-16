# Bundle-Enrichment Experiment (BDC source-blocker review)

Status: spec + pilot. Tests whether the high `INSUFFICIENT_EVIDENCE` / `LOW`
confidence rate in the `bdc_cik_review` loop is a *context* problem (the bundle
carries reconciliation residuals but not source-table structure) rather than an
irreducible-difficulty problem.

## Motivation (measured 2026-06-16)

Verdict distribution over 1,251 packets: INSUFFICIENT_EVIDENCE 1,175 (94%),
PATCH_PROPOSED 48 (3.8%), NO_PATCH_NEEDED 15, ESCALATE 13. Confidence LOW on 1,174.
`missing_evidence` is effectively templated: the same complaint recurs in 80-94% of
ALL verdicts -- "coordinate" 94%, "header" 91%, "position row" 84%, "source table"
83%, "aggregate" 80%. The agent is asking the same thing every time: coordinate-level
source-table classification (is this row a position or an aggregate/header?) to author
a bounded, tested, false-positive-guarded patch. The bundle (188 KB, 131 KB of
`evidence_items`) carries reconciliation residuals, not the source-table grid needed to
make that call -- structure destroyed upstream by flatten-first extraction.

## Hypothesis (falsifiable)

Injecting coordinate-level source-table structure into the bundle raises the VALIDATED
patch rate on the parser-mismatch mechanisms (`position_like` 0.3%, `pct_leaf` 1.9%) by
>=15pp AND drops the source-table `missing_evidence` complaint from ~90% to low.

## Intervention

One additive `evidence_item`, `source_table_neighborhood`; everything else unchanged.
Per blocker row, from the CACHED raw filing (no network):
- ordered neighboring source rows (identifier string + FV) from the same filing,
- the section/category header / parent dimension member the row sits under,
- a derived `appears_under_aggregate_header` flag (the exact position-vs-subtotal call).
Read-only, deterministic.

## Design -- paired, within-packet

Each packet gets two independent verdicts from the same model/prompt: control
(original bundle) and treatment (enriched). Paired -> packet difficulty cancels.
- Strata (recoverable packets only): `position_like` ~40, `pct_leaf` ~40,
  `short_plain_unresolved` ~20 (comparison: lift should be SMALLER here if the gap
  theory holds).
- Test-retest: control run twice on ~15 packets to estimate nondeterminism noise floor.

## Metrics

- PRIMARY: validated-patch rate (PATCH_PROPOSED that passes the bundle's
  `required_validation_commands` -- the gate is the checker, not the agent's confidence).
- INSUFFICIENT_EVIDENCE rate; confidence shift; does the source-table `missing_evidence`
  complaint vanish in treatment; McNemar on discordant pairs.

## Decision rule (pre-registered)

- Confirmed: treatment validated-patch rate significantly > control (McNemar p<0.05) AND
  >=15pp absolute lift on parser-mismatch strata AND source-table complaint drops.
- Refuted: patch rate up but validation fails (overconfidence) OR complaint persists
  (wrong structure injected) OR no lift.
- Null/underpowered: test-retest noise ~ treatment effect.

## Threats (mitigated)

1. Nondeterminism -> paired + test-retest.
2. Overconfidence -> count only gate-validated patches.
3. Bad injected context -> spot-check neighborhoods vs raw filing before trusting the arm.
4. Coverage -> enrichment only where a source table is recoverable; report coverage.
5. Selection -> random within strata.

## Constraints

Read-only on production; all output to a sandbox dir; patch validation in a worktree;
no network (cached only); deterministic enrichment.

## Pilot (this run)

A 2-packet x 2-arm proof of concept on `position_like` packets: build the enrichment,
build paired bundles in a sandbox, run a review subagent per arm, compare verdict /
confidence / missing_evidence. NOT powered for significance -- a signal check that the
injected structure changes the verdict in the predicted direction before scaling.

### Pilot result (2026-06-16) -- hypothesis REFUTED, real mechanism FOUND

Enrichment built: `scripts/bundle_enrich_trial.py` resolves the ambiguous coordinate/
classification candidates already in the bundle into ONE per-blocker statement
(majority classification + section header + aggregate flag + conclusion). Ran 2 packets
(CIK 0000081955, 2023-03-31 & 2023-06-30, both `position_like`) x 2 arms via review
subagents.

Outcome: ALL FOUR verdicts = ESCALATE / MEDIUM. Treatment did NOT flip to
PATCH_PROPOSED. So resolving coordinate ambiguity did not lift conversion.

Why -- the decisive finding:
1. The resolver's conclusion was WRONG. It labelled the blocker `POSITION_ROW` (16/16
   coordinate agreement) -> "genuine missing position." But the blocker is the
   bare-issuer XBRL fact `investmentidentifieraxis=Tilson Technology Management, Inc.`,
   FV 10,550,000 -- an ISSUER-LEVEL ROLLUP of multiple tranches (Series B Pref
   4,559,500 + Series C + warrants + note), NOT a single position. The resolver matched
   identifier text and never reconciled FV.
2. BOTH arms' agents independently FV-reconciled and OVERRODE the resolver. The GoNoodle
   parallel clinched it (bare-issuer axis FV 1,415,360 == "Total GoNoodle" subtotal).
   They noted GAV is already over_coverage (1.45-1.88) so there is no missing FV; adding
   the row would worsen over-inclusion.
3. So the binding constraint is NOT coordinate-level classification (the templated
   complaint) -- it is FV reconciliation of bare-issuer rollup facts. The agent needs
   per-tranche XBRL FV decomposition and a resolved-issuer arithmetic check
   (sum(tranche FV) == issuer-line FV), exactly the IRGSE/signed-residual gate in
   frontier_architecture.md sec 4.

Lessons:
- Threat #3 (bad injected context) MATERIALIZED: a deterministic resolver that asserts a
  wrong conclusion is worse than nothing. Any injected resolution must be FV-grounded and
  able to conclude "issuer rollup -> NO_PATCH / aggregate-filter," not default to position.
- The validated-patch guardrail proved essential: had we scored PATCH_PROPOSED instead of
  VALIDATED patches, a confidently-wrong resolver could have manufactured wrong patches
  (the agents only avoided this by FV-checking on their own).
- Sample is DEGENERATE: both packets are the same issuer (Tilson) in one CIK across two
  quarters = one case studied twice. Not generalizable; rerun on diverse packets.

Revised next enrichment to test: per-tranche XBRL FV decomposition + resolved-issuer
arithmetic (sum of tranche FVs vs the bare-issuer fact), NOT coordinate de-ambiguation.

### v2 result (2026-06-16) -- resolved-issuer arithmetic is CIRCULAR; not run

Rebuilt `scripts/bundle_enrich_trial.py` to inject resolved-issuer FV arithmetic (does
the bare-issuer fact reconcile to the sum of same-issuer tranche leaves -> ROLLUP vs
single position?). Applied to 4 diverse packets (CIKs 1508655, 1280784, 1370755, +
0000081955 Tilson control). The arithmetic came out as garbage and the trial was NOT
run, because computing it requires solving the two problems that CAUSE these blockers:

1. ISSUER EXTRACTION. The flattened identifier is `<Category> <Industry> <Issuer>`
   (e.g. "Debt Investments Consumer & Business Services, Tectura Corporation"). Token
   extraction matched the CATEGORY prefix -> every "Debt Investments ..." row counted as
   a tranche (ratios 936x, 283x, 318x). The pipeline's OWN `issuer_name` column is also
   category-prefixed garbage for these filers ("Debt Investments Software an...",
   "Equity Investments Drug Disc...") -- because broken issuer parsing is exactly why
   these are parser-mismatch blockers. There is no clean issuer key to reconcile on.
2. COMPARATIVE / DIMENSION-PATH DEDUP. Even Tilson (clean issuer name) gave ratio 1.976
   -- ~2x -- because the detail holds comparative-period and multi-dimension-path
   duplicate rows (Series B Preferred repeated at 0.0 and 4,559,500). The sum double-counts
   without the comparative/dimension dedup the pipeline itself struggles with.

CONCLUSION (the real finding of the whole arc): bundle enrichment with DERIVED signals
cannot resolve the parser-mismatch bulk, because every useful derived signal
(coordinate classification in v1, issuer arithmetic in v2) PRESUPPOSES the parse that is
broken. The enrichment is circular. Therefore the high INSUFFICIENT_EVIDENCE / LOW rate
is largely CORRECT behaviour on a genuinely parse-blocked class -- not a fixable
bundling oversight. The agents are right to escalate.

What could actually help (untested / out of scope here):
- Inject the RAW source-table excerpt for the issuer (the filing's actual SOI rows), NOT
  a derived signal, and let the agent reconcile by reading source. Different from v1/v2
  (which injected pipeline-derived conclusions that inherit the broken parse).
- OR treat these as per-CIK Part A wrapper-parsing fixes (the durable fix for the format).
- OR human/source adjudication (what the agents request).

Answer to the original "is it a context issue": partly, but not a context you can
manufacture from derived signals -- the helpful context (clean issuer + deduped tranche
reconciliation) cannot be derived without first solving the parse. So enrichment is not
the unlock; parsing fixes or raw-source adjudication are.

### v3 result (2026-06-16) -- RAW-source injection WORKS; it IS a (raw-)context issue

v3 injects the RAW current-period source rows for the filing (identifier + FV + match
status, unparsed, 175-449 rows) -- NOT a derived conclusion. The agent locates the issuer
by reading and reconciles itself. Ran 4 diverse packets (CIKs 1508655, 1280784, 1370755,
0000081955) x 2 arms, paired.

Result:
  CONTROL  : 1 ESCALATE, 1 INSUFFICIENT_EVIDENCE, 2 NO_PATCH_NEEDED -- all MEDIUM, 0 HIGH.
  TREATMENT: 4 NO_PATCH_NEEDED -- 3 HIGH, 1 MEDIUM. 0 indecisive, 0 regressions.
Two packets flipped indecisive->decisive (ESCALATE->NO_PATCH/HIGH, INSUFFICIENT->NO_PATCH/
HIGH); the other two stayed NO_PATCH but confidence MED->HIGH. Clean directional effect.

Mechanism (why it worked):
- The raw rows let the agent do the FV reconciliation it couldn't before. Tilson treatment
  agent summed the 7 Tilson tranches to EXACTLY 10,550,000 = the bare-issuer FV, and found
  the row's own label `documented_source_issuer_subtotal_arithmetic` -> confident issuer
  rollup, NO_PATCH/HIGH.
- BIG secondary finding: several "blockers" are STALE. The raw current-period rows show the
  blocker identifier with match_status='matched', output_fv == source_fv -- i.e. it is
  already in output. The bundle's `source_only_blocker_rows` snapshot is an older,
  contradicted view (Warrior TopCo and ResearchGate warrant are both already matched).

So: it IS a context issue -- specifically a RAW-context issue. Derived signals (v1/v2)
can't help (circular), but the raw source rows decisively can. This also resolves the
v1-pilot conservatism strand: the raw rows gave the airtight reconciliation the agents
needed to COMMIT (NO_PATCH/HIGH) instead of hedging (ESCALATE).

Honest caveats:
- n=4, unpowered; but the effect is clean (2 flips, 2 confidence lifts, 0 regressions).
- All 4 packets were rollup/stale cases -> the win is confident correct REJECTION
  (NO_PATCH), NOT rule-creation (PATCH_PROPOSED). v3 did NOT test a genuine-missing-
  position -> PATCH path (none in this sample).
- Part of the signal is the raw rows EXPOSING stale match_status, not pure agent
  reconciliation -- which points at a data-hygiene fix (the blocker snapshot is stale).

Implications for the loop:
1. Inject raw current-period source rows into bundles (cheap, deterministic, no parsing).
2. Refresh the stale `source_only_blocker_rows` snapshot -- a chunk of the 1,175
   INSUFFICIENT pile may be ALREADY-MATCHED or issuer-ROLLUP rows that need no patch.
3. Expectation: converts a meaningful fraction of INSUFFICIENT/ESCALATE -> decisive
   NO_PATCH (correct rejection), shrinking the queue WITHOUT parsing fixes. Genuine
   missing-position cases needing a rule are a smaller residual than the raw queue implies.

### v3 POWERED run (2026-06-16) -- raw-source injection does NOT lift PATCH_PROPOSED

Selected 10 packets ENRICHED for genuine single missing positions (identifier carries
company + lien/instrument + rate, FV $3-57M, not already-matched, diverse CIKs), x 2 arms
(20 review subagents).

Result (verdict counts):
  CONTROL  : 1 PATCH_PROPOSED, 1 NO_PATCH, 6 INSUFFICIENT, 2 ESCALATE  (2 decisive)
  TREATMENT: 0 PATCH_PROPOSED, 3 NO_PATCH, 1 INSUFFICIENT, 6 ESCALATE  (3 decisive)

PATCH path: NOT lifted. Treatment produced ZERO patches; the only PATCH came from CONTROL
(1865174, "strip category-pct prefix") and TREATMENT REFUTED it -- the raw rows showed
108/112 pct-prefixed rows already MATCHED, so the proposed rule would false-positive ->
ESCALATE. So raw injection PREVENTED a likely-wrong patch (improved decision quality),
it did not add patches.

The decisive finding (consistent across all 10): the "genuine missing position" blockers
are NOT parser defects. Every one decomposed into:
  - STALE blockers -- already matched in the raw rows (source_only_blocker_rows snapshot
    is stale vs the authoritative reconciliation); recurring.
  - MATCHING/DEDUP artifacts -- FV-distinct duplicate-identifier tranche siblings (same
    normalized issuer+rate+maturity) collapsed by 1:1 matching; "One"/"Two" split rows;
    negative-FV revolver/DDTL fragments.
  - per-CIK HTML TEMPLATE/table-selection gaps (needs scripts/learn_template.py, not a
    global parser rule) -- e.g. 1372807 default_template picked a Statement of Changes,
    1544206 foreign/equity sub-schedules unstaged.
  - XBRL-axis-vs-HTML identifier-scheme mismatch; axis-member-to-row-text misalignment.
And in nearly every case GAV PASSES / over_coverage -- there is NO real missing FV; the
pipeline already covers it.

Conclusion of the whole arc: derived enrichment (v1/v2) is circular/useless; raw-source
injection (v3) improves decisiveness and ACCURACY (confident NO_PATCH on stale/rollup;
honest ESCALATE on real-but-unpatchable) and CATCHES false-positive patches -- but does
NOT lift PATCH_PROPOSED, because the parser-mismatch queue is overwhelmingly NOT parse
defects. The low ~3.8% conversion is a CEILING set by the queue's nature, not a context
gap. Leverage is: (1) refresh the stale blocker snapshot; (2) fix 1:1 matching for
FV-distinct same-identifier siblings; (3) per-CIK template work for template-gap CIKs;
(4) accept most of these need NO patch (GAV already passes). Caveats: n=10 paired,
verdicts MEDIUM confidence; selection still caught some already-matched despite filtering.
