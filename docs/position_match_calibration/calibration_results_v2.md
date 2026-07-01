# Position Match Calibration Results v2 (Post Plans A+B)

Date: 2026-06-11
Calibration round: 2 (post-fix)
Review method: Line-by-line sub-agent review (7 agents, 146 bundles)
Baseline: v1 calibration 2026-06-11 (pre-fix, 4.2% weighted error rate)

## Summary

Plans A (wrapper layer) and B (matching algorithm hardening) reduced the weighted error rate from **4.2% to 2.0%** (95% CI: 0.0%-4.1%). B2 improved substantially (7.6% to 3.1%). C-tier remains stubbornly high (30.0% to 29.4%), and D/E improved but still exceed targets. The dominant residual error pattern is **wrong_tranche** (36 of 58 errors) — same entity, different instrument.

## Weighted Error Rate

| Metric | v1 (pre-fix) | v2 (post-fix) | Target |
|--------|-------------|---------------|--------|
| **Weighted error rate** | **4.2%** (CI: 1.2%-7.1%) | **2.0%** (CI: 0.0%-4.1%) | <2% |

## Per-Tier Error Rates

| Tier | Population | Sampled | Errors | Error Rate | v1 Rate | Target | Status |
|------|-----------|---------|--------|-----------|---------|--------|--------|
| A_within_filing | 60,655 | 40 | 0 | 0.0% | 2.5% | <2% | PASS |
| B1b_position_key | 62,062 | 40 | 1 | 2.5% | 2.5% | <2% | FAIL |
| B2_exact_name | 15,178 | 200 | 6 | 3.1% | 7.6% | <4% | PASS |
| C_normalized_name | 944 | 80 | 20 | 29.4% | 30.0% | <15% | FAIL |
| D_fuzzy | 3,993 | 150 | 20 | 13.4% | 22.5% | <8% | FAIL |
| E_entity_fingerprint | 236 | 90 | 11 | 12.9% | 23.3% | <5% | FAIL |

## Verdict Distribution

| Label | Count | Percentage |
|-------|-------|-----------|
| correct_match | 519 | 86.5% |
| wrong_tranche | 36 | 6.0% |
| ambiguous | 23 | 3.8% |
| wrong_entity | 16 | 2.7% |
| wrong_instrument | 6 | 1.0% |

## Error Analysis by Pattern

### Pattern 1: Wrong Tranche — Multi-Position Tranche Confusion (36 cases)

The largest error category. Same entity, but the algorithm selected the wrong instrument from multiple positions. Examples:
- Term Loan 1 matched to Term Loan 3 (suffix renumbering)
- Term loan matched to revolver at same company
- First Lien matched to Second Lien
- Regular term loan matched to DIP facility (bankruptcy)
- GBP tranche matched to NOK tranche (currency confusion)
- Main facility matched to delayed draw at same company
- Series 2025-ST7 matched to Series 2026-ST1 (structured credit)

**Tier distribution**: C (most), D, E, B2 (few). C-tier's 29.4% error rate is almost entirely wrong_tranche — the normalized name matcher groups all positions for the same entity then picks the wrong one.

**Root cause**: The greedy 1:1 ROW_NUMBER matching selects locally optimal pairs without global optimization across all positions for the same entity. This is the bipartite matching problem identified in Plan B Deliverable 6 (deferred).

### Pattern 2: Wrong Entity — Different Companies (16 cases)

Subpatterns:
- **Industry-prefix fuzzy confusion (6 cases)**: Goldman Sachs BDC's allocation-percentage prefix format and MidCap's industry-label prefix inflate Jaro-Winkler similarity between unrelated companies. The fuzzy matcher scores 0.88-0.94 on completely different entities that share the structural prefix format.
- **Industry-header-as-name (3 cases)**: "Technology", "Industrials", "Retailers" matched to actual company names.
- **Rate/metadata-as-name (1 case)**: "Reference Rate and Spread S + 5.75%" matched to Eptam Plastics.
- **Entity fingerprint false matches (6 cases)**: E-tier matched different companies with similar FV (e.g., Greenlight Biosciences to Daring Foods, Cellares to Astranis).

### Pattern 3: Wrong Instrument — Debt vs Equity (6 cases)

Same entity, but debt position matched to equity position:
- BTR Opco Junior Secured Loans matched to BTR Opco Equity Securities (2 cases across quarters)
- FEH Group warrant matched to Class A common interest
- CCI Topco DIRECT_LENDING matched to COMMON_EQUITY
- Mold-Rite Plastics Super Priority Third Out matched to Second Lien Second Out (capital stack confusion)
- RLG Holdings First Lien matched to Second Lien

