# Cash-Equivalents-Axis Extraction Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ingest schedule-of-investments rows that filers tag on `us-gaap:CashAndCashEquivalentsAxis` with filer-extension members (MMF sweeps, T-bill positions printed after "Total Portfolio Investments"), which the BDC XBRL parser currently drops.

**Architecture:** `_parse_xbrl_contexts()` in `pipeline/bdc_filings.py` only marks a context `is_investment=True` when a dimension local-name contains `investmentidentifier`/`investmentcompany`. Cash/short-term rows are dimensioned on `CashAndCashEquivalentsAxis` with a filer-extension member naming the specific instrument (e.g. `ck0001950976:DreyfusTreasuryObligationsCashManagementMoneyMarketFundMember`), so they are never enumerated. Fix: accept such contexts, deriving the investment identifier from the de-camelized member local-name. Guard against subtotal leakage by accepting only filer-extension members (never `us-gaap:` generic members like `MoneyMarketFundsMember`, which denote category aggregates). Couple with per-CIK conservation-scope carve-outs (existing `pipeline.conservation_scope` mechanism, 1905824 precedent) for filers whose printed Total Investments anchor includes the cash rows, because ingested rows classify CASH and CASH is excluded from the conservation sum by default.

**Tech Stack:** lxml XBRL parsing (pipeline/bdc_filings.py), pytest inline-XML fixtures (tests/test_bdc_filings.py), conservation scope JSON overrides (data/overrides/conservation_scope/).

