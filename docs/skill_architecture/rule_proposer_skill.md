# Rule Proposer Skill Architecture

## Overview

An Agent Skills-based system for automated data quality rule discovery and maintenance. A **rule-proposer agent** iteratively proposes validation rules, a **deterministic classifier** evaluates them against the pipeline data, and the loop converges when the core rule set stabilizes.

The architecture follows the Anthropic Agent Skills open standard (December 2025), adopted by 32+ tools. It separates deterministic operations (classification, diffing, schema validation) from contextual reasoning (rule proposal, failure interpretation, filer-quirk discovery).

## Design Principles

### Two-Zone Split (Block Engineering)

| Zone | Owner | Examples |
|------|-------|---------|
| **Deterministic** (scripts/tools) | Executable code the agent invokes but cannot modify | DuckDB SQL classifier, diff checker, name extractor, schema validator |
| **Reasoning** (agent) | Contextual judgment that benefits from LLM flexibility | Which rule type to propose next, how to interpret classifier output, whether a rule is "core" or "filer-specific" |

### Three Governing Principles

1. **Know what the agent should NOT decide.** The classifier logic, output schema, and reconciliation checks are scripts. The agent calls them; it does not rewrite them.
2. **Know what the agent SHOULD decide.** Rule proposal, failure triage, filer-quirk interpretation, and convergence judgment are agent reasoning tasks.
3. **Write a constitution, not a suggestion.** The SKILL.md encodes hard constraints (budget limits, materiality gates, convergence criteria), not soft guidance.

## Folder Structure

```
.claude/skills/rule-proposer/
|-- SKILL.md                              # Instructions, constraints, protocol
|-- scripts/
|   |-- extract_company_name.py           # Calls haiku for IE from composite identifiers
|   |-- run_classifier.py                 # Invokes DuckDB classifier on a candidate rule set
|   |-- diff_check.py                     # Wraps scripts/diff_outputs.py --semantic
|   |-- validate_rule_schema.py           # JSON schema validation for proposed rules
|   +-- check_regression.py              # Runs proposed rules against ground truth anchors
|-- references/
|   |-- rule_types.md                     # Registry of valid rule types with JSON schemas
|   |-- playbook_delimiter_patterns.md    # How to discover/propose delimiter rules
|   |-- playbook_classification.md        # How to propose classification mapping rules
|   |-- playbook_reconciliation.md        # GAV matching, coverage ratios, cross-source checks
|   |-- playbook_exclusion_lists.md       # How to propose CIK/position exclusions
|   |-- taxonomy.md                       # Index classifications, exposure types, asset classes
|   |-- known_filer_quirks.md             # Per-CIK historical exceptions and reporting changes
|   +-- ground_truth_anchors.md          # V2 spot-check set as regression test suite
+-- templates/
    +-- rule_proposal.json               # Template for a valid rule proposal
```

## Component Details

### SKILL.md

The skill instruction file encodes the agent's operating protocol.

**Frontmatter:**
```yaml
---
name: rule-proposer
description: >
  Proposes data quality rules for the private markets index pipeline.
  Iterates with a deterministic classifier until the rule set converges.
---
```

**Body encodes:**

1. **Convergence criterion.** Stop when no new rules are accepted after a full pass over all rule types and in-scope filers.
2. **Budget constraint.** Maximum 3 proposal attempts per rule candidate before parking it as "needs human review."
3. **Materiality gate.** Any global rule affecting >1% of total rows (currently ~7,200 rows) requires human approval before acceptance. Filer-scoped rules below 100 affected rows can be auto-accepted.
4. **Tool invocation protocol.** Always validate rule schema (validate_rule_schema.py) before invoking the classifier (run_classifier.py). Always run regression check (check_regression.py) before accepting a rule.
5. **Rule type constraint.** The agent may only propose rules from the typed registry in references/rule_types.md. Free-form Python code or arbitrary SQL is not permitted.
6. **Escalation protocol.** When classifier returns "not enough info" 3 times for the same candidate, park it and log it for human review rather than retrying.

### Scripts (Deterministic Zone)

#### extract_company_name.py

Calls a cheap model (haiku) to extract structured fields from composite identifier strings.

**Input:** Raw identifier string (e.g., `"ABC Corp | 2.3% | First Lien"`)
**Output:** Structured JSON:
```json
{
  "issuer_name": "ABC Corp",
  "interest_rate": 0.023,
  "instrument_type": "First Lien"
}
```

**Design notes:**
- Uses haiku for cost efficiency (~100x cheaper than opus for a task it handles well)
- Falls back to RIOLU-style statistical tokenization for common delimiter patterns before calling the LLM (pipe, comma, newline)
- Batch mode: accepts a list of identifiers, deduplicates before calling the model
- Deterministic cache: same input string always returns cached result

