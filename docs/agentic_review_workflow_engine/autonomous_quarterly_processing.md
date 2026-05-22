# Autonomous Quarterly Processing: Multi-Agent Rule Discovery and Data Enrichment

## Problem Statement

The pipeline currently requires extensive manual validation when processing a new quarter. Agents already produce classifications (GICS, aggregate header flags), review verdicts (fund-strategy corrections, FAIL verification), and spot-check labels (aggregate leak suspects). But every agent output still requires human re-validation before it can be accepted into the pipeline. The goal is a system of agents, each with its own deterministic harness and skills, that automatically iterates over new quarterly data -- creating global rules, CIK-specific rules, and enriched columns -- with human review required only at defined boundaries.

## Current Architecture Constraint

Most deterministic rules are hard-coded in Python source, not externalized into agent-modifiable data files.

| Rule type | Location | Agent-modifiable? |
|---|---|---|
| Asset classification keywords | `classification.py` (Python lists/sets) | No |
| Aggregate filter patterns | `bdc_identifier.py` (Python regex list) | No |
| Bad issuer name filters | `classification.py` (Python sets) | No |
| GICS classifications | `company_gics_cache.csv` | Yes |
| Aggregate header exclusions | `aggregate_header_flags.csv` | Yes |
| Row-level corrections | `data/overrides/row_corrections.csv` | Yes |
| Aggregate row overrides | `bdc_aggregate_row_overrides.json` | Yes (unused) |
| Per-CIK rules | **Does not exist** | N/A |

Agents can enrich data (GICS cache, aggregate flags, row corrections) but cannot create new deterministic rules without writing Python code. This means the `pipeline_patch` mutation mode -- the riskiest one -- is currently the only path for agents to author rules.

## Prerequisite: Externalize Rules into Data Files

The highest-leverage engineering change is moving rules out of Python source into config files that agents can read, propose additions to, and that the pipeline loads at runtime.

### Target layout

```
data/rules/
  aggregate_patterns.json          # currently _BDC_AGGREGATE_PATTERNS in bdc_identifier.py
  bad_issuer_names.json            # currently _BAD_ISSUER_NAMES_EXACT in classification.py
  asset_classification.json        # currently _BDC_LOAN_KEYWORDS, _BDC_EQUITY_KEYWORDS, etc.
  fund_vehicle_keywords.json       # currently _BDC_FUND_VEHICLE_KEYWORDS
  structured_credit_keywords.json  # currently _STRUCTURED_CREDIT_KEYWORDS
  industry_prefix_maps.json        # currently GS_INDUSTRY_MAP, IDENTIFIER_INDUSTRY_MAP, etc.
  per_cik/
    {CIK}.json                     # per-CIK overrides (new capability)
```

### What this enables

- Agents propose rules by writing to JSON files, not Python source.
- The pipeline loads rules at runtime (no code changes for new rules).
- Rules are versioned, diffable, and rollbackable via git.
- Per-CIK rules become a natural extension (one JSON file per CIK).
- Gold-standard regression testing becomes trivial: run pipeline with proposed rules, check validation gates.
- The rule files themselves become the audit trail.

### What the pipeline code becomes

Python source becomes a rule engine: it defines how rules are applied (regex matching, keyword lookup, CTE construction) but not which rules exist. The `classification.py` keyword lists become `json.load()` calls. The `bdc_identifier.py` pattern list becomes a loaded regex set. All classification logic remains deterministic SQL/DuckDB -- only the inputs change.

### Per-CIK override schema (new)

```json
{
  "cik": "0001418076",
  "entity_name": "Ares Capital Corporation",
  "overrides": {
    "dimension_dedup_key": {
      "strip_affiliation_prefix": true,
      "custom_normalization": "lowercase, strip 'investments in' prefix"
    },
    "rate_scale": {
      "multiply_basis_spread_by": 0.01,
      "applies_to_filings_before": "2024-01-01"
    },
    "additional_aggregate_patterns": [
      "^Total Senior Secured.*Loans$"
    ],
    "exclude_dimension_paths": [
      "us-gaap:InvestmentTypeAxis=cik:ControlledAffiliatedCompaniesMember"
    ]
  },
  "evidence": "Dimension duplication confirmed in data investigation #7",
  "added_by": "agent:per_cik_rule_agent",
  "added_at": "2026-06-15T10:00:00Z"
}
```

