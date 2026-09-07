# Gate Mechanics Fixes Implementation Plan (Plan 1 of 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the four process holes that let Q1 2026 over-inclusion through the gates: unpadded CIKs from added rows, a duplicate-add guard keyed on exact identifier text, gates that silently evaluate a stale corrected frame, and no count of unfinished investigations in the acceptance artifact.

**Architecture:** All changes are in the agentic correction layer (`pipeline/agent_rule.py`, `pipeline/agent_promoted.py`, `scripts/agent_investigate/run_investigation.py`) plus one new small module `pipeline/investigation_state.py` shared by the driver and `pipeline/quarter_acceptance.py`. No data-semantics change: the conservation numerator, anchors, and thresholds are untouched here (that is Plan 2, `2026-09-07-published-basis-gate.md`). Every task is TDD against synthetic frames; no rebuild is required.

**Tech Stack:** Python 3.11, pandas (small frames only), DuckDB for predicates, pytest.

**Spec:** `docs/superpowers/specs/2026-09-07-published-basis-conservation-gate-design.md` (sections 4a, 4b, 4e; section 3's `investigations.n_stale` metric)

## Global Constraints

- ASCII only in log messages, docstrings, and comments (Windows cp1252).
- No `.apply()` / `.iterrows()` on large frames; these functions run on one CIK's rows (thousands, not hundreds of thousands) so pandas is acceptable, as the existing code already does.
- No network calls. No writes to `data/output/` or `frontend/public/data/` from tests (conftest guard enforces this).
- Commit messages: short subject + 2-4 bullet body, ending with the two attribution lines:
  `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>` and
  `Claude-Session: https://claude.ai/code/session_012y9HXDTAq1SHqB5GKmjmc1`.
- Run only the named test files per task. Do not run the full suite inside this plan; Plan 2's rollout task owns the full-suite run.
- Do not edit `AGENTS.md`. Append to `docs/agent_changelog.md` at the end of the plan (Task 5).

---

### Task 1: CIK padding for added rows + hard validation check

**Files:**
- Modify: `pipeline/agent_rule.py` (`_apply_add`, around line 345)
- Modify: `pipeline/agent_promoted.py` (`apply_promoted_rules`, after the `added` identity fill, around line 540)
- Modify: `pipeline/validate_holdings.py` (new function `check_cik_format`, add near `check_position_count_stability`; call it in `validate_holdings()` after the coverage block)
- Test: `tests/test_agent_rule.py`, `tests/test_agent_promoted.py`, `tests/test_validate_holdings.py`

**Interfaces:**
- Produces: `validate_holdings.check_cik_format(df: pd.DataFrame) -> pd.DataFrame` with columns `["cik", "n_rows", "fair_value_sum", "issue"]`; `issue` is always `"cik_not_10_digits"`. Empty frame means clean.
- Produces: `_apply_add` pads any `cik` supplied inside a position dict to 10 digits.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_agent_rule.py` (after `test_row_add_empty_identifier_never_treated_as_duplicate`):

```python
def test_row_add_pads_position_cik_to_10_digits():
    """A row_add position that carries its own 7-digit cik must land 10-digit padded
    (Q1 2026: one TCW Star cash row landed as '1715933' and split the fund across two keys)."""
    df = pd.DataFrame([{**_h("0000000001", "2025q", 400.0), "bdc_investment_identifier": "A"}])
    pos = {"cik": "1715933", "report_date": "2025q", "fair_value": 55.0,
           "bdc_investment_identifier": "Money Market Fund",
           "bdc_dimensions_raw": "investmentidentifieraxis=mmf",
           "source_row_id": "staging:mmf"}
    corrected, audits = apply_rules(df, [_addrule(positions=[pos])])
    assert audits[0]["rows_added"] == 1
    assert corrected.iloc[-1]["cik"] == "0001715933"
```

Append to `tests/test_agent_promoted.py` (after `test_apply_promoted_rules_row_add_fills_identity`):

```python
def test_apply_promoted_rules_row_add_cik_is_padded_even_when_supplied():
    df = _holdings_frame()
    rule = _valid_rule(
        rule_type="row_add", action="add", predicate=None,
        positions=[{"cik": "123", "report_date": "2025-06-30", "issuer_name": "Recovered Co",
                    "fair_value": 999.0, "bdc_dimensions_raw": "axis=Recovered",
                    "source_row_id": "accession 0001 table 2 row 9"}])
    del rule["predicate_sql"]
    out, _ = ap.apply_promoted_rules(df, {"0000000123": [rule]})
    assert set(out["cik"].unique()) == {"0000000123", "0000000456"}
```

Append to `tests/test_validate_holdings.py` (module level, at the end of the file):

```python
def test_check_cik_format_flags_unpadded_rows():
    from pipeline.validate_holdings import check_cik_format
    df = pd.DataFrame([
        {"cik": "0001715933", "report_date": "2026-03-31", "fair_value": "100"},
        {"cik": "1715933", "report_date": "2026-03-31", "fair_value": "5330000"},
        {"cik": "0001715933", "report_date": "2025-12-31", "fair_value": "200"},
    ])
    res = check_cik_format(df)
    assert list(res.columns) == ["cik", "n_rows", "fair_value_sum", "issue"]
    assert len(res) == 1
    assert res.iloc[0]["cik"] == "1715933"
    assert res.iloc[0]["n_rows"] == 1
    assert float(res.iloc[0]["fair_value_sum"]) == 5330000.0
    assert res.iloc[0]["issue"] == "cik_not_10_digits"


def test_check_cik_format_clean_frame_is_empty():
    from pipeline.validate_holdings import check_cik_format
    df = pd.DataFrame([{"cik": "0000000123", "report_date": "2026-03-31", "fair_value": "1"}])
    assert check_cik_format(df).empty
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:
```
pytest tests/test_agent_rule.py::test_row_add_pads_position_cik_to_10_digits tests/test_agent_promoted.py::test_apply_promoted_rules_row_add_cik_is_padded_even_when_supplied tests/test_validate_holdings.py::test_check_cik_format_flags_unpadded_rows tests/test_validate_holdings.py::test_check_cik_format_clean_frame_is_empty -v
```
Expected: 3 FAIL (assertion on cik value / ImportError for `check_cik_format`), the fourth fails with ImportError too.

- [ ] **Step 3: Implement**

In `pipeline/agent_rule.py`, inside `_apply_add`, replace the loop body that copies keys:

```python
        row = {c: None for c in cols}
        for k, v in p.items():
            if k in cols:                       # source_row_id is metadata, not a holdings column
                row[k] = v
            elif k != "source_row_id":          # extra source columns the holdings schema lacks
                ignored.add(k)
        # CIK padding (Q1 2026: a 7-digit cik on an added row split TCW Star across two keys
        # and hid the row from the conservation join). Digits only, zero-padded to 10.
        if "cik" in cols and row.get("cik") not in (None, ""):
            row["cik"] = re.sub(r"\D", "", str(row["cik"])).zfill(10)
```

(`re` is already imported at the top of `agent_rule.py`.)

In `pipeline/agent_promoted.py`, inside `apply_promoted_rules`, directly after the `if added.any(): ...` block that fills `cik`/`source`/`entity_name`, add:

```python
        # Structural padding: every row in this CIK's slice carries the 10-digit key, whatever
        # a position dict supplied (agent_rule pads too; this is the production backstop).
        corrected["cik"] = (corrected["cik"].astype(str).str.replace(r"\D", "", regex=True)
                            .str.zfill(10))
```

In `pipeline/validate_holdings.py`, add before `def validate_holdings(`:

```python
def check_cik_format(df: pd.DataFrame) -> pd.DataFrame:
    """Hard check: every unified row's cik must be exactly 10 digits. A single unpadded
    row splits its fund across two keys and drops it out of every cik-joined check
    (conservation, GAV, acceptance). Returns one row per offending cik value; empty = clean."""
    cols = ["cik", "n_rows", "fair_value_sum", "issue"]
    if df is None or len(df) == 0 or "cik" not in df.columns:
        return pd.DataFrame(columns=cols)
    cik = df["cik"].astype(str)
    bad = ~cik.str.fullmatch(r"\d{10}")
    if not bad.any():
        return pd.DataFrame(columns=cols)
    sub = df.loc[bad].copy()
    sub["_fv"] = pd.to_numeric(sub.get("fair_value"), errors="coerce").fillna(0.0)
    out = (sub.groupby(cik[bad], sort=True)["_fv"]
           .agg(n_rows="size", fair_value_sum="sum").reset_index())
    out = out.rename(columns={out.columns[0]: "cik"})
    out["issue"] = "cik_not_10_digits"
    return out[cols]
```

In `validate_holdings()`, after the coverage block (before `# Save CSVs`), add:

```python
    # 5b. CIK format (hard check; see check_cik_format)
    cik_bad = check_cik_format(unified_df)
    reports["cik_format"] = cik_bad
    if len(cik_bad) > 0:
        logger.error("  CIK FORMAT: %d non-10-digit cik value(s) on %d rows, FV %.0f -- "
                     "these rows are invisible to every cik-joined check",
                     len(cik_bad), int(cik_bad["n_rows"].sum()),
                     float(cik_bad["fair_value_sum"].sum()))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run the same command as Step 2. Expected: 4 PASS. Then run the three files fully:
```
pytest tests/test_agent_rule.py tests/test_agent_promoted.py -q
pytest tests/test_validate_holdings.py -q -k "cik_format or gav or subsidiary"
```
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add pipeline/agent_rule.py pipeline/agent_promoted.py pipeline/validate_holdings.py tests/test_agent_rule.py tests/test_agent_promoted.py tests/test_validate_holdings.py
git commit -m "fix: pad cik on added rows + hard cik-format check

- _apply_add and apply_promoted_rules zero-pad cik to 10 digits (Q1: one 7-digit TCW Star row split the fund)
- validate_holdings.check_cik_format reports any non-10-digit cik as a hard error
- 4 tests

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_012y9HXDTAq1SHqB5GKmjmc1"
```

---

### Task 2: Widen the duplicate-add guard to (report_date, fair_value, name key)

**Files:**
- Modify: `pipeline/agent_rule.py` (`_existing_position_keys` -> replace with `PositionKeyIndex`; `_apply_add`; the `no_aggregate_addition` block in `gate_rules`)
- Test: `tests/test_agent_rule.py`

**Interfaces:**
- Produces: `class PositionKeyIndex` with `__init__(self, work: pd.DataFrame)`, `contains(self, report_date, identifier, fair_value, issuer_name) -> bool`, and module-level `name_key(text) -> frozenset[str]`.
- Keeps: `_existing_position_keys(work)` as a thin wrapper returning the exact-key set (other callers, and `gate_rules`, keep working).
- Consumed by: Plan 2 does not change this; `agent_promoted.apply_promoted_rules` already reads `rows_skipped_duplicate` from the audit and classifies the rule `superseded`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_agent_rule.py`:

```python
from pipeline.agent_rule import name_key, PositionKeyIndex


def test_name_key_strips_legal_form_and_share_class_tokens():
    assert name_key("Goldman Sachs Financial Square Government Fund - Institutional Shares") == \
        name_key("Goldman Sachs Financial Square Government Fund")
    assert name_key("Acme Holdings, LLC") == frozenset({"acme", "holdings"})
    assert name_key("") == frozenset()


def test_row_add_skips_same_fv_and_similar_name_when_identifier_text_differs():
    """Q1 2026 (Silver Capital, TCW DL): the promoted row_add text differed from the filing
    text the cash-axis fix later extracted natively, so the exact-identifier guard missed it
    and the money-market position was counted twice."""
    native = {**_h("1", "2026-03-31", 157_700_000.0,
                   dims="cashandcashequivalentsaxis=GoldmanSachsFinancialSquareGovernmentFundMember"),
              "bdc_investment_identifier": "Goldman Sachs Financial Square Government Fund - Institutional Shares",
              "issuer_name": "Goldman Sachs Financial Square Government Fund - Institutional Shares",
              "asset_category": "CASH"}
    df = pd.DataFrame([native, {**_h("1", "2026-03-31", 600.0),
                                "bdc_investment_identifier": "Real Co - TL",
                                "issuer_name": "Real Co", "asset_category": "LOAN"}])
    pos = {"report_date": "2026-03-31", "fair_value": 157_700_000.0,
           "bdc_investment_identifier": "GS Financial Square Government Fund",
           "issuer_name": "Goldman Sachs Financial Square Government Fund",
           "bdc_dimensions_raw": "investmentidentifieraxis=x", "source_row_id": "staging:mmf"}
    corrected, audits = apply_rules(df, [_addrule(positions=[pos])])
    assert audits[0]["rows_added"] == 0
    assert audits[0]["rows_skipped_duplicate"] == 1
    assert len(corrected) == 2


def test_row_add_skips_same_fv_against_cash_row_even_with_unrelated_name():
    native = {**_h("1", "2026-03-31", 5_330_000.0), "bdc_investment_identifier": "Cash Sweep",
              "issuer_name": "Cash Sweep", "asset_category": "CASH"}
    df = pd.DataFrame([native])
    pos = {"report_date": "2026-03-31", "fair_value": 5_330_000.0,
           "bdc_investment_identifier": "First American Govt Obligations",
           "issuer_name": "First American Govt Obligations",
           "bdc_dimensions_raw": "investmentidentifieraxis=x", "source_row_id": "staging:fa"}
    _, audits = apply_rules(df, [_addrule(positions=[pos])])
    assert audits[0]["rows_added"] == 0 and audits[0]["rows_skipped_duplicate"] == 1


def test_row_add_appends_same_fv_unrelated_name_non_cash():
    """False-positive guard: two different borrowers can legitimately carry identical FV
    (E10: 28% of cohort rows sit in static-ambiguous blocks). Non-cash + dissimilar name = append."""
    native = {**_h("1", "2026-03-31", 4_960_000.0), "bdc_investment_identifier": "KAMC Holdings TL",
              "issuer_name": "KAMC Holdings, Inc.", "asset_category": "LOAN"}
    df = pd.DataFrame([native])
    pos = {"report_date": "2026-03-31", "fair_value": 4_960_000.0,
           "bdc_investment_identifier": "Heads Up Technologies TL",
           "issuer_name": "Heads Up Technologies, Inc.",
           "bdc_dimensions_raw": "investmentidentifieraxis=x", "source_row_id": "staging:hut"}
    corrected, audits = apply_rules(df, [_addrule(positions=[pos])])
    assert audits[0]["rows_added"] == 1 and audits[0]["rows_skipped_duplicate"] == 0
    assert len(corrected) == 2


def test_position_key_index_requires_exact_fv_match():
    df = pd.DataFrame([{**_h("1", "q", 100.0), "bdc_investment_identifier": "Acme TL",
                        "issuer_name": "Acme Corp", "asset_category": "LOAN"}])
    idx = PositionKeyIndex(df)
    assert idx.contains("q", "acme tl", 100.0, "Acme Corp")
    assert not idx.contains("q", "acme tl", 100.5, "Acme Corp")
    assert not idx.contains("other-q", "acme tl", 100.0, "Acme Corp")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_agent_rule.py -k "name_key or position_key_index or row_add_skips_same or row_add_appends_same" -v`
Expected: ImportError on `name_key` / `PositionKeyIndex` (collection error for the file). That is the expected failure.

- [ ] **Step 3: Implement**

In `pipeline/agent_rule.py`, replace `_existing_position_keys` with:

```python
# Tokens that carry no borrower identity: legal forms, share classes, generic fund words.
_NAME_KEY_STOP = frozenset({
    "llc", "l.l.c", "inc", "inc.", "corp", "corp.", "corporation", "co", "co.", "company",
    "lp", "l.p", "l.p.", "llp", "ltd", "ltd.", "limited", "plc", "sa", "s.a", "gmbh", "sarl",
    "fund", "class", "shares", "share", "institutional", "portfolio", "series", "the", "and", "of",
})
_NAME_KEY_SPLIT = re.compile(r"[^a-z0-9]+")


def name_key(text) -> frozenset[str]:
    """Order-free identity tokens of an issuer name: lower-cased, punctuation split, legal-form
    and share-class tokens removed. Used ONLY for the duplicate-add guard (same FV + similar
    name), never for matching or borrower resolution."""
    toks = _NAME_KEY_SPLIT.split(str(text or "").lower())
    return frozenset(t for t in toks if t and t not in _NAME_KEY_STOP)


def _jaccard(a: frozenset, b: frozenset) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


class PositionKeyIndex:
    """Rows already in the frame, keyed two ways for the duplicate-add guard:
    exact (report_date, identifier, fair_value) and fuzzy (report_date, fair_value) ->
    [(name_key, is_cash)]. Empty identifiers never key on the exact path (fail-open); the
    fuzzy path keys on fair_value alone so an identifier-less native row is still visible."""
    DUP_JACCARD = 0.5

    def __init__(self, work: pd.DataFrame):
        self.exact: set[tuple[str, str, float]] = set()
        self.by_fv: dict[tuple[str, float], list[tuple[frozenset, bool]]] = {}
        if work is None or len(work) == 0 or "report_date" not in work.columns:
            return
        ident = (work["bdc_investment_identifier"].fillna("").astype(str).str.strip().str.lower()
                 if "bdc_investment_identifier" in work.columns
                 else pd.Series("", index=work.index))
        name = (work["issuer_name"].fillna("").astype(str) if "issuer_name" in work.columns
                else pd.Series("", index=work.index))
        cat = (work["asset_category"].fillna("").astype(str).str.upper()
               if "asset_category" in work.columns else pd.Series("", index=work.index))
        rd = work["report_date"].astype(str)
        fv = pd.to_numeric(work.get("fair_value"), errors="coerce")
        for i, n, c, r_, f in zip(ident, name, cat, rd, fv):
            if pd.isna(f):
                continue
            f = float(f)
            if i:
                self.exact.add((r_, i, f))
            self.by_fv.setdefault((r_, f), []).append((name_key(n or i), c == "CASH"))

    def contains(self, report_date, identifier, fair_value, issuer_name) -> bool:
        try:
            f = float(fair_value)
        except (TypeError, ValueError):
            return False
        r_ = str(report_date)
        ident = str(identifier or "").strip().lower()
        if ident and (r_, ident, f) in self.exact:
            return True
        cand = name_key(issuer_name or identifier)
        for key, is_cash in self.by_fv.get((r_, f), []):
            if is_cash:
                return True
            if _jaccard(cand, key) >= self.DUP_JACCARD:
                return True
        return False


def _existing_position_keys(work) -> set[tuple[str, str, float]]:
    """Exact (report_date, normalized identifier, fair_value) keys (kept for gate_rules'
    is-this-row-new test; the add guard uses PositionKeyIndex)."""
    return PositionKeyIndex(work).exact
```

In `_apply_add`, replace the guard:

```python
    existing = PositionKeyIndex(work)
    new_rows, pq, ignored, skipped = [], {}, set(), []
    for p in positions:
        if existing.contains(p.get("report_date"), p.get("bdc_investment_identifier"),
                             p.get("fair_value"), p.get("issuer_name")):
            skipped.append(p.get("bdc_investment_identifier") or p.get("issuer_name"))
            continue
```

Update the `_apply_add` docstring's "Duplicate guard" paragraph to:

```python
    Duplicate guard (gate blind spot 1, 1905824 FHLB veto 2026-09-02; widened 2026-09-07 after
    the Q1 cash double-count): a position is SKIPPED, not appended, when the frame already holds
    a row with the same (report_date, identifier, fair_value) OR the same (report_date,
    fair_value) and either a similar name_key (Jaccard >= 0.5) or a CASH counterpart. The
    identifier-text-only key missed 56 rows / $1.32B in Q1 2026 because rule text differs
    from filing text.
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_agent_rule.py -q`
Expected: all pass, including the two pre-existing dup tests (`test_row_add_skips_duplicate_of_existing_row`, `test_row_add_empty_identifier_never_treated_as_duplicate`). If `test_row_add_empty_identifier_never_treated_as_duplicate` fails: its frame row has issuer_name `"x"` and FV 400 with an empty identifier, and the position is "Recovered Fund" at FV 400 -- `name_key("x")` vs `name_key("Recovered Fund")` has Jaccard 0 and the row is not CASH, so it must still append. Fix the implementation, not the test.

Also run: `pytest tests/test_agent_promoted.py -q` (the superseded-not-drift test relies on `rows_skipped_duplicate`).

- [ ] **Step 5: Commit**

```bash
git add pipeline/agent_rule.py tests/test_agent_rule.py
git commit -m "fix: widen row_add duplicate guard to fair value + name key

- PositionKeyIndex: exact (date, identifier, fv) key plus fuzzy (date, fv) with name_key Jaccard >= 0.5 or a CASH counterpart
- catches the Q1 2026 class (56 rows / \$1.32B) where promoted add text differed from filing text
- false-positive test: same fv, unrelated non-cash name still appends

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_012y9HXDTAq1SHqB5GKmjmc1"
```

---

### Task 3: Rules fingerprint, STALE gate verdict, gate record file, promote refusals

**Files:**
- Create: `pipeline/investigation_state.py`
- Modify: `scripts/agent_investigate/run_investigation.py` (`apply`, `gate`, `promote`, `main`)
- Test: `tests/test_investigation_state.py` (new), `tests/test_investigation_orchestration.py`

**Interfaces:**
- Produces (`pipeline/investigation_state.py`):
  - `rules_fingerprint(rules_dir: Path) -> str` -- sha256 hex over sorted `*.json` filenames and bytes; `""` for a missing/empty directory.
  - `stale_investigations(base_dir: Path, target_quarter: str, ciks: set[str] | None = None) -> list[dict]` -- one dict per stale CIK: `{"cik": <10-digit>, "target_quarter", "reason", "rules_fingerprint", "apply_fingerprint", "gate_fingerprint", "gate_verdict"}`. A CIK is stale when its `rules/` holds at least one `.json` and (a) `apply_audit.json` is missing or its `rules_fingerprint` differs, or (b) `gate.<target_quarter>.json` is missing or its `rules_fingerprint` differs.
- Produces (driver): `apply()` writes `rules_fingerprint` into `apply_audit.json`; `gate()` returns `verdict: "STALE"` when the fingerprint differs and writes `<BASE>/<cik>/gate.<quarter>.json` on every call; `promote()` refuses STALE and refuses `PASS_NOOP` when `rules/` is non-empty; new CLI mode `audit-stale --target-quarter Q`.
- Consumed by: Task 4 (`quarter_acceptance` calls `stale_investigations`).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_investigation_state.py`:

```python
"""pipeline.investigation_state: rules fingerprint + stale-investigation audit."""
import json

from pipeline.investigation_state import rules_fingerprint, stale_investigations


def _rule(path, rule_id="r1"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"rule_id": rule_id, "rule_type": "row_exclusion"}), encoding="utf-8")


def test_fingerprint_empty_and_deterministic(tmp_path):
    assert rules_fingerprint(tmp_path / "missing") == ""
    d = tmp_path / "rules"
    d.mkdir()
    assert rules_fingerprint(d) == ""
    _rule(d / "b.json", "b")
    _rule(d / "a.json", "a")
    f1 = rules_fingerprint(d)
    assert len(f1) == 64
    assert rules_fingerprint(d) == f1
    _rule(d / "a.json", "a-changed")
    assert rules_fingerprint(d) != f1


def _cik_dir(base, cik, *, rules, apply_fp=None, gate_fp=None, gate_verdict="PASS", q="2026-03-31"):
    d = base / cik
    for i in range(rules):
        _rule(d / "rules" / f"r{i}.json", f"r{i}")
    if apply_fp is not None:
        d.mkdir(parents=True, exist_ok=True)
        (d / "apply_audit.json").write_text(json.dumps({"rules_fingerprint": apply_fp}), encoding="utf-8")
    if gate_fp is not None:
        d.mkdir(parents=True, exist_ok=True)
        (d / f"gate.{q}.json").write_text(
            json.dumps({"verdict": gate_verdict, "rules_fingerprint": gate_fp}), encoding="utf-8")
    return d


def test_stale_when_rules_newer_than_apply_or_gate(tmp_path):
    q = "2026-03-31"
    d = _cik_dir(tmp_path, "1838126", rules=2)
    fp = rules_fingerprint(d / "rules")
    # HPS shape: gate FAIL recorded on an earlier rule set, rules rewritten after
    (d / "apply_audit.json").write_text(json.dumps({"rules_fingerprint": "old"}), encoding="utf-8")
    (d / f"gate.{q}.json").write_text(json.dumps({"verdict": "FAIL", "rules_fingerprint": "old"}),
                                      encoding="utf-8")
    out = stale_investigations(tmp_path, q)
    assert [o["cik"] for o in out] == ["0001838126"]
    assert out[0]["rules_fingerprint"] == fp and out[0]["apply_fingerprint"] == "old"
    assert out[0]["gate_verdict"] == "FAIL"
    assert "apply" in out[0]["reason"] and "gate" in out[0]["reason"]


def test_not_stale_when_fingerprints_match(tmp_path):
    q = "2026-03-31"
    d = _cik_dir(tmp_path, "1674760", rules=1)
    fp = rules_fingerprint(d / "rules")
    _cik_dir(tmp_path, "1674760", rules=0, apply_fp=fp, gate_fp=fp)
    assert stale_investigations(tmp_path, q) == []


def test_no_rules_is_never_stale_and_other_quarter_gate_does_not_count(tmp_path):
    _cik_dir(tmp_path, "2083477", rules=0, apply_fp="x")            # clean zero-rule CIK
    d = _cik_dir(tmp_path, "1715933", rules=1)
    fp = rules_fingerprint(d / "rules")
    _cik_dir(tmp_path, "1715933", rules=0, apply_fp=fp, gate_fp=fp, q="2025-12-31")
    out = stale_investigations(tmp_path, "2026-03-31")
    assert [o["cik"] for o in out] == ["0001715933"]
    assert "gate" in out[0]["reason"] and "apply" not in out[0]["reason"]


def test_cik_filter_and_skip_dirs(tmp_path):
    d = _cik_dir(tmp_path, "111", rules=1)
    _cik_dir(tmp_path, "batch", rules=1)          # non-CIK dirs are skipped
    out = stale_investigations(tmp_path, "2026-03-31", ciks={"0000000111"})
    assert [o["cik"] for o in out] == ["0000000111"]
    assert stale_investigations(tmp_path, "2026-03-31", ciks={"0000000222"}) == []
```

Append to `tests/test_investigation_orchestration.py`:

```python
def _wire(tmp_path, monkeypatch, cik="888", q="2026-03-31"):
    """BASE + holdings + a validated MEDIUM anchor so apply/gate run on a synthetic frame."""
    monkeypatch.setattr(ri, "BASE", tmp_path)
    df = pd.DataFrame([
        {"cik": cik, "report_date": q, "fair_value": 1000.0, "bdc_dimensions_raw": "x=y",
         "issuer_name": "Keep Co", "bdc_investment_identifier": "Keep Co"},
        {"cik": cik, "report_date": q, "fair_value": 200.0, "bdc_dimensions_raw": "x=y",
         "issuer_name": "Dup Co", "bdc_investment_identifier": "Dup Co"},
    ])
    monkeypatch.setattr(ri, "_load_holdings", lambda c: df)
    monkeypatch.setattr(ri, "_candidates_with_outlier_filter",
                        lambda c: ({q: {"companyfacts_fv": 1000.0}}, {}))
    rules = tmp_path / cik / "rules"
    rules.mkdir(parents=True)
    rules.joinpath("drop_dup.json").write_text(json.dumps({
        "cik": cik, "rule_id": "drop_dup", "rule_type": "row_exclusion", "action": "exclude",
        "predicate_sql": "issuer_name = 'Dup Co'", "scope": {"quarters": ["all"]},
        "evidence": [{"source": "filing", "quote": "x"}], "rationale": "dup", "confidence": 0.9}),
        encoding="utf-8")
    return rules


def test_apply_records_rules_fingerprint(tmp_path, monkeypatch):
    from pipeline.investigation_state import rules_fingerprint
    rules = _wire(tmp_path, monkeypatch)
    res = ri.apply("888")
    audit = json.loads((tmp_path / "888" / "apply_audit.json").read_text(encoding="utf-8"))
    assert res["rules_fingerprint"] == audit["rules_fingerprint"] == rules_fingerprint(rules)


def test_gate_is_stale_when_rules_change_after_apply(tmp_path, monkeypatch):
    rules = _wire(tmp_path, monkeypatch)
    ri.apply("888")
    rules.joinpath("second.json").write_text(json.dumps({
        "cik": "888", "rule_id": "second", "rule_type": "row_exclusion", "action": "exclude",
        "predicate_sql": "issuer_name = 'Nobody'", "scope": {"quarters": ["all"]},
        "evidence": [{"source": "filing", "quote": "x"}], "rationale": "late", "confidence": 0.5}),
        encoding="utf-8")
    g = ri.gate("888", "2026-03-31")
    assert g["verdict"] == "STALE"
    assert g["rules_fingerprint"] != g["apply_fingerprint"]
    assert "newest_rule_file" in g and g["newest_rule_file"] == "second.json"
    rec = json.loads((tmp_path / "888" / "gate.2026-03-31.json").read_text(encoding="utf-8"))
    assert rec["verdict"] == "STALE"
    # re-apply clears it
    ri.apply("888")
    g2 = ri.gate("888", "2026-03-31")
    assert g2["verdict"] != "STALE"
    assert "rules_fingerprint" in g2


def test_promote_refuses_stale_gate(tmp_path, monkeypatch):
    monkeypatch.setattr(ri, "gate", lambda cik, q: {"verdict": "STALE", "reasons": ["rules changed"]})
    res = promote("888", "2026-03-31", overrides_dir=tmp_path / "ov")
    assert res["status"] == "refused" and res["gate"] == "STALE"


def test_promote_refuses_pass_noop_when_rules_exist(tmp_path, monkeypatch):
    """Silver Capital shape: a PASS_NOOP verdict ('no rules authored') must never promote a
    rules directory that has since been populated."""
    monkeypatch.setattr(ri, "BASE", tmp_path)
    (tmp_path / "888" / "rules").mkdir(parents=True)
    (tmp_path / "888" / "rules" / "late.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(ri, "gate", lambda cik, q: {"verdict": "PASS_NOOP", "reasons": ["noop"]})
    res = promote("888", "2026-03-31", overrides_dir=tmp_path / "ov")
    assert res["status"] == "refused_noop_with_rules"
    assert not (tmp_path / "ov").exists()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_investigation_state.py tests/test_investigation_orchestration.py -q`
Expected: `test_investigation_state.py` fails at import (module missing); the four new orchestration tests fail (`rules_fingerprint` key missing / verdict not STALE / status mismatch). Existing orchestration tests still pass.

- [ ] **Step 3: Implement `pipeline/investigation_state.py`**

```python
"""Investigation state: rules fingerprint + stale-investigation audit.

Q1 2026 (2026-09-07 forensics): HPS's gate verdict was written at 09:00 on a half-finished rule
set; the worker's final rules landed at 11:12/11:18; nothing re-gated; the rules were never
promoted. The gate reads the corrected frame written by the LAST apply, so any rule written
after that apply is invisible to it. This module makes that state explicit: apply and gate
record the fingerprint of the rules they saw, and a CIK whose rules directory no longer
matches is STALE -- refused by promote and counted by the acceptance contract.

ASCII-only. Pure filesystem reads; no pipeline imports.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

_CIK_DIR_RE = re.compile(r"^\d{1,10}$")


def rules_fingerprint(rules_dir: Path) -> str:
    """sha256 over (sorted filename, bytes) of every *.json in rules_dir; '' if none."""
    rules_dir = Path(rules_dir)
    files = sorted(rules_dir.glob("*.json")) if rules_dir.exists() else []
    if not files:
        return ""
    h = hashlib.sha256()
    for p in files:
        h.update(p.name.encode("utf-8"))
        h.update(b"\0")
        h.update(p.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


def newest_rule_file(rules_dir: Path) -> str:
    rules_dir = Path(rules_dir)
    files = sorted(rules_dir.glob("*.json"), key=lambda p: p.stat().st_mtime) if rules_dir.exists() else []
    return files[-1].name if files else ""


def _read_json(path: Path) -> dict:
    try:
        obj = json.loads(path.read_text(encoding="utf-8-sig"))
        return obj if isinstance(obj, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def stale_investigations(base_dir: Path, target_quarter: str,
                         ciks: set[str] | None = None) -> list[dict]:
    """CIKs under base_dir whose staged rules do not match the fingerprint recorded by their
    last apply (apply_audit.json) or their last gate for target_quarter (gate.<q>.json).
    ciks: optional 10-digit filter. CIK dirs are the numeric ones (batch/, routing/ skipped)."""
    base_dir = Path(base_dir)
    out: list[dict] = []
    if not base_dir.exists():
        return out
    for child in sorted(base_dir.iterdir()):
        if not child.is_dir() or not _CIK_DIR_RE.match(child.name):
            continue
        cik10 = child.name.zfill(10)
        if ciks is not None and cik10 not in ciks:
            continue
        fp = rules_fingerprint(child / "rules")
        if not fp:
            continue                                   # no staged rules -> nothing to be stale
        apply_fp = str(_read_json(child / "apply_audit.json").get("rules_fingerprint") or "")
        gate_rec = _read_json(child / f"gate.{target_quarter}.json")
        gate_fp = str(gate_rec.get("rules_fingerprint") or "")
        reasons = []
        if apply_fp != fp:
            reasons.append("rules changed after last apply" if apply_fp else "never applied")
        if gate_fp != fp:
            reasons.append("rules changed after last gate" if gate_fp else "never gated for quarter")
        if reasons:
            out.append({"cik": cik10, "target_quarter": str(target_quarter),
                        "reason": "; ".join(reasons), "rules_fingerprint": fp,
                        "apply_fingerprint": apply_fp, "gate_fingerprint": gate_fp,
                        "gate_verdict": str(gate_rec.get("verdict") or "")})
    return out
```

- [ ] **Step 4: Wire the driver**

In `scripts/agent_investigate/run_investigation.py`:

Add the import after the `pipeline.anchor_validation` import:
```python
from pipeline.investigation_state import newest_rule_file, rules_fingerprint, stale_investigations
```

In `apply()`, add `"rules_fingerprint": rules_fingerprint(out / "rules"),` to the `res` dict (before `"corrected_holdings"`).

Replace `gate()` with:

```python
def _write_gate_record(cik: str, target_quarter: str, res: dict) -> dict:
    out = BASE / _norm(cik)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"gate.{target_quarter}.json").write_text(json.dumps(res, indent=2, default=str),
                                                     encoding="utf-8")
    return res


def gate(cik: str, target_quarter: str) -> dict:
    out = BASE / _norm(cik)
    corrected_path = out / f"corrected_holdings.{_norm(cik)}.csv"
    if not corrected_path.exists():
        return {"cik": _norm(cik), "status": "no_corrected_holdings (run apply first)"}
    # Stale-apply guard (2026-09-07): the gate evaluates the corrected frame the LAST apply
    # wrote. If the rules directory changed since, the verdict would describe rules nobody
    # can promote -- refuse with STALE and tell the operator to re-run apply.
    fp = rules_fingerprint(out / "rules")
    apply_fp = ""
    audit_path = out / "apply_audit.json"
    if audit_path.exists():
        try:
            apply_fp = str(json.loads(audit_path.read_text(encoding="utf-8-sig"))
                           .get("rules_fingerprint") or "")
        except (OSError, json.JSONDecodeError):
            apply_fp = ""
    if fp and fp != apply_fp:
        return _write_gate_record(cik, target_quarter, {
            "cik": _norm(cik), "target_quarter": target_quarter, "verdict": "STALE",
            "rules_fingerprint": fp, "apply_fingerprint": apply_fp,
            "newest_rule_file": newest_rule_file(out / "rules"),
            "checks": {}, "reasons": [
                "rules directory changed after the last apply; corrected holdings are stale "
                "-- re-run apply, then gate"]})
    base = _load_holdings(cik)
    corrected = pd.read_csv(corrected_path, low_memory=False)
    candidates, flags = _candidates_with_outlier_filter(cik)
    tq = str(target_quarter)
    av = classify_anchors(candidates.get(tq, {}))
    out_flag = flags.get(tq)
    anchor_reason = (out_flag.reason if (out_flag and out_flag.flagged) else av.reason)
    if not load_rules(out / "rules"):
        vs = value_sum_by_quarter(base, cik=cik).get(tq, 0.0)
        residual_pct = (round((vs - av.consensus) / av.consensus * 100.0, 3)
                        if av.consensus else None)
        noop = _noop_gate_verdict(residual_pct, av.tier)
        if noop:
            return _write_gate_record(cik, target_quarter, {
                "cik": _norm(cik), "target_quarter": target_quarter,
                "verdict": noop["verdict"], "anchor_tier": av.tier,
                "anchor_reason": anchor_reason, "rules_fingerprint": fp,
                "checks": {"noop_reconciled": True}, "reasons": noop["reasons"]})
    g = gate_rules(base, corrected, cik=cik, target_quarter=target_quarter,
                   anchor_candidates=candidates,
                   threshold_pct=config.FV_CONSERVATION_BAND_PCT)
    return _write_gate_record(cik, target_quarter, {
        "cik": _norm(cik), "target_quarter": target_quarter, "verdict": g.verdict,
        "anchor_tier": av.tier, "anchor_reason": anchor_reason, "rules_fingerprint": fp,
        "checks": g.checks, "reasons": g.reasons})
```

In `promote()`, replace the first two `if` blocks with:

```python
    g = gate(cik, target_quarter)
    src = BASE / _norm(cik) / "rules"
    if g.get("verdict") == "PASS_NOOP":
        # A PASS_NOOP means "no rules authored". If rules now exist the verdict describes a
        # state that no longer holds (Silver Capital 2026-09-02: PASS_NOOP at 08:44, a row_add
        # promoted at 10:49). Refuse; the operator must apply + gate the rules that exist.
        if rules_fingerprint(src):
            return {"cik": _norm(cik), "status": "refused_noop_with_rules", "gate": "PASS_NOOP",
                    "reasons": ["PASS_NOOP verdict but rules directory is non-empty; "
                                "run apply + gate on the staged rules"]}
        return {"cik": _norm(cik), "status": "no_rules_to_promote", "gate": "PASS_NOOP",
                "reasons": g.get("reasons")}
    if g.get("verdict") != "PASS":
        return {"cik": _norm(cik), "status": "refused", "gate": g.get("verdict"),
                "reasons": g.get("reasons")}
```

(and delete the later duplicate `src = BASE / _norm(cik) / "rules"` line).

Add to the promotion record: in the final `return {... "status": "promoted", ...}` include `"rules_fingerprint": g.get("rules_fingerprint", "")`.

In `main()`: add `"audit-stale"` handling. In the subparser loop change the tuple to `("prep", "apply", "gate", "status", "discover", "promote", "audit-stale")`, and treat it like `gate` for `--target-quarter` (add `"audit-stale"` to the `if m in ("prep", "gate", "status", "promote")` tuple) but NOT to the `--cik` branch: change `else: p.add_argument("--cik", required=True)` to `elif m != "audit-stale": p.add_argument("--cik", required=True)`. Then add the dispatch:

```python
    elif args.mode == "audit-stale":
        rows = stale_investigations(BASE, args.target_quarter)
        print(json.dumps({"target_quarter": args.target_quarter, "n_stale": len(rows),
                          "stale": rows}, indent=2))
        return 0 if not rows else 1
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/test_investigation_state.py tests/test_investigation_orchestration.py -q`
Expected: all pass. If `test_gate_is_stale_when_rules_change_after_apply` fails on the second `gate()` with an anchor error: the fixture anchors are `{q: {"companyfacts_fv": 1000.0}}` which classify MEDIUM; the residual after dropping Dup Co is 0.0, so the verdict is PASS. Check that `_wire` was applied (`monkeypatch.setattr(ri, "BASE", tmp_path)` before `ri.apply`).

- [ ] **Step 6: Commit**

```bash
git add pipeline/investigation_state.py scripts/agent_investigate/run_investigation.py tests/test_investigation_state.py tests/test_investigation_orchestration.py
git commit -m "feat: rules fingerprint, STALE gate verdict, promote refusals

- apply records rules_fingerprint; gate returns STALE when the rules dir changed since (HPS Q1 shape) and writes gate.<q>.json
- promote refuses STALE and refuses PASS_NOOP on a non-empty rules dir (Silver Capital Q1 shape)
- pipeline/investigation_state.stale_investigations + audit-stale CLI mode

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_012y9HXDTAq1SHqB5GKmjmc1"
```

---

### Task 4: `investigations.n_stale` metric in the acceptance artifact

**Files:**
- Modify: `pipeline/quarter_acceptance.py` (`compute_acceptance` signature + metrics dict)
- Test: `tests/test_quarter_acceptance.py`

**Interfaces:**
- Consumes: `pipeline.investigation_state.stale_investigations(base_dir, target_quarter, ciks)`.
- Produces: `compute_acceptance(..., investigate_dir: Path | None = None)`; `metrics["investigations"] = {"n_stale": int, "stale_ciks": [cik10...]}`. Default `investigate_dir = config.OUTPUT_DIR / "agent_investigate"`. The threshold check on this metric is added in Plan 2 (thresholds v3); here it is informational.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_quarter_acceptance.py`:

```python
def test_stale_investigations_counted_for_cohort_only(tmp_path):
    inv = tmp_path / "agent_investigate"
    for cik, in_cohort in (("1", True), ("9", False)):
        d = inv / cik / "rules"
        d.mkdir(parents=True)
        (d / "r.json").write_text("{}", encoding="utf-8")       # rules, never applied -> stale
    kw = _setup(tmp_path, ledger_rows=[_cons_row("0000000001", "pass"),
                                       _cons_row("0000000002", "pass"),
                                       _cons_row("0000000003", "pass")])
    res = qa.compute_acceptance(target_quarter=Q, investigate_dir=inv, **kw)
    assert res["metrics"]["investigations"] == {"n_stale": 1, "stale_ciks": ["0000000001"]}


def test_missing_investigate_dir_is_zero_stale(tmp_path):
    kw = _setup(tmp_path, ledger_rows=[_cons_row("0000000001", "pass"),
                                       _cons_row("0000000002", "pass"),
                                       _cons_row("0000000003", "pass")])
    res = qa.compute_acceptance(target_quarter=Q, investigate_dir=tmp_path / "nope", **kw)
    assert res["metrics"]["investigations"] == {"n_stale": 0, "stale_ciks": []}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_quarter_acceptance.py -k stale -v`
Expected: TypeError (unexpected keyword `investigate_dir`).

- [ ] **Step 3: Implement**

In `pipeline/quarter_acceptance.py`:

Add after `AUDIT_FILE = ...`:
```python
INVESTIGATE_DIR = config.OUTPUT_DIR / "agent_investigate"
```

Add `investigate_dir: Path | None = None,` to the `compute_acceptance` signature (after `thresholds_path`).

After the promoted-rule health block (before `# --- per-fund tiers ---`), add:

```python
    # --- unfinished investigations (staged rules newer than their apply/gate) ---
    from pipeline.investigation_state import stale_investigations
    inv_dir = investigate_dir or INVESTIGATE_DIR
    stale = stale_investigations(inv_dir, target_quarter, ciks=set(cohort)) if inv_dir.exists() else []
    if not inv_dir.exists():
        logger.warning("agent_investigate dir missing, stale metric empty: %s", inv_dir)
```

In the `metrics` dict add:
```python
        "investigations": {
            "n_stale": len(stale),
            "stale_ciks": [s["cik"] for s in stale],
        },
```

In `cli()`, add `parser.add_argument("--investigate-dir", type=Path, default=None)` and pass `investigate_dir=args.investigate_dir` to `compute_acceptance`. Add `"investigate": str(inv_dir)` to the `inputs` dict of the result.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_quarter_acceptance.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add pipeline/quarter_acceptance.py tests/test_quarter_acceptance.py
git commit -m "feat: acceptance reports unfinished investigations (n_stale)

- investigations.n_stale + stale_ciks from investigation_state.stale_investigations, cohort-scoped
- informational until thresholds v3 (Plan 2) adds the gate

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_012y9HXDTAq1SHqB5GKmjmc1"
```

---

### Task 5: Live check on the Q1 staged state + changelog

**Files:**
- Modify: `docs/agent_changelog.md` (append)

- [ ] **Step 1: Run the stale audit against the real Q1 investigation store (read-only)**

```
python -m scripts.agent_investigate.run_investigation audit-stale --target-quarter 2026-03-31
```
Expected: exit code 1 with at least `0001838126` (HPS) listed, reason containing "never gated for quarter" or "rules changed after last gate" (its batch gate predates the rules and no `gate.2026-03-31.json` exists yet). Record the full `n_stale` and the CIK list.

- [ ] **Step 2: Run the CIK-format check against the current production frame (read-only)**

```
python -c "import pandas as pd; from pipeline.validate_holdings import check_cik_format; from pipeline import config; df = pd.read_parquet(config.UNIFIED_HOLDINGS_PARQUET_FILE, columns=['cik','fair_value']); print(check_cik_format(df).to_string())"
```
Expected: one row, cik `1715933`, FV 5,330,000 (the TCW Star added cash row). If the parquet is absent use the CSV with `dtype=str`. This is a short one-liner, permitted by the no-ad-hoc-Python rule for a read-only check with a bounded frame.

- [ ] **Step 3: Append the changelog entry**

Append to `docs/agent_changelog.md`:

```markdown
## 2026-09-07 - Gate mechanics fixes (Plan 1 of the published-basis gate spec)

- Spec: docs/superpowers/specs/2026-09-07-published-basis-conservation-gate-design.md;
  plan: docs/superpowers/plans/2026-09-07-gate-mechanics-fixes.md.
- `pipeline/agent_rule.py`: row_add pads cik to 10 digits; duplicate-add guard widened to
  `PositionKeyIndex` (exact identifier key OR same report_date+fair_value with name_key
  Jaccard >= 0.5 or a CASH counterpart). `pipeline/agent_promoted.py`: structural cik padding
  on the corrected slice. `pipeline/validate_holdings.py`: `check_cik_format` hard check
  (report key `cik_format`).
- New `pipeline/investigation_state.py` (rules_fingerprint, stale_investigations).
  `run_investigation`: apply records the fingerprint; gate returns STALE when rules changed
  since apply and writes `<cik>/gate.<quarter>.json`; promote refuses STALE and refuses
  PASS_NOOP with a non-empty rules dir; new `audit-stale` mode.
- `pipeline/quarter_acceptance.py`: `investigations.n_stale` / `stale_ciks` (informational
  until thresholds v3).
- Live read-only checks: audit-stale 2026-03-31 -> n_stale=<N> (<cik list>); check_cik_format
  on production -> 1715933 / $5.33M (the known TCW Star row). No rebuild, no data change.
- Tests: <counts> in test_agent_rule, test_agent_promoted, test_validate_holdings (-k),
  test_investigation_state, test_investigation_orchestration, test_quarter_acceptance.
  Full suite NOT run (Plan 2 rollout owns it).
```
Replace `<N>`, `<cik list>`, `<counts>` with the measured values from Steps 1-2 and the test runs.

- [ ] **Step 4: Commit**

```bash
git add docs/agent_changelog.md
git commit -m "docs: changelog for gate mechanics fixes (Plan 1)

- records audit-stale result on the Q1 store and the live cik-format finding
- test counts per file; full suite deferred to Plan 2 rollout

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_012y9HXDTAq1SHqB5GKmjmc1"
```
