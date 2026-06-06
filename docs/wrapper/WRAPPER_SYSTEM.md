# Wrapper Generation & Maintenance — Engineering Brief

**Audience:** Claude Code, with repo access.
**Status:** architecture spec + build order. Implement in the sequence given; do not skip the foundation work.
**Domain:** structured extraction + normalization of schedule-of-investments data from fund filings (N-2 / N-CSR / BDC), where source is HTML and, where available, iXBRL.

---

## 0. The one idea this whole system rests on

A **wrapper** is a per-source (per-CIK, per-statement-type) **deterministic, versioned program** that maps one filer's idiosyncratic layout into clean structured records. It is written and repaired by an **LLM agent at the edges** (new filer, or detected drift) and **executed by frozen code in the middle** (per row).

The two-speed split is non-negotiable:

- **Hot path (per row, millions/qtr):** deterministic, frozen, fully traceable. **No LLM here, ever.**
- **Edge (per new-CIK or per drift-flag, rare):** the agent generates or repairs a wrapper, gated by deterministic verifiers before anything is committed.

Everything below serves that split. If a design choice reintroduces an LLM into the per-row path, or lets the agent self-certify, it is wrong.

---

## 1. Non-negotiable invariants (enforce in code, not by convention)

1. **Traceability.** Every emitted value carries provenance `{table, col, row}` and the verbatim source string. Extraction is **as-is** — the raw composite cell (`ABC Corp | First Lien | 2%`) is stored exactly as filed; parsing happens *downstream* of the stored raw value, never destructively.
2. **Determinism on the hot path.** Given a frozen wrapper version + an input cell, output is a pure function. Same input ⇒ same output, no model call.
3. **The agent is never its own judge.** A candidate wrapper is accepted **only** when deterministic oracles pass. Acceptance criterion, literally:
   ```
   commit ⟸ reconciliation.pass ∧ content_signatures.pass ∧ remainder ≈ 0
   # NOT model confidence, NOT agent self-assessment
   ```
4. **Wrappers are versioned and diffable.** Every change is a versioned delta (`v3 → v4`) with a human-readable diff. Never silently overwrite a working rule.
5. **Derived truth outranks labeled truth.** Arithmetic invariants are the primary ground truth. Human labels are demoted to fields invariants can't reach — and even there, treated as noisy (see §2).

---

## 2. BUILD STEP 1 — The oracle layer (do this first; the gold set is suspect)

> The gold set is not assumed golden. The first deliverable is the thing that lets us *audit* it. This is also the verification backbone the rest of the system needs, so it is not throwaway work.

### 2.1 Invariant layer (derived truth — free, filer-independent, incorruptible)
Implement as standalone checks that take a parsed filing and return per-check pass/fail + residual:
- `sum_holding_fv == fund_level_fv` (within tolerance)
- `holding_count` within a QoQ band vs prior quarter (no implausible doubling/halving)
- `scale == xbrl_scale_anchor` (thousands/millions resolved by reconciliation against a trusted total, **not** by magnitude prior or LLM guess)
- subtotal/total rows identified by **arithmetic**: a row whose value equals the sum of its leaf children is a subtotal by definition
- allocation/fee internal consistency where applicable (targets ~100%, leverage within regulatory cap)

### 2.2 Audit the existing gold set with §2.1
Run the invariant layer **against the current gold set itself**, not against extractions. Any gold filing whose own holdings don't reconcile to its own stated fund FV is **corrupt gold** — flag it. This grades the foundation mechanically, with zero new human labeling.

### 2.3 Re-grade gold; measure the real ceiling
- Partition fields into **reconcilable/typed** (objectively checkable) vs **judgment** (issuer name, lien class — intrinsically ambiguous).
- For judgment fields, **dual-annotate a sample** and measure inter-annotator disagreement. That disagreement rate **is the accuracy ceiling.** "100% on lien" is fiction if two analysts disagree 10% of the time.
- Expectation to validate: a meaningful chunk of historical "extraction error" is gold noise + genuine ambiguity, i.e. the extractor is likely better than the headline metric claimed, and the true residual is mostly **confidence-routing territory, not rule-quality territory.**

**Deliverable of Step 1:** a verification module reusable as (a) gold auditor, (b) onboarding validator, (c) drift detector, plus a graded gold set with a measured per-field ceiling.

---

## 3. BUILD STEP 2 — The DSL (let one real filer dictate it)

A **DSL program** = a wrapper written in a small, purpose-built declarative language, **not** arbitrary code. The DSL must express only legitimate wrapper operations; the agent fills in this grammar and cannot emit free-form per-row logic.

