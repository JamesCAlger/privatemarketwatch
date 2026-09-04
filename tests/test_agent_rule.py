"""Tests for agent-authored auditable rules (pipeline/agent_rule): validate, apply, gate.
Synthetic frames, no real data, no LLM."""
import pandas as pd
import pytest

from pipeline.agent_rule import (
    validate_rule, apply_rules, value_sum_by_quarter, build_snapshots, gate_rules,
    dedupe_escalations,
)

_CLO = "bdc_dimensions_raw LIKE '%legalentityaxis=FooCloMember%'"


def _rule(**kw):
    base = {"cik": "1377936", "rule_id": "r1", "rule_type": "row_exclusion", "action": "exclude",
            "predicate_sql": _CLO, "scope": {"quarters": ["all"]},
            "evidence": [{"source": "filing", "quote": "Consolidated Schedule ... CLO"}],
            "rationale": "levered consolidated CLO", "confidence": 0.9}
    base.update(kw)
    return base


def _h(cik, q, fv, dims="investmentidentifieraxis=DL"):
    return {"cik": cik, "report_date": q, "fair_value": fv, "bdc_dimensions_raw": dims,
            "issuer_name": "x"}


# -- validate ---------------------------------------------------------------------------

def test_valid_rule_passes():
    assert validate_rule(_rule()) == []


@pytest.mark.parametrize("mut,frag", [
    ({"cik": "abc"}, "cik must be"),
    ({"rule_type": "magic"}, "rule_type must be"),
    ({"action": "rewrite"}, "action for row_exclusion must be"),
    ({"predicate_sql": "SELECT * FROM h"}, "pure boolean row predicate"),
    ({"predicate_sql": "fv > 0; DROP TABLE h"}, "pure boolean row predicate"),
    ({"scope": {"quarters": []}}, "scope.quarters"),
    ({"evidence": []}, "evidence must be"),
    ({"rationale": ""}, "rationale is empty"),
    ({"confidence": 2}, "confidence must be"),
])
def test_invalid_rule_caught(mut, frag):
    errs = validate_rule(_rule(**mut))
    assert any(frag in e for e in errs), errs


# -- apply (per-quarter audit, scope) ---------------------------------------------------

def test_apply_excludes_matching_rows_with_per_quarter_audit():
    df = pd.DataFrame([
        _h("1377936", "2026-02-28", 1000.0),
        _h("1377936", "2026-02-28", 376.0, dims="investmentidentifieraxis=X|legalentityaxis=FooCloMember"),
        _h("1377936", "2025-11-30", 200.0, dims="investmentidentifieraxis=X|legalentityaxis=FooCloMember"),
    ])
    corrected, audits = apply_rules(df, [_rule()])
    assert len(corrected) == 1                       # both CLO rows dropped, DL kept
    a = audits[0]
    assert a["status"] == "ok" and a["rows_excluded"] == 2
    assert a["per_quarter"]["2026-02-28"] == {"rows": 1, "fv": 376.0}
    assert a["per_quarter"]["2025-11-30"] == {"rows": 1, "fv": 200.0}


def test_scope_limits_to_named_quarters():
    df = pd.DataFrame([
        _h("1", "2026-02-28", 376.0, dims="x|legalentityaxis=FooCloMember"),
        _h("1", "2025-11-30", 200.0, dims="x|legalentityaxis=FooCloMember"),
    ])
    corrected, audits = apply_rules(df, [_rule(scope={"quarters": ["2026-02-28"]})])
    assert audits[0]["rows_excluded"] == 1 and set(corrected["report_date"]) == {"2025-11-30"}


def test_invalid_predicate_recorded_not_applied():
    df = pd.DataFrame([_h("1", "2026-02-28", 100.0)])
    corrected, audits = apply_rules(df, [_rule(predicate_sql="DELETE FROM h")])
    assert audits[0]["status"] == "invalid" and len(corrected) == 1   # nothing dropped


# -- value_rescale (fix a scale error WITHOUT deleting the position) ---------------------

def _rescale(**kw):
    base = {"cik": "1", "rule_id": "rs", "rule_type": "value_rescale", "action": "rescale",
            "predicate_sql": "bdc_dimensions_raw = 'x'", "field": "fair_value", "factor": 0.001,
            "scope": {"quarters": ["all"]}, "evidence": [{"source": "query", "quote": "1000x"}],
            "rationale": "fair_value extracted 1000x too large", "confidence": 0.9}
    base.update(kw)
    return base


def test_value_rescale_validates_field_and_factor():
    assert validate_rule(_rescale()) == []
    assert any("field must be one of" in e for e in validate_rule(_rescale(field="cik")))
    assert any("factor must be" in e for e in validate_rule(_rescale(factor=0)))


