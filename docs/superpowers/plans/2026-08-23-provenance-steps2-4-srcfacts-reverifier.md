# Provenance Steps 2-4: src_facts Capture, corrected_fields, Deterministic Re-Verifier -- Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the provenance triple (pathway, anchor, transform) for every BDC value claim -- extractor-side raw values and concept disambiguation (`src_facts`), correction markers (`corrected_fields`), pathway enums for the remaining value fields -- then ship the deterministic two-tier re-verifier that consumes them and emits the field-level provenance ledger.

**Architecture:** Three phases matching scoping-doc section 6 steps 2-4. Phase A (Tasks 1-3): extractor capture in `bdc_filings.py` (per-fact raw values, transform events, dedup fill markers) plus a cohort-scoped cache-only re-extraction mechanism. Phase B (Tasks 4-5): one unified schema batch (8 new `UNIFIED_COLUMNS`) carrying the extractor payload through staging plus `corrected_fields` stamped by every correction layer. Task 6 is the single operator migration (one re-extraction, one `--unified` rebuild, one gate pass). Phase C (Tasks 7-9): `pipeline/provenance_reverify.py` -- cheap tier (re-derive published from declared raw + transforms, DuckDB, no filing access), full tier (re-read cached iXBRL at `src_context_id` + concept), deterministic reason-code triage, ledger artifact + CLI.

**Tech Stack:** Python 3.x, pandas (small frames only), DuckDB (large transforms), lxml (filing re-read), pytest. No new dependencies.

**Spec:** `docs/provenance_columns_scoping.md` -- sections 1 (the contextRef anchor + CONCEPT_MAP ambiguity), 2.3/2.4 (the triple, `src_facts`, `corrected_fields`), 3 (touched modules), 4 (migration risks 1-7), 6 (steps 2-4), 8.1-8.2 (ledger keying + deterministic triage). Section 8.3+ agent lanes and section 5's headline-basis decision are OUT of scope (design intent / owner decision), but Task 9 records the section-5 guard.

