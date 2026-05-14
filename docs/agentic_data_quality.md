# Agentic Data Quality System

## The Problem

The pipeline transforms SEC XBRL filings from 191 BDCs and 158 interval/tender funds into a unified holdings dataset (690K+ rows) that powers privatemarketwatch.com. Each filer has its own XBRL conventions: different dimension hierarchies, identifier formats, rate scales, and subtotal structures. A single set of programmatic transformation rules cannot anticipate every variation.

Today, when a new quarter arrives:

1. The pipeline runs `--unified --validate` and produces 10 validation reports.
2. A human (or Claude Code instance) scans the reports for flagged CIK-quarters.
3. For each failure, the human investigates the raw data, identifies the root cause, and applies a fix — usually adding a keyword to a filter list, sometimes adding a structural transformation step.
4. The human re-runs validation to confirm the fix worked and didn't regress other CIKs.
5. Repeat until all CIK-quarters pass.

This loop has been executed manually at least 5 times in the past 5 weeks. Each cycle adds patterns to a growing list (97 substring patterns, 50 exact matches, 100+ industry labels) that increases false-positive risk and makes the global rules harder to maintain. Structural fixes — adding new SQL CTEs, new dedup mechanisms, new classification rules — require modifying production Python code.

### Empirical observation: rules-only detection does not converge

A directly tested alternative — building a comprehensive set of consistency rules and reviewing only the funds that fail any rule — was attempted over a week of effort. The result: rule count ballooned into the hundreds, and per-CIK review continued to surface real issues that no rule had caught. This confirms a long-tail hypothesis: errors do not cluster into a small number of patterns that a manageable rule set can cover. Each filer has idiosyncratic problems that don't recur often enough to justify a global rule but are real errors when examined directly.

This finding is consistent with published benchmarks: cross-entity financial extraction shows accuracy drops of 14-19% relative to single-document tasks, driven by comparison hallucinations and entity mismatches. Rule sets struggle with exactly the cases where filer-specific conventions diverge.

### What goes wrong: real examples

**Subtotal leakage.** CIK 0001959568 reported a GAV ratio of 0.4x. Investigation revealed that rows like `"Senior Secured First Lien Term Loans"` (a category header, not a company) survived the aggregate filter because the pattern didn't match any existing keyword and lacked the word "total." These rows had large fair values ($500M+) that inflated the denominator without representing real positions.

**Affiliation-axis duplication.** CIK 0001959568 and 11 other BDCs tag the same position under multiple XBRL dimension paths (e.g., "Non-Controlled/Non-Affiliated" and "Investments"). This produces 2-3 copies of each position with identical fair value, pushing pct_of_net_assets sums to 200-5000%. The fix required a new CTE (affiliation-axis dedup) and a new post-processing step (pct correction using consolidated net_assets from fund_financials).

**Identifier format variation.** BDCs use at least 5 pipe-delimited formats and 3 dash-delimited formats for their investment identifiers. A single CIK uses one format consistently, but a universal parser must detect which format is in use and route to the correct extraction logic. New CIKs occasionally introduce formats that don't match any existing variant.

**Source field unreliability.** N-PORT's `issuer_type` field maps `NUSS` (Non-US Sovereign) to GOVERNMENT, but ~360 of 411 NUSS-tagged positions are actually corporate loans (filer mis-tagged). The fix was name-gating: only classify as GOVERNMENT when the issuer name contains explicit government keywords. Similarly, any entity with an `L.P.` suffix was initially reclassified as a FUND, but many L.P. entities are SPVs holding direct lending positions. The fix required co-keyword gating.

**Rate scale ambiguity.** BDC XBRL rates arrive in three scales: decimal (0.1025 = 10.25%), percentage (10.25), or basis points (1025). Rates between 0.50 and 1.0 are genuinely ambiguous — a 0.75% rate and a 75% decimal rate produce the same raw value.

**Fund-level taxonomy errors.** CIK 0001803958 (KKR Real Estate Select Trust Inc.) had its holdings classified as private equity, despite the fund's own prospectus describing it as investing primarily in commercial real estate. No holdings-level rule catches this because the fund's holdings are internally consistent — they're just inheriting the wrong fund-level bucket. This is a different class of error than subtotal leakage and requires a separate validation layer.