def test_value_rescale_fixes_scale_keeps_position():
    df = pd.DataFrame([_h("1", "2025q", 100000000.0, dims="x"),   # 1000x too large
                       _h("1", "2025q", 500.0, dims="y")])
    corrected, audits = apply_rules(df, [_rescale()])
    assert audits[0]["status"] == "ok" and audits[0]["rows_rescaled"] == 1
    assert len(corrected) == 2                                    # position NOT deleted
    assert value_sum_by_quarter(corrected)["2025q"] == 100500.0   # 1e8*0.001 + 500


# -- dedup (keep one per key) ------------------------------------------------------------

def _dd(**kw):
    base = {"cik": "1", "rule_id": "dd", "rule_type": "dedup", "action": "dedup",
            "match_fields": ["issuer_name", "fair_value"], "keep": "first",
            "scope": {"quarters": ["all"]}, "evidence": [{"source": "query", "quote": "dup"}],
            "rationale": "same position twice", "confidence": 0.9}
    base.update(kw)
    return base


def test_dedup_validates_keys_and_keep():
    assert validate_rule(_dd()) == []
    assert any("match_fields not allowed" in e for e in validate_rule(_dd(match_fields=["cik"])))
    assert any("keep must be" in e for e in validate_rule(_dd(keep="middle")))


def test_dedup_keeps_one_per_key():
    df = pd.DataFrame([_h("1", "q", 100.0, dims="A"), _h("1", "q", 100.0, dims="B"),  # dup (x,100)
                       _h("1", "q", 50.0, dims="C")])
    corrected, audits = apply_rules(df, [_dd()])
    assert audits[0]["rows_excluded"] == 1 and len(corrected) == 2


def _dd_content_rows(order):
    """Two content-identical dedup candidates differing only in src_context_id
    plus one unrelated row. `order` in ('ab', 'ba') places ctxA-then-ctxB or the
    reverse. issuer_name/fair_value are the content match_fields."""
    a = {"cik": "1", "report_date": "q", "issuer_name": "Dup Co", "fair_value": 100.0,
         "src_context_id": "ctxA", "accession_number": "acc-1"}
    b = {"cik": "1", "report_date": "q", "issuer_name": "Dup Co", "fair_value": 100.0,
         "src_context_id": "ctxB", "accession_number": "acc-1"}
    other = {"cik": "1", "report_date": "q", "issuer_name": "Solo Co", "fair_value": 50.0,
             "src_context_id": "ctxZ", "accession_number": "acc-1"}
    dup = [a, b] if order == "ab" else [b, a]
    # `other` sits between the two duplicates so caller order is observable.
    return pd.DataFrame([dup[0], other, dup[1]])


def test_dedup_survivor_is_order_invariant_and_preserves_caller_order():
    """S17: the surviving duplicate must be the same context regardless of the
    caller's incoming row order (sort-for-mask), AND the returned frame must keep
    the caller's incoming order (mask-only sort, never a reorder)."""
    rule = _dd(match_fields=["issuer_name", "fair_value"], keep="first")

    corr_ab, aud_ab = apply_rules(_dd_content_rows("ab"), [rule])
    corr_ba, aud_ba = apply_rules(_dd_content_rows("ba"), [rule])

    # (a) One duplicate removed in each order.
    assert aud_ab[0]["rows_excluded"] == 1
    assert aud_ba[0]["rows_excluded"] == 1

    # (b) Deterministic survivor pinned to the anchor: ctxA sorts before ctxB, so
    # keep='first' after the anchor sort must retain ctxA in BOTH input orders.
    surv_ab = set(corr_ab.loc[corr_ab["issuer_name"] == "Dup Co", "src_context_id"])
    surv_ba = set(corr_ba.loc[corr_ba["issuer_name"] == "Dup Co", "src_context_id"])
    assert surv_ab == {"ctxA"}
    assert surv_ba == {"ctxA"}

    # (c) Caller row order preserved. In 'ab' order the surviving rows were rows
    # 0 (Dup Co ctxA) then 1 (Solo Co); the dropped row was index 2. Output must
    # read Dup Co, Solo Co -- NOT reordered by the internal anchor sort.
    assert list(corr_ab["issuer_name"]) == ["Dup Co", "Solo Co"]
    # In 'ba' order the surviving Dup Co (ctxA) was row 2, after Solo Co (row 1);
    # the dropped row (ctxB) was index 0. Output must read Solo Co, Dup Co.
    assert list(corr_ba["issuer_name"]) == ["Solo Co", "Dup Co"]


