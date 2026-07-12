# Resume handoff -- 2026-06-28 (pre-restart)

Snapshot of in-flight work so it can resume cold after a machine restart. Branch
`shadow-ledger-cohort-gate`. None of the changes below are committed.

## 1. Cash decision (DECIDED: cash OUT of v1)

Cash-equivalents (T-bills, money-market sweeps) are **excluded from v1** -- simpler than keep-but-exclude.

Done:
- `pipeline/agent_rule.py` `value_sum_by_quarter`: excludes `asset_category=CASH` from the conservation
  sum (rows retained in the frame, only omitted from the sum). `CONSERVATION_EXCLUDED_CATEGORIES={CASH}`.
  +1 test (`test_value_sum_excludes_cash_but_keeps_rows`); 40 pass.
- `scripts/shadow_conservation_engine.py`: same `AND upper(COALESCE(CAST(asset_category AS VARCHAR),''))
  <> 'CASH'` exclusion in the `_sum_{rule.name}` residual CTE, so engine residuals == gate value_sum.
- Changelog appended (2026-06-28 entry).

Verified: 2031750 value_sum(excl cash) $3,122.9M vs IOAFV $3,120.4M = 0.08% -- reconciles with the
$533M of T-bills KEPT in holdings.

Still TODO (folds into classification work, below):
- Exclude cash from the *published* product holdings (only the conservation sum excludes it so far).
- The `asset_category=CASH` lever is only ~80% complete -- see audit below.

## 2. Classification issues (HANDED OFF)

Audit of unambiguous cash-equivalents (BDC rows): **204 correctly CASH ($10.2B), but 18 mislabeled
LOAN ($1.44B) + 6 OTHER ($0.92B) -- ~19% of cash-equiv FV mislabeled.** Includes a row literally named
"Cash Equivalents US Treasury Bill" sitting under LOAN. So `asset_category=CASH` alone misses ~$2.36B.

Root cause: `asset_category` is keyword-guessed from `issuer_name` (`_CASH_KEYWORDS` etc. in
`pipeline/unified_holdings.py`); the classifier UNDER-USES structure that iXBRL already extracts
(`bdc_dimensions_raw`, the `investment_identifier` prefix, sometimes a type axis). Same filing-lineage
gap that blocks the conservation look-throughs (1975736).

Approach for the next agent (do NOT grow keyword lists -- AGENTS.md forbids): (1) measure misclassification
across all categories first; (2) check what category signal iXBRL already provides vs keyword-guesses;
(3) three-tier fix -- high-precision rules w/ borrower-name guards, derive from filer's own SOI section/
type-axis, agentic review on residuals. Full hand-over prompt is in the chat transcript for this session
(2026-06-28); re-paste it to the classification agent.

## 3. Three-CIK re-run (READY TO RUN)

After the filing-parser change (bundle/filing now wired into B2 + 0.5% rounding tolerance), re-run the
three look-through/anchor CIKs so they re-author with the filing visible:

```powershell
cd "C:\Users\alger\Documents\000. Projects\005. evergreen funds platform xbrl"
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\rerun_filing_parser_three.ps1
```

- CIKs: 1975736 (KKR FS 10-K), 1803498, 1930087 -- all in B1 batch `restall`, all `fv_conservation`
  @ 2025-12-31, all have existing bundles (filing reachable).
- Wrapper around `run_investigation_canary.ps1 -B1BatchId restall -OnlyCik <three> -Fresh`. `-Fresh`
  clears prior rules/escalations/derived artifacts. B3-gates and prints verdicts at the end.
- MUST run from an operator shell OUTSIDE a Codex session (conda-activated) -- the canary asserts this.
- A clean PASS is NOT guaranteed; a re-escalation with the filing now visible is a valid outcome.
- After it runs, gate summary: `data/output/agent_investigate/batch/investigate_restall/b3_gate_summary.csv`.

## 4. Deferred (unchanged from before)

- gap-1 production application (apply promoted rules/overrides to unified holdings so multi-pass converges).
- The 6 cash-dropping CIKs (2031750, 1954360, 1965934, 1920145, 1976336, 2052152) -- production holdings
  were NEVER modified, so the cash is still there; re-run them against the cash-excluded sum so they
  re-author without dropping cash. (Lower priority now that cash is out of v1.)