### Why universal rules hit a ceiling

Each fix to the global transformation rules carries risk:

- **Keyword saturation.** The aggregate filter's 97 patterns already require an entity-signal guard to prevent false positives. Each new pattern adds interaction risk with existing rules.
- **Cross-CIK interference.** A pattern added for one CIK's subtotals may filter out a real company name in another CIK (e.g., `"Total Safety Holdings LLC"` vs. `"Total Senior Secured"`).
- **Structural changes affect all data.** Adding a new CTE or classification rule retroactively changes the output for all 191 BDCs, not just the one being fixed.
- **Diminishing returns.** The first 20 aggregate patterns caught 90% of subtotals. The next 77 patterns catch the remaining 10%, each targeting 1-3 CIKs.
- **Detection rules face the same saturation.** Adding hundreds of consistency rules to flag anomalies replicates the original problem in a different file: false positive management, cross-rule interaction, and a long tail that never quite closes.

---

## The Proposed Solution

### Constrained agent within a deterministic pipeline

Instead of an autonomous reviewer, the system uses a constrained agent as a subroutine inside a deterministic pipeline. The agent has an open action space (add filter words, tag investees, write exploratory Python, modify per-CIK corrections) but operates under three constraints:

1. **A defined success criterion.** Schema-compliant output that passes all validation gates.
2. **Validation rules grounded in independent reference data.** The agent cannot satisfy these rules by manipulating its own output — they require the underlying data to actually be right.
3. **Bounded scope.** Each agent invocation is per-CIK; corrections are scoped to that CIK and cannot affect other CIKs.

This framing matters because it shifts the question from "is the agent capable enough?" to "are the validation rules sufficient as a success signal?" The latter is a tractable engineering question with explicit controls.

### Three-layer architecture

```
Layer 1: Global deterministic transformation rules (pipeline code)
  - Universal patterns (empty identifiers, [member] tags, LOAN+CORPORATE = DIRECT_LENDING)
  - ~20 aggregate patterns that apply to all filers
  - Standard rate normalization, dedup, classification

Layer 2: Per-CIK corrections (JSON configuration)
  - Filer-specific subtotal patterns
  - Identifier format configuration
  - Row-level corrections (duplicate tagging, industry population, classification overrides)
  - Rate scale specification
  - Validated against source filings

Layer 3: Fund-level metadata and overrides (JSON configuration)
  - Strategy classification (RE, PC, PE, Diversified, etc.)
  - N-CEN sub-classification reconciliation
  - Parent/subsidiary relationships
  - Share class consolidation
  - Peer group assignment
```

The global rules shrink to genuinely universal patterns. Filer-specific patterns move to per-CIK corrections where they cannot interfere with other CIKs. Fund-level taxonomy lives at Layer 3 with its own source of truth (N-CEN, prospectus language).

Cross-layer validation rules tie the three layers together: e.g., "if `fund.strategy = REAL_ESTATE`, expect >50% of holdings to be RE-classified instruments." These cross-layer checks are what catch the KKR REIT class of error that no single-layer rule can detect.

---

## Validation as the Primary Defense

The agent's open action space creates reward hacking risk: an agent that can add filter words, override classifications, and write Python can satisfy weak rules without producing correct data. The single most important investment is making the validation rules robust enough that "rules pass" actually means "data is correct."

Robust rules share one property: **they reference data the agent did not generate.** Rules that check the agent's output against fixed external anchors are not hackable. Rules that check the agent's output for internal properties are.

### Source reconciliation (the bedrock)

For each CIK-quarter, mechanically compare the pipeline output against the cached XBRL source filing. The agent cannot change the source. This is the single highest-value rule.

```
Source Reconciliation: CIK 0001959568, 2025-12-31
  Source XBRL facts (investmentidentifieraxis members): 142
  Pipeline output rows: 147
  Matched (by raw identifier): 139
  Missing from pipeline: 3
    - "Acme Corp - Revolver" (FV: $2.1M) -- filtered by aggregate pattern (false positive)
    - "Beta Inc - Delayed Draw" (FV: $0) -- filtered by zero-FV artifact check
    - "Gamma LLC - Equity" (FV: $500K) -- no match found
  Extra in pipeline: 8
    - "Senior Secured First Lien Term Loans" (FV: $890M) -- subtotal, no source match
    - [7 more]
  Value mismatches: 2
```