def test_dedup_anchor_falls_back_to_accession_when_no_row_id():
    """S17: with no row_id column, the anchor is accession+src_context_id+
    nport_holding_id (fillna). ctxA still wins deterministically via the tie key."""
    rule = _dd(match_fields=["issuer_name", "fair_value"], keep="first")
    corr_ab, _ = apply_rules(_dd_content_rows("ab"), [rule])
    corr_ba, _ = apply_rules(_dd_content_rows("ba"), [rule])
    surv_ab = set(corr_ab.loc[corr_ab["issuer_name"] == "Dup Co", "src_context_id"])
    surv_ba = set(corr_ba.loc[corr_ba["issuer_name"] == "Dup Co", "src_context_id"])
    assert surv_ab == surv_ba == {"ctxA"}


def test_dedup_anchor_prefers_row_id_when_present():
    """S17: when row_id is present it is the sole anchor. Pin the survivor to the
    lower row_id regardless of caller order (row_id 'r1' < 'r2')."""
    rule = _dd(match_fields=["issuer_name", "fair_value"], keep="first")

    def _rows(order):
        a = {"cik": "1", "report_date": "q", "issuer_name": "Dup Co", "fair_value": 100.0,
             "row_id": "r1", "src_context_id": "ctxB", "accession_number": "acc-1"}
        b = {"cik": "1", "report_date": "q", "issuer_name": "Dup Co", "fair_value": 100.0,
             "row_id": "r2", "src_context_id": "ctxA", "accession_number": "acc-1"}
        pair = [a, b] if order == "ab" else [b, a]
        return pd.DataFrame(pair)

    corr_ab, _ = apply_rules(_rows("ab"), [rule])
    corr_ba, _ = apply_rules(_rows("ba"), [rule])
    # row_id 'r1' wins in both orders even though its src_context_id sorts later.
    assert set(corr_ab["row_id"]) == {"r1"}
    assert set(corr_ba["row_id"]) == {"r1"}


# -- value_expression (bounded arithmetic DSL; gap-5 vocab) -----------------------------

def _vexpr(**kw):
    base = {"cik": "1", "rule_id": "vx", "rule_type": "value_expression", "action": "set",
            "predicate_sql": "bdc_dimensions_raw = 'x'", "field": "fair_value",
            "expression": "principal_amount * 0.5", "scope": {"quarters": ["all"]},
            "evidence": [{"source": "query", "quote": "fv should be principal*price"}],
            "rationale": "fair_value mis-derived; recompute from principal", "confidence": 0.8}
    base.update(kw)
    return base


def test_value_expression_validates_field_and_expression():
    assert validate_rule(_vexpr()) == []
    assert any("field must be one of" in e for e in validate_rule(_vexpr(field="cik")))
    assert any("unknown column" in e for e in validate_rule(_vexpr(expression="principal_amount * foo")))
    assert any("disallowed expression element" in e for e in validate_rule(_vexpr(expression="abs(cost)")))
    assert any("does not parse" in e for e in validate_rule(_vexpr(expression="principal_amount *")))
    assert any("predicate_sql is required" in e for e in validate_rule(_vexpr(predicate_sql="")))


def test_value_expression_sets_computed_value_keeps_position():
    df = pd.DataFrame([{**_h("1", "2025q", 9.9e9, dims="x"), "principal_amount": 1000.0},  # garbage fv
                       {**_h("1", "2025q", 500.0, dims="y"), "principal_amount": 999.0}])
    corrected, audits = apply_rules(df, [_vexpr(expression="principal_amount * 0.5")])
    assert audits[0]["status"] == "ok" and audits[0]["rows_set"] == 1 and not audits[0]["noop"]
    assert len(corrected) == 2                                     # position NOT deleted
    assert value_sum_by_quarter(corrected)["2025q"] == 1000.0      # 1000*0.5 (fixed) + 500


# -- no-op detection (self-verify: a rule that changes nothing is flagged) ---------------

def test_noop_rule_is_flagged():
    df = pd.DataFrame([_h("1", "q", 100.0, dims="A")])
    corrected, audits = apply_rules(df, [_rule(predicate_sql="bdc_dimensions_raw = 'NOPE'")])
    assert audits[0]["status"] == "ok" and audits[0]["noop"] is True
    assert len(corrected) == 1                                     # nothing dropped
    # a rule that DOES change rows is not flagged
    _, audits2 = apply_rules(df, [_rule(predicate_sql="bdc_dimensions_raw = 'A'")])
    assert audits2[0]["noop"] is False


# -- proposed_mechanism escalation (gap-5 channel) --------------------------------------

