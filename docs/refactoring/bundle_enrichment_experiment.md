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
