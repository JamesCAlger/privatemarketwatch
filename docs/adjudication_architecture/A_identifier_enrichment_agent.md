# Agent A — Identifier Enrichment Agent (build scope)

Status: scoped, no code yet. Companion to `B_and_C_validation_agents.md`. A runs
FIRST (before the deterministic shadow rules) as a new, lower-trust enrichment
provenance over the freeform BDC `investment_identifier`. It does NOT merge as-if-XBRL;
its output is provenance-tagged and gated.

## 0. The gap (grounded in current code)

The freeform `investment_identifier` is the dominant BDC field and the only home for
several index-critical attributes. Measured (cache-only, 2026-06-19; see
`data_investigation_results.md`):

- 627,181 current-period BDC rows carry a freeform identifier (essentially all 2022+).
- Structured-XBRL-twin coverage is uneven and INVERSELY correlated with where parsing
  adds value: `interest_rate` 59%, `basis_spread` 68% (good twins, pipeline already
  extracts them); `maturity_date` 29%, `pik_rate` 8%; `reference_rate_type` 0%,
  `coupon_type` 0% (no twin -- string-only, and exactly the fields the wrapper invents).
- ~33% of rows have NO rate/maturity twin at all.

What already exists and what is missing (the precise seam):

- The wrapper config (`data/overrides/bdc_xbrl_wrappers/<cik>.json`, schema
  `bdc-xbrl-wrapper.v3`, loaded by `pipeline/bdc_xbrl_wrapper.py`) ALREADY holds a
  per-CIK keyword vocabulary (`leaf_markers_by_family`, `aggregate_markers`,
  `non_private_markers`), family dispatch, an `identifier_format.field_order`, and
  per-CIK `staging.hierarchy_issuer_re` / `hierarchy_instrument_re` that split the
  string into category/industry/issuer/instrument by anchoring on keywords like
  "Asset Type" / "Commitment Type". ~70 CIKs are wrapped.
- BUT the wrapper's `canonical_strip_re` STRIPS the rate/maturity tokens ("Interest
  Rate N%", "Reference Rate and Spread X + N%", "Commitment Expiration Date ...")
  rather than extracting them, and `pipeline/bdc_identifier.py` has NO rate/PIK/
  maturity/coupon parsing at all. Those fields are filled only by weak GLOBAL
  text-enrichment regexes (reference_rate_type ~3.6%, maturity ~13% historically).

So Agent A is NOT greenfield. It is the missing extraction stage for the within-string
RATE structure (cash leg / PIK leg / spread / reference / coupon_type / maturity), the
part the wrapper drops on the floor -- plus a semantic gate the wrapper does not apply.
This is also why the user's thesis holds: the wrapper's attention is on row disposition
and issuer/instrument split; nobody is paying attention to the rate sub-fields.

## 1. Two filer regimes (measured, drives the design)

- DELIMITED regime (Golub family; ~0% rate-embedded; well-anchored). Clean delimiters,
  string = name + instrument-type only; rates are structural XBRL. Punctuation-shape
  signature clusters tight (2-5 grammars/filer). A's job here is trivial-to-none.
- FLATTENED-CONCATENATION regime (~30-40 filers: Antares 67%, Crescent 63%, Bain 55%,
  MidCap 54% rate-embedded; weakly anchored). Everything jammed into one string with
  keyword markers, no reliable delimiter, rates embedded. A keyword-anchored signature
  collapses Antares from 178 punctuation-shapes to 23 (2 cover 80%); RATE/date capture
  is 100% on all four filers (the %/date detectors are universal). But the keyword
  VOCABULARY does NOT generalize -- each filer's markers differ ("Asset Type" vs
  "Investment Type" vs inline "Senior Secured Loan"; affiliation inline vs header;
  encoding mojibake breaks literals). So the anchor vocabulary is PER-CIK config, not a
  global list (AGENTS.md Layer 2).

A is needed almost entirely for the flattened regime, which is exactly where the twin
is absent and the naive signature fails -- hard on every axis at once.