def test_validate_escalation():
    from pipeline.agent_rule import validate_escalation
    esc = {"cik": "1715933", "target_quarter": "2025-06-30", "kind": "proposed_mechanism",
           "summary": "two-table double count needs a cross-table dedup op",
           "evidence": [{"source": "query", "quote": "issuer appears 4x"}],
           "why_no_vocab_fits": "dedup key cannot span the two source tables", "confidence": 0.6}
    assert validate_escalation(esc) == []
    assert any("kind must be" in e for e in validate_escalation({**esc, "kind": "whatever"}))
    assert any("why_no_vocab_fits is empty" in e for e in validate_escalation({**esc, "why_no_vocab_fits": ""}))
    assert any("evidence must be" in e for e in validate_escalation({**esc, "evidence": []}))


# -- row_add (recover an under-counted position; grounded by source_row_id) --------------

def _addrule(**kw):
    pos = {"report_date": "2025q", "fair_value": 400.0, "issuer_name": "Recovered Fund",
           "bdc_dimensions_raw": "investmentidentifieraxis=Recovered Fund", "source_row_id": "staging:abc123"}
    base = {"cik": "1", "rule_id": "add", "rule_type": "row_add", "action": "add",
            "scope": {"quarters": ["2025q"]}, "positions": [pos],
            "evidence": [{"source": "staging", "quote": "row in staging, missing from holdings"}],
            "rationale": "extractor dropped a real position", "confidence": 0.85}
    base.update(kw)
    return base


def test_row_add_requires_source_grounding_and_counted_dims():
    assert validate_rule(_addrule()) == []
    drop = lambda key: {k: v for k, v in _addrule()["positions"][0].items() if k != key}
    assert any("source_row_id" in e for e in validate_rule(_addrule(positions=[drop("source_row_id")])))
    assert any("bdc_dimensions_raw" in e for e in validate_rule(_addrule(positions=[drop("bdc_dimensions_raw")])))
    bad_fv = {**_addrule()["positions"][0], "fair_value": "400"}
    assert any("fair_value must be a number" in e for e in validate_rule(_addrule(positions=[bad_fv])))


def test_row_add_tolerates_extra_source_columns():
    # the 1715933 case: the worker pasted the whole staging row. Extra keys must NOT fail it (the
    # applier ignores non-holdings columns); only missing REQUIRED grounding fields fail.
    pos = {**_addrule()["positions"][0], "accession_number": "0001-25", "period": "2025-03-31",
           "cik": "1", "source": "bdc", "pct_of_net_assets": 0.1}
    assert validate_rule(_addrule(positions=[pos])) == []
    df = pd.DataFrame([_h("1", "2025q", 600.0, dims="DL")])
    corrected, audits = apply_rules(df, [_addrule(positions=[pos])])
    assert audits[0]["status"] == "ok" and audits[0]["rows_added"] == 1 and not audits[0]["noop"]
    assert "accession_number" in audits[0]["ignored_keys"]   # extra key dropped, recorded


def test_row_add_recovers_undercount():
    df = pd.DataFrame([_h("1", "2025q", 600.0, dims="DL")])       # under-count: 600 vs anchor 1000
    corrected, audits = apply_rules(df, [_addrule()])
    assert audits[0]["status"] == "ok" and audits[0]["rows_added"] == 1
    assert audits[0]["source_row_ids"] == ["staging:abc123"]
    assert value_sum_by_quarter(corrected)["2025q"] == 1000.0     # 600 + 400, now counted


def test_row_add_skips_duplicate_of_existing_row():
    """Gate blind spot 1 (1905824 FHLB veto): a row_add duplicating an EXISTING
    row is invisible to the conservation gate when the existing row is
    conservation-excluded (CASH). The applier itself must skip exact
    (report_date, identifier, fair_value) duplicates and record them."""
    existing = {**_h("1", "2025q", 400.0, dims="investmentidentifieraxis=FHLB Note 1"),
                "bdc_investment_identifier": "FHLB Note 1", "asset_category": "CASH"}
    df = pd.DataFrame([existing, {**_h("1", "2025q", 600.0),
                                  "bdc_investment_identifier": "Real Co - TL",
                                  "asset_category": "LOAN"}])
    pos_dup = {"report_date": "2025q", "fair_value": 400.0,
               "bdc_investment_identifier": "FHLB Note 1",
               "bdc_dimensions_raw": "investmentidentifieraxis=FHLB Note 1",
               "source_row_id": "staging:dup"}
    pos_new = {"report_date": "2025q", "fair_value": 55.0,
               "bdc_investment_identifier": "New Real Position",
               "bdc_dimensions_raw": "investmentidentifieraxis=New Real Position",
               "source_row_id": "staging:new"}
    corrected, audits = apply_rules(df, [_addrule(positions=[pos_dup, pos_new])])
    a = audits[0]
    assert a["status"] == "ok"
    assert a["rows_added"] == 1
    assert a["rows_skipped_duplicate"] == 1
    assert len(corrected) == 3            # 2 existing + 1 new; no double-count
    assert not a["noop"]


