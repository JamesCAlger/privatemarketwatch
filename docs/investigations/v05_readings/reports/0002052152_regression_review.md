# Apollo regression GICS attribution - 2026-10-16

Reviewer: `/root/apollo_investigation_reviewer`.

**Result: all 130 changed sub-industry labels, and all 83 associated sector changes, are reproduced exactly by the historical GICS lookup change in commit `c8cf047`, independently of Apollo's new correctable-field support. This is causal attribution, not approval of the classifications or label losses.**

| CIK | Changed labels | Pre-commit replay matches rg2 | Current replay matches ao_rg2b | Labels lost | Changed sectors |
|---|---:|---:|---:|---:|---:|
| 0001742313 | 57 | 57 | 57 | 34 | 40 |
| 0001869453 | 73 | 73 | 73 | 4 | 43 |

## Evidence and method

- `rg2/output/company_gics_cache.csv` and `ao_rg2b/output/company_gics_cache.csv` are byte-identical: SHA256 `465fb2fdd6e9a5aff88394860603bde53df1804f4ef6c5d4a7eb89ef87f67097`, 32,270,986 bytes each. Cache drift does not explain these differences.
- Joined final holdings by row_id, selected every changed issuer family, and retained its other rows so the ambiguity check sees the full family, not just changed rows. This selected 815 final rows. Matched raw rows using CIK, accession and source-context ID, avoiding context-ID reuse across filings/funds. In-memory `_prepare_bdc` on those 815 raw rows reconstructed filed names with zero missing joins and no duplicate keys.
- Executed only `_apply_gics_to_holdings` extracted from `git show c8cf047^:pipeline/gics_classification.py`, and the current version, on the identical reconstructed frame and identical cache. All 130 historical labels match rg2, and all 130 current labels match ao_rg2b. Zero mismatches. No classification API, network call, full rebuild, tests, registry write or production artifact write was performed.
- The relevant commit changes the precedence from filed-name first to cleaned issuer first; filed-name lookup becomes a fallback and is withheld where an issuer's filed forms have conflicting labels. The other function inputs are held constant in the replay.
- Independently mapped old and new labels through the current GICS hierarchy: old sectors and new sectors match all 130 rows exactly. This accounts for the 40 + 43 changed sectors as deterministic consequences of the label changes.
- Current uncommitted `pipeline/unified_holdings.py` diff adds only `extracted_industry` to `_CORRECTABLE_FIELDS` with explanatory comments. The replay does not call `_apply_row_corrections`; the 130 changed rows have no extracted industry. Thus that Apollo support is not required to produce these differences.
- D-178 explicitly records fixing the precedence defect and replacing rg1 with rg1b while retaining rg2. Commit c8cf047 is dated 2026-10-15 13:26:23 +0100. This documentary history agrees with the measured old/new replay; chronology alone was not used as proof.

## Practical meaning and limits

The 38 lost labels are not silently accepted. The affected issuers are Relevate Health Group, SI Holdings (Integrated Polymer Solutions), Seran BioScience, and Fiesta Purchaser (Shearer's Foods). Historical cached guesses conflict for several of these issuers; withholding an ambiguous label is the implemented policy, but it still reduces coverage. Other changes include Storable from Application Software to Other Specialized REITs: reproducing cache precedence does not establish that the new classification is financially correct.

Confidence is high that c8cf047 fully explains this specific 130-row classification regression. This does not attest the global correctness of that commit, validate cached guesses against filings, authorize acceptance of the legacy deltas, or replace a complete quarter re-attestation. It also does not evaluate the separate signed-zero cost/provenance difference for CIK0001993402; that was outside this GICS replay.

Reproducible artifacts: `scratch/fund_runs/apollo_gics_replay.py`, `.log`, `_rows.json` (130 individual rows with original/filed names and old/new replay values), and `apollo_gics_summary.py`. The initial broad selections were stopped by explicit row-limit assertions; the completed replay used only 815 rows. The diagnostic process has exited; no build was left running.