Why constrained: a narrow language is parseable, diffable, validatable, and makes two independent agent runs **converge** on the same rule (kills the "two different both-pass wrappers" jitter). It's also what makes synthesis tractable (FlashExtract/PROSE lesson: synthesis is feasible because the space is a small DSL, not all of Python).

**Do not design the DSL in the abstract.** Build a vertical slice for ONE real CIK + ONE quarter end to end first, and let that filer dictate the operators the DSL must support. Add operators only as real filers demand them.

Target shape (declarative, illustrative — refine against the real slice):
```yaml
cik: 12345678
statement: "schedule_of_investments"
version: 4
dispatch:                       # route each row to ONE instrument type
  by: [has_coupon, has_maturity, pik_marker, equity_vocab]
rules:
  debt_term_loan:
    delimiter: "|"
    map: { 1: issuer, 2: instrument_subtype, 3: lien, 4: rate }
    signatures:
      issuer: "^[A-Z][\\w .,&-]+ (Corp|Inc|LLC|LP)$"
      lien:   "∈ {First Lien, Second Lien, Senior Secured, Unsecured}"
      rate:   "%|L\\+\\d+|SOFR\\+\\d+|PIK"
  common_equity: { map: {...}, signatures: {...} }   # own rule + own signatures
  preferred:     { map: {...}, signatures: {...} }
  mezz_pik:      { map: {...}, signatures: {...} }
invariants: [ sum_fv_eq_fund_fv, count_qoq_band, scale_eq_xbrl ]
provenance: per-value {table, col, row}              # as-is audit trail
```

### 3.1 Hierarchical dispatch (handles heterogeneous instruments)
Instrument type is a **bounded set (~5–8 archetypes)**, not an unbounded per-row zoo. Route each row to its type first (cheap, highly verifiable: equity has no coupon/maturity, debt does, PIK has markers, preferred has its own vocab), **then** apply the type-specific split. Each typed sub-rule carries **its own content signature**, so one type's parsing can drift and be repaired in isolation without disturbing the others.

### 3.2 Mandatory `unparsed_remainder`
Every split rule must emit an explicit `unparsed_remainder`. Nothing is silently dropped. A global spike in remainder is itself a drift signal and catches cases the signatures miss.

### 3.3 Structure reconstruction (prerequisite, do not assume tables survive)
Subtotal-by-arithmetic and scale-by-reconciliation presuppose recovered row/col/group geometry. Reconstruct from **deterministic coordinates back onto the source HTML/DOM**, geometrically (x–y alignment, rendered indentation), because filing HTML is frequently pseudo-tabular (whitespace/colspan hacks, not real `<table>` semantics). How a given filer fakes its tables is **stable within that filer**, so layout interpretation is itself a CIK-scoped, QoQ-stable learned component — fold it into the same wrapper/caching machinery.

---

## 4. The two verifiers — ORTHOGONAL, both run with no fresh gold set

This is the crux of correctness. Implement **both**; they cover each other's blind spots.

| | **Content signatures** | **Reconciliation backbone** |
|---|---|---|
| Guards | descriptor fields (issuer/lien/rate) | numbers & their relationships |
| Mechanism | per-field value-distribution fit vs learned signature | arithmetic invariants (§2.1) |
| Blind spot | a same-type substitution that still reconciles | any descriptor shift that doesn't move totals |
| Catches the other's blind spot? | yes | yes |

**Worked drift case** (the canonical test — build a fixture for it):
Filer inserts a segment: `ABC Corp | First Lien | 2%` → `ABC Corp | Debt | First Lien | 2%`. Frozen v3 keeps map `{1→issuer, 2→lien, 3→rate}`:
- `Debt` → lien field (off-vocab → signature flag)
- `First Lien` → rate field (alphabetic where numeric expected → **type-flip, loudest flag**)
- `2%` → overflow → `unparsed_remainder` spike
- **Reconciliation stays fully GREEN** — Σ FV unchanged, count stable, scale matches — while two fields are wrong on every row.

The first diverging field (`rate`) **localizes** the break to the inserted segment at position 2. This is why content signatures are not redundant with reconciliation: reconciliation would never catch this.

**Verification runs with no new gold** because the learned content signatures double as a **labeling oracle** during repair (§5).

---

## 5. BUILD STEP 3 — The agent edge (induction & repair only)

The agent occupies exactly the **inductor** slot (the thing that *writes* the wrapper), never the executor slot. Same architectural position as STALKER's symbolic search / PROSE's version-space algebra, with a richer hypothesis space.