def test_row_add_empty_identifier_never_treated_as_duplicate():
    """Fail-open: rows without an identifier cannot be judged duplicates (the
    position validates via issuer_name; the frame row has the same FV and an
    empty identifier)."""
    df = pd.DataFrame([{**_h("1", "2025q", 400.0), "bdc_investment_identifier": ""}])
    pos = {"report_date": "2025q", "fair_value": 400.0,
           "issuer_name": "Recovered Fund",
           "bdc_investment_identifier": "",
           "bdc_dimensions_raw": "investmentidentifieraxis=x",
           "source_row_id": "staging:noid"}
    corrected, audits = apply_rules(df, [_addrule(positions=[pos])])
    assert audits[0]["rows_added"] == 1
    assert audits[0].get("rows_skipped_duplicate", 0) == 0
    assert len(corrected) == 2


# -- gate guards: anchor-sanity (delete-to-balance) + over-addition ----------------------

def test_gate_fails_aggregate_row_add_on_empty_quarter():
    """Gate blind spot 2 (2008748 veto): extraction has ZERO rows for the target
    quarter; a row_add of category subtotals closes the -100% residual and the
    conservation checks trivially pass. Added rows whose identifiers match the
    canonical aggregate patterns must FAIL no_aggregate_addition."""
    base = pd.DataFrame([_h("1", "2024-12-31", 100.0)])       # target quarter EMPTY
    added = pd.DataFrame([
        {**_h("1", "2025-12-31", 600.0,
              dims="investmentidentifieraxis=Total Senior Secured Loans"),
         "bdc_investment_identifier": "Total Senior Secured Loans"},
        {**_h("1", "2025-12-31", 400.0,
              dims="investmentidentifieraxis=Equity Securities"),
         "bdc_investment_identifier": "Equity Securities"},
    ])
    corrected = pd.concat([base, added], ignore_index=True)
    g = gate_rules(base, corrected, cik="1", target_quarter="2025-12-31",
                   anchors={"2025-12-31": 1000.0, "2024-12-31": 100.0})
    assert g.checks["no_aggregate_addition"] is False
    assert g.verdict == "FAIL"
    assert any("Total Senior Secured Loans" in r for r in g.reasons)


def test_gate_allows_real_position_add_with_total_prefix_name():
    """False-positive guard: 'Total Access Elevator, LLC' is a real company, not
    a subtotal -- entity signals must clear the aggregate check."""
    base = pd.DataFrame([_h("1", "2025-12-31", 600.0),
                         _h("1", "2025-09-30", 100.0, dims="HB"),
                         _h("1", "2024-12-31", 100.0, dims="HA")])
    added = pd.DataFrame([
        {**_h("1", "2025-12-31", 400.0,
              dims="investmentidentifieraxis=Total Access Elevator, LLC - First Lien Term Loan"),
         "bdc_investment_identifier": "Total Access Elevator, LLC - First Lien Term Loan"},
    ])
    corrected = pd.concat([base, added], ignore_index=True)
    g = gate_rules(base, corrected, cik="1", target_quarter="2025-12-31",
                   anchors={"2025-12-31": 1000.0, "2025-09-30": 100.0, "2024-12-31": 100.0})
    assert g.checks["no_aggregate_addition"] is True
    assert g.verdict == "PASS"


def test_gate_flags_excessive_removal_against_bad_anchor():
    # 1743415 shape: schedule $1050, anchor $50 -> "reconcile" by deleting 95% -> anchor_sanity FAIL
    rows = [_h("1", "2023-12-31", 1000.0, dims="A"), _h("1", "2023-12-31", 50.0, dims="KEEP"),
            _h("1", "2024-12-31", 100.0, dims="B"), _h("1", "2025-12-31", 100.0, dims="C")]
    base = pd.DataFrame(rows)
    anchors = {"2023-12-31": 50.0, "2024-12-31": 100.0, "2025-12-31": 100.0}
    rule = _rule(rule_id="del", scope={"quarters": ["2023-12-31"]},
                 predicate_sql="report_date = '2023-12-31' AND bdc_dimensions_raw <> 'KEEP'")
    corrected, _ = apply_rules(base, [rule])
    g = gate_rules(base, corrected, cik="1", target_quarter="2023-12-31", anchors=anchors)
    assert g.verdict == "FAIL" and g.checks["anchor_sanity"] is False
    assert any("removed" in r and "anchor is likely wrong" in r for r in g.reasons)


