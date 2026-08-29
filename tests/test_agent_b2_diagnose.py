"""Tests for the deterministic anchor-scored diagnosis battery (pipeline/agent_b2_diagnose)
and its wiring into the B2 remediation driver. All synthetic, no real data, no LLM."""
import pandas as pd
import pytest

from pipeline.agent_b2_diagnose import (
    diagnose, value_sum, raw_structural_map, select_mechanism, map_legalentity_to_equity,
    spv_lookthrough_view,
)
from pipeline.agent_b2_appliers import apply_spv_lookthrough
from pipeline.agent_b_held_out import gate_correction
from pipeline.correction_leaf import validate_correction
from scripts.agent_b2.run_remediation import group_real_errors, annotate_with_diagnosis


# -- unified-frame helpers --------------------------------------------------------------

_UNI_COLS = ["bdc_dimensions_raw", "fair_value", "cost", "interest_rate", "maturity_date",
             "principal_amount", "shares_held", "cusip", "bdc_investment_identifier",
             "issuer_name", "instrument_description", "report_date"]


def _u(fair_value, ident, *, detail=True, dims="dim", report_date="2026-02-28",
       cost=None, shares_held=None):
    return {"bdc_dimensions_raw": dims, "fair_value": fair_value, "cost": cost,
            "interest_rate": 5.0 if detail else None, "maturity_date": None,
            "principal_amount": None, "shares_held": shares_held, "cusip": None,
            "bdc_investment_identifier": ident, "issuer_name": ident,
            "instrument_description": "Term Loan", "report_date": report_date}


def _uframe(rows):
    return pd.DataFrame(rows, columns=_UNI_COLS)


# -- value_sum --------------------------------------------------------------------------

def test_value_sum_honors_gate_filter():
    df = _uframe([_u(100.0, "A"), _u(50.0, "B", dims=None)])  # B excluded (null dims)
    assert value_sum(df) == 100.0


def test_value_sum_excludes_subsidiary_rows():
    # Retain-and-flag (2026-08-29): is_subsidiary=1 look-through rows are retained in
    # holdings but excluded from the conservation frame -- the consolidated anchor
    # already contains them once. Column absent (as in _uframe) => nothing excluded.
    df = _uframe([_u(100.0, "A"), _u(40.0, "SubLayer")])
    df["is_subsidiary"] = [0, 1]
    assert value_sum(df) == 100.0


# -- battery: a clean aggregate leak reconciles -----------------------------------------

def test_no_detail_aggregate_reconciles():
    rows = [_u(40.0, "LeafA"), _u(30.0, "LeafB"), _u(30.0, "LeafC"),
            _u(100.0, "AGG", detail=False)]                       # no-detail rollup
    out = diagnose(_uframe(rows), anchor=100.0)
    assert out["value_sum"] == 200.0 and out["residual"] == 100.0
    assert out["reconciles"] is True
    assert out["recommended_mechanisms"] == ["aggregate_row_filter"]
    assert out["escalate"] is False


def test_exact_dedup_reconciles():
    rows = [_u(40.0, "LeafA"), _u(30.0, "LeafB"), _u(30.0, "LeafC"),
            _u(40.0, "LeafA")]                                    # exact duplicate of LeafA
    out = diagnose(_uframe(rows), anchor=100.0)
    assert out["reconciles"] is True
    assert "dedup" in out["recommended_mechanisms"]


# -- battery: over-deletion guard + escalation ------------------------------------------

def test_over_deletion_guard_blocks_below_anchor():
    # value_sum 130; removing the no-detail 50 would land at 80 (< anchor 100) -> guarded.
    rows = [_u(80.0, "Leaf"), _u(50.0, "AGG", detail=False)]
    out = diagnose(_uframe(rows), anchor=100.0)
    probe = next(p for p in out["probes"] if p["name"] == "no_detail_aggregate")
    assert probe["over_deletes_below_anchor"] is True
    assert out["composition"] == [] and out["reconciles"] is False and out["escalate"] is True


def test_no_probe_reconciles_escalates_with_residual():
    rows = [_u(70.0, "LeafA"), _u(60.0, "LeafB")]                 # all genuine, sum 130
    out = diagnose(_uframe(rows), anchor=100.0)
    assert out["reconciles"] is False and out["escalate"] is True
    assert "unattributed" in out["escalation_reason"]


