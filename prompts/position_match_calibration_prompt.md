# Position Match Calibration Review Prompt

You are reviewing position match pairs to establish ground-truth error rates
for the position matching pipeline. Your verdicts will be used to calibrate
heuristic thresholds and measure true match accuracy by tier.

## Input

You will receive a JSON bundle at `data/output/position_match_calibration/bundles/BATCH_{NNN}_{CIK}.json`.

Each bundle contains:

- **match_pairs**: 1-5 match pairs to review, each with begin/end side attributes
  and heuristic flags
- **portfolio_context**: all holdings for the CIK at each referenced report_date,
  filtered to same-entity positions plus top-20 by FV for broader context
- **filing_paths**: paths to source XBRL files (for reference only)

## Task

For each match pair, determine whether the begin-side and end-side positions
refer to the **same financial instrument** tracked across consecutive quarters.

## Decision Process

For each pair, work through this checklist:

1. **Same entity?** Do the begin and end `issuer_name` values refer to the same
   company? For fuzzy matches (tiers D/E), check carefully -- similar names may
   be different entities.

2. **Same instrument type?** Compare `instrument_description`,
   `index_classification`, and `lien_position`. A first lien term loan is not
   the same instrument as a second lien term loan or an equity co-investment.

3. **Same tranche?** Check the portfolio context: does this entity have multiple
   positions at either date? If so, verify the match selected the correct one.
   Look at `bdc_investment_identifier`, `position_key`, `interest_rate`,
   `maturity_date`, and `principal_amount` for tranche-level discrimination.

4. **Consistent attributes?** For a correct match, FV, rate, principal, and
   maturity should be consistent with a single instrument moving across quarters:
   - FV changes of <50% are typical; >10x is suspicious
   - Interest rate changes of <200bps are typical for floating-rate loans;
     >500bps suggests different instruments
   - Maturity date should be identical or within 90 days (amendments happen)
   - Principal should be broadly stable (prepayments happen but 5x changes are
     suspicious)

5. **Alternative candidates?** Check the portfolio context to see if there was a
   better match candidate that the algorithm missed.

## Verdict Labels

Use exactly one of these labels per match pair:

- **`correct_match`** -- Same position, correct tranche. The begin and end sides
  are the same financial instrument.

- **`wrong_tranche`** -- Same entity, different instrument. For example, a first
  lien term loan matched to a second lien term loan, or a term loan matched to a
  revolver at the same company.

- **`wrong_entity`** -- Completely different borrower. The issuer names refer to
  different companies.

- **`wrong_instrument`** -- Same entity, fundamentally different instrument type.
  For example, debt matched to equity, or a loan matched to a bond.

- **`ambiguous`** -- Cannot determine from available data. Use this sparingly and
  explain what information is missing.

## Confidence Levels

- **`high`** -- Clear evidence supports the verdict. Multiple attributes confirm.
- **`medium`** -- Verdict is likely correct but some attributes are missing or
  ambiguous.
- **`low`** -- Verdict is uncertain; limited discriminating information available.

## Evidence Requirements

For each verdict, write a brief `evidence_summary` (1-3 sentences) citing
specific attributes that support your conclusion. Examples:

- "Same issuer, same instrument type (First Lien Term Loan), FV moved from $10M
  to $10.2M (2% change), rate consistent at 10.5%. Only one Acme Corp position
  exists at both dates."
- "Begin side is First Lien Term Loan (rate 8.5%, maturity 2028-06-15). End side
  is Second Lien Term Loan (rate 12.0%, maturity 2029-01-15). Fund holds both
  tranches at end date. Matcher selected wrong one."

## Output Format

Write your verdicts to `data/output/position_match_calibration/verdicts/BATCH_{NNN}_{CIK}.json`:

```json
{
  "batch_id": "BATCH_001_0001287750",
  "reviewer": "claude_code",
  "reviewed_at": "2026-06-10T15:30:00",
  "verdicts": [
    {
      "sample_row_key": "abc123...",
      "review_label": "correct_match",
      "review_confidence": "high",
      "evidence_summary": "Same issuer, same instrument type..."
    }
  ]
}
```

## Constraints

- **Bundle-only evidence.** Base verdicts solely on data in the bundle JSON.
  Do not look at external files or make network calls. Verdicts must be
  reproducible from bundle data alone.
- **Position-level semantics.** Each position is a distinct financial instrument.
  Two loans to the same company are two different positions. Do not merge them.
- **Conservative on ambiguity.** If you cannot determine the verdict, use
  `ambiguous` rather than guessing. A calibration sample with honest ambiguity is
  more valuable than one with forced verdicts.
- **Review all pairs.** Every match pair in the bundle must receive a verdict.
  Do not skip pairs.