**Spec:** docs/investigations/agent_fleet_behavior.md (2026-09-02 escalation deep-dive, root cause #1) + B2 escalation `data/output/agent_b2/corrections/0001950976/missing_position_add.json` (cites context `C_680a5380-d8f5-445b-bad3-203a63d51265` in accession 000119312526214004, FV 36,885,000, exact closure 1,588,604,000 + 36,885,000 = 1,625,489,000).

## Global Constraints

- No SEC downloads. All verification uses `data/raw/filings/bdc_xbrl/` cache and `rebuild_cached_bdc_holdings` (cache-only by design).
- ASCII-only log messages.
- No pandas `.apply()`/`.iterrows()` on >10K-row data (parser loops over XML are fine; they are per-filing).
- Tests must not write to `data/output/` (conftest guard enforces).
- Never edit validation code, tolerances, or thresholds. The conservation-scope carve-out is a data override with evidence, not a threshold change.
- Do not touch `scripts/agent_b/run_review.py` or `tests/test_agent_b_preflight.py` (another session's uncommitted work).
- Commit messages: short subject + 2-4 bullet body.

## Verified ground truth (do not re-derive)

- CIK 1950976, accession `000119312526214004` (Q1-2026 10-Q) contains context `C_680a5380-d8f5-445b-bad3-203a63d51265`: instant 2026-03-31, `us-gaap:CashAndCashEquivalentsAxis` = `ck0001950976:DreyfusTreasuryObligationsCashManagementMoneyMarketFundMember`, `us-gaap:InvestmentTypeAxis` = `us-gaap:ShortTermInvestmentsMember`, with `InvestmentOwnedAtFairValue` = 36885000 and `InvestmentOwnedAtCost` = 36885000. The same filing has a 2025-12-31 comparative Dreyfus context. Conservation counts only `period = report_date` rows, so the accession above (report_date 2026-03-31) is the one that heals the quarter.
- CIK 1899996 Q1 filing (`000119312526119504.xml`) tags two State Street MMF members on the same axis pattern (`ck0001899996:StateStreetInstitutionalTreasuryMember`, `ck0001899996:StateStreetInstitutionalTreasuryPlusMoneyMarketFundMember`).
- Conservation sum excludes `asset_category='CASH'` rows unless the CIK has a carve-out JSON in `data/overrides/conservation_scope/` (see `1905824.json` for schema; loaded by `build_cash_filter()` in `scripts/shadow_conservation_engine.py:212`).
- `python scripts/rebuild_outputs.py --bdc-holdings --ciks <list>` re-parses ONLY those CIKs' cached filings and merges over `bdc_holdings.csv`, preserving other CIKs byte-identically (`pipeline/bdc_filings.py:1344`).
- Expected gate effect (verify against artifacts, never assume): 1950976 residual -2.269% -> ~0, 1899996 -1.617% -> ~0, 1905824 -4.420% -> ~0 (its carve-out is already live; its residual $8.6M matches the non-FHLB short-term gap 47,530K - 38,771K = 8,759K if those rows are on the cash axis). Reconcile 61/68 -> up to 64/68 = 94.1% (bar 90).

---

### Task 1: `_humanize_member_local_name` helper

**Files:**
- Modify: `pipeline/bdc_filings.py` (add helper near `_local_name`, ~line 505)
- Test: `tests/test_bdc_filings.py`

**Interfaces:**
- Produces: `_humanize_member_local_name(name: str) -> str` — strips a trailing `Member`, splits camelCase/digit boundaries into spaces, collapses whitespace. Task 2 calls it.

- [ ] **Step 1: Write the failing tests**

```python
class TestHumanizeMemberLocalName:
    def test_mmf_member_decamelized(self):
        assert _humanize_member_local_name(
            "DreyfusTreasuryObligationsCashManagementMoneyMarketFundMember"
        ) == "Dreyfus Treasury Obligations Cash Management Money Market Fund"

    def test_acronym_run_preserved(self):
        assert _humanize_member_local_name(
            "StateStreetInstitutionalUSGovernmentMoneyMarketFundMember"
        ) == "State Street Institutional US Government Money Market Fund"

    def test_digits_split(self):
        assert _humanize_member_local_name("FirstAmerican2Member") == "First American 2"

    def test_no_member_suffix(self):
        assert _humanize_member_local_name("TreasuryBill") == "Treasury Bill"

    def test_empty(self):
        assert _humanize_member_local_name("") == ""
```

- [ ] **Step 2: Run to verify they fail** — `python -m pytest tests/test_bdc_filings.py::TestHumanizeMemberLocalName -v` -> NameError/ImportError.

- [ ] **Step 3: Implement**

```python
_CAMEL_BOUNDARY_RE = re.compile(
    r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])|(?<=[A-Za-z])(?=[0-9])|(?<=[0-9])(?=[A-Za-z])"
)


def _humanize_member_local_name(name: str) -> str:
    """Turn an XBRL member local-name into a readable identifier.

    ``DreyfusTreasuryObligationsCashManagementMoneyMarketFundMember`` ->
    ``Dreyfus Treasury Obligations Cash Management Money Market Fund``.
    """
    text = str(name or "").strip()
    if text.endswith("Member"):
        text = text[: -len("Member")]
    return _CAMEL_BOUNDARY_RE.sub(" ", text).strip()
```

- [ ] **Step 4: Run to verify pass** — same pytest node, expect 5 PASS.
- [ ] **Step 5: Commit** — `feat: member local-name humanizer for cash-axis identifiers`

### Task 2: accept cash-equivalents-axis contexts as investment contexts

**Files:**
- Modify: `pipeline/bdc_filings.py:148` (`_CASH_EQUIV_DIMS` constant), `pipeline/bdc_filings.py:507-598` (`_parse_xbrl_contexts`)
- Test: `tests/test_bdc_filings.py`

**Interfaces:**
- Consumes: `_humanize_member_local_name` from Task 1.
- Produces: contexts dict entries with `is_investment=True` and `investment_identifier=<humanized member>` for qualifying cash-axis contexts. Downstream (`_extract_investment_facts`, staging, classification) unchanged.

- [ ] **Step 1: Write the failing tests** (follow the existing inline-XML fixture style around `tests/test_bdc_filings.py:102-126`)

```python
_CASH_AXIS_XML = """<?xml version="1.0"?>
<xbrl xmlns="http://www.xbrl.org/2003/instance"
      xmlns:xbrldi="http://xbrl.org/2006/xbrldi"
      xmlns:us-gaap="http://fasb.org/us-gaap/2025">
  <context id="c_dreyfus">
    <entity>
      <identifier scheme="http://www.sec.gov/CIK">0001950976</identifier>
      <segment>
        <xbrldi:explicitMember dimension="us-gaap:CashAndCashEquivalentsAxis">ck0001950976:DreyfusTreasuryObligationsCashManagementMoneyMarketFundMember</xbrldi:explicitMember>
        <xbrldi:explicitMember dimension="us-gaap:InvestmentTypeAxis">us-gaap:ShortTermInvestmentsMember</xbrldi:explicitMember>
      </segment>
    </entity>
    <period><instant>2026-03-31</instant></period>
  </context>
  <context id="c_generic_member">
    <entity>
      <identifier scheme="http://www.sec.gov/CIK">0001950976</identifier>
      <segment>
        <xbrldi:explicitMember dimension="us-gaap:CashAndCashEquivalentsAxis">us-gaap:MoneyMarketFundsMember</xbrldi:explicitMember>
      </segment>
    </entity>
    <period><instant>2026-03-31</instant></period>
  </context>
  <context id="c_undimensioned">
    <entity><identifier scheme="http://www.sec.gov/CIK">0001950976</identifier></entity>
    <period><instant>2026-03-31</instant></period>
  </context>
  <us-gaap:InvestmentOwnedAtFairValue contextRef="c_dreyfus" unitRef="usd" decimals="-3">36885000</us-gaap:InvestmentOwnedAtFairValue>
  <us-gaap:InvestmentOwnedAtCost contextRef="c_dreyfus" unitRef="usd" decimals="-3">36885000</us-gaap:InvestmentOwnedAtCost>
  <us-gaap:InvestmentOwnedAtFairValue contextRef="c_generic_member" unitRef="usd" decimals="-3">99999000</us-gaap:InvestmentOwnedAtFairValue>
  <us-gaap:InvestmentOwnedAtFairValue contextRef="c_undimensioned" unitRef="usd" decimals="-3">1625489000</us-gaap:InvestmentOwnedAtFairValue>
</xbrl>"""


class TestCashAxisContexts:
    def _parse(self):
        tree = etree.ElementTree(etree.fromstring(_CASH_AXIS_XML.encode()))
        return tree, _parse_xbrl_contexts(tree)

    def test_filer_extension_cash_member_is_investment(self):
        _, ctxs = self._parse()
        ctx = ctxs["c_dreyfus"]
        assert ctx["is_investment"] is True
        assert ctx["investment_identifier"] == (
            "Dreyfus Treasury Obligations Cash Management Money Market Fund"
        )
        assert ctx["investment_type"] == "ShortTermInvestmentsMember"

    def test_generic_usgaap_cash_member_not_investment(self):
        # us-gaap: members on the cash axis are category aggregates, never positions
        _, ctxs = self._parse()
        assert ctxs["c_generic_member"]["is_investment"] is False

    def test_undimensioned_total_context_not_investment(self):
        _, ctxs = self._parse()
        assert ctxs["c_undimensioned"]["is_investment"] is False

    def test_facts_extracted_for_cash_axis_row(self):
        tree, ctxs = self._parse()
        facts = _extract_investment_facts(tree, ctxs)
        by_ctx = {f["_context_id"]: f for f in facts}
        assert "c_dreyfus" in by_ctx
        assert by_ctx["c_dreyfus"]["fair_value"] == 36885000
        assert "c_generic_member" not in by_ctx
        assert "c_undimensioned" not in by_ctx

    def test_identifier_axis_context_still_wins_over_cash_axis(self):
        # A context carrying BOTH an investment-identifier dim and a cash-axis dim
        # must keep the identifier-axis value.
        xml = _CASH_AXIS_XML.replace(
            '<xbrldi:explicitMember dimension="us-gaap:InvestmentTypeAxis">us-gaap:ShortTermInvestmentsMember</xbrldi:explicitMember>',
            '<xbrldi:typedMember dimension="test:InvestmentIdentifierAxis"><test:x>Real Co | First Lien</test:x></xbrldi:typedMember>',
        )
        tree = etree.ElementTree(etree.fromstring(xml.encode()))
        ctxs = _parse_xbrl_contexts(tree)
        assert ctxs["c_dreyfus"]["investment_identifier"] == "Real Co | First Lien"
```

Note: the typed-member replacement needs an `xmlns:test` declaration — add `xmlns:test="http://test"` to the root element of `_CASH_AXIS_XML` so the replacement parses.

- [ ] **Step 2: Run to verify they fail** — `python -m pytest tests/test_bdc_filings.py::TestCashAxisContexts -v`. Expected: `test_filer_extension_cash_member_is_investment` and `test_facts_extracted_for_cash_axis_row` FAIL (is_investment False / c_dreyfus missing); the two negative guards may already pass (that is fine — they are regression locks).

- [ ] **Step 3: Implement.** In `pipeline/bdc_filings.py`:

Add next to `_INVESTMENT_ID_DIMS` (line 148):

```python
# Cash-equivalents axis: filers tag MMF/T-bill schedule rows here (printed
# after "Total Portfolio Investments"). Only filer-extension members name a
# specific instrument; us-gaap: members are category aggregates.
_CASH_EQUIV_DIMS = ("cashandcashequivalent",)
```

In `_parse_xbrl_contexts`, initialise `cash_equiv_id = ""` beside `company_id`. In the `typedMember` branch add after the `_COMPANY_ID_DIMS` elif:

```python
                elif any(kw in dim_ln for kw in _CASH_EQUIV_DIMS):
                    cash_equiv_id = val
```

In the `explicitMember` branch, after the `_COMPANY_ID_DIMS` check (line 582-583), add:

```python
                if (
                    any(kw in dim_ln for kw in _CASH_EQUIV_DIMS)
                    and member_val
                    and not member_val.lower().startswith("us-gaap:")
                ):
                    cash_equiv_id = _humanize_member_local_name(member_ln)
```

After the `company_id` fallback (line 585-586), add:

```python
        # Cash-equivalents-axis rescue: filer-extension members on the cash
        # axis name a specific schedule position (Dreyfus/State Street MMF
        # class, 2026-09-02 escalation deep-dive). Generic us-gaap members and
        # fully undimensioned contexts (the printed totals) never reach here.
        if not is_investment and cash_equiv_id and not _is_non_position_identifier(cash_equiv_id):
            investment_id = cash_equiv_id
            is_investment = True
```

- [ ] **Step 4: Run to verify pass** — `python -m pytest tests/test_bdc_filings.py::TestCashAxisContexts tests/test_bdc_filings.py::TestHumanizeMemberLocalName -v` -> all PASS.
- [ ] **Step 5: Run the full parser/staging test files** — `python -m pytest tests/test_bdc_filings.py tests/test_unified_holdings.py -q`. Expected: all pass (no behavior change for identifier-axis contexts). `test_unified_holdings.py` is slow (~30-40s/test); run it once here, not per-iteration.
- [ ] **Step 6: Commit** — `feat: ingest cash-equivalents-axis schedule rows (extraction gap, 6-CIK class)`

### Task 3: classification sanity check for humanized MMF identifiers

**Files:**
- Test: `tests/test_unified_holdings.py` (or the classification test file if a closer fit exists — search for `_MONEY_MARKET_KEYWORDS` usages in tests)

**Interfaces:**
- Consumes: existing `_sql_classify_bdc_asset` / staging classification path.
- Produces: regression lock that the two real humanized identifiers classify as CASH (so they stay out of conservation sums for non-carve-out CIKs and out of the DIRECT_LENDING index).

- [ ] **Step 1: Write the test.** Find the existing test pattern for identifier classification (search `tests/` for `money market` or `_CASH_KEYWORDS`). Add cases asserting that `"Dreyfus Treasury Obligations Cash Management Money Market Fund"` and `"State Street Institutional Treasury Plus Money Market Fund"` classify with `asset_category = 'CASH'` through the same path production uses (whatever helper that test file already exercises — do not invent a new harness).
- [ ] **Step 2: Run it.** If it FAILS because the keywords do not match, STOP and report — do not widen `_CASH_KEYWORDS`/`_MONEY_MARKET_KEYWORDS` without checking the false-positive tests around them; that is a judgment step for the operator session.
- [ ] **Step 3: Commit** — `test: CASH classification lock for humanized cash-axis identifiers`

### Task 4: conservation-scope carve-outs for 1950976 and 1899996

**Files:**
- Create: `data/overrides/conservation_scope/1950976.json`
- Create: `data/overrides/conservation_scope/1899996.json`
- Test: existing `tests/test_conservation_scope.py` covers the loader; add one loader round-trip case per new file ONLY if that file's pattern makes it natural — otherwise no new tests (these are data files).

**Interfaces:**
- Consumes: `pipeline.conservation_scope.included_categories_for` (reads `include_asset_categories`).
- Produces: CASH rows count toward the conservation sum for these two CIKs (whose printed Total Investments anchor includes the short-term rows — proven by exact arithmetic below).

- [ ] **Step 1: Verify the arithmetic from the cached filings** (read-only; use `Select-String` on the cached XML or the escalation JSONs — no ad-hoc Python):
  - 1950976: extracted sum 1,588,604,000 + Dreyfus 36,885,000 = 1,625,489,000 = filing "Total Investments at Fair Value" (escalation `0001950976/missing_position_add.json`, confidence 0.98).
  - 1899996: current residual is -1.617% of 1,635.657M ~= -26.45M; find the State Street member facts for period 2026-03-31 in `data/raw/filings/bdc_xbrl/1899996/000119312526119504.xml` and confirm their FV sum is within the 0.5% band of the residual. Record the exact values found in the JSON evidence.
- [ ] **Step 2: Write the two JSONs** following the 1905824 schema exactly (`cik`, `include_asset_categories: ["CASH"]`, `scope_quarters: ["all"]`, `evidence` [filing quote + query quote with the exact numbers from Step 1], `rationale`, `confidence`).
- [ ] **Step 3: Run** `python -m pytest tests/test_conservation_scope.py -q` -> PASS.
- [ ] **Step 4: Commit the code-side files only if the 1905824 precedent is git-tracked** (`git ls-files data/overrides/conservation_scope/`). If tracked: commit both JSONs (`fix: conservation-scope carve-outs for 1950976/1899996 cash-axis rows`). If not tracked: leave uncommitted for the owner at sign-off, and say so in the report.

### Task 5: targeted re-extraction + verification (operator runs these; battery follows)

**Files:** none created — pipeline runs.

- [ ] **Step 1: Check the other four class CIKs' filings** (read-only `Select-String`) for the same cash-axis pattern in their 2026-03-31 accessions: 1905824, 1715933, 1916608, 1920453, 1930087, 2008748. Record which have filer-extension cash-axis members with 2026-03-31 facts (these will heal; the others will not — say so honestly in the report).
- [ ] **Step 2: Cohort-scoped re-extraction** (cache-only, merges over `bdc_holdings.csv`):
  `python scripts/rebuild_outputs.py --bdc-holdings --ciks <cohort list from pipeline.cohort_guard.load_cohort_ciks>` — use the full wrapper cohort so the semantic diff shows the fix's true cohort-wide effect, not a 3-CIK sliver.
- [ ] **Step 3: Spot-check** `data/output/bdc_holdings.csv` gained the Dreyfus/State Street rows for period 2026-03-31 (rg for "Dreyfus Treasury" — expect the 2026-03-31 row from accession 000119312526214004 plus comparatives).
- [ ] **Step 4: Battery** — `python scripts/run_quarter_pass.py --pass-id q1p3_20260831 --quarter 2026-03-31 --from rebuild_post --force`.
- [ ] **Step 5: Verify against artifacts** — `acceptance_post.json` (reconcile >= 90 expected), `quarter_acceptance_funds.csv` per-CIK residuals for 1950976/1899996/1905824, `agent_fix_application_audit.csv` (0 drift/not_ok on the 176 live rules), `python -m scripts.reattest_quarters check` (read the flip LIST — a 2025-12-31 regression is stop-and-report), `python scripts/diff_outputs.py --semantic` (review the cohort-wide FV delta from new CASH rows; the public headline FV will rise — flag the magnitude for the owner at sign-off).