#### run_classifier.py

Invokes the existing DuckDB SQL classification pipeline on a candidate rule set.

**Input:** A rule set (JSON array of typed rule proposals)
**Output:** Classification summary statistics:
```json
{
  "total_rows_affected": 1247,
  "classification_changes": {
    "UNCLASSIFIED -> DIRECT_LENDING": 892,
    "UNCLASSIFIED -> PRIVATE_EQUITY_FUND": 43,
    "DIRECT_LENDING -> COMMON_EQUITY": 12
  },
  "gav_reconciliation_delta": -0.003,
  "coverage_ratio_change": 0.002,
  "regression_failures": 0,
  "verdict": "valid"
}
```

**Design notes:**
- Wraps existing unified_holdings.py classification CTEs
- Applies proposed rules as additional SQL predicates
- Returns aggregate statistics, not row-level results (keeps context small)
- The agent cannot modify this script or the underlying SQL

#### diff_check.py

Wraps `scripts/diff_outputs.py --semantic` to compare pipeline outputs before and after a proposed rule set.

**Input:** Two output snapshots (before/after rule application)
**Output:** Semantic diff summary (number of files changed, rows changed, semantic deltas)

#### validate_rule_schema.py

Validates that a proposed rule conforms to the typed rule registry schema.

**Input:** A rule proposal JSON object
**Output:** Valid/invalid + list of schema violations

#### check_regression.py

Runs the proposed rule set against the ground truth anchor set (V2 spot-checked positions).

**Input:** A rule set + the ground truth anchor file
**Output:** Pass/fail + list of any anchor positions that changed classification

### References (Knowledge Base)

#### rule_types.md

The typed rule registry. Each rule type has a fixed JSON schema. The agent may only propose rules conforming to one of these types.

**Rule Type 1: Delimiter Pattern**
```json
{
  "rule_type": "delimiter_pattern",
  "scope": "cik:<CIK>",
  "delimiter": "|",
  "field_count": 3,
  "field_mapping": ["issuer_name", "interest_rate", "instrument_type"],
  "field_extractors": {
    "interest_rate": "percent_string_to_float"
  }
}
```
Scope: per-CIK or per-source. Defines how to parse composite identifier strings for a specific filer.

**Rule Type 2: Keyword List**
```json
{
  "rule_type": "keyword_list",
  "scope": "global",
  "target_field": "index_classification",
  "target_value": "PRIVATE_EQUITY_FUND",
  "keywords": ["L.P.", "Partners Fund", "Capital Partners"],
  "require_co_keyword": true,
  "co_keywords": ["fund", "partners", "capital", "venture"]
}
```
Scope: global or per-source. Extends the keyword-matching classification logic.

**Rule Type 3: Classification Mapping**
```json
{
  "rule_type": "classification_mapping",
  "scope": "global",
  "condition": {
    "source": "nport",
    "nport_asset_cat": "EC",
    "issuer_type": "CORP"
  },
  "set_fields": {
    "exposure_type": "DIRECT",
    "asset_class": "PRIVATE_EQUITY",
    "index_classification": "COMMON_EQUITY"
  }
}
```
Scope: global. Maps a combination of input fields to classification outputs.

**Rule Type 4: Threshold/Range Constraint**
```json
{
  "rule_type": "threshold",
  "scope": "global",
  "field": "pct_of_net_assets",
  "min": -0.5,
  "max": 4.0,
  "action": "flag_outlier"
}
```
Scope: global. Defines acceptable ranges for numeric fields.

**Rule Type 5: Exclusion List**
```json
{
  "rule_type": "exclusion",
  "scope": "global",
  "target": "cik",
  "values": ["0001658645", "0001678130"],
  "reason": "Consumer/marketplace lending positions with opaque numeric IDs"
}
```
Scope: global. Excludes specific CIKs, issuers, or position patterns from the unified holdings.

**Rule Type 6: Reconciliation Constraint**
```json
{
  "rule_type": "reconciliation",
  "scope": "global",
  "check": "gav_sum_equals_fund_total",
  "tolerance": 0.05,
  "left": "SUM(fair_value) GROUP BY cik, report_date",
  "right": "total_net_assets FROM fund_financials",
  "action": "warn"
}
```
Scope: global. Cross-table consistency checks.

**Rule Type 7: Composition Constraint**
```json
{
  "rule_type": "composition",
  "scope": "per_fund_type",
  "fund_type": "REAL_ESTATE_FUND",
  "condition": "asset_class = 'REAL_ESTATE'",
  "min_pct": 0.50,
  "action": "warn"
}
```
Scope: per fund type. Validates that fund-level composition matches expected distribution.