## Prerequisite: Persistent Gold Standard

The second prerequisite is a growing set of validated decisions that serves as the regression test suite for all agent-proposed changes.

### Structure

```
data/gold_standard/
  gold_standard.csv
```

Columns: `entity_key`, `name_norm`, `issuer_name_raw`, `decision_type` (GICS, AGGREGATE_HEADER, JV_SUBSIDIARY, ROW_CORRECTION, CLASSIFICATION_OVERRIDE), `gold_label`, `gold_confidence`, `reviewed_by`, `reviewed_at`, `source_workflow`, `cik`, `report_date`, `fair_value`.

### Seeding

The gold standard is seeded from decisions already validated in the repository:

- Accepted GICS cache entries where `source = "cc_skill"` and confidence is high.
- Reviewed aggregate leak spot-check samples (the `review_label` column in the 385-row stratified sample).
- Accepted fund-strategy review verdicts.
- Validated row corrections.
- Known aggregate header patterns (the `AGG_EXACT` set in `process_gics_batches.py` -- these are definitionally correct).

### Growth

Every manual review adds rows. Every agent run that passes human spot-check adds its verified outputs. The gold standard grows monotonically; entries are never deleted but can be superseded (a `superseded_by` column tracks corrections to the gold standard itself).

### Use

- **Regression testing for new rules:** When an agent proposes a new aggregate pattern, run it against all gold-labeled entities. Any entity labeled `false_positive_valid_position` that the new pattern would catch is a regression.
- **Agent accuracy benchmarking:** Before accepting a batch of agent classifications, run the agent on a held-out slice of the gold set. If accuracy exceeds the threshold for that decision type, accept the batch with spot-check review.
- **Convergence monitoring:** Track agent accuracy on the gold set over time. If accuracy drifts below threshold, escalate to heavier human review.

## Multi-Agent Architecture

### Overview

```
New quarter data arrives
    |
    v
Pipeline runs (deterministic) --> unified holdings + 14 validation checks
    |
    v
Residual analysis (deterministic) --> clusters residuals by mechanism, CIK, FV impact
    |
    |----------+------------------+--------------------+-----------------+
    v          v                  v                    v                 v
  GICS      Aggregate         Per-CIK Rule        Row Correction    Global Rule
  Enrichment  Header           Agent               Agent             Discovery
  Agent       Agent                                                  Agent
    |          |                  |                    |                 |
    v          v                  v                    v                 v
  gics_      agg_flags.csv     per_cik/             row_              proposed
  cache.csv  + patterns.json   {CIK}.json           corrections.csv   rules in
  + agg_                                                              patterns.json,
  flags.csv                                                           keywords.json
    |          |                  |                    |                 |
    +-----+----+------+-----------+----------+---------+---------+------+
          |           |                      |                   |
          v           v                      v                   v
    Schema         Gold-set               Pipeline-level      Cross-agent
    validation     regression             regression gate     conflict check
          |           |                      |                   |
          +-----+-----+----------+-----------+-------------------+
                |                 |
                v                 v
          No regression      Regression detected
                |                 |
                v                 v
          Accept round      Rollback + flag for human review
                |
                v
          Next iteration (or stop if converged)
```

### Agent Specifications

Each agent has four components:

1. **Input residuals**: The specific validation artifacts it reads.
2. **Mutation surface**: The specific files it can write.
3. **Deterministic harness**: Validates agent output before it reaches the pipeline.
4. **Regression gate**: Pipeline-level checks that must not worsen.

#### GICS Enrichment Agent