### 5.1 Loop (PBE propose→run→inspect→revise; reward = oracles)
```
READ      QoQ diff + failing rows + learned signatures (signatures double as labeling oracle)
LOCALIZE  first diverging field ⇒ which segment broke / was inserted
PROPOSE Δ minimal delta to the cached wrapper — NOT regeneration
RE-VERIFY run BOTH verifiers on the candidate; all green ⇒ version, freeze, promote
```

### 5.2 Agent fires on exactly three triggers (and no other time)
1. **Cold start** — first time a CIK is seen.
2. **Structural divergence** — this quarter's column profile diverges from the cached CIK grammar (catches silent drift that reconciles).
3. **Validation failure** — an invariant or signature flag trips.

Do **not** run the agent proactively on every column — that multiplies cost and gives the agent chances to break things that were fine.

### 5.3 Containing agent-induced non-determinism
Using an agent as inductor risks jitter in the *rules themselves* (two runs ⇒ two different both-pass wrappers). Contain it:
- emit into the **constrained DSL**, not free-form code
- **prefer minimal-delta repair** over regeneration (also keeps the agent's edit context small and prevents it editing the wrong sub-rule)
- a **simplicity/generalization preference** so independent runs converge
- **freeze + version** once accepted
- gate high-value / low-confidence wrappers behind human review before promotion

### 5.4 Hard boundaries
- **Never** on the per-row hot path.
- **Never** its own production verifier.
- Direct per-instance data parsing by the agent is allowed **only** as the bottom escalation tier for a genuinely novel residual — output flagged low-confidence and routed to review, **never silently merged.**

---

## 6. Scoping: CIK, not CIK-quarter

Scope the ruleset to the **CIK**, versioned. A filer's Q+1 is mostly identical to Q. Re-deriving rules per quarter injects **pipeline-origin jitter** that then trips your own QoQ continuity checks for artifactual reasons. Per quarter, generate only **deltas** against the cached grammar when the quarter actually diverges. You still *process* CIK-quarter by CIK-quarter; you don't *rebuild* per quarter.

**Keep two things distinct:**
- **Global validation invariants** (FV reconciliation, coupon ranges, QoQ continuity) — permanent domain truths, run **always**, on every CIK-quarter. The backbone.
- **Global parsing priors** — cold-start defaults that get **specialized away** per filer.

"Global rules on first filing only" is correct for parsing priors and **wrong** for validation invariants. Per-CIK specialization must never erode the invariant backbone.

---

## 7. Onboarding a new CIK (minimize human involvement)

The agent **specializes the global wrapper**, it does not induce from scratch. Onboarding question is narrow: *what minimal specialization makes this filer's output pass the oracles?*

**Self-supervision via triangulation** (no labels):
1. Run global wrapper + invariants on the new filing.
2. Rows that **reconcile arithmetically AND match global signatures AND agree across HTML/XBRL channels** are **multiply-confirmed** → this CIK's **bootstrap gold**, earned by independent agreement.
3. Learn filer-**specific** content signatures from those confirmed rows.
4. Agent loop (§5.1) closes the gap on unconfirmed rows until oracles pass.

**Human attention only on the residual:** channel disagreements, rows the agent can't get green, and genuinely novel structure (new instrument archetype / field type ⇒ schema or DSL extension needing human ratification).

**Coverage gating:** quantify onboarding coverage = fraction of rows reaching multiply-confirmed status. A new wrapper stays **provisional** until coverage clears a threshold; its first quarter carries elevated review by default. That review both catches errors and **enriches bootstrap gold**, so quarter two is cheaper — cold-start cost amortizes, doesn't recur.

**Compounding:** each onboarded CIK enriches global signatures, adds DSL operators, contributes transferable archetypes. Marginal onboarding cost **decays** with scale (the inverse of human-template incumbents, whose per-filer cost is flat).

**Honest boundary:** a filer with thin holding-level XBRL and no clean fund-level total gives triangulation too few independent channels. Correct behavior = report low confidence, route a large review queue. **Never emit an unvalidated wrapper that merely runs.**

---

## 8. Rule sprawl: factor, don't shrink

A big wrapper is fine if it's big because the filer is genuinely heterogeneous (honest compressed encoding of real complexity). It's a problem only when big from **un-factored duplication**.

- The wrapper is **data, not linear code**: dispatch selects one small sub-rule per row, so the **active program is tiny** regardless of total size. Cost scales with the matched rule, not the file.
- **Hunt accidental duplication:** near-duplicate sub-rules ⇒ factor shared structure, parameterize a default, let types inherit + override.
- **Promotion path:** a CIK-specific rule that recurs across many filers should **graduate to global**. Conditional generation (§5.2) plus dedup/precedence/expiry keeps the corpus from exploding.
- Large wrappers are survivable **only because nobody hand-edits them**: signatures verify each sub-rule independently, drift localizes to one sub-rule, agent repairs in isolation. Keep the DSL **legible** so promotion diffs are human-reviewable.

**Where size genuinely bites:** (a) the **dispatch/router** — a misroute is silent and worse than a slightly-off split; keep the router simple, conservative, ambiguous⇒flag. (b) **Induction context** — argues for minimal-delta repair + factoring so the agent reasons over one sub-rule + shared defaults. (c) **Reviewer auditability** — argues for legible, factored DSL.

---

## 9. XBRL: anchor/validation channel, not primary feed

XBRL gives machine-readability of the filer's *presentation*, **not** normalized semantics — which is why bulk XBRL is "just as bad." Two failure modes survive tagging: **shallow holding-level tagging** (nothing to map ⇒ fall back to HTML) and **packed values** (`ABC Corp / First Lien / L+550 / 2026` in one tagged fact ⇒ same composite-parse problem, just on a tagged string).

- As an **extraction** channel for holding detail: unreliable (tagging depth varies wildly across filers).
- As an **anchor/validation** channel: excellent (fund-level totals + explicit `scale` attribute are tagged consistently and authoritatively).

Architecture is **one wrapper per source, multiple input channels** — draw on whichever channel carries the semantics for a given field, anchored by the channel that carries the invariants. Stop framing it as "XBRL vs HTML extraction."

---

## 10. Recommended build order (summary)

1. **Oracle layer** (§2): invariant checks → audit existing gold → re-grade gold → measure per-field ceiling via dual annotation.
2. **Vertical slice** (§3): one CIK, one quarter, end-to-end. Let it dictate the DSL.
3. **Two verifiers** (§4): content signatures + reconciliation, with the canonical drift fixture (§4 worked case) as a regression test.
4. **Agent edge** (§5): cold-start induction + minimal-delta repair, oracle-gated, DSL-constrained, versioned.
5. **Generalize horizontally:** +1 CIK (tests dispatch/invariant generalization), then +1 quarter on CIK #1 (tests drift → verify → reinduce against a real format change).
6. **Onboarding pipeline** (§7) + sprawl management (§8) once ≥ a handful of filers are live.

Each step adds exactly one new source of difficulty, so failures are attributable.

---

## 11. Gate every architectural change behind the experiment harness

Changes like CIK-scoped-delta vs global-first, or proactive vs triggered specialization, have real failure modes. **A/B them** on: flag rate, review-queue size, and held-out (re-graded) ground-truth accuracy. "Tighter" must be a number before commit. Use the existing experiment framework.

---

## 12. Anti-patterns (reject on sight)

- LLM call on the per-row path.
- Agent accepting its own output without oracle pass.
- Trusting model confidence as the routing signal (use calibrated confidence: ensemble agreement + grounding + held-out validation, mapped to a true error rate).
- Destructive parsing that loses the verbatim raw value / provenance.
- Re-inducing a whole wrapper when a minimal delta would do.
- Treating the gold set as ground truth on judgment fields without measuring annotator disagreement.
- Designing the DSL before a real filer has exercised it.
- Emitting a wrapper for a filer triangulation couldn't confirm, instead of flagging low confidence.
- Grounding-validates-presence mistaken for grounding-validates-field-assignment (a correct value can be grounded yet assigned to the wrong field — use cross-field business-logic checks).

---

## 13. Lineage (for context when reasoning about design)

This is **wrapper induction + wrapper maintenance**, modernized:
- per-CIK learned grammar = wrapper induction (one wrapper per source)
- validation metrics + QoQ checks = wrapper **verification**
- agent generating candidate rules on a flag = wrapper **reinduction/repair**
- sector→industry→issuer→tranche tree = STALKER's hierarchical (embedded-catalog) decomposition

Novel recombination here: the inductor is an **LLM agent** (not symbolic search), the verifier is **arithmetic reconciliation** (a far stronger drift signal than the content-pattern heuristics in the classic maintenance literature), pointed at over-determined financial tables. The generation step is best expressed as **program-synthesis-by-example into a DSL** (FlashExtract/PROSE descendant) so emitted rules are deterministic and verifiable.

Key references if deeper reasoning is needed: Lerman/Minton/Knoblock, *Wrapper Maintenance* (JAIR 2003) — the verification/reinduction tradeoffs; Muslea/Minton/Knoblock, *Hierarchical Wrapper Induction* (2001) — the dispatch tree; Le/Gulwani, *FlashExtract* (2014) — synthesis into a DSL.