This is fully deterministic. It reads the cached XBRL instance document, extracts every `investmentidentifieraxis` member with its fair value, cost, rate, and principal, and diffs against the pipeline output. No judgment required.

The reconciliation answers:
- **Completeness:** Are all source positions present in the pipeline output?
- **Accuracy:** Do the numeric values match?
- **Purity:** Are there rows in the pipeline output that don't correspond to real positions?

### Cross-layer consistency rules

These check internal coherence between Layers 1, 2, and 3. The agent cannot satisfy them by manipulating one layer alone:

- If `fund.strategy = REAL_ESTATE`, expect >50% of holdings to be RE-classified instruments
- If `fund.is_bdc = true`, expect direct lending or PE-style holdings, not REIT subsidiaries
- If `fund.strategy = CREDIT`, expect >70% of holdings to be debt instruments
- Holdings sum (Layer 1+2) must match N-CEN reported net assets (Layer 3 reference) within 10%
- Sector mix must roughly match prospectus-stated focus

These are the rules that catch the KKR REIT class of error. They require independent reference data (N-CEN, prospectus) that the agent does not author.

### Cross-quarter stability rules

Prior quarter outputs are locked in and serve as fixed reference. The agent's current-quarter output must reconcile against them:

- Position count change >40% QoQ flags
- Position-level matching: positions present last quarter should generally persist (allowing for legitimate sales)
- Strategy classification should never change QoQ without explicit override
- Specific holding's classification should not change QoQ unless the underlying instrument changed

This is one of the strongest constraints because it forces the system to converge over time rather than drift.

### Aggregate validation checks (existing 10 checks)

The pipeline already has 10 validation checks operating at the CIK-quarter level:

| # | Check | What it catches | Key metric |
|---|---|---|---|
| 1 | Spot-check sample | Classification errors in random sample | Visual review |
| 2 | Classification summary | CIKs with anomalous classification mix | `pct_unclassified > 50%` |
| 3 | Aggregate leak audit | Subtotals that survived the main filter | Keyword superset scan |
| 4 | Cross-source overlap | Same position in both BDC and N-PORT | Jaro-Winkler + FV proximity |
| 5 | Coverage | Holdings vs. universe completeness | `holdings_to_assets_ratio` |
| 6 | Classification cross-reference | Internal consistency across 3 classification axes | 10 rules, 0 disagreements = pass |
| 7 | GAV reconciliation | Holdings sum vs. reported investments | `gav_ratio_adjusted` in 0.8-1.2x |
| 8 | Pct-of-net-assets sum | BDC leverage sanity | `pct_sum` in 100-200% |
| 9 | Position count stability | QoQ count consistency | `count_fv_divergence` flag |
| 10 | Income yield consistency | Rate field sanity via fund income | `yield_ratio` in 0.5-2.5x |

GAV reconciliation (check 7) is particularly strong because it compares the pipeline's holdings sum against the fund's own reported `investments_at_fair_value` from independent SEC filings. The agent cannot satisfy this rule by adding filter words unless the data is genuinely correct.

### Rule strength hierarchy

Not all rules are equally robust. The hacking literature distinguishes:

**Strong (independent reference, hard to hack):**
- Source reconciliation against XBRL facts
- GAV reconciliation against N-CEN net assets
- Cross-quarter position matching
- Cross-layer fund/holdings consistency

**Moderate (reference internal but constrained):**
- Position count stability
- Classification cross-reference rules
- Yield consistency

**Weak (internal only, easier to hack):**
- "Pct sum is between 50% and 200%" — agent can scale proportionally
- "No position >50% of net assets" — agent can split a position
- "Industry populated >80%" — agent can fill with anything

**Design principle:** weight strong rules as gating; treat weak rules as flags requiring strong-rule corroboration.

---

## What the Agent Produces

For each assigned CIK, the agent produces a corrections file with mandatory evidence and mechanism documentation:

```json
{
  "cik": "0001959568",
  "entity_name": "Example Capital Corp",
  "last_reviewed": "2026-05-08",
  "last_reviewed_quarter": "2026Q1",

  "subtotal_patterns": [
    {
      "pattern": "senior secured first lien term loans",
      "mechanism": "category_header",
      "evidence": {
        "row_count": 1,
        "fair_value": 890000000,
        "entity_signals": [],
        "appears_in_quarters": ["2025Q4", "2026Q1"],
        "source_reconciliation": "no matching XBRL fact"
      },
      "confidence": "high"
    }
  ],

  "identifier_format": {
    "type": "dash",
    "delimiter": " - ",
    "issuer_segment": 0,
    "industry_segment": null,
    "instrument_segments": [1, 2]
  },

  "dedup": {
    "affiliation_axis": true,
    "mechanism": "duplicate_dimension_paths_identical_fv",
    "evidence": {
      "duplicate_pairs": 5,
      "fv_match_rate": "100%"
    }
  },

  "rate_scale": "decimal",

  "row_corrections": [
    {
      "report_date": "2025-12-31",
      "raw_identifier": "Total Safety Holdings LLC - Term Loan",
      "correction": "not_aggregate",
      "mechanism": "real_company_with_total_prefix",
      "evidence": {
        "entity_signal": "LLC",
        "appears_in_external_registries": true
      },
      "confidence": "high"
    }
  ]
}
```

Three things distinguish this from a simple corrections file:

**Mechanism field.** The agent must articulate *why* a correction works, not just that it does. "Adding a subtotal pattern because GAV improved" is insufficient. "Adding a subtotal pattern because the row has no entity signals and represents a category-label" is the required form. This prevents pattern-matched wrong fixes that happen to improve metrics for adjacent reasons.

**Evidence field.** Each correction must cite the specific data supporting the mechanism claim. This is auditable and makes confabulation harder — an agent cannot fabricate XBRL row counts or fair values without being caught.

**Confidence field.** Drives downstream review priority. Low-confidence corrections are sampled for human review at higher rates.

The pipeline applies global rules first, then per-CIK corrections as a final pass. Corrections survive pipeline re-runs, are auditable (JSON diffs), and are scoped to a single CIK.

---

## The Fund-Level Run

A separate agent operates on fund-level metadata, parallel to the holdings-level run.

### Why a separate run

Fund-level data has a different shape than holdings-level data:

- ~349 entities vs. 690K rows
- Strategy/structure changes are rare (once-in-a-lifetime, with SEC-filed amendments)
- Source of truth is prose (N-2 prospectus, N-CEN sub-classification fields), not XBRL
- One-time backfill plus thin quarterly delta, not a recurring quarterly loop

### Source of truth

N-CEN Item C.6 has machine-readable fund-type fields including BDC flag and sub-classification. This is the deterministic gate. The agent only earns its keep where N-CEN is ambiguous or where strategy nuance below the N-CEN buckets matters.

### Fund-level correction types

Fund-level corrections look like:

- `strategy` / `sub_strategy` overrides (the KKR REIT case)
- `excluded_subsidiary_ciks` (parent/sub deduplication, feeder funds)
- `share_class_consolidation` (multi-class funds reported as one entity)
- `inception_date` / `liquidation_date` overrides for stale or wrong N-CEN values
- `peer_group` assignment for comparison purposes

### Cross-run validation

The fund-level run produces outputs that feed cross-layer rules in the holdings-level run. This is where the symmetry pays off: classification disagreements between the two runs surface automatically.

---

## The Agentic Loop

### Agent assignment

Each failing CIK is assigned to an agent instance. The agent's goal: **produce schema-compliant output that passes all validation gates, documenting every decision with mechanism and evidence.**

### Tool access

The agent has:

- `reconcile(cik, quarter)` — source reconciliation diff
- `validate(cik, quarter)` — full aggregate validation suite
- `query_xbrl(cik, quarter, filter)` — read-only access to cached XBRL facts
- `query_filing_text(cik, filing_type)` — read-only access to filing prose
- `web_search` and `web_fetch` — for external evidence (sector lookup, prospectus retrieval)
- `write_correction(cik, correction)` — append to corrections file
- `run_python(code)` — exploratory data analysis (sandboxed, scoped to one CIK's data)
- `escalate(reason, evidence)` — exit path when no resolution found

### The loop

```
1. RUN SOURCE RECONCILIATION
   Tool: reconcile(cik, quarter)
   Returns: matched/missing/extra/mismatched rows

2. IF extra rows exist (subtotal leakage):
   - Examine the extra rows for entity signals, FV concentration, naming patterns
   - Document mechanism: "category_header" / "duplicate_dimension_path" / etc.
   - Add subtotal patterns or dedup config to corrections file with evidence
   - Re-run reconciliation to confirm

3. IF missing rows exist:
   - Determine cause: false-positive filtering? Zero-FV artifact filter?
   - Add row-level "not_aggregate" corrections for false positives
   - Re-run reconciliation

4. IF value mismatches exist:
   - Determine cause: dollar_unit? rate_scale? decimals normalization?
   - Add corrections with mechanism documentation
   - Re-run reconciliation

5. RUN AGGREGATE VALIDATION
   Tool: validate(cik, quarter)

6. IF any aggregate metric fails:
   - Investigate using strong rules first (cross-layer, cross-quarter)
   - Apply targeted corrections; re-validate

7. IF cross-layer rules disagree (fund strategy vs. holdings mix):
   - Check fund-level metadata (Layer 3); flag for fund-level run if needed
   - Apply classification overrides only with explicit prospectus or N-CEN evidence

8. REVIEW ENRICHMENT COLUMNS
   - Sample 20-50 rows
   - Check issuer_name, classification, industry
   - Add corrections for errors found

9. VALIDATE FINAL STATE
   All gates must pass:
     - Source reconciliation: 0 extra, 0 missing, 0 mismatched (or documented residual)
     - GAV ratio: 0.8-1.2x
     - Pct sum: 50-200%
     - Cross-layer consistency: passes
     - Cross-quarter stability: passes

10. PERSIST corrections file with audit trail

11. IF unable to resolve after N attempts:
    - escalate(reason, evidence) -- exit cleanly, do not force a fit
```

### Handling new quarters

**Case 1: Existing corrections still work.** The CIK's filing format hasn't changed. Validation passes. No agent intervention needed.

**Case 2: New issues emerge.** Validation flags the CIK. The agent is re-dispatched, sees the existing corrections file, and adds to it incrementally.

**Case 3: A new CIK appears.** The agent runs the full loop from step 1.

### Explicit failure as a first-class outcome

When the agent cannot resolve a failure, it must use the `escalate` exit, not force the rules to pass. This is a critical control: "failed gracefully with documented reason" is a better outcome than "passed gates by manipulation." The audit trail captures which CIKs failed and why, surfacing them for human review.

---

## Reward Hacking Mitigations

Open action space creates documented hacking risks at deployment time. The literature on in-context reward hacking shows that self-refinement loops produce subtle exploitation that only sampling reveals. Five controls address this:

### 1. Independent reference data in validation rules

Already covered above. The strongest protection. Source reconciliation against XBRL is unhackable by any agent action because the agent cannot edit the XBRL.

### 2. Binary success gates, not partial credit

Research on RL-based code generation finds that partial-credit rewards (e.g., "K of N tests passing") incentivize gaming. Binary all-or-nothing is more robust. The system uses "all gates pass for this CIK-quarter" as the success signal, not "validation score improved."

### 3. Mechanism documentation requirement

Every correction must specify the *category* of fix being applied and demonstrate the category fits. Adding a subtotal pattern requires showing the row has no entity signals. Enabling affiliation-axis dedup requires showing duplicate dimension paths with matching FV. "I improved the metric" is insufficient.

### 4. Evidence requirements with structured citations

Every correction must cite specific evidence (XBRL row counts, FV values, dimension paths, prospectus quotes) supporting the mechanism. This makes confabulation harder and creates a reviewable audit surface.

### 5. Sampling-based human review

Non-optional. The literature is unanimous that at-deployment self-refinement produces subtle failures invisible to rules alone. Specific protocol:

- 5-10% of all agent-authored corrections reviewed by hand each quarter
- 100% of classification overrides affecting >5% of a fund's portfolio reviewed
- Random sample stratified by confidence level (more low-confidence)
- Tracked metrics: false-correction rate, missed-correction rate, evidence quality score
- Threshold: if false-correction rate exceeds 2%, halt agent deployment and tighten rules

This is the layer that catches "coordinated correctness in the wrong direction" — cases where the agent finds a self-consistent wrong answer that satisfies all rules.

---

## Pattern Graduation with Evidence

Per-CIK corrections that prove general should graduate to global rules, but graduation requires evidence, not just frequency.

### Graduation protocol

1. **Discovery.** Pattern appears in CIK X's corrections file with documented mechanism.
2. **Replication.** Pattern appears in 10+ CIKs' corrections files over 2+ quarters.
3. **Evidence bundle.** Verifier replays the pattern as a global rule across all 191 BDCs.
4. **Regression check.** Verify no CIKs that previously passed now fail.
5. **Promotion.** Pattern moves from per-CIK corrections to global `_BDC_AGGREGATE_PATTERNS`. Per-CIK entries removed.
6. **Deprecation review.** After 1 quarter as a global rule, audit whether any new false positives emerged.

This is stricter than frequency-only graduation. The audited-skill-graph approach in recent agentic research uses verifier-backed evidence bundles for promotion decisions specifically to prevent shaky patterns from accumulating in the global layer.

### Code lifecycle policy

Agent-authored exploratory Python is a separate artifact class. Policy:

- **Exploratory scripts** are discarded after the agent extracts findings into the corrections file. They do not persist as pipeline code.
- **Per-CIK transformations** are expressed as corrections, not code. If a transformation cannot be expressed as a correction, escalate for human review of whether a new correction type is needed.
- **Cross-CIK transformations** are proposed as global pipeline changes via pull request, not auto-applied. Code-as-correction is the rare exception.

This prevents agent-authored code from accumulating as a permanent third category alongside global rules and per-CIK corrections.

---

## Audit Trail

Every agent decision is logged in the corrections file alongside the correction itself:

```json
{
  "audit_trail": [
    {
      "timestamp": "2026-05-08T14:30:00",
      "action": "add_subtotal_pattern",
      "pattern": "senior secured first lien term loans",
      "mechanism": "category_header",
      "evidence": {
        "row_count": 1,
        "fair_value": 890000000,
        "entity_signals": [],
        "appears_in_quarters": ["2025Q4", "2026Q1"],
        "source_reconciliation": "no matching XBRL fact"
      },
      "metrics_before": {"gav_ratio": 1.52, "pct_sum": 312},
      "metrics_after": {"gav_ratio": 1.21, "pct_sum": 245},
      "confidence": "high",
      "decision": "applied"
    },
    {
      "timestamp": "2026-05-08T14:35:00",
      "action": "skip_missing_row",
      "raw_identifier": "Gamma LLC - Equity Co-Invest",
      "mechanism": "dedup_kept_null_fv_path",
      "reason": "Affiliation-axis dedup retained control path with FV=NULL; non-affiliated path with FV=$500K dropped. Known limitation when dimension paths have different populated fields.",
      "decision": "accepted_residual",
      "impact": "$500K missing (0.03% of portfolio)"
    },
    {
      "timestamp": "2026-05-08T14:42:00",
      "action": "escalate",
      "reason": "Classification cross-reference rule fails on 23 rows. Hypothesized affiliation issue, tested, did not resolve. Hypothesized industry mapping issue, tested, did not resolve. No mechanism identified after 5 attempts.",
      "evidence": {
        "failed_rows_sample": ["..."],
        "attempts": [
          {"hypothesis": "affiliation", "result": "no improvement"},
          {"hypothesis": "industry_mapping", "result": "no improvement"}
        ]
      },
      "decision": "escalated"
    }
  ]
}
```

Note that escalation is itself a logged action. This makes "the agent gave up" a first-class, traceable outcome rather than a hidden failure.

---

## Sampling Discipline

Required protocol for human review:

### Random sample (catches general drift)

- 5% of all agent-authored corrections per quarter
- Stratified by confidence: 10% sample from low-confidence, 5% from medium, 2% from high

### Targeted sample (catches high-impact errors)

- 100% of classification overrides affecting >5% of a fund's portfolio
- 100% of fund-level strategy overrides
- 100% of new correction types not previously seen
- 100% of corrections in CIKs that account for >2% of total dataset value

### Tracking

A reviewer dashboard records, per agent decision:

- False fill: agent filled a field with a wrong value that passed rules
- Missed fill: agent left a field null when it could have been correctly filled
- Wrong mechanism: agent's stated mechanism didn't match the actual cause
- Evidence quality: cited evidence actually supports the value (binary)

### Action thresholds

- False-fill rate >2% in any quarter: halt deployment, tighten rules or restrict action space
- Wrong-mechanism rate >5%: revise mechanism taxonomy
- Persistent missed-fill in a category: extend agent capabilities or add new tool

---

## Public Site Considerations

privatemarketwatch.com is public-facing, which raises the bar above internal-pipeline standards. Three additional design elements:

### Provenance display

Each fund page shows: last reviewed timestamp, source filing reference, validation status, confidence tier. Users see the data is recent and traceable. Hiding ambiguity erodes trust faster than acknowledging it.

### Confidence tiers

- **Verified:** all validation gates pass, recent agent review, no open corrections
- **Preliminary:** validation passes but agent corrections recent and unsampled
- **Under review:** validation gates fail or agent escalated
- **Stale:** no recent quarterly update

Display the tier on each fund page. Filter UI lets users restrict to verified data.

### User error reporting

A "report an error" button on each fund page generates a structured ticket: CIK, field, expected value, evidence URL. Tickets feed directly into the corrections file format. This creates a free distributed QA layer and turns user disagreement into productive signal rather than complaint.

### Disagreement transparency

For classification fields specifically (strategy, sector, asset class), display the underlying signal alongside the assigned label: N-CEN sub-class value, prospectus language excerpt, holdings mix percentages. Users see *why* a fund is classified the way it is. Defensible-but-arguable classifications become productive conversations rather than "your data is wrong."

---

## Comparison: Current System vs. Proposed System

| Aspect | Current | Proposed |
|---|---|---|
| **Fix scope** | Global (all 191 CIKs affected) | Per-CIK (only target CIK affected) |
| **Fix mechanism** | Edit Python source code | Edit JSON corrections file |
| **Regression risk** | High (new pattern may filter real positions in other CIKs) | Low (corrections scoped to one CIK) |
| **Trigger** | Human scans validation CSVs | Automated: validation flags failing CIKs |
| **Detection layer** | Manual page-by-page review OR rule-only flagging | Constrained agent on residual after deterministic checks |
| **Continuity** | Each Claude session starts fresh | Corrections file persists prior work |
| **Audit trail** | Git commit messages + code comments | Structured JSON with mechanism, evidence, and metrics |
| **Validation** | 10 aggregate checks | Source reconciliation + cross-layer rules + cross-quarter rules + 10 aggregate checks + enrichment review |
| **Fund-level taxonomy** | Implicit, often wrong (e.g., KKR REIT) | Explicit Layer 3 with N-CEN reconciliation |
| **Reward hacking protection** | N/A | Independent rules + binary gates + mechanism docs + sampling |
| **Novel pattern discovery** | Human investigates raw data | Agent investigates with bounded action space, escalates if needed |
| **Pattern graduation** | Immediate global addition | Evidence-backed promotion after 10+ CIK replication |
| **New quarter cost** | 30-60 min per failing CIK, manual | Hierarchical: deterministic for stable CIKs, agent for residual |

---

## Implementation Path

### Phase 1: Source reconciliation tool

Build the mechanical diff between pipeline output and cached XBRL source. This is the highest-value tool because it answers "is the extraction correct?" without any judgment. Run it across all 191 BDCs as a one-time audit; expect 60-70% of remaining issues to fall into mechanical buckets that don't need an agent at all.

- Input: CIK, quarter
- Output: matched/missing/extra/mismatched rows with evidence
- Implementation: read cached XBRL from `data/raw/filings/bdc_xbrl/<CIK>/`, extract `investmentidentifieraxis` facts, match against pipeline output by raw identifier
- No LLM or agent required — purely deterministic

### Phase 2: Fund-level metadata table and Layer 3 infrastructure

- N-CEN Item C.6 ingestion for all 349 funds
- Strategy taxonomy with explicit override file format
- Cross-layer validation rule: strategy vs. holdings mix
- Manual override for known-wrong N-CEN values (with evidence)

This phase alone fixes the KKR REIT class of error.

### Phase 3: Per-CIK corrections infrastructure

- Define corrections JSON schema with mechanism, evidence, confidence fields
- Pipeline step that reads corrections files and applies them after global transformation rules
- Tests for corrections application and regression
- Initial backfill: convert existing per-CIK code branches into corrections format

### Phase 4: Cross-quarter stability and additional rules

- Position-level QoQ matching against locked-in prior outputs
- Strategy-level stability check
- Pct-of-net-assets reconciliation against N-CEN
- Yield consistency cross-checks

This rounds out the validation suite to the level of robustness needed before agent deployment.

### Phase 5: User-facing error reporting

Before deploying agents to production data, ship the user error reporting UX. This creates the feedback loop that catches agent errors that internal sampling misses.

### Phase 6: Agent skill (holdings-level)

- Skill prompt for per-CIK review loop
- Tool access: reconcile, validate, query_xbrl, query_filing_text, web_search, write_correction, run_python (sandboxed), escalate
- Mechanism taxonomy enforced via JSON schema
- Confidence calibration calibrated against initial human-reviewed sample
- Cost instrumentation from day one (tokens per CIK, runs per quarter, $ per CIK)

### Phase 7: Agent skill (fund-level)

- Parallel agent operating on Layer 3 metadata
- Cross-run validation rules

### Phase 8: Sampling discipline and dashboard

- Reviewer dashboard with stratified sampling
- False-fill / missed-fill / mechanism-correctness tracking
- Threshold-based deployment gates

### Phase 9: Pattern graduation

Periodic scan of corrections files identifying patterns that should graduate to global rules, with evidence-backed promotion protocol.

---

## Research Grounding

The architecture is consistent with published findings on agentic structured extraction.

**Verifier-guided iterative refinement** is the dominant successful pattern. Multi-agent decompositions with explicit extraction → validation → refinement loops outperform single-pass extraction across structured-output benchmarks (CycleIE, SCIR, TabAgent, AEC).

**Reward hacking is documented.** "LLMs gaming verifiers" and the Reward Hacking Benchmark catalog the specific failure modes that emerge when agents have tool access and self-verification. Mitigations in the literature align with the controls above: independent reference data, binary outcome rewards, mandatory evidence, mechanism documentation.

**In-context reward hacking is a deployment-time risk**, not just a training-time risk. Self-refinement loops where agents see feedback and adjust produce subtle exploitation that requires sampling to detect.

**Hierarchical orchestration is Pareto-optimal.** Empirical work on 10K SEC filings shows reflexive (always-agent) architectures achieve highest accuracy at 2.3x cost, while hierarchical architectures with selective escalation achieve 89% of the accuracy gains at 1.15x cost. This is the architecture proposed here: deterministic rules first, agent for the residual.

**Cross-entity tasks are the hard problem.** Fin-RATE benchmark documents 14-19% accuracy degradation as tasks shift from single-document to cross-entity reasoning, driven by comparison hallucinations and entity mismatches. This is the regime in which the BDC pipeline operates and explains why rule-only approaches saturate.

**Production validation evidence is thin.** The published literature documents architectural success on benchmarks but offers limited evidence on sustained production accuracy under distribution shift. This is why the system requires its own measurement discipline — false-fill rate, drift over quarters, cost per CIK — rather than relying on published numbers.

---

## Summary

The system is a constrained agent operating inside a deterministic pipeline, gated by validation rules grounded in independent reference data, with mandatory evidence and mechanism documentation, sampled human review, and explicit failure paths. The agent is a subroutine, not an autonomous reviewer. The validation rules — especially source reconciliation, cross-layer consistency, and cross-quarter stability — are the load-bearing protection against reward hacking; the agent is what handles the residual that rules alone cannot reach.

The empirical case for this design rests on three observations: that universal transformation rules saturate at ~80% coverage, that pure rule-based detection does not converge in practice (tested over a week of effort), and that fund-level taxonomy errors (KKR REIT class) require their own validation layer no holdings-level rule can substitute for. The architectural choices map onto current research findings on verifier-guided extraction, reward hacking mitigations, and Pareto-optimal hierarchical orchestration.