- **Feasibility:** High. Already operational.
- **Risk:** Low. Wrong labels are analytics quality issues, not data corruption.
- **Input:** NEEDS_SEARCH entities from `process_gics_batches.py` triage; new entities absent from `company_gics_cache.csv`.
- **Mutation surface:** `company_gics_cache.csv`, `aggregate_header_flags.csv`.
- **Harness:** GICS vocabulary check (label must be in `gics_sub_industries.json`). Verdict must be in {GICS, AGGREGATE_HEADER, JV_SUBSIDIARY, UNRESOLVABLE}. Confidence must be in {high, medium, low}. Dedup against existing cache.
- **Regression gate:** Gold-set accuracy >= 93%. No new aggregate header flags for entities labeled `false_positive_valid_position` in gold set.
- **Expected volume per quarter:** 100--500 new entities.
- **Autonomy level:** Fully autonomous for high-signal verdicts (industry prefix extraction, exact name match). Human spot-check for medium-signal verdicts (company name interpretation).

#### Aggregate Header Detection Agent

- **Feasibility:** High. Pattern-based triage already handles most cases.
- **Risk:** Medium. False negatives (missed headers) inflate FV sums and corrupt GAV reconciliation. False positives (real companies flagged as headers) drop valid positions.
- **Input:** Aggregate leak audit residuals from `validate_holdings.py`. Entities with high FV and no GICS classification. Entities whose `dimensions_raw` contains affiliation/category axis members.
- **Mutation surface:** `aggregate_header_flags.csv` (entity-level flags). `data/rules/aggregate_patterns.json` (new regex proposals, requires externalization).
- **Harness:** For flags: schema validation, confidence check, evidence requirement. For pattern proposals: gold-set regression (zero new false positives on entities labeled `false_positive_valid_position`). FV impact reporting.
- **Regression gate:** GAV reconciliation must not worsen. Coverage ratios must not drop. No gold-set regressions.
- **Expected volume per quarter:** 10--50 new flags, 1--5 new pattern proposals.
- **Autonomy level:** Fully autonomous for entity flags (low mutation risk per entity). Human review for new pattern proposals (global rule, affects all CIKs).

#### Per-CIK Rule Agent

- **Feasibility:** Medium. Requires new per-CIK config system.
- **Risk:** Medium. Per-CIK rules affect only one filer, limiting blast radius. But wrong rules for high-FV CIKs (e.g., Ares Capital) have large impact.
- **Input:** CIK-level validation residuals: GAV misses, pct-sum outliers, count instability, dimension-path duplication, source reconciliation blockers. Restricted to one CIK at a time.
- **Mutation surface:** `data/rules/per_cik/{CIK}.json`.
- **Harness:** Per-CIK override schema validation. Evidence requirement (must cite specific accession numbers, dimension paths, or raw field values). FV impact bound (proposed change must not alter aggregate FV by more than a configurable threshold without human approval).
- **Regression gate:** That CIK's GAV ratio must improve or stay flat. pct-sum must improve or stay flat. No new validation FAILs for that CIK. Gold-set entities from that CIK must not regress.
- **Expected volume per quarter:** 5--20 CIK-level configs, concentrated in CIKs with known dimension quirks.
- **Autonomy level:** Autonomous for known pattern types (affiliation prefix strip, rate scale correction). Human review for novel dimension structures or CIKs processed for the first time.

#### Row Correction Agent

- **Feasibility:** High. Tiny mutation surface (one row at a time).
- **Risk:** Low. Each correction is specific and verifiable.
- **Input:** Row-level validation FAILs from `row_validation_issues.csv`: C101 (missing FV), X06 (principal/FV ratio), C402 (maturity date), X09 (pct > 100%).
- **Mutation surface:** `data/overrides/row_corrections.csv`.
- **Harness:** Row correction schema validation. Evidence requirement (must cite raw source field values and explain the discrepancy). Correction must resolve the specific FAIL it targets. Correction must not create new FAILs.
- **Regression gate:** Net FAIL count must decrease. No new FAILs with severity >= the corrected one. GAV reconciliation must not worsen for the affected CIK-quarter.
- **Expected volume per quarter:** 10--50 row corrections, concentrated in known mechanisms (scale mismatch, context mismatch, sentinel dates).
- **Autonomy level:** Autonomous for known mechanisms with clear source evidence. Human review for corrections where the raw source is ambiguous or missing.

#### Global Rule Discovery Agent