# -- raw structural map (probe (a)) -----------------------------------------------------

_RAW_COLS = ["period", "report_date", "investment_identifier", "fair_value",
             "interest_rate", "maturity_date", "principal_amount", "shares_held"]


def _r(fair_value, ident, *, detail=True, period="2026-02-28", report_date="2026-02-28"):
    return {"period": period, "report_date": report_date, "investment_identifier": ident,
            "fair_value": fair_value, "interest_rate": 5.0 if detail else None,
            "maturity_date": None, "principal_amount": None, "shares_held": None}


def _rframe(rows):
    return pd.DataFrame(rows, columns=_RAW_COLS)


def test_raw_map_flags_extraction_anomaly():
    # aggregates sum to the anchor exactly; leaves over-sum with no dup -> anomaly.
    rows = [_r(100.0, "TOTAL INVESTMENTS", detail=False),
            _r(60.0, "Healthcare", detail=False), _r(40.0, "Tech", detail=False),
            _r(70.0, "LeafA"), _r(60.0, "LeafB")]                 # leaves = 130
    xref = raw_structural_map(_rframe(rows), anchor=100.0, report_date="2026-02-28")
    assert xref["reconciling_class"] == ["no_detail_aggregate"]
    assert xref["partition_inconsistent"] is True
    assert "anomaly" in xref["finding"]
    assert xref["leaf_minus_anchor"] == 30.0


def test_raw_map_clean_aggregate_leak_points_to_filter():
    rows = [_r(60.0, "LeafA"), _r(40.0, "LeafB"),                 # leaves = 100 (truth)
            _r(60.0, "Healthcare", detail=False)]                # aggregate leak
    xref = raw_structural_map(_rframe(rows), anchor=100.0, report_date="2026-02-28")
    assert xref["reconciling_class"] == ["has_detail_leaf"]
    assert "aggregate_row_filter" in xref["finding"]


def test_raw_map_excludes_other_periods():
    rows = [_r(60.0, "LeafA"), _r(40.0, "LeafB"),
            _r(999.0, "PriorLeaf", period="2025-02-28")]          # comparative, must be dropped
    xref = raw_structural_map(_rframe(rows), anchor=100.0, report_date="2026-02-28")
    assert xref["buckets"]["has_detail_leaf"]["fv_sum"] == 100.0


# -- selector ---------------------------------------------------------------------------

def test_select_mechanism_use():
    out = diagnose(_uframe([_u(40.0, "A"), _u(30.0, "B"), _u(30.0, "C"),
                            _u(100.0, "AGG", detail=False)]), anchor=100.0)
    sel = select_mechanism(out)
    assert sel["action"] == "use" and sel["fix_classes"] == ["aggregate_row_filter"]


def test_select_mechanism_escalate_prefers_raw_finding():
    diag = {"reconciles": False, "escalation_reason": "generic",
            "raw_cross_reference": {"finding": "specific raw anomaly here"}}
    sel = select_mechanism(diag)
    assert sel["action"] == "escalate" and sel["reason"] == "specific raw anomaly here"


# -- wiring into run_remediation --------------------------------------------------------

def _verdict(mechanism, findings=None):
    return {"verdict": "real_error", "mechanism": mechanism, "findings": findings or []}


def test_group_marks_symptom_packet_needs_diagnosis():
    verdicts = {"RVQ_1": _verdict("subtotal_leak")}
    meta = {"RVQ_1": {"cik": "0001377936", "report_date": "2026-02-28", "rule_name": "fv_conservation"}}
    packets = group_real_errors(verdicts, meta)
    assert len(packets) == 1
    p = packets[0]
    assert p["fix_class"] == "subtotal_filter"      # provisional guess
    assert p["fix_class_derived"] is True
    assert p["needs_diagnosis"] is True             # but flagged for the battery


def test_findings_packet_is_not_flagged_for_diagnosis():
    verdicts = {"RVQ_1": _verdict("genuine_value_defect",
                                  findings=[{"fix_class": "dedup", "citation": "x"}])}
    meta = {"RVQ_1": {"cik": "0001", "report_date": "2026-02-28", "rule_name": "c113"}}
    p = group_real_errors(verdicts, meta)[0]
    assert p["fix_class"] == "dedup" and p["needs_diagnosis"] is False