def test_gate_flags_over_addition_past_anchor():
    base = pd.DataFrame([_h("1", "2025q", 600.0, dims="DL"),
                         _h("1", "hq1", 1000.0, dims="X"), _h("1", "hq2", 1000.0, dims="Y")])
    anchors = {"2025q": 1000.0, "hq1": 1000.0, "hq2": 1000.0}
    over = _addrule(scope={"quarters": ["2025q"]}, positions=[          # add 600 -> 1200 > anchor 1000
        {"report_date": "2025q", "fair_value": 600.0, "issuer_name": "Over",
         "bdc_dimensions_raw": "investmentidentifieraxis=Over", "source_row_id": "s"}])
    corrected, _ = apply_rules(base, [over])
    g = gate_rules(base, corrected, cik="1", target_quarter="2025q", anchors=anchors)
    assert g.verdict == "FAIL" and g.checks["no_over_addition"] is False


def test_gate_allows_proportional_dedup_removal():
    # a genuine ~27% removal (not delete-to-balance) must still PASS anchor_sanity.
    base = _three_quarter_frame()                                   # CLO 376 of 1376 (~27%)
    anchors = {"2026-02-28": 1000.0, "2025-11-30": 1000.0, "2025-08-31": 1000.0}
    corrected, _ = apply_rules(base, [_rule()])
    g = gate_rules(base, corrected, cik="1377936", target_quarter="2026-02-28", anchors=anchors)
    assert g.verdict == "PASS" and g.checks["anchor_sanity"] and g.checks["no_over_addition"]


# -- gate guard: anchor_validated (contested/absent anchor -> escalate) -----------------

def test_gate_fails_when_target_anchor_is_contested():
    # two INDEPENDENT (strong) anchors DISAGREE -> residual undefined. Even a rule that
    # "reconciles" to one of them must not PASS: anchor_validated FAILs first.
    base = _three_quarter_frame(anchor=1000.0, clo_fv=376.0)
    corrected, _ = apply_rules(base, [_rule()])
    candidates = {
        "2026-02-28": {"companyfacts_fv": 1000.0, "printed_schedule_total": 1400.0},  # contested
        "2025-11-30": {"companyfacts_fv": 1000.0, "printed_schedule_total": 1001.0},
        "2025-08-31": {"companyfacts_fv": 1000.0, "printed_schedule_total": 1001.0},
    }
    g = gate_rules(base, corrected, cik="1377936", target_quarter="2026-02-28",
                   anchor_candidates=candidates)
    assert g.verdict == "FAIL" and g.checks["anchor_validated"] is False
    assert any("anchor not validated" in r for r in g.reasons)


def test_gate_passes_with_validated_medium_anchor():
    # single strong anchor (the only one this repo wires today) -> MEDIUM; a clean reconcile still
    # PASSES, and the MEDIUM caveat is surfaced in the reasons. An extraction re-sum is ignored.
    base = _three_quarter_frame(anchor=1000.0, clo_fv=376.0)
    corrected, _ = apply_rules(base, [_rule()])
    candidates = {q: {"companyfacts_fv": 1000.0, "schedule_total": 3500.0}
                  for q in ("2026-02-28", "2025-11-30", "2025-08-31")}
    g = gate_rules(base, corrected, cik="1377936", target_quarter="2026-02-28",
                   anchor_candidates=candidates)
    assert g.verdict == "PASS", g.reasons
    assert g.checks["anchor_validated"] is True
    assert any("anchor_validated=MEDIUM" in r for r in g.reasons)


# -- value_sum / snapshots --------------------------------------------------------------

def test_value_sum_honors_gate_filter():
    df = pd.DataFrame([_h("1", "q", 100.0), {**_h("1", "q", 50.0), "bdc_dimensions_raw": None}])
    assert value_sum_by_quarter(df) == {"q": 100.0}


# -- gate (B3 over the agent's rules) ---------------------------------------------------

def _three_quarter_frame(anchor=1000.0, clo_fv=376.0):
    rows = []
    for q in ("2026-02-28", "2025-11-30", "2025-08-31"):
        rows.append(_h("1377936", q, anchor))                         # DL book == anchor
    rows.append(_h("1377936", "2026-02-28", clo_fv,                   # CLO over-count, target qtr only
                   dims="investmentidentifieraxis=X|legalentityaxis=FooCloMember"))
    return pd.DataFrame(rows)


def test_gate_passes_when_rule_reconciles_target_and_holds_others():
    base = _three_quarter_frame()
    anchors = {"2026-02-28": 1000.0, "2025-11-30": 1000.0, "2025-08-31": 1000.0}
    corrected, _ = apply_rules(base, [_rule()])
    g = gate_rules(base, corrected, cik="1377936", target_quarter="2026-02-28", anchors=anchors)
    assert g.verdict == "PASS", g.reasons
    assert g.checks["target_cleared"] and g.checks["no_over_deletion"]