**Owner decisions folded in (2026-08-23):**
- `src_facts` entries are sparse ("only where non-trivial", scoping 2.4 #3): `r` (raw) always for the four staging-rescaled rate fields, `r`+`x` whenever an extractor-side transform fired, `c` (concept) only when the winning concept is non-canonical for its column or a transform fired. The full tier re-locates facts by replaying `_match_concept`, so canonical concepts need no per-row storage. This bounds the size cost the scoping doc flagged.
- `corrected_fields` and `src_filled_fields` are flat `;`/`,`-joined strings like the step-1 columns, not JSON (SQL-groupable, consistent with `src_transforms`). Deviation from the doc's "JSON list" wording, same rationale as step-1's flat `src_transforms`.
- New pathway enums use `'xbrl_field'`/`'identifier_text'`/`''`. `cost_source`/`shares_held_source` keep their step-1 semantics (`''` = as-extracted, `'derived_proxy'` = Class-C fill); the re-verifier treats `''` on those two as the xbrl pathway. Documented in schemas.md, not retrofitted.
- Correction markers do NOT flip `*_source` -- the enum keeps describing the original extraction pathway; `corrected_fields` is the overlay marker. The re-verifier needs both facts separately (scoping 8.2: "corrected_fields hit -> verify against the correction audit trail instead").
- Re-extraction mechanism: extend `rebuild_cached_bdc_holdings()` (cache-only by construction, "for parser/dedupe changes where every cached instance should be reinterpreted") with a `ciks=` filter + merge-back, rather than the network-capable `--holdings` path. Confines drift risk and runtime to the cohort (scoping risk 1/2).

## Global Constraints

(from AGENTS.md + scoping doc section 3/4)
- **No network calls.** All tasks are cache-only. Never route through the EDGAR download path.
- **ASCII-only log messages.** No inline `python -`/`python -c` diagnostics -- named scratch scripts with row limits only.
- **No `.apply()`/`.iterrows()`/row loops on >10K-row frames.** DuckDB SQL for the unified frame; pandas loops only over per-CIK sub-frames, correction leaves, or per-filing iteration (bounded by filing count, not row count).
- **Pytest write-guard is active** (blocks writes to `data/output/`): all tests use `tmp_path` and monkeypatched config paths; rebuilds happen outside pytest.
- **Silent-drop trap (scoping risk 3):** every new unified column goes into `UNIFIED_COLUMNS` in the same commit as its staging emission; `position_matching.py`/`gics_classification.py` reorder to the constant and silently drop anything else.
- **row_id stability (scoping section 3):** provenance columns must NOT enter the row_id natural key or the `src_anchor` basis. No changes to `_assign_row_ids` or `position_id_registry`.
- **Dirty-worktree rule:** stage only named files; never `git add -A`/`-u`.
- **Sequencing:** PRECONDITION -- the step-1 passthroughs plan (`2026-08-22-provenance-step1-passthroughs.md`) is fully executed and gated (columns `src_context_count`, `src_conflict_fields`, `src_transforms`, `src_field_overrides`, `cost_source`, `shares_held_source` exist in `UNIFIED_COLUMNS` and are populated). Task 6 here is a data migration: one migration through the gates at a time; do not interleave with any other rebuild.
- **Commit style:** short subject + 2-4 bullets.
- **Values-identical gates (scoping risk 2):** the Task-6 re-extraction and rebuild must show ZERO semantic deltas -- new columns only. Any value drift stops the migration for separate adjudication.

## File Structure

| File | Change | Task |
|---|---|---|
| `pipeline/bdc_filings.py` | `src_facts` capture in fact loop + decimals/Stepstone event recording; `dedupe_filled_fields` marker in dedup; `ciks=` param on `rebuild_cached_bdc_holdings` | 1, 2, 3 |
| `scripts/rebuild_outputs.py` | `--ciks`/`--cohort` passthrough for `--bdc-holdings` | 3 |
| `pipeline/unified_holdings.py` | 8 new `UNIFIED_COLUMNS`; `corrected_fields` stamping in `_apply_row_corrections` | 4, 5 |
| `pipeline/staging_bdc.py` | `_optional_cols` + Phase C emissions (passthroughs + 5 pathway enums) | 4 |
| `pipeline/staging_nport.py` | `''` emissions for all 8 | 4 |
| `pipeline/agent_promoted.py` | `CORRECTED_TRACKED_FIELDS`, `append_corrected_fields`, `mark_corrected_fields`; wiring in stage2 + rules appliers | 5 |
| `pipeline/provenance_reverify.py` (new) | cheap tier, full tier, reason-code triage, ledger writer, CLI | 7, 8, 9 |
| `pipeline/config.py` | `PROVENANCE_LEDGER_FILE`, `PROVENANCE_LEDGER_SUMMARY_FILE` | 9 |
| `tests/test_bdc_filings.py` | extractor capture + dedup marker + cohort rebuild tests | 1, 2, 3 |
| `tests/test_unified_holdings.py` | staging passthrough + enum + row-correction marker tests | 4, 5 |
| `tests/test_agent_promoted.py` | `mark_corrected_fields` + applier wiring tests | 5 |
| `tests/test_provenance_reverify.py` (new) | cheap tier, full tier, triage, ledger tests | 7, 8, 9 |
| `docs/reference/schemas.md`, `docs/agent_changelog.md` | column + event + ledger vocabulary; migration + run records | 6, 9 |

**`src_facts` grammar (v1, versioned in schemas.md):** compact JSON, sorted keys, e.g.
`{"interest_rate":{"r":0.105},"principal_amount":{"c":"investmentownedbalancesharesornumberofcontractsorprincipalamount","r":58702,"x":["decimals_rescale:10^3"]}}`
- `r`: value as parsed from the instance BEFORE any transform (number).
- `c`: winning concept localname (lowercase), present only when non-canonical for the column OR a transform fired.
- `x`: ordered extractor-side transform events. Vocabulary: `decimals_rescale:10^<k>` (k = decimals diff, may be negative), `cik_scale_fix:x1000` (Stepstone 2025q4).
- Absent field key => the field had no XBRL fact in this context, or (for monetary fields) raw == stored value with no transform. Absent `r` with present `c` => raw equals the bdc_holdings value.

---

### Task 1: Extractor `src_facts` capture

**Files:**
- Modify: `pipeline/bdc_filings.py` (`_extract_investment_facts` fact loop ~:748-828, `_normalize_mixed_decimals_monetary_facts` ~:573-622, `_apply_stepstone_2025q4_monetary_scale_correction` ~:690-725, module constants near `_MONETARY_COLUMNS` ~:97)
- Test: `tests/test_bdc_filings.py`

**Interfaces:**
- Consumes: existing `facts_by_ctx` accumulation, `_match_concept`, `_parse_fact_value`, `CONCEPT_MAP`.
- Produces: every record dict from `_extract_investment_facts` gains key `"src_facts"` (compact JSON string per the grammar above, `""` when empty). New module-level helpers later tasks and the re-verifier import: `CANONICAL_CONCEPT` (dict col -> first CONCEPT_MAP pattern) and `_record_value_xform(record, col, old_value, code)`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_bdc_filings.py` (self-contained; builds the tree + contexts dict directly, matching the shapes `_extract_investment_facts` consumes):

```python
import json

from lxml import etree

from pipeline.bdc_filings import _extract_investment_facts


def _ctx(period="2025-12-31", ident="Acme Corp - Term Loan"):
    return {
        "is_investment": True, "period": period,
        "investment_identifier": ident, "industry": "", "investment_type": "",
        "affiliation": "", "dimensions_raw": f"investmentidentifieraxis={ident}",
    }


def _tree(facts_xml: str):
    return etree.ElementTree(etree.fromstring(
        f'<xbrl xmlns:us-gaap="http://fasb.org/us-gaap/2024">{facts_xml}</xbrl>'
    ))


class TestSrcFactsCapture:
    def test_rate_fields_record_raw_value(self):
        tree = _tree(
            '<us-gaap:InvestmentInterestRate contextRef="c1">0.105'
            '</us-gaap:InvestmentInterestRate>'
            '<us-gaap:InvestmentOwnedAtFairValue contextRef="c1" unitRef="usd" '
            'decimals="-3">1000000</us-gaap:InvestmentOwnedAtFairValue>'
        )
        recs = _extract_investment_facts(tree, {"c1": _ctx()})
        prov = json.loads(recs[0]["src_facts"])
        assert prov["interest_rate"]["r"] == 0.105
        # canonical concept, no transform -> no "c", no "x"
        assert "c" not in prov["interest_rate"]
        # fair_value: canonical concept, no transform -> NO entry at all
        assert "fair_value" not in prov

    def test_noncanonical_concept_recorded(self):
        # SharesOrNumberOfContractsOrPrincipalAmount is the NON-canonical
        # principal_amount concept (canonical = InvestmentOwnedBalancePrincipalAmount)
        tree = _tree(
            '<us-gaap:InvestmentOwnedBalanceSharesOrNumberOfContractsOr'
            'PrincipalAmount contextRef="c1" unitRef="usd" decimals="0">58702'
            '</us-gaap:InvestmentOwnedBalanceSharesOrNumberOfContractsOr'
            'PrincipalAmount>'
        )
        recs = _extract_investment_facts(tree, {"c1": _ctx()})
        prov = json.loads(recs[0]["src_facts"])
        assert prov["principal_amount"]["c"] == (
            "investmentownedbalancesharesornumberofcontractsorprincipalamount")

    def test_decimals_rescale_records_raw_and_event(self):
        # 5+ facts at decimals=-3, one outlier at -6 and >100x the median:
        # normalization multiplies the outlier by 10^-3; src_facts must keep
        # the pre-fix raw and the event.
        base = "".join(
            f'<us-gaap:InvestmentOwnedAtFairValue contextRef="c{i}" '
            f'unitRef="usd" decimals="-3">{1000000 + i}'
            f'</us-gaap:InvestmentOwnedAtFairValue>' for i in range(5))
        outlier = ('<us-gaap:InvestmentOwnedAtFairValue contextRef="c9" '
                   'unitRef="usd" decimals="-6">500000000'
                   '</us-gaap:InvestmentOwnedAtFairValue>')
        contexts = {f"c{i}": _ctx(ident=f"P{i}") for i in range(5)}
        contexts["c9"] = _ctx(ident="Outlier LP")
        recs = _extract_investment_facts(_tree(base + outlier), contexts)
        by_ctx = {r["_context_id"]: r for r in recs}
        assert by_ctx["c9"]["fair_value"] == 500000000 * 10 ** -3
        prov = json.loads(by_ctx["c9"]["src_facts"])
        assert prov["fair_value"]["r"] == 500000000
        assert prov["fair_value"]["x"] == ["decimals_rescale:10^-3"]

    def test_no_facts_means_empty_src_facts(self):
        tree = _tree('<us-gaap:InvestmentOwnedAtFairValue contextRef="c1" '
                     'unitRef="usd">1000</us-gaap:InvestmentOwnedAtFairValue>')
        recs = _extract_investment_facts(tree, {"c1": _ctx()})
        # fair_value canonical + untransformed and no rate facts -> "" not "{}"
        assert recs[0]["src_facts"] == ""
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_bdc_filings.py -k SrcFactsCapture -v`
Expected: FAIL -- `KeyError: 'src_facts'`.

- [ ] **Step 3: Implement**

3a. Module constants (below `_MONETARY_COLUMNS`), plus `import json` at the top imports:

```python
# Fields whose raw as-extracted value is ALWAYS recorded in src_facts: staging
# applies threshold-heuristic rescales to these, so the cheap re-verification
# tier needs the pre-pipeline value (scoping doc 2.3/2.4).
_RATE_PROV_COLUMNS = frozenset({
    "interest_rate", "basis_spread", "pik_rate", "pct_of_net_assets",
})

# col -> its FIRST (canonical) CONCEPT_MAP pattern. src_facts records the
# winning concept only when it is non-canonical -- the full re-verify tier
# re-locates canonical facts by replaying _match_concept.
CANONICAL_CONCEPT: dict[str, str] = {}
for _pat, _col in CONCEPT_MAP:
    CANONICAL_CONCEPT.setdefault(_col, _pat)


def _record_value_xform(
    record: dict[str, Any], col: str, old_value: Any, code: str,
) -> None:
    """Record an extractor-side value transform into the record's src_facts.

    Sets ``r`` to the pre-transform value (first writer wins -- chained
    transforms keep the original instance value) and appends ``code`` to the
    ordered ``x`` event list.
    """
    try:
        prov = json.loads(record.get("src_facts") or "{}")
    except json.JSONDecodeError:
        prov = {}
    entry = prov.setdefault(col, {})
    entry.setdefault("r", old_value)
    entry.setdefault("x", []).append(code)
    record["src_facts"] = json.dumps(prov, sort_keys=True, separators=(",", ":"))
```

3b. In `_extract_investment_facts`: add `prov_by_ctx: dict[str, dict[str, dict]] = {}` next to `facts_by_ctx`. In the first-non-null store branch (currently `facts_by_ctx[ctx_ref][col] = value` at ~:785), append:

```python
            entry: dict[str, Any] = {}
            if CANONICAL_CONCEPT.get(col, "") not in local:
                entry["c"] = local
            if col in _RATE_PROV_COLUMNS and isinstance(value, (int, float)):
                entry["r"] = value
            if entry:
                prov_by_ctx.setdefault(ctx_ref, {})[col] = entry
```

3c. Change the decimals-normalization call to pass the accumulator:
`_normalize_mixed_decimals_monetary_facts(facts_by_ctx, monetary_facts_stored, prov_by_ctx)`. In that function, add the third parameter `prov_by_ctx: dict[str, dict[str, dict]]` and at the correction site (after `facts_by_ctx[ctx_ref][col] = corrected`):

```python
            entry = prov_by_ctx.setdefault(ctx_ref, {}).setdefault(col, {})
            entry.setdefault("r", val)
            entry.setdefault("x", []).append(f"decimals_rescale:10^{diff}")
            # non-canonical marker may be absent; force concept retention so the
            # full tier can exact-match the transformed fact
            entry.setdefault("c", CANONICAL_CONCEPT.get(col, ""))
```

Note: at this point the loop no longer has `local` in scope -- `CANONICAL_CONCEPT[col]` is the correct value here only when the fact used the canonical concept. To keep it exact, extend `monetary_facts_stored` tuples from `(ctx_ref, col, dec_val)` to `(ctx_ref, col, dec_val, local)` at the append site in the fact loop, and use that `local` in the correction site (`entry.setdefault("c", local)`). Update the two unpacking loops in `_normalize_mixed_decimals_monetary_facts` accordingly (`for ctx_ref, col, fact_dec, _local in ...`).

3d. In the record-build loop (~:810-828), after `record["interest_rate_concept"] = ...`:

```python
        prov = prov_by_ctx.get(ctx_id) or {}
        record["src_facts"] = (
            json.dumps(prov, sort_keys=True, separators=(",", ":")) if prov else "")
```

3e. In `_apply_stepstone_2025q4_monetary_scale_correction`, inside the per-column loop where the value changes (`row[col] = after; row_corrected = True`), add before the assignment:

```python
                _record_value_xform(row, col, before, "cik_scale_fix:x1000")
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_bdc_filings.py -k "SrcFactsCapture" -v` then the full file `python -m pytest tests/test_bdc_filings.py -q` (existing extraction tests must still pass -- values are untouched, only the new key is added).
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pipeline/bdc_filings.py tests/test_bdc_filings.py
git commit -m "provenance step 2: extractor src_facts capture

- raw as-extracted values for the 4 staging-rescaled rate fields,
  non-canonical concept names, decimals_rescale + cik_scale_fix events
- sparse by design (scoping doc 2.4: only where non-trivial); values
  byte-identical, new record key only"
```

---

### Task 2: Dedup fill markers + `src_facts` survival

**Files:**
- Modify: `pipeline/bdc_filings.py` (`_deduplicate_bdc_holdings` fill loop ~:1075-1091)
- Test: `tests/test_bdc_filings.py`

**Interfaces:**
- Consumes: the `picked` frame + `{col}_dedupe_fill` columns from Task-independent existing code.
- Produces: `dedupe_filled_fields` column on the dedup output (comma-joined field names filled from a losing context, same join style as `dedupe_conflict_fields`; `""` otherwise). `src_facts` is guaranteed to be the WINNING row's payload (never filled from losers).

**Why:** the dedup fill copies a missing field's value from a losing context into the winner. The published value then did NOT come from `src_context_id` -- the anchor is primary-of-N (scoping risk 5). Without a marker the full re-verify tier would look up the fact at the winner's context, find nothing, and emit a false mismatch. Marked fields are excluded from anchor verification, like conflict fields.

- [ ] **Step 1: Write the failing tests**

```python
from pipeline.bdc_filings import _deduplicate_bdc_holdings


def _dedup_frame(rows):
    base = {
        "accession_number": "0001-24-000001", "investment_identifier": "Acme TL",
        "period": "2025-12-31", "dimensions_raw": "axis=Acme",
    }
    return pd.DataFrame([{**base, **r} for r in rows])


class TestDedupeFilledFields:
    def test_fill_from_losing_context_is_marked(self):
        # winner (complete row, ctxA) is missing cost; loser (ctxB) has it
        df = _dedup_frame([
            {"_context_id": "ctxA", "fair_value": 1000.0, "cost": None,
             "principal_amount": 900.0,
             "src_facts": '{"interest_rate":{"r":0.1}}'},
            {"_context_id": "ctxB", "fair_value": None, "cost": 950.0,
             "principal_amount": None, "src_facts": ""},
        ])
        out = _deduplicate_bdc_holdings(df)
        assert len(out) == 1
        row = out.iloc[0]
        assert row["src_context_id"] == "ctxA"
        assert row["cost"] == 950.0
        assert "cost" in str(row["dedupe_filled_fields"]).split(",")
        # fair_value came from the winner itself -> not marked
        assert "fair_value" not in str(row["dedupe_filled_fields"]).split(",")
        # src_facts is the WINNER's payload, never filled from the loser
        assert row["src_facts"] == '{"interest_rate":{"r":0.1}}'

    def test_single_context_group_unmarked(self):
        df = _dedup_frame([
            {"_context_id": "ctxA", "fair_value": 1000.0, "cost": 950.0,
             "principal_amount": 900.0, "src_facts": ""},
        ])
        out = _deduplicate_bdc_holdings(df)
        assert out.iloc[0]["dedupe_filled_fields"] == ""
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_bdc_filings.py -k DedupeFilledFields -v`
Expected: FAIL -- `KeyError: 'dedupe_filled_fields'`.

- [ ] **Step 3: Implement**

In `_deduplicate_bdc_holdings`, immediately after `picked` is built (the `.drop_duplicates(...).merge(...)` at ~:1060-1073) add `picked["dedupe_filled_fields"] = ""`. Then, in the fill loop, compute the actually-filled mask BEFORE the existing assignment and stamp AFTER it -- the existing assignment line itself is untouched (values must stay byte-identical):

```python
    for col in value_cols:
        fill_col = f"{col}_dedupe_fill"
        if fill_col not in picked.columns:
            continue
        has_conflict = ...   # existing code, unchanged
        missing_value = ...  # existing code, unchanged
        actually_filled = (
            missing_value & ~has_conflict
            & picked[fill_col].notna()
            & (picked[fill_col].astype("string").str.strip() != "")
        )
        picked.loc[missing_value & ~has_conflict, col] = picked.loc[
            missing_value & ~has_conflict, fill_col
        ]
        picked.loc[actually_filled, "dedupe_filled_fields"] = (
            picked.loc[actually_filled, "dedupe_filled_fields"]
            .map(lambda val, field=col: field if val == "" else f"{val},{field}")
        )
        picked.drop(columns=[fill_col], inplace=True)
```

A non-null fill landing on a missing winner value implies the donor is a different row of the group, i.e. a losing context -- no group-size check needed (a single-row group can only "fill" from itself, which cannot satisfy `missing_value & fill.notna()`).

`src_facts` is structurally excluded from filling already: `value_cols` is derived from `_VALUE_COLUMNS` (CONCEPT_MAP columns), which does not contain `src_facts` -- the first test pins this so a future widening of `value_cols` fails loudly.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_bdc_filings.py -q`
Expected: PASS, including all pre-existing dedup tests (fill behavior unchanged, only the marker added).

- [ ] **Step 5: Commit**

```bash
git add pipeline/bdc_filings.py tests/test_bdc_filings.py
git commit -m "provenance step 2: mark dedup-filled fields

- dedupe_filled_fields names fields whose published value came from a
  losing context (primary-of-N anchor, scoping risk 5)
- src_facts pinned to the winning context's payload"
```

---

### Task 3: Cohort-scoped cache-only re-extraction

**Files:**
- Modify: `pipeline/bdc_filings.py` (`rebuild_cached_bdc_holdings` :1257-1307)
- Modify: `scripts/rebuild_outputs.py` (`rebuild_bdc_holdings` :39-47 + argparse)
- Test: `tests/test_bdc_filings.py`

**Interfaces:**
- Consumes: `_normalize_cik_digits` (bdc_filings :625), `cohort_guard.load_cohort_ciks()` (returns 10-digit-padded CIK set), `BDC_FILINGS_INDEX_FILE` columns `cik`/`xbrl_download_status`/`xbrl_local_path`.
- Produces: `rebuild_cached_bdc_holdings(filings_index=None, ciks=None)` -- when `ciks` is given, only those CIKs' cached filings are re-parsed and the result is merged over the existing `bdc_holdings.csv` (other CIKs' rows byte-preserved). CLI: `python scripts/rebuild_outputs.py --bdc-holdings --cohort` (cohort manifest) or `--bdc-holdings --ciks 1849894 ...`.

- [ ] **Step 1: Write the failing tests**

```python
from pipeline.bdc_filings import rebuild_cached_bdc_holdings


class TestCohortScopedRebuild:
    def test_ciks_filter_merges_over_existing(self, tmp_path, monkeypatch):
        import pipeline.bdc_filings as bf
        out_file = tmp_path / "bdc_holdings.csv"
        monkeypatch.setattr(bf, "BDC_HOLDINGS_FILE", out_file)
        # existing artifact: one cohort CIK (stale) + one out-of-scope CIK
        pd.DataFrame([
            {"cik": "0000000001", "accession_number": "A1",
             "investment_identifier": "Old Row", "period": "2025-12-31",
             "dimensions_raw": "d", "fair_value": "1"},
            {"cik": "0000000002", "accession_number": "B1",
             "investment_identifier": "Keep Row", "period": "2025-12-31",
             "dimensions_raw": "d", "fair_value": "2"},
        ]).to_csv(out_file, index=False)
        # index: both CIKs cached; parse stub returns fresh rows w/ src_facts
        idx = pd.DataFrame([
            {"cik": "1", "accession_number": "A1",
             "xbrl_download_status": "cached", "xbrl_local_path": "x.xml"},
            {"cik": "2", "accession_number": "B1",
             "xbrl_download_status": "cached", "xbrl_local_path": "y.xml"},
        ])
        monkeypatch.setattr(Path, "exists", lambda self: True)
        monkeypatch.setattr(bf, "_parse_single_filing", lambda p, m: [{
            "cik": m["cik"], "accession_number": m["accession_number"],
            "investment_identifier": "New Row", "period": "2025-12-31",
            "dimensions_raw": "d", "_context_id": "c1", "fair_value": 9.0,
            "src_facts": '{"interest_rate":{"r":0.1}}'}])
        out = rebuild_cached_bdc_holdings(filings_index=idx, ciks=["1"])
        cik1 = out[out["cik"].astype(str).str.contains("1")]
        cik2 = out[out["cik"].astype(str).str.contains("2")]
        assert list(cik1["investment_identifier"]) == ["New Row"]   # replaced
        assert list(cik2["investment_identifier"]) == ["Keep Row"]  # untouched
        assert "src_facts" in out.columns
        # untouched rows get '' in the new column, not NaN
        assert cik2["src_facts"].fillna("").iloc[0] == ""
```

(The `Path.exists` monkeypatch is broad but test-local; it lets the stub index pass the cached-file existence check without fixture files. `write_parquet_companion` is called on the monkeypatched tmp path, which is fine.)

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_bdc_filings.py -k CohortScopedRebuild -v`
Expected: FAIL -- `TypeError: rebuild_cached_bdc_holdings() got an unexpected keyword argument 'ciks'`.

- [ ] **Step 3: Implement**

3a. `rebuild_cached_bdc_holdings(filings_index=None, ciks: list[str] | None = None)`. After the index is loaded, filter:

```python
    if ciks:
        wanted = {_normalize_cik_digits(c) for c in ciks}
        cik_norm = filings_index["cik"].map(_normalize_cik_digits)
        filings_index = filings_index.loc[cik_norm.isin(wanted)]
        logger.info("Cohort-scoped rebuild: %d CIKs, %d index rows",
                    len(wanted), len(filings_index))
```

3b. After `holdings = _deduplicate_bdc_holdings(pd.DataFrame(records))` and before the `to_csv`, merge back when scoped:

```python
    if ciks and BDC_HOLDINGS_FILE.exists():
        existing = pd.read_csv(BDC_HOLDINGS_FILE, dtype=str)
        keep = ~existing["cik"].map(_normalize_cik_digits).isin(wanted)
        existing = existing.loc[keep]
        for col in holdings.columns:
            if col not in existing.columns:
                existing[col] = ""
        for col in existing.columns:
            if col not in holdings.columns:
                holdings[col] = ""
        holdings = pd.concat([existing, holdings], ignore_index=True)
        logger.info("Merged over existing artifact: %d kept + %d re-extracted",
                    int(keep.sum()), len(holdings) - int(keep.sum()))
```

3c. `scripts/rebuild_outputs.py`: `rebuild_bdc_holdings(ciks=None)` passes through (`df = rebuild_cached_bdc_holdings(ciks=ciks)`); argparse gains `--ciks` (`nargs="*"`) and `--cohort` (`action="store_true"`); the `--bdc-holdings` dispatch resolves:

```python
    ciks = args.ciks or None
    if args.cohort:
        from pipeline.cohort_guard import load_cohort_ciks
        ciks = sorted(load_cohort_ciks())
    rebuild_bdc_holdings(ciks=ciks)
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_bdc_filings.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pipeline/bdc_filings.py scripts/rebuild_outputs.py tests/test_bdc_filings.py
git commit -m "provenance step 2: cohort-scoped cache-only re-extraction

- rebuild_cached_bdc_holdings(ciks=...) re-parses only the given CIKs'
  cached filings and merges over the existing artifact
- rebuild_outputs --bdc-holdings gains --ciks / --cohort (manifest-driven)
- confines provenance-migration drift + runtime to the cohort (risks 1/2)"
```

---

### Task 4: Unified schema batch -- 8 columns through staging

**Files:**
- Modify: `pipeline/unified_holdings.py` (`UNIFIED_COLUMNS`, after the step-1 `"shares_held_source",` entry)
- Modify: `pipeline/staging_bdc.py` (`_optional_cols` ~:410; Phase C SELECT, after the step-1 emission block that follows `src_context_id` ~:2589)
- Modify: `pipeline/staging_nport.py` (after the step-1 `'' AS shares_held_source,` line ~:299)
- Test: `tests/test_unified_holdings.py` (append to `TestPrepareBdc`)

**Interfaces:**
- Consumes: `src_facts` + `dedupe_filled_fields` in bdc_holdings.csv (Tasks 1-2); staging intermediates `_fv`, `_pa`, `_pct`, `_pik`, `_ugl`, `_text_pik_rate` (all already present in the Phase C scope).
- Produces: `UNIFIED_COLUMNS` order (insert after `"shares_held_source"`): `"fair_value_source", "principal_amount_source", "pct_of_net_assets_source", "pik_rate_source", "bdc_unrealized_gain_loss_source", "src_facts", "src_filled_fields", "corrected_fields"`. Task 5 populates `corrected_fields`; this task leaves it `''`.

- [ ] **Step 1: Write the failing tests**

Append to `TestPrepareBdc` in `tests/test_unified_holdings.py`:

```python
    def test_src_facts_and_filled_fields_pass_through(self):
        df = self._make_bdc_df([
            {"investment_identifier": "Acme Corp - Term Loan", "cik": "123",
             "fair_value": 1000000,
             "src_facts": '{"interest_rate":{"r":0.105}}',
             "dedupe_filled_fields": "cost"},
        ])
        result = _prepare_bdc(df)
        assert list(result["src_facts"]) == ['{"interest_rate":{"r":0.105}}']
        assert list(result["src_filled_fields"]) == ["cost"]
        assert list(result["corrected_fields"]) == [""]

    def test_value_field_pathway_enums(self):
        df = self._make_bdc_df([
            # fv + principal + pct + ugl from XBRL; pik from identifier text
            {"investment_identifier":
                 "Acme Corp - Term Loan 10.5% (incl. 2.0% PIK)",
             "cik": "123", "fair_value": 1000000, "principal_amount": 900000,
             "pct_of_net_assets": 0.4, "unrealized_gain_loss": 5000},
            # nothing populated
            {"investment_identifier": "Bare Corp - Equity", "cik": "123"},
        ])
        result = _prepare_bdc(df).set_index("issuer_name")
        acme = result.loc["Acme Corp"]
        assert acme["fair_value_source"] == "xbrl_field"
        assert acme["principal_amount_source"] == "xbrl_field"
        assert acme["pct_of_net_assets_source"] == "xbrl_field"
        assert acme["bdc_unrealized_gain_loss_source"] == "xbrl_field"
        assert acme["pik_rate_source"] == "identifier_text"
        bare = result.loc["Bare Corp"]
        for col in ("fair_value_source", "principal_amount_source",
                    "pct_of_net_assets_source", "pik_rate_source",
                    "bdc_unrealized_gain_loss_source"):
            assert bare[col] == ""

    def test_pik_rate_xbrl_pathway(self):
        df = self._make_bdc_df([
            {"investment_identifier": "Pik Corp - Term Loan", "cik": "123",
             "fair_value": 1, "pik_rate": 2.0},
        ])
        result = _prepare_bdc(df)
        assert result.iloc[0]["pik_rate_source"] == "xbrl_field"
```

NOTE: if the `_make_bdc_df` helper does not accept `unrealized_gain_loss`/`pct_of_net_assets` keys directly, mirror however the neighboring tests set those columns (the helper builds a raw bdc_holdings-shaped frame; these are raw column names there). The PIK identifier-text fixture must actually trigger `_text_pik_rate` -- check the nearest existing identifier-text PIK test for a string that parses (adjust the identifier if the pattern differs) and assert on `pik_rate` too, to prove which branch ran.

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_unified_holdings.py -k "src_facts_and_filled or pathway_enums or pik_rate_xbrl" -v`
Expected: FAIL -- `KeyError`.

- [ ] **Step 3: Implement (four edits)**

3a. `unified_holdings.py` -- in `UNIFIED_COLUMNS`, after `"shares_held_source",` insert:

```python
    "fair_value_source",
    "principal_amount_source",
    "pct_of_net_assets_source",
    "pik_rate_source",
    "bdc_unrealized_gain_loss_source",
    "src_facts",
    "src_filled_fields",
    "corrected_fields",
```

3b. `staging_bdc.py` `_optional_cols` -- append `"src_facts", "dedupe_filled_fields",`.

3c. `staging_bdc.py` Phase C SELECT -- after the step-1 emission block add:

```sql
            CASE WHEN _fv IS NOT NULL THEN 'xbrl_field' ELSE '' END AS fair_value_source,
            CASE WHEN _pa IS NOT NULL THEN 'xbrl_field' ELSE '' END AS principal_amount_source,
            CASE WHEN _pct IS NOT NULL THEN 'xbrl_field' ELSE '' END AS pct_of_net_assets_source,
            CASE WHEN _pik IS NOT NULL AND _pik >= 0 THEN 'xbrl_field'
                 WHEN _pik IS NULL AND _text_pik_rate IS NOT NULL THEN 'identifier_text'
                 ELSE '' END AS pik_rate_source,
            CASE WHEN _ugl IS NOT NULL THEN 'xbrl_field' ELSE '' END AS bdc_unrealized_gain_loss_source,
            COALESCE(CAST(src_facts AS VARCHAR), '') AS src_facts,
            COALESCE(CAST(dedupe_filled_fields AS VARCHAR), '') AS src_filled_fields,
            '' AS corrected_fields,
```

(The `pik_rate_source` conditions are copied from the published `pik_rate` CASE branch order at ~:2508-2513: `_pik < 0` publishes NULL and gets `''`.)

3d. `staging_nport.py` -- after the step-1 `'' AS shares_held_source,` line add eight `'' AS <col>,` lines in the same order as 3a.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_unified_holdings.py -k "TestPrepareBdc" -v` then `python -m pytest tests/test_unified_holdings.py tests/test_row_id.py -q` (the exact-schema assertion and row_id neighbors must pass -- row_id inputs are untouched).
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pipeline/unified_holdings.py pipeline/staging_bdc.py pipeline/staging_nport.py tests/test_unified_holdings.py
git commit -m "provenance step 2/3: schema batch -- src_facts + pathway enums through staging

- src_facts / src_filled_fields carried from the extractor into unified
- pathway enums for fair_value/principal/pct/pik/ugl (xbrl_field vs
  identifier_text vs empty); corrected_fields added empty for Task 5
- all columns in UNIFIED_COLUMNS in the same commit (silent-drop trap)"
```

---

### Task 5: `corrected_fields` from every correction layer

**Files:**
- Modify: `pipeline/agent_promoted.py` (new helpers + wiring in `apply_promoted_stage2_corrections` ~:156-177 and `apply_promoted_rules` ~:365)
- Modify: `pipeline/unified_holdings.py` (`_apply_row_corrections` apply site ~:1908-1914)
- Test: `tests/test_agent_promoted.py`, `tests/test_unified_holdings.py`

**Interfaces:**
- Consumes: `corrected_fields` column present from staging (Task 4).
- Produces: public `agent_promoted.CORRECTED_TRACKED_FIELDS: list[str]`, `agent_promoted.append_corrected_fields(df, idx, fields) -> None`, `agent_promoted.mark_corrected_fields(before_tracked: pd.DataFrame, after: pd.DataFrame) -> pd.DataFrame`. Every row whose tracked field a promoted B2 correction, promoted rule, or manual row correction modified carries the field name in `corrected_fields` (`;`-joined, deduped); applier-added rows carry `_row:added`. The re-verifier (Task 7) reads this to route corrected fields to `corrected` instead of a false mismatch (scoping risk 4).

- [ ] **Step 1: Write the failing tests**

In `tests/test_agent_promoted.py`:

```python
from pipeline.agent_promoted import (
    CORRECTED_TRACKED_FIELDS, append_corrected_fields, mark_corrected_fields,
)


class TestCorrectedFieldsMarking:
    def _frames(self):
        before = pd.DataFrame(
            {"fair_value": [100.0, 200.0], "interest_rate": [10.0, 11.0]},
            index=[5, 9])
        after = pd.DataFrame(
            {"fair_value": [100.0, 250.0], "interest_rate": [10.0, 11.0],
             "corrected_fields": ["", ""]},
            index=[5, 9])
        return before, after

    def test_changed_field_marked_on_changed_row_only(self):
        before, after = self._frames()
        out = mark_corrected_fields(before, after)
        assert out.loc[9, "corrected_fields"] == "fair_value"
        assert out.loc[5, "corrected_fields"] == ""

    def test_added_row_marked(self):
        before, after = self._frames()
        after.loc[77] = {"fair_value": 5.0, "interest_rate": 8.0,
                         "corrected_fields": ""}
        out = mark_corrected_fields(before, after)
        assert out.loc[77, "corrected_fields"] == "_row:added"

    def test_append_dedupes_and_sorts_incrementally(self):
        df = pd.DataFrame({"corrected_fields": ["fair_value", ""]}, index=[1, 2])
        append_corrected_fields(df, pd.Index([1, 2]), ["fair_value", "cost"])
        assert df.loc[1, "corrected_fields"] == "fair_value;cost"
        assert df.loc[2, "corrected_fields"] == "fair_value;cost"

    def test_nan_vs_nan_not_marked(self):
        before = pd.DataFrame({"fair_value": [None]}, index=[0])
        after = pd.DataFrame({"fair_value": [None], "corrected_fields": [""]},
                             index=[0])
        assert mark_corrected_fields(before, after).loc[0, "corrected_fields"] == ""
```

In `tests/test_unified_holdings.py`, next to the existing `_apply_row_corrections` tests (find them with `rg "_apply_row_corrections" tests/test_unified_holdings.py` and copy the corrections-CSV fixture of the nearest passing test):

```python
    def test_row_correction_stamps_corrected_fields(self, tmp_path):
        # arrange: copy the nearest existing row-corrections fixture verbatim
        # (frame with one matching row + corrections CSV patching fair_value),
        # ensure the frame has corrected_fields="" before the call
        ...
        result = _apply_row_corrections(df, corrections_path=corr_file)
        assert result.iloc[0]["corrected_fields"] == "fair_value"
```

(The `...` is fixture reuse, not a design gap: the neighboring test already constructs the matched-correction scenario; add the `corrected_fields` column and assertion.)

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_agent_promoted.py -k CorrectedFieldsMarking -v`
Expected: FAIL -- `ImportError`.

- [ ] **Step 3: Implement**

3a. `agent_promoted.py` helpers (module level, below the existing constants):

```python
# Fields whose modification by a correction layer is stamped into
# corrected_fields. Value fields feed the provenance re-verifier (a corrected
# row legitimately disagrees with its anchor -- scoping doc risk 4);
# classification fields are marked for audit symmetry.
CORRECTED_TRACKED_FIELDS = [
    "fair_value", "cost", "principal_amount", "shares_held",
    "pct_of_net_assets", "interest_rate", "basis_spread", "pik_rate",
    "maturity_date", "reference_rate_type", "coupon_type",
    "issuer_name", "instrument_description", "bdc_unrealized_gain_loss",
    "asset_category", "issuer_category", "index_classification",
    "exposure_type", "asset_class", "lien_position", "instrument_type",
    "is_subsidiary",
]


def append_corrected_fields(df: pd.DataFrame, idx, fields: list[str]) -> None:
    """Append field names to df['corrected_fields'] at idx (';'-joined, deduped,
    order-preserving). Creates the column if absent."""
    if "corrected_fields" not in df.columns:
        df["corrected_fields"] = ""

    def _merge(val: object) -> str:
        parts = [p for p in str(val or "").split(";") if p]
        parts.extend(f for f in fields if f and f not in parts)
        return ";".join(parts)

    df.loc[idx, "corrected_fields"] = df.loc[idx, "corrected_fields"].map(_merge)


def mark_corrected_fields(before_tracked: pd.DataFrame,
                          after: pd.DataFrame) -> pd.DataFrame:
    """Stamp after['corrected_fields'] with tracked fields whose value changed
    vs the pre-applier snapshot. Index-aligned (appliers preserve the original
    index; added rows appear as new labels and are marked '_row:added').
    NA-safe string comparison; per-CIK sub-frames only -- never the full frame."""
    common = after.index.intersection(before_tracked.index)
    added = after.index.difference(before_tracked.index)
    if len(added):
        append_corrected_fields(after, added, ["_row:added"])
    for col in before_tracked.columns:
        if col not in after.columns:
            continue
        b = before_tracked.loc[common, col].astype("string").str.strip().fillna("")
        a = after.loc[common, col].astype("string").str.strip().fillna("")
        changed = common[(a != b).to_numpy()]
        if len(changed):
            append_corrected_fields(after, changed, [col])
    return after
```

3b. Wire into `apply_promoted_stage2_corrections` -- in the per-leaf loop, around the `apply_scoped` call (~:158-159):

```python
            _before = corrected[
                [tc for tc in CORRECTED_TRACKED_FIELDS if tc in corrected.columns]
            ].copy()
            corrected, audit = apply_scoped(corrected, c)
            corrected = mark_corrected_fields(_before, corrected)
```

3c. Wire into `apply_promoted_rules` -- around the `apply_rules` call (~:365):

```python
        _before = sub[
            [tc for tc in CORRECTED_TRACKED_FIELDS if tc in sub.columns]].copy()
        corrected, rule_audits = apply_rules(sub, rules)
        corrected = mark_corrected_fields(_before, corrected)
```

3d. `unified_holdings.py` `_apply_row_corrections` -- at the apply site (:1908-1910), manual patches are explicit (row, field) edits, so mark unconditionally:

```python
        for field, value, reason in patches:
            df.loc[mask, field] = value
            if "corrected_fields" in df.columns:
                from pipeline.agent_promoted import append_corrected_fields
                append_corrected_fields(df, df.index[mask], [field])
            n_applied += 1
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_agent_promoted.py tests/test_unified_holdings.py -q`
Expected: PASS, including all pre-existing stage2/rules tests (values unchanged; only the marker column is written).

- [ ] **Step 5: Commit**

```bash
git add pipeline/agent_promoted.py pipeline/unified_holdings.py tests/test_agent_promoted.py tests/test_unified_holdings.py
git commit -m "provenance step 3: corrected_fields from every correction layer

- promoted B2 stage-2 leaves, promoted rules, and manual row corrections
  stamp per-row changed tracked fields; applier-added rows get _row:added
- without the marker the re-verifier would misroute every applied
  correction as extraction-wrong (scoping doc risk 4)"
```

---

### Task 6: Operator phase A -- re-extraction, gates, rebuild, docs

Preconditions (all must hold before Step 1):
- Step-1 passthroughs plan Task 5 closed (its rebuild gated + changelog written).
- No other data migration in flight; no running pytest/rebuild processes from other agents:
  `Get-Process | Where-Object { $_.ProcessName -match 'python|pytest' } | Select-Object Id, ProcessName`

- [ ] **Step 1: Snapshot**

```powershell
New-Item -ItemType Directory -Force data\snapshots\pre_prov_step2_20260823 | Out-Null
Copy-Item data\output\bdc_holdings.csv data\snapshots\pre_prov_step2_20260823\
Copy-Item data\output\private_markets_holdings.csv data\snapshots\pre_prov_step2_20260823\
```

- [ ] **Step 2: Cohort re-extraction (cache-only)**

```powershell
python scripts\rebuild_outputs.py --bdc-holdings --cohort
```

- [ ] **Step 3: GATE 1 -- bdc_holdings values identical (scoping risks 1/2)**

Save as `scratch/2026-08-23_prov_step2/bdc_holdings_gate.py` (named temp diagnostic per AGENTS.md; delete the session dir after the changelog entry) and run `python scratch\2026-08-23_prov_step2\bdc_holdings_gate.py`:

```python
"""Gate: provenance re-extraction changed NOTHING but the two new columns."""
import duckdb

OLD = "data/snapshots/pre_prov_step2_20260823/bdc_holdings.csv"
NEW = "data/output/bdc_holdings.csv"
con = duckdb.connect()
for name, path in (("o", OLD), ("n", NEW)):
    con.execute(f"CREATE VIEW {name} AS SELECT * FROM "
                f"read_csv_auto('{path}', header=true, all_varchar=true)")
checks = []
for label, sql in [
    ("row_count", "SELECT COUNT(*) FROM {t}"),
    ("per_cik_acc", "SELECT COUNT(*) FROM (SELECT cik, accession_number, "
     "COUNT(*) c FROM {t} GROUP BY 1,2)"),
    ("fv_sum", "SELECT ROUND(SUM(TRY_CAST(fair_value AS DOUBLE)), 2) FROM {t}"),
    ("cost_sum", "SELECT ROUND(SUM(TRY_CAST(cost AS DOUBLE)), 2) FROM {t}"),
    ("principal_sum",
     "SELECT ROUND(SUM(TRY_CAST(principal_amount AS DOUBLE)), 2) FROM {t}"),
    ("shares_sum",
     "SELECT ROUND(SUM(TRY_CAST(shares_held AS DOUBLE)), 2) FROM {t}"),
]:
    ov = con.execute(sql.format(t="o")).fetchone()[0]
    nv = con.execute(sql.format(t="n")).fetchone()[0]
    checks.append((label, ov, nv, ov == nv))
# per-cik-accession row-count drift (top offenders if any)
drift = con.execute("""
    SELECT COALESCE(a.cik, b.cik) cik, COALESCE(a.acc, b.acc) acc,
           COALESCE(a.c, 0) old_c, COALESCE(b.c, 0) new_c
    FROM (SELECT cik, accession_number acc, COUNT(*) c FROM o GROUP BY 1,2) a
    FULL OUTER JOIN (SELECT cik, accession_number acc, COUNT(*) c
                     FROM n GROUP BY 1,2) b
      ON a.cik = b.cik AND a.acc = b.acc
    WHERE COALESCE(a.c, 0) != COALESCE(b.c, 0)
    ORDER BY ABS(COALESCE(a.c, 0) - COALESCE(b.c, 0)) DESC LIMIT 25""").fetchall()
ok = all(c[3] for c in checks) and not drift
for label, ov, nv, eq in checks:
    print(f"  {'PASS' if eq else 'FAIL'} {label}: old={ov} new={nv}")
for row in drift:
    print(f"  DRIFT cik={row[0]} acc={row[1]} old_rows={row[2]} new_rows={row[3]}")
print("GATE:", "PASS" if ok else "FAIL")
raise SystemExit(0 if ok else 1)
```

If FAIL: STOP. The extractor has drifted since the last bdc_holdings build. Per scoping risk 2, adjudicate the drift separately (do not proceed to Step 4, do not fold drift into this migration). Restore the snapshot if abandoning.

- [ ] **Step 4: Unified rebuild + GATE 2**

```powershell
python scripts\rebuild_outputs.py --unified
```

Adapt `scratch/2026-08-22_anchor_rowid/unified_drift_gate.py` (point OLD at `data/snapshots/pre_prov_step2_20260823/private_markets_holdings.csv`): identical row count, total FV, per-classification and per-cik-quarter FV, `row_id` values unchanged. Additionally verify only the 8 new columns differ from the old schema.

- [ ] **Step 5: Coverage stats (record in changelog)**

DuckDB CLI over `data/output/private_markets_holdings.parquet`: rows with `src_facts != ''` (total + per cohort CIK); counts per pathway enum value for the 5 new `*_source` columns; `src_filled_fields != ''` count; `corrected_fields != ''` count (expect ~the 34 live B2 corrections' row footprint plus rules/manual rows); rows with `decimals_rescale` / `cik_scale_fix` events.

- [ ] **Step 6: Full suite + backstop**

```powershell
python -m pytest --durations=50 --durations-min=0.5 -q
python scripts\diff_outputs.py --semantic
```

Expected: green; semantic deltas remain the documented pre-existing set. (Reminder: pytest overwrites derived CSVs -- rerun `python scripts\rebuild_outputs.py --unified` afterward if the suite ran matching/returns tests, per the known test-overwrite pitfall.)

- [ ] **Step 7: Docs + commit**

- `docs/reference/schemas.md`: the 8 columns, the `src_facts` grammar + event vocabulary, the `''`-vs-`'xbrl_field'` convention note for `cost_source`/`shares_held_source`, and the known-empty region (N-PORT rows, non-cohort BDC rows until a wider re-extraction).
- `docs/agent_changelog.md`: dated entry with gate results, coverage stats, test counts.

```bash
git add docs/reference/schemas.md docs/agent_changelog.md
git commit -m "docs: provenance step-2/3 migration record

- cohort re-extraction gate results (values-identical) + coverage stats
- src_facts grammar v1 and pathway-enum conventions documented"
```

---

### Task 7: Re-verifier cheap tier (`pipeline/provenance_reverify.py`)

**Files:**
- Create: `pipeline/provenance_reverify.py`
- Test: `tests/test_provenance_reverify.py`

**Interfaces:**
- Consumes: unified holdings columns `row_id`, `source`, `cik`, `accession_number`, `report_date`, `src_context_id`, `src_facts`, `src_transforms`, `src_conflict_fields`, `src_filled_fields`, `corrected_fields`, the `*_source` enums, and the published value columns.
- Produces: `cheap_tier(holdings_df=None, holdings_path=None, ciks=None) -> pd.DataFrame` -- long format, one row per (row_id, field), columns: `row_id, cik, accession_number, report_date, src_context_id, field, pathway, declared_raw, declared_events, published, expected, cheap_status`. `cheap_status` enum: `pass | pass_trivial | fail | corrected | derived | text_pathway | filled_field | merged_conflict | missing_raw_with_transform | no_provenance`. Task 8 consumes this frame.

**Verification rule (scoping 2.3):** `published == declared_raw * 10^k(decimals) * 1000(cik_scale_fix) * m(staging events)` where staging `m` comes from `src_transforms` codes: `rate_x100 -> x100`, `rate_div100 -> /100`, `pik_boundary_div100 -> /100`, `neg_null -> published must be NULL`. Fields checked: `interest_rate`, `basis_spread`, `pik_rate`, `pct_of_net_assets` (raw always declared), plus `fair_value`, `cost`, `principal_amount`, `shares_held` (raw declared only when an extractor event fired; otherwise `pass_trivial` -- published equals the extractor value by construction and only the full tier can add information).

- [ ] **Step 1: Write the failing tests**

`tests/test_provenance_reverify.py`:

```python
"""Tests for pipeline.provenance_reverify -- deterministic two-tier
re-verification of provenance-annotated unified holdings rows."""
import json

import pandas as pd
import pytest

from pipeline.provenance_reverify import cheap_tier


def _row(**kw):
    base = {
        "row_id": "ROW-0000000000000001", "source": "bdc", "cik": "0001287750",
        "accession_number": "0001287750-26-000001", "report_date": "2025-12-31",
        "src_context_id": "ctx1", "src_facts": "", "src_transforms": "",
        "src_conflict_fields": "", "src_filled_fields": "",
        "corrected_fields": "",
        "fair_value": 1000000.0, "cost": None, "principal_amount": None,
        "shares_held": None, "pct_of_net_assets": None,
        "interest_rate": None, "basis_spread": None, "pik_rate": None,
        "interest_rate_source": "", "basis_spread_source": "",
        "pik_rate_source": "", "pct_of_net_assets_source": "",
        "fair_value_source": "xbrl_field", "cost_source": "",
        "shares_held_source": "", "principal_amount_source": "",
    }
    return {**base, **kw}


class TestCheapTier:
    def test_rate_x100_pass_and_fail(self):
        df = pd.DataFrame([
            _row(row_id="ROW-a", interest_rate=10.5,
                 interest_rate_source="xbrl_field",
                 src_facts=json.dumps({"interest_rate": {"r": 0.105}}),
                 src_transforms="interest_rate:rate_x100"),
            _row(row_id="ROW-b", interest_rate=99.0,
                 interest_rate_source="xbrl_field",
                 src_facts=json.dumps({"interest_rate": {"r": 0.105}}),
                 src_transforms="interest_rate:rate_x100"),
        ])
        out = cheap_tier(holdings_df=df)
        ir = out[out["field"] == "interest_rate"].set_index("row_id")
        assert ir.loc["ROW-a", "cheap_status"] == "pass"
        assert ir.loc["ROW-a", "expected"] == pytest.approx(10.5)
        assert ir.loc["ROW-b", "cheap_status"] == "fail"

    def test_decimals_event_on_monetary_field(self):
        df = pd.DataFrame([_row(
            row_id="ROW-c", fair_value=500000.0,
            src_facts=json.dumps({"fair_value":
                {"c": "investmentownedatfairvalue", "r": 500000000,
                 "x": ["decimals_rescale:10^-3"]}}))])
        out = cheap_tier(holdings_df=df)
        fv = out[(out["field"] == "fair_value")].iloc[0]
        assert fv["cheap_status"] == "pass"
        assert fv["expected"] == pytest.approx(500000.0)

    def test_untransformed_monetary_is_trivial_pass(self):
        out = cheap_tier(holdings_df=pd.DataFrame([_row()]))
        fv = out[out["field"] == "fair_value"].iloc[0]
        assert fv["cheap_status"] == "pass_trivial"

    def test_short_circuit_statuses(self):
        df = pd.DataFrame([
            _row(row_id="ROW-t", interest_rate=10.0,
                 interest_rate_source="identifier_text"),
            _row(row_id="ROW-d", cost=1000.0, cost_source="derived_proxy"),
            _row(row_id="ROW-k", fair_value=5.0,
                 corrected_fields="fair_value"),
            _row(row_id="ROW-f", cost=99.0, src_filled_fields="cost"),
            _row(row_id="ROW-m", fair_value=7.0,
                 src_conflict_fields="fair_value"),
            _row(row_id="ROW-n", src_context_id=""),
        ])
        out = cheap_tier(holdings_df=df).set_index(["row_id", "field"])
        assert out.loc[("ROW-t", "interest_rate"), "cheap_status"] == "text_pathway"
        assert out.loc[("ROW-d", "cost"), "cheap_status"] == "derived"
        assert out.loc[("ROW-k", "fair_value"), "cheap_status"] == "corrected"
        assert out.loc[("ROW-f", "cost"), "cheap_status"] == "filled_field"
        assert out.loc[("ROW-m", "fair_value"), "cheap_status"] == "merged_conflict"
        assert out.loc[("ROW-n", "fair_value"), "cheap_status"] == "no_provenance"

    def test_neg_null_event(self):
        df = pd.DataFrame([_row(
            row_id="ROW-e", interest_rate=None,
            src_facts=json.dumps({"interest_rate": {"r": -1.0}}),
            src_transforms="interest_rate:neg_null")])
        out = cheap_tier(holdings_df=df)
        ir = out[out["field"] == "interest_rate"].iloc[0]
        assert ir["cheap_status"] == "pass"

    def test_event_without_raw_fails_loudly(self):
        df = pd.DataFrame([_row(
            row_id="ROW-g", interest_rate=10.5,
            interest_rate_source="xbrl_field",
            src_transforms="interest_rate:rate_x100", src_facts="")])
        out = cheap_tier(holdings_df=df)
        ir = out[out["field"] == "interest_rate"].iloc[0]
        assert ir["cheap_status"] == "missing_raw_with_transform"
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_provenance_reverify.py -v`
Expected: FAIL -- `ModuleNotFoundError: pipeline.provenance_reverify`.

- [ ] **Step 3: Implement**

Create `pipeline/provenance_reverify.py`. Core design -- one DuckDB query per field (generated from a spec table, UNION ALL'd), never a pandas row loop:

```python
"""Deterministic two-tier re-verification of provenance-annotated holdings.

Cheap tier (this half): re-derive each published value from its declared raw
(src_facts) + declared transform events (src_facts.x + src_transforms) with no
filing access -- runnable on every rebuild. Full tier (full_tier): re-read the
cached iXBRL instance at (accession, src_context_id, concept). Consumes the
provenance columns; never writes to the holdings artifact (verification STATE
lives in the ledger only -- scoping doc section 2). ASCII-only. Cache-only.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

logger = logging.getLogger(__name__)

# field -> (pathway enum column, empty-pathway-means-xbrl?) -- cost/shares keep
# step-1 semantics where '' = as-extracted xbrl pathway.
CHEAP_FIELDS: dict[str, tuple[str, bool]] = {
    "interest_rate": ("interest_rate_source", False),
    "basis_spread": ("basis_spread_source", False),
    "pik_rate": ("pik_rate_source", False),
    "pct_of_net_assets": ("pct_of_net_assets_source", False),
    "fair_value": ("fair_value_source", False),
    "cost": ("cost_source", True),
    "principal_amount": ("principal_amount_source", False),
    "shares_held": ("shares_held_source", True),
}
_RATE_FIELDS = ("interest_rate", "basis_spread", "pik_rate", "pct_of_net_assets")

_ID_COLS = ("row_id, cik, accession_number, report_date, src_context_id")


def _field_sql(field: str, source_col: str, empty_is_xbrl: bool) -> str:
    """One SELECT producing the cheap-tier verdict for *field* (long format)."""
    is_rate = field in _RATE_FIELDS
    pathway = f"COALESCE(CAST({source_col} AS VARCHAR), '')"
    raw = f"TRY_CAST(json_extract_string(NULLIF(src_facts, ''), '$.{field}.r') AS DOUBLE)"
    # extractor-side multiplier from src_facts.x
    dec = (f"CASE WHEN json_extract_string(NULLIF(src_facts, ''), '$.{field}.x') "
           f"LIKE '%decimals_rescale:10^%' THEN POWER(10.0, TRY_CAST("
           f"regexp_extract(json_extract_string(NULLIF(src_facts, ''), "
           f"'$.{field}.x'), 'decimals_rescale:10\\^(-?\\d+)', 1) AS INTEGER)) "
           f"ELSE 1.0 END")
    cik_fix = (f"CASE WHEN json_extract_string(NULLIF(src_facts, ''), "
               f"'$.{field}.x') LIKE '%cik_scale_fix:x1000%' THEN 1000.0 "
               f"ELSE 1.0 END")
    ev = "COALESCE(CAST(src_transforms AS VARCHAR), '')"
    stag = (f"CASE WHEN {ev} LIKE '%{field}:rate_x100%' THEN 100.0 "
            f"WHEN {ev} LIKE '%{field}:rate_div100%' THEN 0.01 "
            f"WHEN {ev} LIKE '%{field}:pik_boundary_div100%' THEN 0.01 "
            f"ELSE 1.0 END")
    neg_null = f"({ev} LIKE '%{field}:neg_null%')"
    has_event = (f"({ev} LIKE '%{field}:%' OR "
                 f"json_extract_string(NULLIF(src_facts, ''), '$.{field}.x') "
                 f"IS NOT NULL)")
    published = f"TRY_CAST({field} AS DOUBLE)"
    expected = f"({raw} * {dec} * {cik_fix} * {stag})"
    marker = lambda col: (f"(',' || COALESCE(CAST({col} AS VARCHAR), '') || ',') "
                          f"LIKE '%,{field},%' OR "
                          f"(';' || COALESCE(CAST({col} AS VARCHAR), '') || ';') "
                          f"LIKE '%;{field};%'")
    return f"""
    SELECT {_ID_COLS}, '{field}' AS field, {pathway} AS pathway,
           {raw} AS declared_raw,
           {ev} AS declared_events,
           {published} AS published, {expected} AS expected,
           CASE
             WHEN {marker('corrected_fields')} THEN 'corrected'
             WHEN {pathway} = 'derived_proxy' THEN 'derived'
             WHEN {pathway} = 'identifier_text' THEN 'text_pathway'
             WHEN {marker('src_filled_fields')} THEN 'filled_field'
             WHEN {marker('src_conflict_fields')} THEN 'merged_conflict'
             WHEN COALESCE(CAST(src_context_id AS VARCHAR), '') = ''
               THEN 'no_provenance'
             WHEN {published} IS NULL AND {raw} IS NULL AND NOT {has_event}
               THEN 'pass_trivial'
             WHEN {neg_null} THEN
               CASE WHEN {published} IS NULL THEN 'pass' ELSE 'fail' END
             WHEN {raw} IS NULL AND {has_event}
               THEN 'missing_raw_with_transform'
             WHEN {raw} IS NULL THEN
               {"'fail'" if is_rate else "'pass_trivial'"}
             WHEN ABS({expected} - {published})
                  <= 1e-6 * GREATEST(ABS({expected}), ABS({published}), 1e-12)
               THEN 'pass'
             ELSE 'fail'
           END AS cheap_status
    FROM h
    WHERE lower(COALESCE(CAST(source AS VARCHAR), '')) = 'bdc'
    """
```

Note the one asymmetry: for rate fields, a NULL declared raw with an `xbrl_field` pathway and a non-null published value means the declaration is incomplete -> `fail` (the extractor always records `r` for rates); for monetary fields NULL raw is the documented "raw equals stored value" case -> `pass_trivial`. Guard the rate-fields branch further: when `pathway` is `''` and `published` is NULL -> the field is simply absent -> emit `pass_trivial`, not `fail` (add `WHEN {pathway} = '' AND {published} IS NULL THEN 'pass_trivial'` above the rate-NULL-raw branch).

```python
def cheap_tier(holdings_df: pd.DataFrame | None = None,
               holdings_path: Path | None = None,
               ciks: list[str] | None = None) -> pd.DataFrame:
    """Cheap-tier verdicts for every (bdc row, checkable field)."""
    con = duckdb.connect()
    if holdings_df is not None:
        con.register("h_src", holdings_df)
        con.execute("CREATE VIEW h AS SELECT * FROM h_src")
    else:
        if holdings_path is None:
            from pipeline import config
            holdings_path = config.UNIFIED_HOLDINGS_PARQUET_FILE
        src = str(holdings_path).replace("'", "''")
        reader = ("read_parquet" if str(holdings_path).endswith(".parquet")
                  else "read_csv_auto")
        con.execute(f"CREATE VIEW h AS SELECT * FROM {reader}('{src}')")
    if ciks:
        wanted = ",".join(
            f"'{str(c).lstrip('0') or '0'}'" for c in sorted(set(ciks)))
        con.execute("CREATE OR REPLACE VIEW h AS SELECT * FROM h WHERE "
                    "ltrim(regexp_replace(CAST(cik AS VARCHAR), '[^0-9]', '', "
                    f"'g'), '0') IN ({wanted})")
    parts = [_field_sql(f, sc, e) for f, (sc, e) in CHEAP_FIELDS.items()]
    out = con.execute(" UNION ALL ".join(parts)).fetchdf()
    con.close()
    return out
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_provenance_reverify.py -v`
Expected: PASS. Iterate on the SQL until all status paths behave (the tests cover every branch).

- [ ] **Step 5: Commit**

```bash
git add pipeline/provenance_reverify.py tests/test_provenance_reverify.py
git commit -m "provenance step 4: cheap-tier re-verifier

- re-derives published values from declared raw + transform events in
  DuckDB, no filing access -- runnable on every rebuild
- short-circuits corrected/derived/text/filled/conflict/no-provenance
  rows into their own statuses (verified-FV accounting rule)"
```

---

### Task 8: Re-verifier full tier + reason-code triage

**Files:**
- Modify: `pipeline/provenance_reverify.py`
- Test: `tests/test_provenance_reverify.py`

**Interfaces:**
- Consumes: the cheap-tier frame (Task 7); `pipeline.bdc_filings` internals `_local_name`, `_match_concept`, `_parse_fact_value`, `CANONICAL_CONCEPT`; `BDC_FILINGS_INDEX_FILE` (columns `accession_number`, `xbrl_local_path`, `xbrl_download_status`).
- Produces:
  - `full_tier(cheap_df, xml_loader=None, filings_index=None) -> pd.DataFrame` -- cheap_df plus columns `instance_raw` (float|None), `full_status` in `raw_match | raw_stale | published_mismatch | anchor_missing | context_missing | source_unavailable | not_checked`.
  - `classify_reason(cheap_status, full_status) -> str` -- pure function, the deterministic triage of scoping 8.2. Reason enum: `verified | anchor_stale | transform_drift | filing_mismatch | anchor_missing | provenance_wrong | source_unavailable | corrected | derived | text_pathway | merged_context_excluded | no_provenance | unchecked_trivial`.
  - `xml_loader(cik, accession) -> lxml tree | None` injectable for tests; production default resolves `xbrl_local_path` from the filings index.

**Triage table (implement exactly; scoping 8.2):**

| cheap_status | full_status | reason_code |
|---|---|---|
| corrected | (any) | corrected |
| derived | (any) | derived |
| text_pathway | (any) | text_pathway |
| filled_field / merged_conflict | (any) | merged_context_excluded |
| no_provenance | (any) | no_provenance |
| pass / pass_trivial | raw_match | verified |
| pass / pass_trivial | raw_stale | anchor_stale (extractor improved; re-stamp, no code fix) |
| (any checkable) | published_mismatch | filing_mismatch (extraction-wrong vs parser-drift vs amended: adjudication, not triage) |
| fail / missing_raw_with_transform | raw_match | transform_drift (declared events no longer reproduce published; registry/code drift) |
| (any checkable) | anchor_missing | anchor_missing |
| (any checkable) | context_missing | provenance_wrong |
| (any checkable) | source_unavailable | source_unavailable |
| pass_trivial | not_checked | unchecked_trivial |

**Full-tier semantics per (row, field):** parse the filing once per accession; collect the elements whose `contextRef == src_context_id`; the field's fact = declared `c` exact localname match when `c` is present, else replay `_match_concept` and take the first non-nil, non-empty match in document order (the extractor's own rule). Then:
- fact absent -> `anchor_missing`; context absent entirely -> `context_missing`; file unresolvable -> `source_unavailable`.
- `expected_published = instance_raw * declared extractor+staging multipliers` (reuse the cheap-tier multiplier logic in Python: parse `x` events + `declared_events` string). Mismatch vs published -> `published_mismatch`.
- else `instance_raw == declared_raw` (or raw undeclared) -> `raw_match`; declared but different -> `raw_stale`.

- [ ] **Step 1: Write the failing tests**

```python
from pipeline.provenance_reverify import classify_reason, full_tier


_FIXTURE_XML = (
    '<xbrl xmlns:us-gaap="http://fasb.org/us-gaap/2024">'
    '<us-gaap:InvestmentInterestRate contextRef="ctx1">0.105'
    '</us-gaap:InvestmentInterestRate>'
    '<us-gaap:InvestmentOwnedAtFairValue contextRef="ctx1" unitRef="usd">'
    '1000000</us-gaap:InvestmentOwnedAtFairValue>'
    '</xbrl>')


def _loader(cik, accession):
    from lxml import etree
    return etree.ElementTree(etree.fromstring(_FIXTURE_XML))


class TestFullTier:
    def _cheap(self, **kw):
        base = {
            "row_id": "ROW-a", "cik": "0001287750",
            "accession_number": "0001287750-26-000001",
            "report_date": "2025-12-31", "src_context_id": "ctx1",
            "field": "interest_rate", "pathway": "xbrl_field",
            "declared_raw": 0.105,
            "declared_events": "interest_rate:rate_x100",
            "published": 10.5, "expected": 10.5, "cheap_status": "pass",
        }
        return pd.DataFrame([{**base, **kw}])

    def test_verified_roundtrip(self):
        out = full_tier(self._cheap(), xml_loader=_loader)
        assert out.iloc[0]["full_status"] == "raw_match"
        assert out.iloc[0]["instance_raw"] == pytest.approx(0.105)

    def test_stale_declared_raw_but_published_consistent(self):
        # declared raw is stale (0.2) but published 10.5 == instance 0.105*100
        out = full_tier(self._cheap(declared_raw=0.2, cheap_status="fail"),
                        xml_loader=_loader)
        assert out.iloc[0]["full_status"] == "raw_stale"

    def test_published_no_longer_matches_filing(self):
        out = full_tier(self._cheap(published=99.0), xml_loader=_loader)
        assert out.iloc[0]["full_status"] == "published_mismatch"

    def test_anchor_and_context_and_file_missing(self):
        assert full_tier(self._cheap(field="basis_spread", declared_raw=None,
                                     declared_events="", published=None),
                         xml_loader=_loader).iloc[0]["full_status"] == "anchor_missing"
        assert full_tier(self._cheap(src_context_id="ctxZZ"),
                         xml_loader=_loader).iloc[0]["full_status"] == "context_missing"
        assert full_tier(self._cheap(),
                         xml_loader=lambda c, a: None).iloc[0]["full_status"] == "source_unavailable"

    def test_short_circuits_not_checked(self):
        out = full_tier(self._cheap(cheap_status="corrected"),
                        xml_loader=_loader)
        assert out.iloc[0]["full_status"] == "not_checked"


class TestClassifyReason:
    @pytest.mark.parametrize("cheap,full,reason", [
        ("pass", "raw_match", "verified"),
        ("pass", "raw_stale", "anchor_stale"),
        ("fail", "raw_match", "transform_drift"),
        ("pass", "published_mismatch", "filing_mismatch"),
        ("pass", "anchor_missing", "anchor_missing"),
        ("pass", "context_missing", "provenance_wrong"),
        ("pass", "source_unavailable", "source_unavailable"),
        ("corrected", "not_checked", "corrected"),
        ("derived", "not_checked", "derived"),
        ("text_pathway", "not_checked", "text_pathway"),
        ("filled_field", "not_checked", "merged_context_excluded"),
        ("merged_conflict", "not_checked", "merged_context_excluded"),
        ("no_provenance", "not_checked", "no_provenance"),
        ("pass_trivial", "not_checked", "unchecked_trivial"),
    ])
    def test_table(self, cheap, full, reason):
        assert classify_reason(cheap, full) == reason
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_provenance_reverify.py -k "FullTier or ClassifyReason" -v`
Expected: FAIL -- `ImportError`.

- [ ] **Step 3: Implement**

In `pipeline/provenance_reverify.py`:

```python
_SHORT_CIRCUIT = frozenset({"corrected", "derived", "text_pathway",
                            "filled_field", "merged_conflict", "no_provenance"})


def _staging_multiplier(field: str, events: str) -> float:
    if f"{field}:rate_x100" in events:
        return 100.0
    if f"{field}:rate_div100" in events or f"{field}:pik_boundary_div100" in events:
        return 0.01
    return 1.0


def _extractor_multiplier(x_events: list[str]) -> float:
    mult = 1.0
    for code in x_events or []:
        if code.startswith("decimals_rescale:10^"):
            mult *= 10.0 ** int(code.split("^", 1)[1])
        elif code.startswith("cik_scale_fix:x"):
            mult *= float(code.split("x", 1)[1])
    return mult


def _numbers_close(a: float, b: float) -> bool:
    return abs(a - b) <= 1e-6 * max(abs(a), abs(b), 1e-12)


def _default_xml_loader(filings_index: pd.DataFrame):
    paths = dict(zip(filings_index["accession_number"].astype(str),
                     filings_index["xbrl_local_path"].astype(str)))

    def _load(cik: str, accession: str):
        from lxml import etree
        p = paths.get(str(accession), "")
        if not p or not Path(p).exists():
            return None
        try:
            return etree.parse(p)
        except Exception:
            return None
    return _load


def full_tier(cheap_df: pd.DataFrame, xml_loader=None,
              filings_index: pd.DataFrame | None = None) -> pd.DataFrame:
    """Re-read each anchored fact from the cached instance. Row loop is over
    ACCESSIONS (filing count), never holdings rows."""
    from pipeline.bdc_filings import (
        CANONICAL_CONCEPT, _local_name, _match_concept, _parse_fact_value)

    if xml_loader is None:
        if filings_index is None:
            from pipeline.config import BDC_FILINGS_INDEX_FILE
            filings_index = pd.read_csv(BDC_FILINGS_INDEX_FILE, dtype=str)
        xml_loader = _default_xml_loader(filings_index)

    out = cheap_df.copy()
    out["instance_raw"] = None
    out["full_status"] = "not_checked"
    checkable = ~out["cheap_status"].isin(_SHORT_CIRCUIT)
    # pass_trivial monetary rows with nothing declared stay not_checked only
    # when there is nothing to look up (no published value)
    checkable &= ~((out["cheap_status"] == "pass_trivial")
                   & out["published"].isna())

    for (cik, accession), grp in out.loc[checkable].groupby(
            ["cik", "accession_number"], sort=False):
        tree = xml_loader(str(cik), str(accession))
        if tree is None:
            out.loc[grp.index, "full_status"] = "source_unavailable"
            continue
        # one pass over the tree: ctx -> field -> (local, raw_text) first-wins
        wanted_ctx = set(grp["src_context_id"].astype(str))
        facts: dict[str, dict[str, tuple[str, str]]] = {}
        seen_ctx: set[str] = set()
        for elem in tree.getroot().iter():
            ctx = elem.get("contextRef")
            if ctx is None or ctx not in wanted_ctx:
                continue
            seen_ctx.add(ctx)
            local = _local_name(elem.tag).lower()
            raw_text = (elem.text or "").strip()
            if not raw_text:
                continue
            col = _match_concept(local)
            if col is None:
                continue
            facts.setdefault(ctx, {}).setdefault(col, (local, raw_text))
            facts[ctx].setdefault(f"__by_local__{local}", (local, raw_text))
        for i, r in grp.iterrows():
            ctx = str(r["src_context_id"])
            if ctx not in seen_ctx:
                out.at[i, "full_status"] = "context_missing"
                continue
            field = str(r["field"])
            declared_c = ""
            try:
                sf = json.loads(str(r.get("src_facts") or "") or "{}")
                declared_c = str((sf.get(field) or {}).get("c") or "")
                x_events = list((sf.get(field) or {}).get("x") or [])
            except (json.JSONDecodeError, AttributeError):
                x_events = []
            hit = (facts.get(ctx, {}).get(f"__by_local__{declared_c}")
                   if declared_c else facts.get(ctx, {}).get(field))
            if hit is None:
                out.at[i, "full_status"] = "anchor_missing"
                continue
            _local, raw_text = hit
            instance_raw = _parse_fact_value(field, raw_text)
            out.at[i, "instance_raw"] = instance_raw
            if not isinstance(instance_raw, (int, float)):
                out.at[i, "full_status"] = "anchor_missing"
                continue
            mult = (_extractor_multiplier(x_events)
                    * _staging_multiplier(field, str(r["declared_events"] or "")))
            neg_null = f"{field}:neg_null" in str(r["declared_events"] or "")
            published = r["published"]
            if neg_null:
                pub_ok = pd.isna(published) and instance_raw < 0
            else:
                pub_ok = (not pd.isna(published)
                          and _numbers_close(instance_raw * mult, float(published)))
            if not pub_ok:
                out.at[i, "full_status"] = "published_mismatch"
                continue
            declared_raw = r["declared_raw"]
            if pd.isna(declared_raw) or _numbers_close(float(declared_raw),
                                                      float(instance_raw)):
                out.at[i, "full_status"] = "raw_match"
            else:
                out.at[i, "full_status"] = "raw_stale"
    return out


_REASON_TABLE = {
    "corrected": "corrected", "derived": "derived",
    "text_pathway": "text_pathway",
    "filled_field": "merged_context_excluded",
    "merged_conflict": "merged_context_excluded",
    "no_provenance": "no_provenance",
}


def classify_reason(cheap_status: str, full_status: str) -> str:
    """Deterministic triage (scoping doc 8.2): re-derivable from evidence."""
    if cheap_status in _REASON_TABLE:
        return _REASON_TABLE[cheap_status]
    if full_status == "source_unavailable":
        return "source_unavailable"
    if full_status == "context_missing":
        return "provenance_wrong"
    if full_status == "anchor_missing":
        return "anchor_missing"
    if full_status == "published_mismatch":
        return "filing_mismatch"
    if full_status == "raw_stale":
        return "anchor_stale"
    if full_status == "raw_match":
        return "transform_drift" if cheap_status in (
            "fail", "missing_raw_with_transform") else "verified"
    return "unchecked_trivial"
```

NOTE for the implementer: `full_tier` requires `src_facts` on the cheap frame for declared-concept lookups -- add `src_facts` to `_ID_COLS` in Task 7's output (and to the Task 7 test base dict assertions if the schema check breaks). Do this as part of this task and update Task 7's tests accordingly.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_provenance_reverify.py -v`
Expected: PASS (both tiers + triage table).

- [ ] **Step 5: Commit**

```bash
git add pipeline/provenance_reverify.py tests/test_provenance_reverify.py
git commit -m "provenance step 4: full-tier filing re-read + reason triage

- re-reads each anchored fact at (accession, contextRef, concept) from the
  cached instance; one parse per accession, no row-level scans
- classify_reason implements the 8.2 triage table incl. the anchor_stale
  vs regression split that protects the future code-repair lane"
```

---

### Task 9: Ledger artifact, CLI, cohort run, docs

**Files:**
- Modify: `pipeline/provenance_reverify.py` (ledger writer + `main()`)
- Modify: `pipeline/config.py`
- Test: `tests/test_provenance_reverify.py`
- Docs: `docs/reference/schemas.md`, `docs/agent_changelog.md`

**Interfaces:**
- Consumes: `cheap_tier`, `full_tier`, `classify_reason`.
- Produces: `build_ledger(ledger_df, out_dir) -> tuple[Path, Path]` writing `provenance_ledger.csv` (keyed `(row_id, field)` per scoping 8.1: identity cols + both tiers' evidence + `reason_code` + `artifact_mtime` of the holdings file it was computed against) and `provenance_ledger_summary.csv` (per cik x report_date: field counts per reason_code, `verified_fv`, `derived_fv`, `total_fv`, `verified_fv_share`). CLI: `python -m pipeline.provenance_reverify --cohort [--cheap-only] [--ciks ...] [--out DIR]`.
- Config: `PROVENANCE_LEDGER_FILE = OUTPUT_DIR / "provenance_ledger.csv"`, `PROVENANCE_LEDGER_SUMMARY_FILE = OUTPUT_DIR / "provenance_ledger_summary.csv"`.

**Verified-FV accounting rule (scoping 2.4, mandatory):** `verified_fv` sums `fair_value` only over rows whose `fair_value` field's reason is `verified`. `derived`/`corrected` FV are their own buckets, never the verified numerator. `verified_fv_share = verified_fv / total_fv`.

- [ ] **Step 1: Write the failing tests**

```python
from pipeline.provenance_reverify import build_ledger


class TestLedger:
    def test_ledger_and_summary_written(self, tmp_path):
        df = pd.DataFrame([
            {"row_id": "ROW-a", "cik": "1", "accession_number": "A",
             "report_date": "2025-12-31", "src_context_id": "c1",
             "field": "fair_value", "pathway": "xbrl_field",
             "declared_raw": None, "declared_events": "",
             "published": 100.0, "expected": None, "instance_raw": 100.0,
             "cheap_status": "pass_trivial", "full_status": "raw_match"},
            {"row_id": "ROW-b", "cik": "1", "accession_number": "A",
             "report_date": "2025-12-31", "src_context_id": "c2",
             "field": "fair_value", "pathway": "",
             "declared_raw": None, "declared_events": "",
             "published": 50.0, "expected": None, "instance_raw": None,
             "cheap_status": "corrected", "full_status": "not_checked"},
        ])
        ledger_path, summary_path = build_ledger(
            df, out_dir=tmp_path, holdings_mtime="2026-08-23T00:00:00")
        ledger = pd.read_csv(ledger_path)
        assert set(["row_id", "field", "reason_code"]) <= set(ledger.columns)
        assert ledger.set_index("row_id").loc["ROW-a", "reason_code"] == "verified"
        assert ledger.set_index("row_id").loc["ROW-b", "reason_code"] == "corrected"
        summary = pd.read_csv(summary_path)
        row = summary.iloc[0]
        assert row["verified_fv"] == 100.0
        assert row["total_fv"] == 150.0
        assert row["verified_fv_share"] == pytest.approx(100.0 / 150.0)
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_provenance_reverify.py -k Ledger -v`
Expected: FAIL -- `ImportError: build_ledger`.

- [ ] **Step 3: Implement**

```python
def build_ledger(tier_df: pd.DataFrame, out_dir: Path,
                 holdings_mtime: str = "") -> tuple[Path, Path]:
    ledger = tier_df.copy()
    ledger["reason_code"] = [
        classify_reason(c, f) for c, f in
        zip(ledger["cheap_status"], ledger["full_status"])]
    ledger["holdings_artifact_mtime"] = holdings_mtime
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = out_dir / "provenance_ledger.csv"
    ledger.to_csv(ledger_path, index=False)

    fv = ledger[ledger["field"] == "fair_value"].copy()
    fv["published"] = pd.to_numeric(fv["published"], errors="coerce").fillna(0.0)
    grp = fv.groupby(["cik", "report_date"], dropna=False)
    summary = grp.apply(lambda g: pd.Series({
        "n_fields": len(g),
        "n_verified": int((g["reason_code"] == "verified").sum()),
        "verified_fv": g.loc[g["reason_code"] == "verified", "published"].sum(),
        "derived_fv": g.loc[g["reason_code"] == "derived", "published"].sum(),
        "corrected_fv": g.loc[g["reason_code"] == "corrected", "published"].sum(),
        "total_fv": g["published"].sum(),
    })).reset_index()
    summary["verified_fv_share"] = (
        summary["verified_fv"] / summary["total_fv"].replace(0, pd.NA))
    # reason-code counts wide, all fields
    counts = (ledger.groupby(["cik", "report_date", "reason_code"])
              .size().unstack(fill_value=0).reset_index())
    summary = summary.merge(counts, on=["cik", "report_date"], how="left")
    summary_path = out_dir / "provenance_ledger_summary.csv"
    summary.to_csv(summary_path, index=False)
    return ledger_path, summary_path
```

(The `groupby.apply` here runs over cik-quarter groups -- hundreds, not rows -- within the sanctioned small-summary pandas envelope.)

`main()` at module bottom:

```python
def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        description="Deterministic provenance re-verification -> ledger.")
    ap.add_argument("--ciks", nargs="*", default=None)
    ap.add_argument("--cohort", action="store_true")
    ap.add_argument("--cheap-only", action="store_true")
    ap.add_argument("--out", default=None,
                    help="output dir (default: data/output)")
    args = ap.parse_args(argv)
    from pipeline import config
    ciks = args.ciks
    if args.cohort:
        from pipeline.cohort_guard import load_cohort_ciks
        ciks = sorted(load_cohort_ciks())
    holdings = config.UNIFIED_HOLDINGS_PARQUET_FILE
    logger.info("Cheap tier over %s (ciks=%s)", holdings.name,
                len(ciks) if ciks else "all")
    cheap = cheap_tier(holdings_path=holdings, ciks=ciks)
    tiers = cheap.assign(instance_raw=None, full_status="not_checked") \
        if args.cheap_only else full_tier(cheap)
    import datetime as _dt
    mtime = _dt.datetime.fromtimestamp(holdings.stat().st_mtime).isoformat()
    out_dir = Path(args.out) if args.out else config.OUTPUT_DIR
    lp, sp = build_ledger(tiers, out_dir=out_dir, holdings_mtime=mtime)
    logger.info("Ledger: %s; summary: %s", lp, sp)
    return 0


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)-8s %(message)s")
    sys.exit(main())
