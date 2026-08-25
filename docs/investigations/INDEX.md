# Data Investigations Index

GENERATED -- do not edit by hand. Rebuild: python scripts/split_investigations.py --reindex

## Holdings classification & EDA ([classification_holdings_eda.md](classification_holdings_eda.md))
- 1. Position Classification Stability Across Quarters (2026-04-07)
- 2. Firm-Level Exposure Breakdown (2026-04-08)
- 5. BDCs with Holdings but Missing from Unified (2026-05-04)
- 2026-06-16 - Derivative universe characterization + hedge-vs-portfolio base rates
- iXBRL capture of instrument type (revolver / DDTL / term loan), like lien (2026-06-17)
- 2026-06-17 - iXBRL field-status overlay was joining on the WRONG key; fix recovers lien/maturity
- Per-position instrument-type XBRL reconciliation: measured ~0 lift (2026-06-17)

## Frontend / public data checks ([frontend_data_checks.md](frontend_data_checks.md))
- 2026-05-17: BDC Credit Stress Chart Validation
- Blackstone Private Credit Fund return chart drop - 2026-05-17
- 2026-05-24 - Frontend Fund and Position Data Source Spot Check

## Data-quality audits & triage ([data_quality_audits.md](data_quality_audits.md))
- Fund financials schema flags audit - 2026-05-17
- Validation warning triage - 2026-05-17
- Non-accrual reconciliation - 2025q4
- Data quality root-cause audit - 2026-05-18
- Universe gating residuals - 2026-05-18
- 2026-06-15 - bdc_fund_highlights balance-sheet fields broadly unreliable

## Source reconciliation & blocker chains ([source_reconciliation.md](source_reconciliation.md))
- BDC source reconciliation blockers - 2026-05-19
- BDC source-only blocker classification - 2026-05-20
- BDC source-only percentage hierarchy split - 2026-05-20
- Crescent hierarchy percentage leaf parser repair - 2026-05-20
- Aggregate leak suspect spot-check review - 2026-05-21
- BDC source-blocker manual review progress - 2026-05-27
- 2026-05-27 - MSD Investment Corp. Source-Reconciliation Blocker
- 2026-06-17 - JV look-through double-count: BCRED Emerald JV ($6.5B), surfaced via gold-set labeling
- 2026-07-21 - Do high-FP review rules catch real errors no other rule catches? (unique-catch analysis)
- 2026-07-21 (part 2) - Row-level unique-catch analysis: high-FP rules DO catch unique row-level errors
- 2026-07-21 (part 3) - Disposition-trace diagnosis of source-only blocking rows: the parser loses NOTHING; drops are aggregate-filter and promoted-rule effects
- 2026-07-21 (part 4) - Row-level verification of Wave-1 promoted exclusions against the E1 blockers
- 2026-07-21 (part 5) - Phase-2 semantics adjudication of the five verified promoted-exclusion rules (printed-SOI evidence)
- 2026-07-22 (part 6) - Two evidence-class excusal mechanisms added to the source-only classifier; blocking pool 2,305 -> 2,065
- 2026-07-22 (part 7) - Attribution of the rule-unexplained E1 drops (Ares $14.8B solved)
- 2026-07-22 (part 8) - Global JV-axis staging drop REJECTED by evidence; the pipeline already has a retain-and-flag design the conservation engine ignores
- 2026-08-25: pct_sense_check "context-to-position pairing defect" -- resolved, no pairing defect exists

## Per-CIK wrapper residual reviews ([wrapper_residuals.md](wrapper_residuals.md))
- 2026-06-04 - Golub bare-name 2024-06-30 wrapper residuals
- 2026-06-04 - Oaktree wrapper comparison against cached HTML
- 2026-06-05 - North Haven wrapper comparison against cached HTML
- 2026-06-05 - Monroe wrapper economic-reality residual review
- 2026-06-05 - Ares Core Infrastructure cached HTML wrapper check
- 2026-06-05 - Barings Private Credit wrapper residual closeout
- 2026-06-05 - MidCap Financial wrapper residual closeout

## Conservation / shadow-panel engine ([conservation_shadow_engine.md](conservation_shadow_engine.md))
- 2026-06-15 - Top overshoot 0001851322 2025-12-31 = duplicate filing (10-K + 10-K/A)
- 2026-06-15 - Shadow-gate overshoot bucket: concentrated in ~5 funds, not 204
- 2026-06-15 - Dominant-fund overshoot diagnosis: issuer-subtotal duplication in UNWRAPPED CIKs
- 2026-06-16 - Shadow-panel adapter assessment: false positives in conservation engine + fund_financials MODERATE
- 2026-06-16 - Shadow panel: complete surfaced-category assessment (all 6,441 surfaced flags)
- 2026-06-16 - Re-anchoring the conservation engine: explored, not worth it (retirement validated)
- 2026-06-16 - cost_conservation is WORSE than fv_conservation (do not keep cost-only)
- 2026-06-16 - CORRECTION: a fund-level reported cost DOES exist (companyfacts InvestmentOwnedAtCost)
- 2026-06-16 - "15 leaked category headers" RESOLVED: MidCap flattened-identifier issuer mis-parse (not subtotal leaks)
- 2026-06-16 - Strong-anchor blind-spot profile: broad, skews pre-XBRL/N-PORT; published cohort 25.7%
- 2026-06-16 - BDC cross-target anchor coverage: CUSIP zero, N-PORT issuer coupled to paused entity resolution

## Identifier & rate semantics (Agent A) ([identifier_rate_semantics.md](identifier_rate_semantics.md))
- 2026-06-19 - Structured-XBRL-twin coverage for freeform investment_identifier (Agent A anchor budget)
- 2026-06-19 - Format-signature (cik, shape) clustering probe: TWO REGIMES, naive mask is regime-dependent
- 2026-06-20 - Why text-spread disagrees with the XBRL basis_spread tag (Agent A gold conflicts)
- 2026-06-20 - CORRECTION to the above: all-in reconciliation REVERSES it (tag, not text)
- 2026-06-21 - Twin (structured) vs identifier (text) disagreements: who is right, and where to resolve
- 2026-06-23 - Why the 8 Agent A "completeness" FAILs fail: 0% encoding, ~84% regex/sampling, ~16% scope-out
- 2026-07-20 - XBRL linkbase-layer evidence: rate-concept fingerprints, presentation labels, calc arcs, domain-default anchors

## Agentic campaign retrospectives ([agent_campaigns.md](agent_campaigns.md))
- 2026-07-07 - Per-fingerprint stratification retrospective re-cut of ens2 B1 adjudications
- 2026-08-20 - B2 correction-agent Q4 2025 track record: cross-batch metrics rollup + round-4 fleet acceptance criteria

## Quarter-over-quarter EDA ([quarter_eda.md](quarter_eda.md))
- 2026-07-24 - Why Q1 2026 has fewer facts than Q4 2025 (quarter-over-quarter EDA)
- 2026-07-24 (part 2) - Per-fact shadow rule-firing comparison, Q4 2025 vs Q1 2026