- **Feasibility:** Medium. Highest-value but highest-risk agent.
- **Risk:** Higher. Global rules affect all CIKs. A false-positive-prone regex in `aggregate_patterns.json` drops valid positions across the entire universe.
- **Input:** Pattern clusters from the NEEDS_SEARCH residual and from validation residuals. Cross-CIK pattern analysis: "this pattern appears in 15 CIKs with the same structure."
- **Mutation surface:** `data/rules/aggregate_patterns.json`, `data/rules/asset_classification.json`, `data/rules/industry_prefix_maps.json`, `data/rules/fund_vehicle_keywords.json`.
- **Harness:** Gold-set regression (zero false positives on any gold-labeled entity). Cross-CIK impact analysis (report which CIKs are affected and how many rows change). Pattern specificity check (proposed regex must not match >N% of all entities, as overly broad patterns are likely wrong).
- **Regression gate:** All existing validation metrics must be flat or improved across all CIKs. Gold-set regression must pass. Affected row count must be within a configurable bound.
- **Autonomy level:** Never fully autonomous. The agent proposes; human reviews the cross-CIK impact report and approves. This is the one agent where the plan's calibration pilot makes sense: test the proposed rule on a held-out sample before applying globally.
- **Expected volume per quarter:** 2--5 global rule additions. Most will be new entries in existing maps (e.g., a new industry prefix); few will be new regex patterns.

### Orchestration

The orchestrator is a script that runs the loop:

1. Run pipeline: `python -m pipeline.main --unified --validate`
2. Run residual analysis: cluster validation outputs by mechanism, CIK, FV impact.
3. Dispatch agents (parallel where independent): GICS and aggregate header agents can run concurrently; per-CIK and row correction agents can run concurrently; global rule discovery depends on the others' outputs.
4. Collect agent outputs. Run harness validation on each.
5. Run cross-agent conflict detection: check for entities claimed by multiple agents with conflicting verdicts.
6. Stage accepted outputs (write to rule files, caches, corrections).
7. Re-run pipeline with staged changes.
8. Re-run validation. Compare to pre-iteration baseline.
9. Regression gate: if any metric worsens beyond threshold, roll back the iteration and flag.
10. If no regression: accept the iteration. Update gold standard with newly validated decisions.
11. Check convergence: if remaining improvable residuals (by FV) are below threshold, or max iterations reached, stop. Otherwise, go to step 2.

### Convergence

The system should stop iterating when:

- Remaining improvable residuals are below a materiality threshold (e.g., $10M total FV across all residual categories).
- The last iteration produced zero accepted changes (no agent found anything actionable).
- Maximum iterations reached (recommend 3--5 per quarter; diminishing returns after that).
- A regression was detected and rolled back (stop and escalate to human).

In practice, expect 2--3 iterations to capture 90% of the value per quarter.

## Feasibility Summary

| Agent | Feasibility | Risk | Autonomy | Prerequisite |
|---|---|---|---|---|
| GICS Enrichment | High | Low | Full (high-signal) / Spot-check (medium-signal) | None -- already works |
| Aggregate Header Detection | High | Medium | Full (flags) / Human review (patterns) | Rule externalization |
| Per-CIK Rule | Medium | Medium | Autonomous (known patterns) / Human review (novel) | Per-CIK config system |
| Row Correction | High | Low | Autonomous (known mechanisms) / Human review (ambiguous) | None -- already works |
| Global Rule Discovery | Medium | Higher | Never fully autonomous | Rule externalization + gold standard |

**Overall: ~80% of quarterly processing can be automated.** The GICS enrichment, aggregate header flagging, and row correction agents can run with high autonomy because the pipeline's existing validation gates (GAV, coverage, count stability) catch their errors at the pipeline level. The remaining ~20% -- per-CIK dimension quirks, genuinely novel filing patterns, global rule promotion -- benefits from agent-assisted investigation but requires human judgment for final acceptance.

## What Should Always Require Human Review

- Changes to validation thresholds or gates (agents must never weaken their own constraints).
- Global rules that affect more than 1,000 rows.
- New CIKs that have never been processed (no historical baseline to regress against).
- Any iteration where the regression gate fires.
- The quarterly summary report before data reaches the frontend or indices.