```

Config additions after `UNIFIED_HOLDINGS_PARQUET_FILE` (config.py:152):

```python
PROVENANCE_LEDGER_FILE = OUTPUT_DIR / "provenance_ledger.csv"
PROVENANCE_LEDGER_SUMMARY_FILE = OUTPUT_DIR / "provenance_ledger_summary.csv"
```

- [ ] **Step 4: Run tests, then the cohort run (operator phase B)**

```powershell
python -m pytest tests/test_provenance_reverify.py -q
python -m pipeline.provenance_reverify --cohort --cheap-only   # smoke first
python -m pipeline.provenance_reverify --cohort                # full run
```

Record in the changelog: rows/fields checked, reason-code distribution, cohort `verified_fv_share` per quarter, runtime. Expect a nonzero `filing_mismatch`/`anchor_stale` residue -- that residue IS the product (it seeds the future routing lanes); do not tune anything to shrink it (AGENTS.md: failed validation is a valid outcome).

- [ ] **Step 5: Docs + commit**

- `docs/reference/schemas.md`: ledger + summary schemas, the reason-code enum with the 8.2 semantics (esp. `anchor_stale` vs `filing_mismatch`), and the verified-FV accounting rule.
- `docs/agent_changelog.md`: dated entry with run stats.
- **Section-5 guard (record verbatim in the changelog entry):** the ledger does NOT change any public export basis. The homepage headline stays the all-rows cohort sum until the owner explicitly decides option (A) keep-headline+publish-verified-share (recommended by the scoping doc) or (B) verified-rows-everywhere. Any export change is a separate, owner-approved task.

```bash
git add pipeline/provenance_reverify.py pipeline/config.py tests/test_provenance_reverify.py docs/reference/schemas.md docs/agent_changelog.md
git commit -m "provenance step 4: ledger artifact + CLI

