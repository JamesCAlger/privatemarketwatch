# Order-dependent row-pick site inventory

This document catalogs every production site in the BDC/unified holdings pipeline
where row-pick outcomes can depend on physical dataframe or cursor order rather than
deterministic sort keys. Sites were identified by the 2026-08-24 scout pass over all
paths feeding `bdc_holdings.csv` and `private_markets_holdings.csv`.

The twin-build gate is the standing regression test for this invariant: run
`python -m pipeline.main --unified` twice in sequence and assert the two artifacts
are content-identical (DuckDB EXCEPT both directions = 0 rows). This gate is strictly
binary -- no accepted-flip residuals going forward. The twin-build gate proves
determinism for the current cached inputs; sites listed with residual dispositions
rely on stable cache read order and are the follow-up worklist. Future work that
adds a new ORDER BY or window-function pick site MUST (a) append the anchor keys
(`src_context_id` / `nport_holding_id`) as final sort keys and (b) include an
order-invariance test asserting the same survivor regardless of input frame order.

## Site table

Scope: production paths feeding `bdc_holdings.csv` and `private_markets_holdings.csv`.
Severity: FLIP-PRONE = ties realistic and physical row order decides;
DETERMINISTIC-ALREADY = ordering keys complete; ORDER-IRRELEVANT = commutative aggregate.

| # | File:Line | Function/CTE | Partition key | Current ORDER/sort keys (verbatim per scout) | Anchor cols in scope | Severity | Disposition |
|---|-----------|--------------|---------------|---------------------------------------------|----------------------|----------|-------------|
| S1 | staging_bdc.py:1325 | CTE raw (_row_id numbering) | global | cik, report_date, accession_number, investment_identifier, dimensions_raw, fair_value | accession, dims | DETERMINISTIC-ALREADY (numbering) | already deterministic |
| S2 | staging_bdc.py:1395 | no_amendments | cik, report_date, form_type_stripped | filing_date DESC, accession_number DESC | accession | DETERMINISTIC-ALREADY | already deterministic |
| S3 | staging_bdc.py:2127-2154 | no_affil_dupes | cik, accession, report_date, name/instr/fv/cost/pa/sh | affil-score, LENGTH(_raw_id), _raw_id, dimensions_raw, affiliation, _row_id | accession, _row_id; src_context_id in frame | FLIP-PRONE (final key _row_id is scan-order) | hardened (this migration) |
| S4 | unified_holdings.py:864 | nport_deduped | cik, rd, name/instr/fv(-2)/pa/sh/maturity/cat/cusip | nport_quarter DESC, accession DESC, nport_holding_id, cusip, fv, cost, sh | accession, nport_holding_id | FLIP-PRONE (blank holding_id ties) | residual: appended keys were already in the ORDER BY (no-op); blank-holding-id payload ties remain physical-order, twin-build-stable via cache read order only; real fix (payload-column ORDER BY, mirroring S16) scheduled as a re-gated follow-up |
| S5 | unified_holdings.py:923 | deduped (cross-source) | cik, rd, name/instr/fv(-2)/pa/sh | source-pref, accession DESC, bdc_id, nport_id, cusip, fv, cost, sh | accession, bdc_id, nport_id, src_context_id | FLIP-PRONE (same-source residual dupes) | hardened (this migration); attenuated blank-holding-id residual, see S4 |
| S6 | unified_holdings.py:994 | bdc_dim_ranked | cik, accession, rd, name/instr/fv/pa/sh | LENGTH(issuer_name), issuer_name, bdc_investment_identifier, accession | accession, bdc_id; src_context_id in staged frame | FLIP-PRONE (accession constant in partition) | hardened (this migration) |
| S7 | unified_holdings.py:1072 | with_cost FIRST_VALUE | cik, issuer, instr_norm, cusip | report_date, fair_value, accession, bdc_id, nport_id, shares_held | accession, bdc_id, nport_id, src_context_id | FLIP-PRONE | hardened (this migration) |
| S8 | unified_holdings.py:1107/1118 | with_shares_fix LAST/FIRST_VALUE | cik, issuer | report_date, accession, bdc_id, nport_id, _sh_val | accession, bdc_id, nport_id, src_context_id | FLIP-PRONE | hardened (this migration) |
| S9 | unified_holdings.py:262 | _stabilize_classification ranked | class group | n_q DESC, cls (alphabetical) | n/a | DETERMINISTIC-ALREADY | already deterministic |
| S10 | staging_bdc.py:2727 | canonical casing QUALIFY | cik, LOWER(issuer_name) | _cnt DESC, uppercase-penalty, issuer_name | _row_id | DETERMINISTIC-ALREADY | already deterministic |
| S11 | bdc_filings.py:1042 | _dedupe_row_order stamp | whole frame | range(len(result)) physical order | _context_id in frame | FLIP-PRONE (primary residual source) | hardened (this migration) |
| S12 | bdc_filings.py:1125/1136 | dedup pick + fill sort | _EFFECTIVE_KEY | _dedupe_score DESC, _dedupe_row_order ASC | _context_id | FLIP-PRONE | hardened (this migration) |
| S13 | bdc_filings.py:1077 | null-FV best_key pick | _DEDUP_KEY_COLUMNS | _dedupe_score DESC, _dedupe_row_order ASC -> groupby().first() | _context_id | FLIP-PRONE | hardened (this migration) |
| S14 | unified_holdings.py:680 | _apply_unclassified_cache dedup | name_norm | drop_duplicates(keep="first"), no sort | none (cache CSV order) | FLIP-PRONE | hardened (this migration) |
| S15 | bdc_xbrl_html_bridge.py:294 | load_bridge_table dedup | cik, accession, rd, raw_id_lower | keep="last" (JSON iteration order) | accession | FLIP-PRONE (supplementary fields) | hardened (this migration) |
| S16 | bdc_xbrl_html_bridge.py:1085 | wrapper-columns overlay dedup | _k | keep="last" | accession | FLIP-PRONE (supplementary) | hardened (this migration) |
| S17 | agent_rule.py:297 | _apply_dedup (agent rules) | agent-authored match_fields | keep first/last on reset-index frame | anchor cols in frame | FLIP-PRONE | hardened (this migration) |
| S18 | agent_promoted.py:525 | entity_name mode fill | cik | sorted(mode())[0] | n/a | DETERMINISTIC-ALREADY | already deterministic |
| S19 | unified_holdings.py:1758 | _apply_wrapper_position_keys lot rank | cik, source, rd, position_key | _principal_abs DESC, _fv_abs DESC, _cost_abs DESC, _source_index ASC (physical) | src_context_id/nport_id in frame; row_id not yet | FLIP-PRONE (lot suffix flips) | hardened (this migration) |
| S20 | staging_nport.py:124 | level3 ROW_NUMBER() OVER () | global | none (undefined order) | nport_holding_id downstream | FLIP-PRONE (label only) | hardened (this migration); attenuated blank-holding-id residual, see S4 |

