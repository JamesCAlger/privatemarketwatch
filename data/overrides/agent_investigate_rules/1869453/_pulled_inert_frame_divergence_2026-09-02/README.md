# Pulled 2026-09-02

rule_id: dedup_fiesta_revolver_partial_context_20260331
reason: apply-error in production: dedup on position_key, which is not in DEDUP_KEY_FIELDS (invalid rule passed a residual-already-zero gate pre-guard). Reauthored as row_exclusion on bdc_investment_identifier + fair_value=0.
Pulled by operator session 2026-09-02 (q1p3 inert-rule reauthor); replacement promoted through run_investigation gate.
