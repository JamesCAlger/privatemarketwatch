# Full-suite failure diagnosis

2026-10-17, independent reviewer `/root/apollo_investigation_reviewer`. Bounded read-only diagnosis. No shared code, inputs, gates or dispositions changed; no network or builds. Full-suite result supplied by root and checked against its failure log: 6650 passed, 5 failed, 13 skipped, 2 xfailed; exit 1. No protected-output violation reported.

## 1. Anchor adjudicator: cached basis differs from test premise

`test_override_agreeing_with_companyfacts_yields_high` supplies an ex-cash override of 691,956,192. Actual candidate reconstruction returns `companyfacts_fv_plus_cash=699051778` and `verified_investments_ex_cash=691956192`. Their relative disagreement is 0.01015030105538191, exceeding the 1% threshold, so NONE follows deterministically. The test comment assumes an agreeing ex-cash companyfacts candidate; current cached holdings trigger the cash-inclusive candidate instead.

`load_anchor_candidates` intentionally preserves the higher-basis cash-inclusive candidate when an ex-cash override differs. The basis-aware handling predates Apollo (b9af645, 2026-09-08). Neither the four-line correction allowlist change nor Apollo's CIK-specific row/match inputs is on this test path. Evidence: `apollo_failure_evidence.py/.log`. This establishes the current failure mechanism, not the historical date on which cached holdings began triggering it. Do not raise the tolerance or discard the cash candidate to pass this test.

## 2. Financial migration: obsolete expectation contradicts owner ruling

`test_final_writer_rate_income_donors_and_registry_replay_are_one_contract` expects absent R2 cost to become 100 from the first observed fair value. Commit `69f9daa` (2026-10-12) added `config.COST_PROXY_ENABLED=False`, explicitly documenting the owner's instruction that rows without filed cost publish no cost. `identity_finalization.finish` passes this flag to `cost_proxies`; the observed NaN is consistent with that decision. The fixture uses CIK 0000000123, whereas all four new reject-only directives apply to Apollo. Its four-unmatched warning is input leakage into the fixture, not evidence of an applied match rejection: the preceding one-position-chain assertion passes.

Do not restore proxy costs merely to satisfy the stale assertion. The integration test needs to express the decided disabled-proxy contract while retaining separate, explicitly enabled donor coverage where appropriate. No such edit was made here.

## 3. Principal-reference FX: stale five-fund scope assertion

`test_only_the_five_sample_funds_opt_in` asserts a five-CIK subset against the live wrapper store. Independently enumerating tracked wrapper JSON at HEAD found 37 `principal_usd_reference` opt-ins, including Apollo already at HEAD. MidCap alone disproves the subset and was added in `fb441d8` (2026-10-10). Thus failure is present in committed inputs independently of the current Apollo edits. This diagnosis does not approve each of the 37 opt-ins; the test's five-fund scope is demonstrably stale.

## 4. Programme source-refresh count: committed extraction inputs outgrew pin

For `0000930413-26-001612` (Lord Abbett), the source hash assertion passes, but parsed/deduplicated count is 351 versus pinned 350. The affected extractor modules and Lord Abbett wrapper have no uncommitted Apollo changes; the only pipeline diff is an allowlist in unified_holdings, which this direct parsing test does not call.

Relevant committed change `fb441d8` (2026-10-10) added the exact wrapper declaration `0000930413-26-001612 c355 => Arkas Bidco Limited Equity` plus bare-entity position handling. `page_labelled_contexts.name_declared_contexts` marks declared contexts as investments, providing a concrete mechanism for an extra extracted row. The source-refresh registry still carries the old 350-row pin. This is strong attribution to pre-existing extraction/registry drift rather than Apollo. However, this bounded review did not parse both historical configurations and identify the extra row by set difference; it therefore does not certify c355 as the sole count cause or approve changing the count pin. A source-grounded row delta remains the next verification step.

## 5. Programme source snapshot: stale reviewed wrapper hash

`test_registered_refresh_support_matches_reviewed_cached_wrapper` correctly rejects the Lord Abbett wrapper hash. Pin: `034e45de3cc88751e7543e3b808d3d68ec986fff3c2fa34a422aa614f0c7bec8`. Current disk: `e3fc5e6973dae3ef5601519902fadf11c42a3700279c710a0c1489b1e84d5ddc`. HEAD blob: `d8a6d090593d00ceb74d5d5c38609abd5a589ad39623b04766e6aaaed52fbfc5`. Disk and HEAD are identical after CRLF/LF normalization; the hash pin disagrees with both. Committed semantic changes include fb441d8's context declaration and e3fdc6b (2026-10-13)'s issuer/instrument stripping. No Apollo edit changed this wrapper.

The evidence script also detects mismatching BCRED and Goldman II support pins; this test stops at Lord Abbett, so repairing only its first error would not establish a clean registry. Do not refresh hashes without reviewing dependent extraction changes. Hash comparisons are byte-sensitive; newline differences between working-tree files and Git blobs were explicitly accounted for when assessing content equality.

## Verification and limits

Named evidence scripts and logs reside in this directory. A diagnostic pytest plugin removes `extracted_industry` from the correction allowlist in memory and redirects position-match overrides to an empty temporary directory. Only the two exact failed anchor/migration nodes were selected, with normal protected-output guards. Its final outcome is recorded below once the process exits. No full-suite rerun or source-refresh rebuild was launched. The code/data evidence supports pre-existing failure conditions; it does not make the suite green or waive source-refresh review.

Counterfactual rerun completed: **2 failed in 101.83 seconds**, exit 1, at the same assertions (NONE versus HIGH; NaN versus 100). No unmatched-override warning and no protected-output violation. This directly rules out the Apollo allowlist and match directives as necessary causes of these two failures. Log: `apollo_failure_baseline_rerun.log`; plugin: `apollo_failure_baseline_plugin.py`. No semantic output diff was rerun in this bounded diagnostic; the normal native-IO manifest guard completed without a violation. Final process inspection found no Python processes. All writes stopped after this note.