## Deep-dive findings and resolutions

### S11-S13: `_assign_row_ids` and extractor dedup (Task 1)

`_deduplicate_bdc_holdings` in `bdc_filings.py` stamps `_dedupe_row_order` from
`range(len(result))` (physical scan order) before sorting by score. When two candidate
rows have equal `_dedupe_score`, the winner was determined by whichever row happened
to appear earlier in the pandas DataFrame -- a function of OS I/O ordering and XBRL
parse iteration order, not filing content.

Resolution (commit 97a127f): inserted `_context_id` as a sort key between
`_dedupe_score` and `_dedupe_row_order` at all three sites (S11 stamp sort, S12 fill
sort, S13 winner pick). `_context_id` is the XBRL contextRef string, which is stable
across parses of the same filing. Winner within tied-score groups is now
lexicographically-first `_context_id`. Tests: `TestDedupeDeterminism` (2 tests in
`tests/test_bdc_filings.py`).

### `_assign_row_ids` collision suffix (Task 2)

`_assign_row_ids` in `unified_holdings.py` hashes `source|accession_number|src_context_id`
(N-PORT: `source|accession_number|nport_holding_id`) into a 16-hex `row_id`. A collision
(two rows with the same anchor triple) would produce duplicate `row_id` values; prior
behavior logged a warning and assigned the duplicate hash. Current artifact measured
2026-08-24: 0 duplicates in 780,726 rows.

Resolution (commits ea93302, 504294b): before hashing, a vectorized content-rank block
appends `|dup<k>` (k >= 1) to collision keys, where k is the 0-based rank within the
collision group ordered by `(fair_value, cost, principal_amount, shares_held,
bdc_investment_identifier)` with nulls-last. Rank-0 rows keep the bare key -- no live
id changes on the current artifact. The suffix is an internal disambiguation device;
only the final `row_id` hash is surfaced. Three correctness defects found and fixed
in a code-review follow-on commit: (1) index misalignment in the rank frame when the
input DataFrame has a non-default index (RangeIndex-safe `_col_r()` helper); (2)
nulls-first inversion from `fillna('')` (per-column null indicator added); (3) fragile
`groupby(sort=False)` after `sort_values` (reverted to default `sort=True`).

## Convention going forward

Every new site that picks a row under a ROW_NUMBER, FIRST_VALUE, LAST_VALUE, or
pandas `drop_duplicates` / `sort_values` MUST append anchor keys
(`src_context_id` / `nport_holding_id`, COALESCE-wrapped for SQL, fillna("") for
pandas) as the final sort keys, and MUST include an order-invariance test asserting
the same survivor regardless of input frame order. The twin-build gate is the
end-to-end acceptance criterion.