## Known Hard Problems

### Novel patterns

Each quarter can bring new BDC registrations, new filer-specific XBRL extensions, or entirely new filing formats. Agents operating from known patterns will miss these. The detection mechanism is: after all iterations, the residual should be small relative to previous quarters. If it is disproportionately large, something novel is present that needs human investigation. The system should surface "these are the residuals I could not resolve" as its final output.

### Cross-agent consistency

If the GICS agent classifies an entity as a real company while the aggregate header agent flags it as a header, the orchestrator has a conflict. Conflict detection runs after all agents complete and before staging: check for entity key overlap across output files. Conflicts are escalated to human review, not resolved by priority rules.

### Compounding errors

If agent A misclassifies an entity and agent B uses that classification downstream, errors propagate. Mitigation: each agent works from source data and pipeline outputs, not from other agents' intermediate files. The pipeline re-run between iterations acts as a synchronization point -- all agents see the same ground truth.

### Trust calibration over time

Agent accuracy on today's gold set does not guarantee accuracy on next quarter's novel entities. The gold set must grow continuously. If agent accuracy on the growing gold set drifts below threshold, the system should automatically escalate to heavier human review for that agent type. Track accuracy per agent per quarter as a time series.

## Implementation Order

1. **Externalize rules into data files.** This is the architectural prerequisite. Without it, agents are limited to enrichment or writing Python code. One-time refactor; the pipeline code becomes a rule engine loading JSON at runtime.

2. **Build the gold standard.** Seed from existing validated decisions. Define the schema. Write the regression harness (run rules against gold set, report false positives and false negatives). This is the gating mechanism that makes autonomous operation safe.

3. **Build the orchestration loop.** Pipeline run, residual analysis, agent dispatch, harness validation, pipeline re-run, regression gate, accept/reject. This is the skeleton that all agents plug into.

4. **Deploy GICS Enrichment Agent first.** Lowest risk, highest volume, already operational. Validates the orchestration loop on a safe workload.

5. **Deploy Aggregate Header Agent and Row Correction Agent.** Medium risk, high value. These exercise the rule externalization and gold-set regression infrastructure.

6. **Deploy Per-CIK Rule Agent.** Requires the per-CIK config system. Exercises the most complex evidence and harness requirements.

7. **Deploy Global Rule Discovery Agent last.** Highest risk. Requires the most mature gold standard and the strongest regression testing. Human review remains mandatory for global rule acceptance.

This ordering validates the infrastructure at each step before moving to higher-risk agents. Each step exercises a superset of the previous step's capabilities.

## Relationship to the Workflow Engine Plan

The workflow engine plan (`docs/agentic_review_workflow_engine/README.md`) and this document address related but distinct concerns.

The workflow engine plan focuses on review process controls: evidence bundles, verdict schemas, calibration pilots, mutation modes, and merge gates. Its vocabulary (review_only, deterministic_merge, config_patch, pipeline_patch) and its risk taxonomy (enrichment vs. blocker remediation) remain valid and are adopted here.

This document focuses on the architecture that makes autonomous operation feasible: rule externalization, a persistent gold standard, pipeline-level regression gates, and a concrete orchestration loop. The two documents are complementary:

- The workflow engine plan defines what agents are allowed to do and how their output is validated.
- This document defines the infrastructure that lets agents propose rules (not just verdicts) and the feedback loop that validates proposed rules against the pipeline's existing deterministic checks.

Where they overlap, this document prefers lighter-weight mechanisms:

- **Gold-set regression** replaces per-run calibration pilots for most agents. The gold set is persistent and grows; calibration pilots are disposable and per-run.
- **Pipeline validation gates** replace per-agent merge gates. GAV, coverage, count stability, and pct-sum checks already run after every `--unified --validate`. They are the acceptance criteria, not a separate gate layer.
- **Per-agent config files** replace a generic manifest schema. Each agent's mutation surface, harness, and gates are defined by its specific input/output contract, not by a shared manifest format.

The exception is the Global Rule Discovery Agent, where the workflow engine plan's calibration pilot and heavier review process are warranted because global rules have the largest blast radius.