- provenance_ledger.csv keyed (row_id, field) with two-tier evidence and
  deterministic reason codes; summary with verified-FV accounting
- cohort run recorded; public export basis explicitly unchanged
  (scoping doc section 5 decision remains with the owner)"
```

---

## Self-Review Notes

- **Spec coverage:** scoping 2.4 #3 `src_facts` -> Tasks 1, 4 (sparse variant, deviation recorded); #6 `corrected_fields` -> Task 5; #1 enum extension -> Task 4 (five new enums; `cost/shares` keep step-1 semantics, recorded); section 6 step 2 re-extraction + risks 1/2 gates -> Tasks 3, 6; risk 3 silent-drop -> Task 4 single-commit rule; risk 4 -> Task 5; risk 5 merged contexts -> Task 2 + `merged_context_excluded` routing; risk 6 (bridge sha) -> full tier does not verify bridge-overlaid fields (they are `src_field_overrides` territory, step-1) -- the cheap tier's `text_pathway`/enum short-circuits keep them out of anchor checks; risk 7 test schema -> Task 4 Step 4; section 6 step 4 two-tier re-verifier -> Tasks 7-9; 8.1 field-level ledger keying + build id -> Task 9; 8.2 deterministic triage incl. anchor-staleness-vs-regression -> Task 8. Section 5 -> Task 9 guard note (decision stays with owner). Out of scope, recorded: 8.3+ lanes/agents, amendments (8.7), N-PORT (7), identifier-text grammar verification (Class B full check -- `text_pathway` bucket measures its size for prioritization).
- **Deliberate deviations from the scoping doc:** sparse `src_facts` instead of always-populated (size; full tier replays `_match_concept` for canonical concepts); flat `;`-strings for `corrected_fields`/`src_filled_fields` (consistency with step-1); population is re-extraction-scoped (cohort) rather than gated in the extractor (simpler, and a future universe-wide re-parse gets provenance for free); `*_source` not flipped on correction (corrected_fields is the single overlay marker).
- **Type consistency:** `src_facts` JSON grammar identical across Task 1 (writer), Task 4 (passthrough), Tasks 7-8 (readers); event codes `decimals_rescale:10^<k>` / `cik_scale_fix:x1000` written in Task 1 and parsed by `_extractor_multiplier` in Task 8 and the SQL in Task 7; `cheap_status`/`full_status`/`reason_code` enums match between Tasks 7, 8, 9 and the triage table; `mark_corrected_fields(before_tracked, after)` signature consistent between helper definition and both wiring sites.
- **Known risks encoded:** GATE 1 stops on any extractor drift (values-identical or abort); `pass_trivial` monetary rows still get a full-tier read (the cheap tier alone cannot verify untransformed values); rate-field `fail` on missing declared raw makes incomplete extraction declarations loud instead of silently trivial-passing.
