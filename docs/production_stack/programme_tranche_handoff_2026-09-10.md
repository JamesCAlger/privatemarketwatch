# First programme tranche: candidate complete, verification stopped

The stronger dependency proposal was implemented and the authorized additional build **succeeded**. The tranche remains **incomplete** because full-suite verification hit its time limit and wrote six empty cache files into a protected output directory. The [commentable review page](programme_tranche_review.html) is the main reading document.

## Completed

- Captured the physical Python environment and user packages: **247,333 files, 11.97 GiB**, including the metadata omitted earlier. Native isolation and actual holdings/matching/PIK preflight passed. Full stages checked runtime content before and after execution. Windows system components remain an explicit trusted boundary.
- Sealed all three stages of candidate `t1-runtime-20260910-v5`: **780,425 holdings**, **497,451 assigned position matches**, and **780,425 PIK status rows**. All **11 CSV/Parquet pairs** agree, including duplicates. Unified processing took approximately 36.7 worker minutes, identity 10.7 and evidence 1.3, plus controller checks.
- **68 focused tests passed** before the full suite. These do not verify the later test-isolation fix.
- Prepared the versioned 28-criterion/50-metric framework, 61 source dispositions, 20 label proposals, four full-schedule review requests and four remediation proposals. No independent reference approvals exist. The four proposed repairs remain unimplemented and concern different quarters; their values are not a portfolio-wide error total.

Completed stages and their exact parent identities are retained. Their format and execution checks do not establish financial accuracy. Candidate measurement, semantic comparisons between its stages and the frozen starting data, and the actual timeout/reuse/restore drill did not run. All **50 programme metrics remain UNMEASURED** in the stopped status inventory.

## What stopped

Full pytest reached its **90-minute controller allowance** at approximately 79% progress. The complete controller job, including protected-file inventories, took 96.49 minutes. **Four failure markers** appeared earlier; no final traceback or JUnit report was produced. The worker and its children were terminated. The earlier version of this handoff incorrectly counted one marker. The owner's subsequent [bounded investigation](programme_verification_investigation_2026-09-10.md) reproduced all four failures and preserved their tracebacks: three stale wrapper-version assertions and one regex-validator dialect mismatch. The original sealed handoff remains historical evidence with this correction.

The outer controller detected six new zero-row Parquet query caches under `data/output/agent_investigate/_qcache/666/` and `/999/`, totalling **9,580 bytes**. All 237,621 pre-existing protected files retained their size and modification time; none was deleted. This is not a content-hash proof of every protected file.

The mechanism is confirmed: investigation `prep()` prewarms `agent_data_query.describe()`. Tests mocked the investigation directory but missed the query module's separate cache root and real default sources. Native DuckDB `COPY TO` bypasses the Python file-open guard. The suite timed out before pytest's final inventory check; the outer controller caught the writes.

The [approved tranche](programme_execution_tranche_2026-09-09.md) requires: **"Stop the tranche for attempted writes to protected production/reference/baseline assets"**. At that stop, further tests, candidate measurements and recovery workloads ceased; read-only preservation and handoff preparation continued. The owner's later instruction, "investigate the issues", authorized a separate bounded diagnostic exercise. It did not restart the expired eight-hour tranche.

## Test correction and remaining work

The fix redirects query caches to each test's temporary folder, isolates orchestration prewarming from real sources, and adds a file-backed cache/CIK-filtering regression case. **All 54 cache/query and orchestration tests passed in the subsequent bounded investigation**, with native write prevention and unchanged protected-output metadata. Production query behavior is unchanged. The original [prepared-fix record](programme_tranche_evidence_2026-09-10/test-boundary-fix-v1/status.json) remains historical; the [investigation](programme_verification_investigation_2026-09-10.md) records subsequent verification, stale-version test repairs, remaining staging cost and diagnostic-controller defects.

Next: correct the production regex validator, incorporate the diagnostic native boundary and durable outcome handling into full-suite execution, finish the suite with sufficient measured time, then validate and reuse the sealed candidate for integrated measurement and recovery verification. Rebuild only when relevant frozen inputs or execution code changed. The [updated proposal](programme_tranche_resume_proposal_2026-09-10.md) explains this sequence and the authorization boundary.

Automatic approval review rejected removal of the six files as **"blocked by policy"**, with no further reason. They remain in place. Their hashes, zero-row counts, before/after inventory evidence and forensic copies are preserved in [the incident record](programme_tranche_evidence_2026-09-10/test-boundary-failure-v1/diagnosis.json).

## Preservation and limits

The read-only preservation check **passed**: all **1,117** frozen original pipeline/data/control files, **1,605** used matching-reference files, original gold labels and both source-reference freezes retain their hashes. The five-artifact semantic comparison found no material change from the pre-run record under the existing numeric-noise rule. It retains the existing official-baseline differences: holdings 11 groups, matches 7, position returns 7, index returns 6, fund financials zero. Twenty-one derived aggregate differences are recorded as floating-point roundoff; no tolerance was widened.

The broader byte-plus-semantic scan timed out before producing its report. The narrower semantic check completed without further changes among 237,627 protected files. This is **not a clean-baseline or whole-tree content-hash claim**. The six added cache files remain a separate incident; preservation of original inputs does not clear it. See the [preservation result](programme_tranche_evidence_2026-09-10/boundary-preservation-v1/result.json) and [sealed stopped handoff](programme_tranche_evidence_2026-09-10/handoff-boundary-v1/verification.json).

The sealed candidate has not been adopted. No production holdings rebuild/export, frontend application build, baseline refresh, SEC download, paid enrichment, original-gold promotion or delegated agents ran. The target schema, all-in rate, dbt, persistent identity and public PDF citation work remain later implementation packages. Legacy rate and position-ID behavior remain in place.

The original window was **08:43:01-16:43:01 UTC on 10 September 2026**. The [work record](programme_tranche_2026-09-10_work_record.md) and tranche ledger preserve process ownership and timing. Earlier v3 outputs remain unsealed; historical stopped evidence was not overwritten.
