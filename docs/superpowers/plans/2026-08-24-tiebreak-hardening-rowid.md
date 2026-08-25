# Tie-Break Hardening: Anchor Identity as the Deterministic Final Key -- Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every order-dependent row-pick in the holdings build deterministic by adding the filing-anchor identity (`src_context_id` / `_context_id` / `nport_holding_id` -- the inputs to `row_id`) as the final tie-break key, so rebuilds are bit-reproducible and the values-identical migration gate becomes strictly binary (no more "accepted ordinal flip" residuals).

**Architecture:** The 2026-08-22 anchor migration gave every row a content-independent, filing-assigned identity: `row_id = hash(source|accession_number|src_context_id)` (N-PORT: `nport_holding_id`). Rows that are tied on every content key ALWAYS differ on their anchor, and the anchor never changes across rebuilds (accessions are immutable). This plan threads that identity into all 12 flip-prone pick sites found by the 2026-08-24 scout (inventory: `scratch/2026-08-24_tiebreak_scout/inventory.md`, sites S3-S20; committed as `docs/reference/tiebreak_site_inventory.md` in Task 5). Where the pick runs before `row_id` is minted (extractor, staging, mid-build), the underlying anchor columns are used directly -- they carry identical ordering power because `row_id` is a pure function of them. One final, adjudicated flip event happens at the migration rebuild; after that, the twin-build gate (build twice, byte-equal content) proves determinism.

**Tech Stack:** Python 3.x, pandas (small frames), DuckDB SQL (large transforms), pytest. No new dependencies.

**Spec:** The scoping context is `docs/provenance_columns_scoping.md` (row_id anchor semantics, section 3) plus the accepted-residual history in `docs/agent_changelog.md` (2026-08-22 anchor migration: 8 flips; 2026-08-23 step-1: 13 CIK-quarters; 2026-08-23 steps-2-4: 17-20 flips). The site inventory `scratch/2026-08-24_tiebreak_scout/inventory.md` is this plan's companion -- site numbers (S3...S20) refer to it; it quotes each site's current partition and ordering keys verbatim.

**Current facts (measured 2026-08-24):** 780,726 unified rows; row_id duplicates: 0; `row_id_basis='src_anchor'` on 780,567 rows, `natural_key` on 159 (correction-added rows). The `_assign_row_ids` collision path (two rows sharing accession+context, e.g. axis-split rows) is structural but not live -- Task 2 hardens it as an invariant without changing any published id.

## Global Constraints