def test_annotate_use_replaces_guess_with_measured():
    packet = {"cik": "1", "fix_class": "subtotal_filter", "fix_class_derived": True,
              "needs_diagnosis": True, "quarters": ["2026-02-28"]}
    diag = {"reconciles": True, "recommended_mechanisms": ["dedup"],
            "residual": 40.0, "residual_after_composition": 0.0}
    out = annotate_with_diagnosis(packet, diag)
    assert out["fix_class"] == "dedup" and out["fix_class_derived"] is False
    assert out["needs_diagnosis"] is False and out["diagnosis"]["action"] == "use"


def test_annotate_escalate_drops_fix_class():
    packet = {"cik": "1", "fix_class": "subtotal_filter", "fix_class_derived": True,
              "needs_diagnosis": True, "quarters": ["2026-02-28"]}
    diag = {"reconciles": False, "escalation_reason": "residual unattributed",
            "residual": 358.0, "residual_after_composition": 285.0}
    out = annotate_with_diagnosis(packet, diag)
    assert out["fix_class"] is None and out["diagnosis"]["action"] == "escalate"


def test_annotate_leaves_non_diagnosis_packet_untouched():
    packet = {"cik": "1", "fix_class": "dedup", "needs_diagnosis": False}
    assert annotate_with_diagnosis(packet, {"reconciles": True}) == packet


# -- SPV / consolidated-subsidiary look-through (the leverage-aware rule) ----------------

def _spv_frame(*, equity_fv, collateral_fvs, member, equity_name, anchor_dl=1000.0):
    """DL book summing to anchor_dl + a parent SPV equity line + look-through collateral."""
    rows = [_u(anchor_dl * 0.6, "LeafA", dims="investmentidentifieraxis=DL"),
            _u(anchor_dl * 0.4, "LeafB", dims="investmentidentifieraxis=DL"),
            _u(equity_fv, equity_name, cost=equity_fv, shares_held=10,
               dims=f"investmentidentifieraxis={equity_name}")]
    for i, cfv in enumerate(collateral_fvs):
        rows.append(_u(cfv, f"BSL {i}", cost=cfv,
                       dims=f"investmentidentifieraxis=BSL {i}|legalentityaxis={member}"))
    return _uframe(rows)


def test_spv_view_mismatch_levered_clo_suggests_use_equity():
    # CLO/Saratoga case: equity carried at 0, collateral 376 -> diverge. The VIEW only reports;
    # it does not apply or decide for the agent.
    df = _spv_frame(equity_fv=0.0, collateral_fvs=[200.0, 176.0],
                    member="FooFinancingSpvLlcMember", equity_name="Control - Foo Financing SPV LLC")
    view = spv_lookthrough_view(df)
    assert len(view) == 1
    v = view[0]
    assert v["legal_entity"] == "FooFinancingSpvLlcMember"
    assert v["underlying_fv"] == 376.0 and v["equity_fv"] == 0.0 and v["mapped"] is True
    assert v["reconciles_to_equity"] is False and v["suggested_decision"] == "use_equity"


def test_spv_view_match_unlevered_suggests_keep_lookthrough():
    df = _spv_frame(equity_fv=100.0, collateral_fvs=[60.0, 40.0],
                    member="BarCreditSpvLlcMember", equity_name="Bar Credit SPV LLC", anchor_dl=900.0)
    v = spv_lookthrough_view(df)[0]
    assert v["underlying_fv"] == 100.0 and v["equity_fv"] == 100.0
    assert v["reconciles_to_equity"] is True and v["suggested_decision"] == "keep_lookthrough"


def test_battery_does_not_autodecide_spv():
    # The auto-battery must NOT resolve SPV structure -- that is the agent's job (Layer 2).
    df = _spv_frame(equity_fv=0.0, collateral_fvs=[200.0, 176.0],
                    member="FooFinancingSpvLlcMember", equity_name="Control - Foo Financing SPV LLC")
    out = diagnose(df, anchor=1000.0)
    assert "spv_lookthrough" not in out["recommended_mechanisms"]
    assert out["reconciles"] is False and out["escalate"] is True