#### Playbooks

Each playbook is a per-rule-type instruction file that the agent loads on demand.

**playbook_delimiter_patterns.md** covers:
- How to detect delimiter characters from a sample of identifier strings
- When to use statistical tokenization vs. LLM extraction
- How to validate that a proposed delimiter pattern covers >95% of a filer's identifiers
- Common edge cases (nested delimiters, inconsistent field counts, missing fields)
- When to fall back to the extract_company_name.py tool

**playbook_classification.md** covers:
- The 2-axis classification system (exposure_type x asset_class)
- How index_classification derives from the 2-axis values
- The NUSS name-gating rule and why it exists
- The L.P. co-keyword requirement and why it exists
- How to use nport_asset_cat to refine classifications
- Known residual disagreements (E2 cases) and why they're acceptable

**playbook_reconciliation.md** covers:
- GAV = sum of positions check (tolerance: 5%)
- Coverage ratio validation (0.8x-1.2x of total assets)
- Cross-source dedup verification
- Affiliation-axis duplication detection
- pct_of_net_assets correction using consolidated net_assets

**playbook_exclusion_lists.md** covers:
- Criteria for CIK exclusion (consumer lending, aggregate-only XBRL)
- Criteria for position exclusion (aggregate headers, zero-FV rows)
- How to validate that an exclusion doesn't remove legitimate positions
- Documentation requirements for any new exclusion

#### taxonomy.md

Domain knowledge reference. Contains:
- Index classification definitions (DIRECT_LENDING, COMMON_EQUITY, etc.)
- Exposure type definitions (DIRECT, FUND, LIQUID)
- Asset class definitions (PRIVATE_CREDIT, PRIVATE_EQUITY, REAL_ESTATE, etc.)
- Instrument type hierarchy (first lien > second lien > mezzanine > equity)
- Fund type characteristics (BDC, interval fund, tender offer fund)
- How public credit indices (Morningstar LSTA, ICE BofA HY) define constituents

#### known_filer_quirks.md

Per-CIK exception log. Grows over time as the proposer discovers new quirks.

Example entries:
```
## CIK 0001418076 - Ares Capital Corporation
- Uses pipe delimiter in investment_identifier
- Reports same position under multiple affiliation dimensions
- Requires pct_of_net_assets correction via consolidated net_assets
- Changed reporting format in 2024 Q3 (added industry sub-field)

## CIK 0001287750 - Prospect Capital Corporation
- Uses newline delimiter in investment_identifier
- Embeds industry classification in identifier string
- Has aggregate headers that leak through standard filtering
```

#### ground_truth_anchors.md

Formalized regression test set derived from V2 spot-checks. Contains hand-verified classifications for ~200 positions across the top BDCs and interval/tender funds. Any proposed rule set must pass 100% of these anchors.

### Templates

#### rule_proposal.json

```json
{
  "proposal_id": "<auto-generated UUID>",
  "rule_type": "<one of the 7 registered types>",
  "scope": "<global | per_source | cik:<CIK>>",
  "rule_body": { },
  "justification": "<natural language explanation>",
  "expected_impact": {
    "rows_affected_estimate": 0,
    "classification_changes": {},
    "is_core_rule": false
  }
}
```

## Loop Protocol

### Phase 1: Initialization

1. Load current rule set from pipeline configuration
2. Run classifier on current rules to establish baseline statistics
3. Run regression check against ground truth anchors (must pass 100%)

### Phase 2: Proposal Loop

For each rule type in the registry:

```
1. Load the relevant playbook from references/
2. Query the classifier for current statistics relevant to this rule type
   (e.g., for classification rules: current UNCLASSIFIED count and examples)
3. Propose a candidate rule using the rule_proposal.json template
4. Validate schema (validate_rule_schema.py)
   - If invalid: fix and retry (max 2 retries)
5. Run classifier (run_classifier.py) with the candidate rule added
   - If "valid": proceed to step 6
   - If "not enough info": retry with modified approach (max 3 total attempts)
   - If "invalid" (regression or constraint violation): discard, log reason
6. Run regression check (check_regression.py)
   - If any anchor position changes: discard the rule
7. Check materiality gate:
   - If global rule AND >1% of rows affected: flag for human approval
   - Otherwise: auto-accept
8. Add accepted rule to the working rule set
```

### Phase 3: Convergence Check

After a full pass over all rule types:

1. Run diff_check.py comparing outputs with and without the newly accepted rules
2. If semantic deltas == 0: the rule set has converged. Stop.
3. If new rules were accepted: return to Phase 2 for another pass
4. If no new rules were accepted but deltas remain: log the residual deltas for human review. Stop.