def test_gate_fails_on_over_deletion_below_anchor():
    # anchor higher than the post-drop value_sum -> dropping the CLO lands below anchor.
    base = _three_quarter_frame(anchor=1000.0, clo_fv=376.0)
    anchors = {"2026-02-28": 1018.0, "2025-11-30": 1000.0, "2025-08-31": 1000.0}
    corrected, _ = apply_rules(base, [_rule()])         # target -> 1000 < anchor 1018
    g = gate_rules(base, corrected, cik="1377936", target_quarter="2026-02-28", anchors=anchors)
    assert g.verdict == "FAIL" and g.checks["no_over_deletion"] is False


# -- the investigate-to-zero loop decision ----------------------------------------------

def test_loop_decision_stops_within_tolerance():
    from scripts.agent_investigate.run_investigation import loop_decision
    d = loop_decision(0.4, iteration=2, gate_verdict="PASS")
    assert d["stop"] is True and d["success"] is True


def test_loop_decision_stops_on_negative_residual_within_tolerance():
    from scripts.agent_investigate.run_investigation import loop_decision
    d = loop_decision(-0.4, iteration=1, gate_verdict="PASS")  # undershoot but |0.4| <= band
    assert d["stop"] is True and d["success"] is True


def test_loop_decision_band_matches_engine_band():
    """The loop stop tolerance and the engine reconcile band must be the SAME
    constant -- a loop-level success outside the engine band re-flags after
    promotion (Wave-1: 1930087/1930679 landed in the 0.5-1.0% gap)."""
    from pipeline.config import FV_CONSERVATION_BAND_PCT
    from scripts.agent_investigate.run_investigation import STOP_TOL_PCT
    from scripts.shadow_conservation_engine import RULES
    fv_rule = next(r for r in RULES if r.name == "fv_conservation")
    assert STOP_TOL_PCT == FV_CONSERVATION_BAND_PCT
    assert fv_rule.tolerance_pct == FV_CONSERVATION_BAND_PCT / 100.0
    # residual just outside the band must iterate, just inside must stop
    from scripts.agent_investigate.run_investigation import loop_decision
    outside = loop_decision(FV_CONSERVATION_BAND_PCT + 0.01, iteration=1, gate_verdict="PASS")
    inside = loop_decision(FV_CONSERVATION_BAND_PCT - 0.01, iteration=1, gate_verdict="PASS")
    assert outside["stop"] is False
    assert inside["stop"] is True and inside["success"] is True


def test_loop_decision_continues_when_residual_ok_but_gate_fails():
    from scripts.agent_investigate.run_investigation import loop_decision
    d = loop_decision(0.0, iteration=1, gate_verdict="FAIL")
    assert d["stop"] is False and d["success"] is False
    assert "gate FAIL" in d["reason"]


def test_gate_rules_none_tier_target_fails_only_anchor_validated():
    """1930679 circularity: a NONE-tier target must produce ONE actionable
    failure, not a cascade of absent-snapshot failures."""
    import pandas as pd
    df = pd.DataFrame({
        "cik": ["1930679"] * 2, "report_date": ["2025-12-31"] * 2,
        "fair_value": [1_000_000.0, 2_000_000.0], "asset_category": ["LOAN", "LOAN"],
    })
    res = gate_rules(df, df.copy(), cik="1930679", target_quarter="2025-12-31",
                     anchor_candidates={"2025-12-31": {}})   # no candidates -> tier NONE
    assert res.verdict == "FAIL"
    assert res.checks == {"anchor_validated": False}
    assert any("snapshot checks skipped" in r for r in res.reasons)
    assert not any("absent from trial snapshots" in r for r in res.reasons)


def test_loop_decision_continues_when_outside_tolerance():
    from scripts.agent_investigate.run_investigation import loop_decision
    d = loop_decision(11.3, iteration=2)
    assert d["stop"] is False and d["success"] is False


def test_loop_decision_stops_unsuccessfully_at_max_iterations():
    from scripts.agent_investigate.run_investigation import loop_decision
    d = loop_decision(11.3, iteration=5)
    assert d["stop"] is True and d["success"] is False


def test_loop_decision_stops_unsuccessfully_at_max_iterations_with_gate_fail():
    from scripts.agent_investigate.run_investigation import loop_decision
    d = loop_decision(0.0, iteration=5, gate_verdict="FAIL")
    assert d["stop"] is True and d["success"] is False