def test_map_legalentity_collapse_match_and_failclosed():
    parent = pd.DataFrame([
        {"issuer_name": "Saratoga Investment Corp. CLO 2013-1, Ltd. - Class F",
         "bdc_investment_identifier": "Control investments - 10.1% - Saratoga Investment Corp. CLO 2013-1, Ltd."},
        {"issuer_name": "Pepper Palace, Inc.", "bdc_investment_identifier": "Control - Pepper Palace"},
    ])
    hit = map_legalentity_to_equity("SaratogaInvestmentCorpCLO20131LtdMember", parent)
    assert hit == [0]                                    # robust to punctuation + digit grouping
    assert map_legalentity_to_equity("XyzHoldingsLlcMember", parent) == []   # fail-closed: no match
    assert map_legalentity_to_equity("AbcMember", parent) == []              # fail-closed: key too short


def test_spv_template_validates_and_rejects_bad_decision():
    base = {"cik": "1377936", "mechanism": "subtotal_leak", "fix_class": "spv_lookthrough",
            "source_review_ids": ["RVQ_1"], "evidence_citations": [{"table_index": 1, "row_index": 2}],
            "confidence": 0.9, "rationale": "CLO collateral over-includes vs $0 equity"}
    ok = validate_correction({**base, "template": {"entities": [
        {"legal_entity": "FooFinancingSpvLlcMember", "decision": "use_equity"}]}})
    assert ok.ok, ok.errors
    bad = validate_correction({**base, "template": {"entities": [
        {"legal_entity": "FooFinancingSpvLlcMember", "decision": "delete_everything"}]}})
    assert not bad.ok and any("decision must be one of" in e for e in bad.errors)


def test_apply_spv_lookthrough_both_branches():
    df = _spv_frame(equity_fv=0.0, collateral_fvs=[200.0, 176.0],
                    member="FooFinancingSpvLlcMember", equity_name="Control - Foo Financing SPV LLC")
    use_eq, a1 = apply_spv_lookthrough(df, {"entities": [
        {"legal_entity": "FooFinancingSpvLlcMember", "decision": "use_equity"}]})
    assert a1["rows_dropped"] == 2 and value_sum(use_eq) == 1000.0      # collateral gone, equity kept
    keep_lt, a2 = apply_spv_lookthrough(df, {"entities": [
        {"legal_entity": "FooFinancingSpvLlcMember", "decision": "keep_lookthrough"}]})
    assert a2["rows_dropped"] == 1 and value_sum(keep_lt) == 1376.0     # equity line gone, collateral kept


def _snap(vs, anchor, flagged):
    return {"flags": ["fv_conservation"] if flagged else [],
            "conservation": {"value_sum": vs, "anchor_value": anchor},
            "fv_at_risk": abs(vs - anchor) if flagged else 0.0}


def test_spv_end_to_end_through_b3_gate():
    anchor = 1000.0
    target = _spv_frame(equity_fv=0.0, collateral_fvs=[200.0, 176.0],
                        member="FooFinancingSpvLlcMember", equity_name="Control - Foo Financing SPV LLC")
    template = {"entities": [{"legal_entity": "FooFinancingSpvLlcMember", "decision": "use_equity"}]}
    trial_target, _ = apply_spv_lookthrough(target, template)
    base_vs, trial_vs = value_sum(target), value_sum(trial_target)
    assert (base_vs, trial_vs) == (1376.0, 1000.0)
    baseline = {"2026-02-28": _snap(base_vs, anchor, True),
                "2025-11-30": _snap(1000.0, anchor, False),
                "2025-08-31": _snap(1000.0, anchor, False)}
    trial = {"2026-02-28": _snap(trial_vs, anchor, False),
             "2025-11-30": _snap(1000.0, anchor, False),
             "2025-08-31": _snap(1000.0, anchor, False)}
    res = gate_correction(cik="1377936", target_quarter="2026-02-28",
                          target_flags={"fv_conservation"}, baseline=baseline, trial=trial)
    assert res.verdict == "PASS", res.reasons
    assert res.checks["target_cleared"] and res.checks["residual_improved"]