### Phase 4: Output

1. Write the final rule set to a versioned JSON file
2. Write a human-readable changelog of all accepted/rejected/parked rules
3. Write updated known_filer_quirks.md if new per-CIK patterns were discovered
4. Run scripts/rebuild_outputs.py with the new rule set
5. Run scripts/diff_outputs.py --semantic as final verification

## Cost Model

| Component | Model | Cost per call | Calls per full run (est.) |
|-----------|-------|--------------|--------------------------|
| Rule proposer | sonnet | ~$0.01 | ~200 (7 types x ~30 filers with issues) |
| Name extractor | haiku | ~$0.001 | ~500 (batch deduped) |
| Classifier | DuckDB SQL | $0 | ~200 |
| Schema validator | local | $0 | ~200 |
| Regression check | DuckDB SQL | $0 | ~200 |
| Diff check | local | $0 | ~5 (per convergence pass) |
| **Total estimated** | | **~$2.50-5.00 per full run** | |

## Risk Mitigations

### Non-convergence
**Risk:** The proposer keeps generating rules that the classifier rejects.
**Mitigation:** Budget constraint (max 3 attempts per candidate) + full-pass convergence check (stop after one pass with zero acceptances).

### Hallucinated rules
**Risk:** The LLM proposes rules that are syntactically valid but semantically wrong.
**Mitigation:** Ground truth regression check. Schema validation catches structural errors; regression check catches semantic errors against hand-verified positions.

### Knowledge base staleness
**Risk:** Filer changes reporting format; known_filer_quirks.md is outdated.
**Mitigation:** The classifier's rejection signal should trigger a "flag for human review" entry, not infinite retry. New quirks discovered during the loop are appended to known_filer_quirks.md automatically.

### Cascading misclassification
**Risk:** A rule change cascades through dependent rules, causing widespread reclassification.
**Mitigation:** Materiality gate (>1% of rows requires human approval) + regression check (ground truth anchors catch classification drift).

### Circular feedback
**Risk:** Historical statistics were computed from data processed by previous rules, creating circularity.
**Mitigation:** Ground truth anchors are independent of the rule set. They are hand-verified against source filings (HTML/PDF), not against pipeline output.

## Comparison with Existing Systems

| Dimension | This architecture | Ataccama ONE | Anomalo | Argos (Microsoft) |
|-----------|------------------|-------------|---------|-------------------|
| Rule format | Typed JSON registry (7 types) | Opaque internal | No explicit rules (ML-based) | Python functions |
| Classifier | Deterministic DuckDB SQL | ML-based (opaque) | XGBoost anomaly score | Validation set accuracy |
| Domain knowledge | Explicit playbooks + taxonomy | Generic profiling | None (unsupervised) | None (data-driven) |
| Filer-specific rules | Per-CIK scope + quirks log | Not supported | Not supported | Not applicable |
| Human gate | Materiality-based | Confidence-based | Alert threshold | None (auto-deploy) |
| Ground truth | Hand-verified anchor set | None | None | Labeled test set |
| Cost per run | ~$2.50-5.00 | SaaS pricing | SaaS pricing | Azure compute |
| Portability | Agent Skills open standard | Vendor lock-in | Vendor lock-in | Open source |

## References

- [Anthropic Agent Skills specification](https://github.com/anthropics/skills)
- [Block: 3 Principles for Designing Agent Skills](https://engineering.block.xyz/blog/3-principles-for-designing-agent-skills)
- [LinkedIn CAPT: Contextual Agent Playbooks & Tools](https://www.linkedin.com/blog/engineering/ai/contextual-agent-playbooks-and-tools-how-linkedin-gave-ai-coding-agents-organizational-context)
- [Argos: Agentic Time-Series Anomaly Detection (arXiv 2501.14170)](https://arxiv.org/abs/2501.14170)
- [AgentSpec: Runtime Enforcement for LLM Agents (arXiv 2503.18666)](https://arxiv.org/abs/2503.18666)
- [LLM Augmentation with Codified Expert Knowledge (arXiv 2601.15153)](https://arxiv.org/html/2601.15153v1)
- [RuleMiner: Data Quality Rules Discovery (ICDE 2014)](https://cs.uwaterloo.ca/~ilyas/papers/ChuICDE2014Demo.pdf)
- [RIOLU: Automated Pattern Inference (arXiv 2412.05240)](https://arxiv.org/abs/2412.05240)
- [Hydra: Efficient Denial Constraint Discovery (VLDB 2017)](https://www.vldb.org/pvldb/vol11/p311-bleifub.pdf)