## 2. Reuse / extend / new

REUSE unchanged:
- Override store + schema + loader: `data/overrides/bdc_xbrl_wrappers/`,
  `pipeline/bdc_xbrl_wrapper.py`. A's config is an EXTENSION block in the same per-CIK
  file, not a new store.
- Family dispatch, `aggregate_markers`, `non_private_markers`, hierarchy split regexes
  (issuer/instrument/industry/category) -- already curated for ~70 CIKs.
- Row disposition: `bdc_row_disposition_ledger.csv` (is_total / bare_header / leak).
- Agent harness pattern: `scripts/review_agent/` (sample_bundles, build_claims,
  evidence_cli, aggregate_verdicts) and `pipeline/review_bundles.py`.
- Evidence library: `pipeline/html_soi_evidence.py` (anchored raw-source lookup).
- Variant/drift machinery: `scripts/learn_template.py` (variant selection, revalidate).
- Shadow ledger + B: A's format contracts become ledger rules B can adjudicate.

EXTEND:
- Wrapper schema: add a `rate_grammar` (a.k.a. `field_extraction`) block per
  (cik, family/signature): how to parse the rate/maturity SEGMENT the
  `canonical_strip_re` currently discards into {interest_rate (cash leg), pik_rate,
  basis_spread, reference_rate_type, coupon_type, maturity_date}, with the reconciliation
  invariants attached (see section 4).
- `pipeline/bdc_identifier.py` (or a new sibling `bdc_identifier_rate.py`): deterministic
  apply of `rate_grammar` over all rows ($0, vectorized).

NEW:
- `pipeline/identifier_signature.py`: regime detector + signature builder (punctuation
  shape for delimited; keyword-anchored signature for flattened, using the per-CIK
  marker vocab). Emits per-row signature + the (none)/degenerate flag. [P0 DONE]
- A2 SKILL (e.g. `identifier-grammar`): operator entry point that builds one
  (cik, signature) variant-bundle and dispatches a SANDBOXED CODEX AGENT (the B model)
  to induce the dialect/grammar; supporting harness under `scripts/agent_a/`
  (sample_variant -> build_claim -> evidence_cli -> stage_config), reusing the
  `scripts/review_agent/` pattern and `html_soi_evidence`.
- `pipeline/identifier_overlay.py`: provenance-tagged COALESCE of A-parsed fields into
  unified holdings (precedence: structured XBRL > iXBRL > A-parse; conflicts -> flag).

## 3. Pipeline (A0-A4, mapped to B's stages)

- A0 Deterministic cluster + cheap flags (no agent). Build signature per row
  (`identifier_signature.py`). Key = (cik, signature). Degenerate/`(none)` signatures
  and "category-keyword with no issuer/rate" rows -> aggregate-candidate + "vocabulary
  not learned" flags. FV-weight the worklist.
- A1 Existing-rule check (no agent). Apply the (cik, family) `rate_grammar` if present;
  score parse-completeness (every char assigned vs residual) + run the section-4 gate.
  Clean -> done. New signature, or known grammar now leaving residual -> drift -> A2.
