# Plan C: Re-Calibration

Status: Not started
Depends on: Plan A (wrapper layer) and Plan B (matching algorithm) both complete
Blocks: Decision on v2 agentic triage

## Motivation

Plans A and B introduce wrapper fixes and matching algorithm gates based on the 2026-06-11 calibration findings (4.2% weighted error rate, 112 errors in 600 pairs). After those changes are implemented, the position match output will be different -- some previously-matched pairs will be rejected by new gates, some previously-mismatched pairs will match correctly due to fixed issuer names.

A second calibration round is necessary to:
1. Measure the actual post-fix error rate (vs the projected estimates in Plans A/B)
2. Discover whether the fixes introduced new failure modes
3. Determine whether residual errors are systematic (more rules needed) or idiosyncratic (agentic triage justified)
4. Provide updated per-tier error rates for J05/J06 oracle threshold calibration

## Deliverables

### 1. Rebuild position matches

```bash
python scripts/rebuild_outputs.py --unified
```

This rebuilds unified holdings (incorporating wrapper fixes from Plan A) and position matches (incorporating algorithm gates from Plan B).

### 2. Re-run 600-pair calibration

```bash
python scripts/calibration_review.py --generate
```

Use the same sample design (same tier allocation, same seed) to generate a new 600-pair sample from the rebuilt matches. The sample will be different because:
- The match population changed (some pairs rejected by new gates)
- Some positions previously matched via D/E now match via B2 (due to fixed issuer names)
- Tier populations shifted

Note: the same seed produces deterministic selection within each tier, but the rows available in each tier have changed, so the sample will not be the same 600 rows.

### 3. Review all 600 pairs

Use the same review workflow as the first calibration: batch into ~150 bundles, review via sub-agents, collect verdicts.

### 4. Compute and compare calibration metrics

```bash
python scripts/calibration_review.py --collect
```

Compare against the 2026-06-11 baseline:

| Metric | Baseline (2026-06-11) | Post-fix target |
|--------|----------------------|-----------------|
| Weighted error rate | 4.2% (CI: 1.2%-7.1%) | <2% |
| A_within_filing | 2.5% | <2% |
| B1b_position_key | 2.5% | <2% |
| B2_exact_name | 7.6% | <4% |
| C_normalized_name | 30.0% | <15% |
| D_fuzzy | 22.5% | <8% |
| E_entity_fingerprint | 23.3% | <5% |

### 5. Residual error analysis

Classify any remaining errors into:
- **Systematic**: same root cause affects multiple matches -> new rule needed (iterate Plans A/B)
- **Idiosyncratic**: unique per-match circumstances, no common pattern -> agentic triage candidate (v2)
- **Irreducible**: genuinely ambiguous cases where ground truth cannot be determined -> accept as noise floor

If systematic errors remain, document them as amendments to Plans A/B and iterate before declaring the calibration complete.

### 6. V2 agentic triage decision

Based on the residual error analysis:
- If residual weighted error rate is <1% and remaining errors are idiosyncratic: v2 agentic triage is not worth the complexity. Accept the error rate.
- If residual rate is 1-3% with identifiable idiosyncratic patterns: v2 agentic triage is justified for C/D/E tier matches only. Design a post-matching review step where an agent evaluates flagged matches using bundle context.
- If residual rate is >3%: systematic issues remain. Do not build agentic triage -- fix the rules first.

## Verification

- Calibration sample sums to 600 (`--dry-run`)
- All 600 verdicts collected (no missing batches)
- Weighted error rate computation matches manual spot-check of 20 verdicts
- Comparison table against baseline is produced and documented
- Residual errors are classified with evidence

## Files to create/modify

| File | Action |
|------|--------|
| `data/output/position_match_calibration/` | Regenerated sample, bundles, verdicts, summary |
| `docs/position_match_calibration/calibration_results_v2.md` | Post-fix calibration results and comparison |

## Timeline dependency

This plan cannot start until both Plan A and Plan B are complete and their changes are merged into the rebuilt outputs. The rebuild itself takes ~60 seconds for unified holdings + position matches. The review of 600 pairs takes ~2-3 hours of agent time.