def test_iteration_prompt_carries_residual_and_gate_feedback():
    from scripts.agent_investigate.run_investigation import _prompt
    state = {"target_quarter": "2025-12-31", "residual_pct": 11.3, "anchor": 645193114.0,
             "gate_reasons": ["conservation residual did not improve"],
             "rule_summary": [{"rule_id": "dedup-fka", "predicate_sql": "issuer_name LIKE '%(fka%'"}],
             "corrected_holdings": "data/output/agent_investigate/1715933/corrected.csv"}
    txt = _prompt("1715933", "2025-12-31", {"2025-12-31": 645193114.0}, __import__("pathlib").Path("x"),
                  iteration=2, state=state)
    assert "Iteration 2" in txt and "11.3%" in txt and "dedup-fka" in txt
    assert "--holdings" in txt and "did not improve" in txt
    # iteration 1 has no feedback block
    txt1 = _prompt("1715933", "2025-12-31", {"2025-12-31": 645193114.0}, __import__("pathlib").Path("x"))
    assert "Iteration 2" not in txt1


def test_value_sum_excludes_cash_but_keeps_rows():
    # cash-equivalents (T-bills/sweeps) stay in holdings but are NOT in the conservation sum
    df = pd.DataFrame([
        {**_h("1", "q", 1000.0), "asset_category": "LOAN"},
        {**_h("1", "q", 200.0), "asset_category": "CASH"},
    ])
    assert value_sum_by_quarter(df)["q"] == 1000.0   # cash excluded from the sum
    assert len(df) == 2                              # but the cash row is retained in the frame


def test_value_sum_excludes_subsidiary_rows_but_keeps_them():
    # Retain-and-flag (owner decision 2026-08-29): nonconsolidated-subsidiary /
    # look-through rows stay in holdings, but the filing's consolidated total already
    # contains them once -- summing them again double-counts, so the conservation
    # frame excludes is_subsidiary=1.
    df = pd.DataFrame([
        {**_h("1", "q", 1815.0), "is_subsidiary": 0},
        {**_h("1", "q", 406.0), "is_subsidiary": 1},     # look-through layer
        {**_h("1", "q", 100.0), "is_subsidiary": None},  # unset counts as not-subsidiary
    ])
    assert value_sum_by_quarter(df)["q"] == 1915.0
    assert len(df) == 3  # rows retained, only the sum is subsidiary-aware


# -- dedupe_escalations ---------------------------------------------------------------

def test_dedupe_escalations_collapses_same_quarter_category():
    escs = [
        {"target_quarter": "2026-03-31", "category": "vocab", "summary": "v1"},
        {"target_quarter": "2026-03-31", "category": "vocab", "summary": "v2 restated"},
        {"target_quarter": "2026-03-31", "category": "anchor", "summary": "a1"},
        {"target_quarter": "2025-12-31", "category": "vocab", "summary": "other quarter"},
    ]
    out = dedupe_escalations(escs)
    assert len(out) == 3
    assert {e["summary"] for e in out} == {"v2 restated", "a1", "other quarter"}


def test_value_sum_respects_conservation_scope(monkeypatch):
    from pipeline import conservation_scope
    df = pd.DataFrame({
        "cik": ["1905824"] * 2, "report_date": ["2026-03-31"] * 2,
        "fair_value": [156_078_000.0, 38_767_000.0],
        "asset_category": ["LOAN", "CASH"],
    })
    assert value_sum_by_quarter(df)["2026-03-31"] == 156_078_000.0   # default: CASH out
    monkeypatch.setattr(conservation_scope, "scope_override_for",
                        lambda cik: (frozenset({"CASH"}), None))
    assert value_sum_by_quarter(df, cik="1905824")["2026-03-31"] == 194_845_000.0


def test_value_sum_quarter_scoped_carveout_leaves_other_quarters(monkeypatch):
    """A carve-out scoped to Q1-2026 must not pull CASH into the Q4-2025 sum
    (the "all"-scope regression of the attested 2025-12-31, 2026-09-02)."""
    from pipeline import conservation_scope
    df = pd.DataFrame({
        "cik": ["1950976"] * 4,
        "report_date": ["2026-03-31", "2026-03-31", "2025-12-31", "2025-12-31"],
        "fair_value": [1_588_604_000.0, 36_885_000.0, 1_482_846_000.0, 65_057_000.0],
        "asset_category": ["LOAN", "CASH", "LOAN", "CASH"],
    })
    monkeypatch.setattr(conservation_scope, "scope_override_for",
                        lambda cik: (frozenset({"CASH"}), frozenset({"2026-03-31"})))
    vs = value_sum_by_quarter(df, cik="1950976")
    assert vs["2026-03-31"] == 1_625_489_000.0   # CASH rescued in-scope
    assert vs["2025-12-31"] == 1_482_846_000.0   # CASH still excluded out-of-scope