- A2 Agent grammar/dialect author (the ONLY LLM step; one bounded variant-bundle =
  ~10-15 homogeneous sample rows, never the cluster). Output = proposed `rate_grammar`
  (+ anchor vocabulary if the filer is unwrapped) + per-segment format contracts +
  reconciliation invariants + per-sample labels (evidence). Also surfaces ambiguous
  aggregate candidates, one per bundle.
  IMPLEMENTATION: a SANDBOXED CODEX AGENT, exactly as B (soft blinding via prompt; the
  hard sandbox is the Codex-harness step), CALLABLE VIA SKILL (like /wrapper,
  /highlights-wrapper). The skill is the operator entry point; it builds the bounded
  variant-bundle, dispatches the sandboxed Codex agent (cache-only, read-only on
  production, append-only to A's output dir, no network/rebuild), and stages the
  proposed grammar for the A3 gate. The agent NEVER writes production fields directly;
  it emits a proposed-config JSON the deterministic A3 gate must clear.
- A3 Deterministic gate (the strong check; section 4). Apply proposed grammar to ALL
  rows of the variant; promote only if every gate passes on the full set + held-out
  quarters. Fail -> human. [BUILT 2026-06-19] `pipeline/identifier_held_out.py` renders the
  cross-quarter PASS/FAIL: >=2 signature-bearing quarters; per-quarter completeness >=90%
  AND gating-invariant >=85% in EVERY quarter; none-share STABILITY (a quarter > median+10pp
  = a format the pooled induction sample missed; uniformly-high none = sparse data, not a
  fail). It is the PROMOTION gate; pooled evaluate_cik is diagnostic only. First run: Antares
  /Bain/Crescent PASS; MidCap FAIL (2024-06-30 completeness 87.8% -- a per-quarter dip the
  pooled 97.9% HID). So none of the four is auto-promotable yet (MidCap fails; the other
  three pass held-out but the production-merge overlay is still unbuilt).
- A4 Drift watch (quarterly). Re-run A1; known (cik, signature) leaving residual =>
  re-learn as new variant; new signature => new variant. Only drift + new filers reach
  the agent. The (none)/residual share is the per-filer coverage KPI.

No-haystack invariant (from B spec section 3) holds throughout: the agent sees a dozen
homogeneous rows or one aggregate candidate; breadth = fan-out across variants;
`evidence_cli roam` is the targeted escape hatch, out of the static bundle budget.

## 4. The gate -- semantic reconciliation, not format shape

Format/shape contracts are necessary but NOT sufficient (a wrong value can still be a
valid `n%`). A3 promotes a grammar only if, applied to ALL rows of the variant:

1. Parse-completeness: no unexplained residual above threshold (text analog of FV
   conservation -- parsing redistributes characters, invents/drops none).
2. Arithmetic identity where anchored: total_rate == cash_leg + pik_leg (e.g. 11==7+4).
   Catches the canonical mis-bin (total mis-stored as basis_spread).
3. Fixed/floating DERIVED, not guessed: basis_spread present (structured, 68%) <=>
   floating <=> a reference token exists in the string; basis_spread absent => fixed =>
   any reference_rate_type / "floating" emitted is fabricated (the invented-LIBOR bug).
4. Cross-source agreement: where a structured twin exists (interest_rate 59%, maturity
   29%), the parse must reconcile to it; disagreement -> flag, not overwrite.
5. FV / row-count preserved; counts within D01/D02 bands.
6. Held-out: inert/correct on the CIK's other quarters sharing the signature
   (>=2 to auto-promote, else flagged unvalidated_cross_quarter -> human).

Unanchored fields (0%-twin: reference_rate_type, coupon_type) get only #1 + #3 +
grammar-stability; they stay permanently lower-confidence and feed the gold slice --
never graduate to "verified" on stability alone.

## 5. Provenance and merge

Every A-derived field carries source=agentA_parse + confidence. Unified COALESCE
precedence is explicit: structured XBRL fact > iXBRL overlay > A-parse. Conflicts are
surfaced as ledger flags, never silently overwritten. A-parse fields land via
`identifier_overlay.py`, blank-fill-only by default (cannot clobber a structured value),
mirroring the existing iXBRL overlay discipline.

## 6. Calibration

Reuse `scripts/gold/`. A is calibrated on parse precision per field per (cik, signature)
and on the unanchored fields via a blind human gold slice (Rogan-Gladen, agent-relative
until the slice exists). The arithmetic-identity and cross-twin pass-rates are
deterministic self-checks; the human slice is the only tie to filing truth.

## 7. Phasing (thin slices, each with a measurable exit)

- P0 [DONE 2026-06-19] Signature + regime (deterministic only). Shipped
  `pipeline/identifier_signature.py` + `tests/test_identifier_signature.py` (17 pass);
  `python -m pipeline.identifier_signature` writes `identifier_signature_report.csv`
  (per-CIK: regime, distinct-sig count, cover80/90/95, (none)-share, rate-capture) and
  `identifier_signature_detail.csv` (top sigs/CIK + examples), one streaming scan of
  627,181 rows, read-only. EXIT MET: reproduces the measured table -- Antares 23 sigs /
  2-for-80 / 1.9% none; Golub delimited 43 shapes / 2-for-80; MidCap/Bain/Crescent exact.
  191 CIKs (90 delimited, 101 flattened); the flattened (none)% ranking IS the P2/P3
  dialect-induction worklist (KPI).
- P1 [DONE 2026-06-19] Rate-grammar schema + deterministic apply on Antares. Shipped
  `pipeline/identifier_rate.py` + `tests/test_identifier_rate.py` (9 pass) +
  hand-authored grammar `data/overrides/identifier_rate_grammars/0001993402.json`
  (schema `agentA-rate-grammar.v1`, sibling store for isolation). `python -m
  pipeline.identifier_rate` parses the 6,579 debt-signature rows and stages a
  provenance-tagged overlay (`data/output/agent_a/identifier_rate_overlay_0001993402.csv`).
  EXIT MET: parse-completeness 97.5%; FV preserved exactly (delta $0.00 on $22.5B);
  cross-twin agreement of decided rows -- all_in 97.4%, spread 98.7%, pik 99.2%,
  maturity 98.9%, floating_has_reference 100% (0 fail -> invented-LIBOR guard holds).
  The ~2.6% all_in failures verified as REAL string-vs-XBRL disagreements (parser
  extracts the string value correctly; twin differs), correctly FLAGGED not overwritten.
  NOTE: Antares states ALL-IN incl PIK (cash = all_in - pik), the inverse of MidCap's
  additive "cash + pik" -- `pik_convention` is a per-CIK grammar field. No production
  merge. PIK twin is sparse (124 decided of 6,579) -> pik validation is thin where the
  string is the only source (the unanchored-field caveat in practice).
- P2 [DEMONSTRATED 2026-06-19 on MidCap; Bain/Crescent pending] Agent A2 pilot. Shipped
  the skill `.claude/skills/identifier-grammar/SKILL.md`, the bundle sampler
  `scripts/agent_a/sample_variant.py`, per-CIK anchor store + `load_anchors` in
  identifier_signature, and engine extensions in identifier_rate (additive `pik_convention`,
  `bps` spread, `sum_identity` invariant). Ran the full loop on MidCap (1278752): built the
  bounded bundle -> sandboxed induction agent (Claude-subagent stand-in for Codex, per B)
  authored `identifier_anchors/1278752.json` + `identifier_rate_grammars/1278752.json` ->
  A3 gate. RESULT: the gate CAUGHT a real defect (agent over-required `pik_rate` ->
  parse-completeness 5.1%); one-line localized fix (PIK is optional on floating loans) ->
  97.9%. Dominant variant (SECDEBT REFRATE RATE MAT, 4,974 rows, $31.2B) then gates clean:
  completeness 97.9%, FV preserved exactly, spread_vs_twin 98.9%, pik 97.7%, maturity 99.3%,
  floating_has_reference 100%. (none)-share dropped 30.9% -> 17.5% (EQUITY anchor caught the
  equity rows; CLO/other instrument types remain -> iterative, NOT yet at Antares's 1.9%).
  sum_identity correctly inert on floating; passes on the 9 fixed-total "cash plus PIK" rows
  (small-N in current MidCap data). After an anchor iteration (added CASH for money-market/
  government funds + broadened AFFIL to the "controlled investments" space form + STRUCTURED),
  MidCap none 30.9 -> 16.0%; the residual is genuinely SPARSE issuer+industry-only rows (no
  instrument/rate/maturity tokens), a data property not a vocab gap -- stopped iterating.
  Bain (1655050) and Crescent (1633336) induced via the SAME loop (parallel sandboxed agents),
  both gate GREEN: Bain none 15.6 -> 0.3%, completeness 99.5%, all_in 97.9 / spread 99.0 /
  pik 99.5 / maturity 99.4 / floating_has_reference 99.9%, FV preserved; Crescent (hardest --
  was a degenerate "RATE"-only signature) none 21.7 -> 1.1%, dominant now
  "DEBT INVTYPE REFRATE RATE MAT" 59.6%, completeness 99.9%, all_in 99.0 / spread 95.0 /
  pik 90.0 / floating_has_reference 100%, FV preserved (maturity mm/yyyy -> text-only, agent
  correctly declined to fabricate a day). pik_convention varied per filer (MidCap additive,
  Bain+Crescent inclusive) -- confirms the per-CIK convention design. The gate caught the
  MidCap required_fields defect; Bain/Crescent agents pre-applied that lesson. Held-out-quarter
  (cross-quarter) check still pending for all three.
- P3 [STAGED, NOT MERGED 2026-06-19] Provenance overlay + impact diff on the 4 gated filers.
  Shipped `pipeline/identifier_overlay.py` + tests (4 pass). Blank-only/no-clobber merge logic
  (the same the staging_bdc iXBRL/HTML-bridge overlays use): fill blanks, confirm agreements,
  flag conflicts (never overwrite), bucket format-incompatible values as not_mergeable. Ran as
  a STAGED diff (no merge; production bdc_holdings/unified untouched), artifacts under
  data/output/agent_a/p3_staged_*. MEASURED over 19,273 gated rows:
  * reference_rate_type FILL 19,242 rows / $89.5B (native ~0% -> A fills ~all; 0 conflicts).
  * coupon_type contributed on all 19,273 rows; interest_rate_cash_leg on ~14.2K.
  * basis_spread/interest_rate/maturity are mostly CONFIRM (A corroborates existing twins);
    real conflicts only 834 rows (genuine string-vs-twin disagreements incl. MidCap mis-bins)
    -> flag artifact, not overwritten.
  * MEASURE-FIRST CATCH: Crescent maturity is mm/yyyy text (no day) vs ISO month-end twin ->
    4,957 rows NOT date-mergeable; a blind merge would have polluted maturity_date. Excluded.
  Remaining before merge: human gold slice (truth, not twin); decide merge scope (exclude
  Crescent maturity; store as maturity_text provenance if wanted); then wire into staging_bdc.
- P3-scale Scale induction to the ~30-40 flattened cohort; format contracts -> shadow ledger
  -> B. Pending the merge decision above.

## 8. Contracts / risks

- Cache-only, read-only on production artifacts, append-only to A's own dir; ASCII logs;
  no rebuild during agent runs; per-CIK config (global only on cross-CIK evidence + full
  regression), per B-spec Decision 1.
- Highest blast radius of the three agents (generative over the bulk, at the SOURCE), so
  the STRONGEST gate -- never weaker than B. The deterministic-proposes/agent-disposes
  inversion + the section-4 gate are what make it safe; do not let A write production
  fields without A3 green.
- Main risk: the signature normalizer (A0) is where value/risk concentrate -- a naive
  signature re-creates the haystack. Treat A0 as the load-bearing deterministic build,
  not plumbing.
- Encoding mojibake in source identifiers (e.g. Crescent "Investment<mojibake>Type") must
  be normalized in the signature/anchor matching, not crash it.

## 9. Open decisions

1. Signature granularity for the variant key: family-level (coarse, ~4/filer) vs full
   keyword-signature (finer, ~23/filer). Recommend family-level for grammar authoring,
   full signature for drift detection.
2. Does `rate_grammar` live in the existing wrapper file or a sibling
   `identifier_rate/<cik>.json`? Recommend same file (one per-CIK source of truth) with
   a new top-level block + schema version bump.
3. Delimited regime: confirm A is a no-op there (rates structural) or a thin validator
   only. Likely no grammar authoring needed; just the cross-twin check.