(from AGENTS.md + this project's migration protocol)
- **This is a value-moving migration by design** -- the LAST flip event. The Task 5 gate expects a bounded set of row-identity flips (same class as the three prior accepted residuals) with FV conserved per cik-quarter and ZERO stable-row value changes (row_id-joined diff). Anything outside that profile is a hard FAIL.
- **The twin-build gate is the acceptance test:** after migration, two consecutive `--unified` rebuilds must produce content-identical artifacts (DuckDB full-row EXCEPT in both directions = 0). That is the deliverable.
- Published `row_id` values must NOT change for any currently-existing row (Task 2's collision suffix only activates for future duplicate anchors; gate verifies id-set identity modulo the flip set).
- No network calls. ASCII-only log/script output. No inline `python -` / long `python -c`; named scratch scripts only.
- No `.apply()`/`.iterrows()`/row loops on >10K-row frames -- DuckDB or vectorized pandas.
- Pytest write-guard active: tests use tmp_path/monkeypatched paths only; rebuilds outside pytest.
- Dirty-worktree rule: the B3 workstream's uncommitted files (`pipeline/agent_b2_appliers.py`, `pipeline/correction_leaf.py`, `pipeline/review_bundles.py`, `pipeline/verdict_leaf.py`, `scripts/agent_b2/*`, their tests) must remain untouched. Before staging ANY file, run `git diff HEAD -- <file>` and confirm every hunk is yours; if a foreign hunk appears, STOP and escalate. Stage only named files; never `git add -A`/`-u`.
- One migration through the gates at a time; do not interleave with other rebuilds. Check for running python/pytest processes before Task 5.
- Commit style: short subject + 2-4 bullets.

## File Structure

| File | Change | Task |
|---|---|---|
| `pipeline/bdc_filings.py` | `_context_id` as tie-break key in `_deduplicate_bdc_holdings` (S11/S12/S13) | 1 |
| `pipeline/unified_holdings.py` | anchor keys appended at S4/S5/S6/S7/S8; collision suffix + uniqueness check in `_assign_row_ids`; S14 cache dedup sort; S19 lot-rank sort | 2, 3, 4 |
| `pipeline/staging_bdc.py` | S3 affil-dedup final key | 3 |
| `pipeline/staging_nport.py` | S20 ROW_NUMBER ORDER BY | 3 |
| `pipeline/bdc_xbrl_html_bridge.py` | S15/S16 deterministic load order + dedup sort | 4 |
| `pipeline/agent_rule.py` | S17 deterministic candidate order in `_apply_dedup` | 4 |
| `tests/test_bdc_filings.py` | S11-S13 order-invariance tests | 1 |
| `tests/test_row_id.py` | collision-suffix + uniqueness tests | 2 |
| `tests/test_unified_holdings.py` | S4-S8, S14, S19 order-invariance tests | 3, 4 |
| `tests/test_bdc_xbrl_html_bridge_fields.py` | S15/S16 tests | 4 |
| `tests/test_agent_rule.py` (or nearest agent-rule test file) | S17 test | 4 |
| `docs/reference/tiebreak_site_inventory.md` | committed copy of the scout inventory + dispositions | 5 |
| `docs/reference/schemas.md`, `docs/agent_changelog.md` | invariant + migration record | 5 |

**The shared test idiom (used throughout -- "order-invariance test"):** build the same fixture frame twice, once in order A and once reversed; run the function/CTE; assert the SAME winner row (identified by its anchor column) both times. This is the property the whole plan enforces; a test that only checks one input order proves nothing.

---

### Task 1: Extractor dedup determinism (S11, S12, S13)

**Files:**
- Modify: `pipeline/bdc_filings.py` (`_deduplicate_bdc_holdings`: the `_dedupe_row_order` stamp ~:1042, the null-FV best-key pick ~:1077, the fill sort ~:1125 and winner pick ~:1136 -- anchor on `_dedupe_score` / `_dedupe_row_order` if lines drifted)
- Test: `tests/test_bdc_filings.py`

**Interfaces:**
- Consumes: `_context_id` (present on every extractor record before dedup).
- Produces: all three sort sites use key order `["_dedupe_score" DESC, "_context_id" ASC, "_dedupe_row_order" ASC]`. `_dedupe_row_order` remains as last-resort (only reachable when `_context_id` is missing/equal -- equal context within one dedup group means the same fact row duplicated, where either winner is identical).

- [ ] **Step 1: Write the failing order-invariance test**

Append to `tests/test_bdc_filings.py` (reuse the module's existing `_dedup_frame` helper from the `TestDedupeFilledFields` class -- same base dict):

```python
class TestDedupeDeterminism:
    def _rows(self):
        # two candidates TIED on completeness score (same non-empty fields),
        # different contexts, different cost values
        return [
            {"_context_id": "ctxB", "fair_value": 1000.0, "cost": 950.0,
             "principal_amount": 900.0, "src_facts": ""},
            {"_context_id": "ctxA", "fair_value": 1000.0, "cost": 940.0,
             "principal_amount": 900.0, "src_facts": ""},
        ]

    def test_winner_independent_of_input_order(self):
        rows = self._rows()
        out_fwd = _deduplicate_bdc_holdings(_dedup_frame(rows))
        out_rev = _deduplicate_bdc_holdings(_dedup_frame(list(reversed(rows))))
        assert len(out_fwd) == 1 and len(out_rev) == 1
        # deterministic winner: lexicographically-first context (ctxA)
        assert out_fwd.iloc[0]["src_context_id"] == "ctxA"
        assert out_rev.iloc[0]["src_context_id"] == "ctxA"
        assert out_fwd.iloc[0]["cost"] == 940.0
        assert out_rev.iloc[0]["cost"] == 940.0

    def test_fill_donor_independent_of_input_order(self):
        # winner missing cost; two tied DONORS with different costs -- the
        # donated value must not depend on input order
        rows = [
            {"_context_id": "ctxW", "fair_value": 1000.0, "cost": None,
             "principal_amount": 900.0, "shares_held": 10.0, "src_facts": ""},
            {"_context_id": "ctxY", "fair_value": None, "cost": 950.0,
             "principal_amount": None, "src_facts": ""},
            {"_context_id": "ctxX", "fair_value": None, "cost": 940.0,
             "principal_amount": None, "src_facts": ""},
        ]
        out_fwd = _deduplicate_bdc_holdings(_dedup_frame(rows))
        out_rev = _deduplicate_bdc_holdings(_dedup_frame(list(reversed(rows))))
        assert out_fwd.iloc[0]["cost"] == out_rev.iloc[0]["cost"] == 940.0
```

(If `_dedup_frame` requires columns these dicts omit, mirror the existing helper's defaults. The exact winner value assertions pin lexicographic-context semantics, not just consistency.)

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_bdc_filings.py -k DedupeDeterminism -v`
Expected: at least one order fails (winner follows input order today).

- [ ] **Step 3: Implement**

In `_deduplicate_bdc_holdings`, change every `sort_values(by=["_dedupe_score", "_dedupe_row_order"], ascending=[False, True], ...)` (three sites: the null-FV best-key pick, the fill-values sort, the winner pick) to:

```python
        .sort_values(
            by=["_dedupe_score", "_context_id", "_dedupe_row_order"],
            ascending=[False, True, True],
            kind="mergesort",
        )
```

Guard for frames lacking `_context_id` (defensive -- callers always have it): before the first sort, `if "_context_id" not in result.columns: result["_context_id"] = ""`.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_bdc_filings.py -q`
Expected: PASS including all pre-existing dedup/filled-fields tests (their fixtures have distinct contexts or single candidates; if any pre-existing test pinned an order-dependent winner, inspect whether its expectation encoded physical order -- if so, update the TEST and record it in the report as a semantics correction).

- [ ] **Step 5: Commit**

```bash
git add pipeline/bdc_filings.py tests/test_bdc_filings.py
git commit -m "tiebreak hardening: context id breaks extractor dedup ties

- _context_id sorts between completeness score and physical row order at
  all three pick/fill sites in _deduplicate_bdc_holdings (S11-S13)
- winner and fill donors now independent of input row order"
```

---

### Task 2: row_id uniqueness invariant (collision suffix, no live id changes)

**Files:**
- Modify: `pipeline/unified_holdings.py` (`_assign_row_ids` ~:1438-1530 -- anchor on the function name)
- Test: `tests/test_row_id.py`

**Interfaces:**
- Consumes: the existing anchor-key construction `source|accession|anchor_part`.
- Produces: when N>1 rows share the same anchor key, rows 2..N get key suffix `|dup<k>` before hashing, where `k` is the row's rank within the group ordered by the CONTENT columns `(fair_value, cost, principal_amount, shares_held, bdc_investment_identifier)` (stringified, NULLS LAST) -- content-stable ranks, not frame order. Row 1 (rank 0) keeps the unsuffixed key, so ALL current ids are unchanged (current duplicate count is 0). A post-assignment uniqueness assertion logs an ASCII warning with the offending keys if duplicates ever survive.

- [ ] **Step 1: Write the failing tests**

In `tests/test_row_id.py` (mirror its existing fixture style for building minimal frames):

```python
def test_colliding_anchors_get_distinct_ids_content_ranked():
    df = _frame([
        {"source": "bdc", "accession_number": "A1", "src_context_id": "ctx1",
         "fair_value": 200.0, "cost": 90.0},
        {"source": "bdc", "accession_number": "A1", "src_context_id": "ctx1",
         "fair_value": 100.0, "cost": 90.0},
    ])
    out = _assign_row_ids(df)
    assert out["row_id"].nunique() == 2
    # rank 0 (lowest fair_value=100) keeps the UNSUFFIXED id: recompute it
    import hashlib
    base = hashlib.md5(b"bdc|A1|ctx1").hexdigest()[:16]
    low_fv_id = out.loc[out["fair_value"] == 100.0, "row_id"].iloc[0]
    assert low_fv_id == f"ROW-{base}"

def test_collision_ids_independent_of_frame_order():
    rows = [
        {"source": "bdc", "accession_number": "A1", "src_context_id": "ctx1",
         "fair_value": 200.0, "cost": 90.0},
        {"source": "bdc", "accession_number": "A1", "src_context_id": "ctx1",
         "fair_value": 100.0, "cost": 90.0},
    ]
    out_fwd = _assign_row_ids(_frame(rows))
    out_rev = _assign_row_ids(_frame(list(reversed(rows))))
    fwd = dict(zip(out_fwd["fair_value"], out_fwd["row_id"]))
    rev = dict(zip(out_rev["fair_value"], out_rev["row_id"]))
    assert fwd == rev

def test_unique_anchor_ids_unchanged():
    # non-colliding row's id must equal the pre-change formula exactly
    df = _frame([{"source": "bdc", "accession_number": "A1",
                  "src_context_id": "ctxZ", "fair_value": 5.0}])
    import hashlib
    expected = "ROW-" + hashlib.md5(b"bdc|A1|ctxZ").hexdigest()[:16]
    assert _assign_row_ids(df).iloc[0]["row_id"] == expected
```

(Adapt `_frame` to whatever helper `tests/test_row_id.py` already uses; the hash-recompute assertions must match the ACTUAL id format in `_assign_row_ids` -- read the function first and mirror its exact md5/truncation/prefix so `test_unique_anchor_ids_unchanged` passes against CURRENT code before your change.)

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_row_id.py -k "colliding or collision or unchanged" -v`
Expected: `test_unique_anchor_ids_unchanged` PASSES already (pin); the two collision tests FAIL (duplicate ids today).

- [ ] **Step 3: Implement**

In `_assign_row_ids`, after building `keys` (the anchor-or-natural-key Series) and before hashing: compute the duplicate rank with content-stable ordering, vectorized:

```python
    # Collision suffix: rows sharing an anchor key get content-ranked |dup<k>
    # suffixes (k>=1); rank 0 keeps the bare key so existing ids never change.
    # Content rank (not frame order) keeps the ids rebuild-stable.
    rank_frame = pd.DataFrame({
        "k": keys,
        "_fv": _col("fair_value"), "_cost": _col("cost"),
        "_pa": _col("principal_amount"), "_sh": _col("shares_held"),
        "_bid": _col("bdc_investment_identifier"),
    })
    dup_rank = (rank_frame
                .sort_values(["k", "_fv", "_cost", "_pa", "_sh", "_bid"],
                             kind="mergesort")
                .groupby("k").cumcount()
                .reindex(rank_frame.index))
    keys = keys.where(dup_rank == 0, keys + "|dup" + dup_rank.astype(str))
```

(`_col` is the function's existing string-normalizing accessor. If the function hashes via DuckDB rather than pandas, apply the suffix to the key Series BEFORE it is registered/hashed -- the mechanism is key-suffixing, not hash-stage changes.) After id assignment, add the invariant check:

```python
    n_dup = int(df["row_id"].duplicated().sum())
    if n_dup:
        logger.warning("row_id uniqueness violated on %d rows after "
                       "collision suffixing -- investigate", n_dup)
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_row_id.py -q` then `python -m pytest tests/test_source_recon_anchor_ids.py -q` (anchor-id consumers must be unaffected -- suffixes only appear for duplicate anchors, which reconciliation ids never carried).
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pipeline/unified_holdings.py tests/test_row_id.py
git commit -m "tiebreak hardening: content-ranked collision suffix for row_id

- duplicate anchor keys get |dup<k> suffixes ranked by content columns,
  not frame order; rank-0 keeps the bare key so live ids are unchanged
  (current artifact has 0 duplicates -- this hardens the invariant)
- post-assignment uniqueness warning"
```

---

### Task 3: SQL pick sites -- anchor as final ORDER BY key (S3, S4, S5, S6, S7, S8, S20)

**Files:**
- Modify: `pipeline/unified_holdings.py` (CTEs at ~:864, :923, :994, :1072, :1107/:1118)
- Modify: `pipeline/staging_bdc.py` (~:2127-2154 `no_affil_dupes`)
- Modify: `pipeline/staging_nport.py` (~:124 `level3`)
- Test: `tests/test_unified_holdings.py`

**Interfaces:**
- Consumes: `src_context_id` and `nport_holding_id` columns present in the staged/unified frames (verified by the scout for S4-S8; for S6 confirm `src_context_id` is selected into the CTE's source relation -- if the intermediate SELECT list omits it, thread it through).
- Produces: each site's ORDER BY gains, AFTER its existing keys (existing keys unchanged -- semantics preserved, only true ties resolved):
  `COALESCE(CAST(src_context_id AS VARCHAR), ''), COALESCE(CAST(nport_holding_id AS VARCHAR), '')`
  For S3 (staging_bdc affil dedup): insert `COALESCE(CAST(src_context_id AS VARCHAR), '')` immediately BEFORE the existing final `_row_id` key (keep `_row_id` as last resort). For S20 (staging_nport): `ROW_NUMBER() OVER ()` becomes `ROW_NUMBER() OVER (ORDER BY accession_number, nport_holding_id)`.

- [ ] **Step 1: Write the failing order-invariance tests**

Append to `tests/test_unified_holdings.py`. Two representative tests drive the pattern (S6 dimension dedup and S7 cost proxy); the remaining sites are exercised by Task 5's twin-build gate, and each edit is condition-identical (reviewer verifies per-site key placement):

```python
class TestSqlTiebreakDeterminism:
    def _two_orders(self, rows):
        return self._make_bdc_df(rows), self._make_bdc_df(list(reversed(rows)))

    def test_dim_dedup_winner_independent_of_order(self):
        # two rows tied on the S6 partition AND on LENGTH(issuer_name),
        # issuer_name, bdc_investment_identifier -- differ only in context
        rows = [
            {"investment_identifier": "Tie Corp - Term Loan", "cik": "123",
             "fair_value": 1000.0, "dimensions_raw": "axis=A",
             "src_context_id": "ctxB"},
            {"investment_identifier": "Tie Corp - Term Loan", "cik": "123",
             "fair_value": 1000.0, "dimensions_raw": "axis=B",
             "src_context_id": "ctxA"},
        ]
        fwd, rev = self._two_orders(rows)
        out_f, out_r = _prepare_bdc(fwd), _prepare_bdc(rev)
        surv_f = sorted(out_f["src_context_id"])
        surv_r = sorted(out_r["src_context_id"])
        assert surv_f == surv_r  # same surviving context set either order

    def test_cost_proxy_donor_independent_of_order(self):
        # two same-quarter donors tied on report_date/fair_value/accession/
        # identifier -- proxy source must not depend on frame order; assert
        # equal published cost across both orders via build_unified_holdings
        ...  # copy the arrange/act of the nearest TestCostProxy fixture,
             # duplicate the donor row with a different src_context_id and
             # different cost, run both orders, assert equal cost outputs
```

(The `...` is fixture reuse from `TestCostProxy` per that class's established pattern -- copy its tmp_path/patch arrange verbatim. If constructing a genuine S6 tie through `_prepare_bdc` proves impossible because upstream CTEs already separate the rows, demonstrate the property at the closest reachable layer and say so in the report -- the twin-build gate remains the end-to-end proof.)

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_unified_holdings.py -k SqlTiebreakDeterminism -v`
Expected: FAIL on at least the reversed order (or, if current physical order coincidentally agrees, verify the test FAILS when you temporarily reverse the new sort key -- prove the test can detect the defect, note the method in the report).

- [ ] **Step 3: Implement (seven edits)**

For each site, append to the existing ORDER BY / `sort_values`-equivalent, changing nothing else:

3a. `unified_holdings.py` ~:864 (`nport_deduped`): after `..., shares_held` append `, COALESCE(CAST(nport_holding_id AS VARCHAR), ''), COALESCE(CAST(accession_number AS VARCHAR), '')` (holding_id first -- it is the N-PORT anchor).
3b. ~:923 (`deduped`): after `..., shares_held` append `, COALESCE(CAST(src_context_id AS VARCHAR), ''), COALESCE(CAST(nport_holding_id AS VARCHAR), '')`.
3c. ~:994 (`bdc_dim_ranked`): after `..., accession_number` append `, COALESCE(CAST(src_context_id AS VARCHAR), '')`.
3d. ~:1072 (`with_cost` FIRST_VALUE window ORDER BY): after `..., COALESCE(CAST(shares_held AS VARCHAR), '')` append `, COALESCE(CAST(src_context_id AS VARCHAR), ''), COALESCE(CAST(nport_holding_id AS VARCHAR), '')`.
3e. ~:1107/:1118 (`with_shares_fix` windows): same two keys appended to each window's ORDER BY.
3f. `staging_bdc.py` ~:2154 (`no_affil_dupes` ORDER BY): insert `COALESCE(CAST(src_context_id AS VARCHAR), ''),` immediately before the final `_row_id` key.
3g. `staging_nport.py` ~:124: `ROW_NUMBER() OVER ()` -> `ROW_NUMBER() OVER (ORDER BY accession_number, nport_holding_id)`.

For 3d/3e: the `with_cost` window was copied verbatim during the provenance migration with an explicit "byte-identical" contract -- that contract is being deliberately amended here; note it in the commit body.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_unified_holdings.py -q` (full file -- cost/shares/dedup neighbors must stay green; the appended keys only bind on true ties).
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pipeline/unified_holdings.py pipeline/staging_bdc.py pipeline/staging_nport.py tests/test_unified_holdings.py
git commit -m "tiebreak hardening: anchor ids terminate every SQL pick ORDER BY

- src_context_id / nport_holding_id appended as final keys at the nport,
  cross-source, and dimension dedups and the cost/shares windows (S3-S8)
- staging_nport ROW_NUMBER gains a deterministic ORDER BY (S20)
- amends the with_cost/with_shares_fix byte-identical contract knowingly"
```

---

### Task 4: Pandas pick sites (S14, S15, S16, S17, S19)

**Files:**
- Modify: `pipeline/unified_holdings.py` (`_apply_unclassified_cache` ~:680; `_apply_wrapper_position_keys` ~:1758)
- Modify: `pipeline/bdc_xbrl_html_bridge.py` (~:294 `load_bridge_table`; ~:1085 overlay dedup)
- Modify: `pipeline/agent_rule.py` (~:297 `_apply_dedup`)
- Test: `tests/test_unified_holdings.py`, `tests/test_bdc_xbrl_html_bridge_fields.py`, the agent-rule test file (locate with `rg -l "_apply_dedup|apply_rules" tests/`)

**Interfaces (per site):**
- S14 `_apply_unclassified_cache`: before `drop_duplicates(subset=["name_norm"], keep="first")`, stable-sort the cache frame `classify_df.sort_values(list(classify_df.columns), kind="mergesort")`; if the dropped duplicates DISAGREE on classification, log one ASCII warning naming the name_norms.
- S19 `_apply_wrapper_position_keys`: replace the `_source_index = range(len(work))` last-resort with anchor order: build `_anchor = work["src_context_id"].fillna("").astype(str).where(lambda s: s != "", work["nport_holding_id"].fillna("").astype(str))` and sort `[... existing keys ..., "_anchor", "_source_index"]` (keep `_source_index` as true last resort).
- S15/S16 bridge dedups: make the record iteration order deterministic (sorted file glob + stable sort on the dedup subset plus `html_sha256`/`table_index`/`row_index` before `keep="last"`), preserving last-wins semantics against a now-deterministic order.
- S17 `agent_rule._apply_dedup`: before computing `duplicated(...)`, stable-sort the frame by `[*match_fields, <anchor>]` where `<anchor>` = `row_id` if present else `accession_number`+`src_context_id`+`nport_holding_id` (fillna("")); restore the caller's row order after computing the drop mask (sort is for mask determination only -- the returned frame keeps its incoming order to avoid perturbing downstream, per the agent_promoted concat lesson).

- [ ] **Step 1: Write the failing tests**

One order-invariance test per site, same pattern as Tasks 1/3 (build fixture in two orders, assert identical survivor/assignment). For S19 specifically:

```python
    def test_lot_suffix_independent_of_frame_order(self):
        # two same-position-key rows tied on principal/fv/cost, different
        # contexts: lot numbering must follow the anchor, not frame order
        rows = [
            {"investment_identifier": "Lot Corp - TL", "cik": "123",
             "fair_value": 100.0, "principal_amount": 90.0, "cost": 95.0,
             "src_context_id": "ctxB"},
            {"investment_identifier": "Lot Corp - TL", "cik": "123",
             "fair_value": 100.0, "principal_amount": 90.0, "cost": 95.0,
             "src_context_id": "ctxA"},
        ]
        # arrange per the nearest _apply_wrapper_position_keys test fixture;
        # assert the ctxA row gets the lower lot suffix in BOTH input orders
```

For S17: a frame with two content-identical candidate rows differing only in `src_context_id`, a dedup rule with `match_fields` covering the content columns, `keep="first"`: assert the SAME surviving context in both input orders AND that the returned frame preserves the caller's row order.

- [ ] **Step 2: Run to verify failure** -- each new test red (or detectably red via key-reversal probe as in Task 3 Step 2).

- [ ] **Step 3: Implement** per the Interfaces block above. All sorts `kind="mergesort"`. No behavior change for frames without ties.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_unified_holdings.py tests/test_bdc_xbrl_html_bridge_fields.py <agent-rule test file> -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pipeline/unified_holdings.py pipeline/bdc_xbrl_html_bridge.py pipeline/agent_rule.py tests/test_unified_holdings.py tests/test_bdc_xbrl_html_bridge_fields.py <agent-rule test file>
git commit -m "tiebreak hardening: deterministic pandas pick sites

- unclassified-cache dedup, wrapper lot ranking, bridge dedups, and
  agent-rule dedup all order candidates by anchor before picking
  (S14-S17, S19); agent-rule dedup preserves caller row order"
```

---

### Task 5: Operator phase -- the final flip event, twin-build gate, docs

Preconditions: Tasks 1-4 committed; no other migration/rebuild in flight; no running python/pytest processes (`Get-Process | Where-Object { $_.ProcessName -match 'python|pytest' }`).

- [ ] **Step 1: Snapshot**

```powershell
New-Item -ItemType Directory -Force data\snapshots\pre_tiebreak_20260824 | Out-Null
Copy-Item data\output\bdc_holdings.csv data\snapshots\pre_tiebreak_20260824\
Copy-Item data\output\private_markets_holdings.csv data\snapshots\pre_tiebreak_20260824\
```

- [ ] **Step 2: Rebuild both artifacts (cache-only)**

```powershell
python scripts\rebuild_outputs.py --bdc-holdings          # full cached re-parse (Task 1 changed extractor dedup)
python scripts\rebuild_outputs.py --unified
```

- [ ] **Step 3: GATE A -- the final flip event (values conserved, flips inventoried)**

Copy `scratch/2026-08-23_prov_step2/unified_gate2.py` to `scratch/2026-08-24_tiebreak/final_flip_gate.py`, point OLD at `data/snapshots/pre_tiebreak_20260824/private_markets_holdings.csv`, set `NEW_EXPECTED_COLS = set()` (no schema change), and FIX the known NULL-classification join artifact (wrap the classification join key in `COALESCE(k, '<NULL>')` on both sides). Required profile:
- row count identical; FV total identical; per-cik-quarter FV 0 mismatches; **stable-row value diff = 0 rows** (hard fail otherwise);
- a bounded row-identity flip set (expected same order of magnitude as prior residuals, plus any winners moved by the new deterministic keys) -- write the full flip list (old_row_id, new_row_id, cik, report_date, issuer_name) to `scratch/2026-08-24_tiebreak/flip_inventory.csv`;
- cost/shares/principal deltas explainable entirely by the flip set (exact DECIMAL sums; deltas ride on flipped identities only).
Run the analogous check on bdc_holdings.csv vs its snapshot (adapt `scratch/2026-08-23_prov_step2/bdc_holdings_gate.py`, expected added columns = none). Any stable-row value change: STOP, adjudicate before proceeding.

- [ ] **Step 4: GATE B -- the twin-build gate (the deliverable)**

```powershell
Copy-Item data\output\private_markets_holdings.csv scratch\2026-08-24_tiebreak\build1.csv
python scripts\rebuild_outputs.py --unified
```

Then compare build1 vs the new build with a named scratch script (`twin_build_gate.py`, DuckDB): row counts equal; `SELECT * FROM b1 EXCEPT SELECT * FROM b2` and the reverse both return 0 rows (full-row content equality, all columns). PASS = determinism achieved. FAIL = a site was missed: diff the differing rows' columns, map back to the responsible pick site, fix (fix loop through the executing process), re-run Steps 2-4.

- [ ] **Step 5: Re-verifier sanity + full suite + semantic diff**

```powershell
python -m pipeline.provenance_reverify --cohort --cheap-only --out scratch\2026-08-24_tiebreak\ledger_smoke
python -m pytest --durations=50 --durations-min=0.5 -q
python scripts\diff_outputs.py --semantic
```

Expected: cheap-tier smoke clean (flipped rows carry their own valid anchors); suite green; semantic deltas confined to the documented pre-existing set + this migration's flip inventory.

- [ ] **Step 6: Docs + commit**

- Commit the site inventory: copy `scratch/2026-08-24_tiebreak_scout/inventory.md` to `docs/reference/tiebreak_site_inventory.md`, adding a "disposition" column (hardened in this plan / already deterministic / order-irrelevant).
- `docs/reference/schemas.md`: document the row_id collision-suffix rule (`|dup<k>`, content-ranked) and the determinism invariant (twin-build gate is the standing acceptance test for future migrations).
- `docs/agent_changelog.md`: APPEND a dated entry -- the final flip event's inventory (count, CIKs, magnitudes), twin-build gate PASS, suite counts, and the statement that the values-identical gate is now strictly binary for future migrations.

```bash
git add docs/reference/tiebreak_site_inventory.md docs/reference/schemas.md docs/agent_changelog.md
git commit -m "docs: tiebreak hardening migration record

- final flip event inventoried; twin-build gate PASS = builds are now
  content-deterministic; future migration gates are strictly binary
- site inventory committed with dispositions; row_id |dup<k> rule"
```

---

## Self-Review Notes

- Coverage vs the scout inventory: S11/S12/S13 -> Task 1; row_id collision (deep-dive A) -> Task 2; S3/S4/S5/S6/S7/S8/S20 -> Task 3; S14/S15/S16/S17/S19 -> Task 4; DETERMINISTIC-ALREADY sites (S1/S2/S9/S10/S18) and ORDER-IRRELEVANT aggregates deliberately untouched, recorded via the committed inventory's disposition column (Task 5).
- The plan deliberately does NOT reorder existing keys anywhere -- anchors are appended/inserted as FINAL tie-breakers only, so non-tied picks are provably unchanged and the Task 5 flip set stays bounded.
- Known risk: some S6-S8 ties may be unreachable through public fixtures (upstream CTEs may separate the candidates); the tests prove the property where reachable and the twin-build gate is the end-to-end proof. Key-reversal probing (Task 3 Step 2) guards against vacuously-green tests.
- Known scope cut: `position_matching.py` / `index_returns.py` / export-layer tie-breaks are OUT (they do not feed the two holdings artifacts); `data/output` cache files' internal order (S14's source CSVs) is made irrelevant by sorting at load. The B3-dirty file `agent_b2_appliers.py` is NOT touched (its `apply_dedup` runs on quarter-scoped trial frames; production dedup leaves flow through `agent_rule._apply_dedup` and stage-2 `apply_scoped` -- if execution discovers a live tie-break inside `agent_b2_appliers.apply_dedup`, escalate rather than edit the dirty file).
- Type consistency: `_context_id` (extractor) vs `src_context_id` (staged/unified) used correctly per layer; the anchor append expression is identical across all Task 3 sites.