**Root cause**: The classification flip veto (Plan B) only operates when `index_classification` differs. In these cases, both sides had the same classification but different instrument types within that classification, or the classification was wrong on one side.

## Heuristic Flag Correlation

| Flag | Flagged | Error Rate | Unflagged | Error Rate |
|------|---------|-----------|-----------|-----------|
| flag_fv_ratio_extreme | 3 | 66.7% | 574 | 9.8% |
| flag_maturity_mismatch | 19 | 63.2% | 558 | 8.2% |
| flag_rate_discontinuity | 13 | 53.8% | 564 | 9.0% |
| flag_principal_ratio_extreme | 16 | 37.5% | 561 | 9.3% |
| flag_classification_flip | 1 | 100.0% | 576 | 9.9% |
| flag_name_divergence | 0 | n/a | 577 | 10.1% |

The flags have good precision (high error rate when flagged) but low recall — most errors occur in unflagged pairs (9-10% background error rate in C/D/E).

## What Improved vs v1

| Change | Effect |
|--------|--------|
| Wrapper name fixes (Plan A) | A-tier errors eliminated (2.5% to 0.0%) |
| Classification flip veto | Reduced cross-classification matches |
| Instrument sub-type veto | Reduced revolver-vs-term-loan confusion |
| Maturity mismatch veto | Reduced some D/E false matches |
| Suffix tiebreaker | Marginal improvement in tranche selection |

**B2 improved significantly** (7.6% to 3.1%) — the attribute tiebreakers and suffix matching helped.

**C-tier did NOT improve** (30.0% to 29.4%) — the hard gates don't help when the error is selecting the wrong position among multiple correct-looking candidates for the same entity.

## V2 Agentic Triage Decision

Per the Plan C decision framework, with weighted error rate at 2.0%:

> If residual rate is 1-3% with identifiable idiosyncratic patterns: v2 agentic triage is justified for C/D/E tier matches only.

**Decision: V2 agentic triage IS justified for C/D/E tier matches.**

The dominant error (wrong_tranche, 36 of 58) requires context-aware judgment that rules cannot easily provide — the algorithm needs to evaluate which of several same-entity candidates is the best match using full portfolio context. This is precisely what an agentic post-matching review step can do.

### Recommended v2 Design

1. **Bipartite matching** (Plan B Deliverable 6): Implement as a post-processing step for multi-position entities in C/D/E tiers. Use the Hungarian algorithm to globally optimize assignments based on FV proximity, rate similarity, maturity match, and instrument type.

2. **Agentic review for residual C/D/E matches**: After bipartite matching, flag remaining C/D/E pairs where:
   - Entity has 3+ positions at either date
   - Any heuristic flag is raised
   - FV ratio >3x or rate change >300bps

   An agent reviews these flagged pairs using portfolio context, similar to the calibration review protocol.

3. **CIK-specific prefix stripping for D-tier**: Goldman Sachs BDC and MidCap Financial's naming patterns inflate fuzzy scores. Add CIK-specific name normalization before Jaro-Winkler scoring.

## Methodology Note

This calibration used 7 sub-agents reviewing 146 bundles line-by-line, following the review protocol in `prompts/position_match_calibration_prompt.md`. Each agent read the full bundle JSON (match pairs + portfolio context) and applied the 5-point checklist (entity identity, instrument type, tranche discrimination, attribute consistency, alternative candidates).

An earlier heuristic-based review (0.1% weighted error rate) significantly underestimated errors by missing most wrong_tranche cases. The sub-agent review is authoritative.

## Files

| File | Description |
|------|------------|
| `data/output/position_match_calibration/sample.csv` | 600-pair sample with verdicts |
| `data/output/position_match_calibration/calibration_summary.md` | Machine-generated summary |
| `data/output/position_match_calibration/verdicts/` | 146 per-batch verdict JSONs (sub-agent) |
| `data/output/position_match_calibration/verdicts_v2_heuristic_backup/` | Heuristic verdicts (superseded) |
| `data/output/position_match_calibration/verdicts_v1_backup/` | v1 calibration verdicts |
| `data/output/position_match_calibration/bundles/` | Review bundles with portfolio context |
| `docs/position_match_calibration/calibration_results_v2.md` | This document |
