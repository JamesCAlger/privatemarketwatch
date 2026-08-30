"""Tests for the B2 correction-leaf schema + constrained template registry."""

from __future__ import annotations

import json

from pipeline import correction_leaf as cl


def _corr(**over):
    base = {
        "cik": "0001950803",
        "mechanism": "dimension_double_count",
        "fix_class": "dedup",
        "template": {"match_fields": ["issuer_name", "interest_rate", "report_date"], "keep": "first"},
        "source_review_ids": ["RVQ_BLK_abc123"],
        "evidence_citations": [{"table_index": 5, "row_index": 13, "quoted_text": "dup row"}],
        "confidence": 0.85,
        "rationale": "rows 12/13 identical",
    }
    base.update(over)
    return base


def test_valid_dedup_correction():
    rep = cl.validate_correction(_corr())
    assert rep.ok, rep.errors


def test_valid_rate_rescale_with_factor():
    rep = cl.validate_correction(_corr(
        mechanism="rate_scale", fix_class="rate_rescale",
        scope={"quarters": ["2025-12-31"]},
        template={"field": "interest_rate", "factor": 0.1,
                  "row_selector": {"issuer_name": "InFarm Technologies Limited"}}))
    assert rep.ok, rep.errors


def test_valid_all_pik_normalization():
    rep = cl.validate_correction(_corr(
        mechanism="genuine_value_defect", fix_class="all_pik_normalization",
        scope={"quarters": ["2025-12-31"]},
        template={"row_selector": {"issuer_name": "WDE TorcSill"}, "cash_rate": 0.0, "pik_rate": 25.75}))
    assert rep.ok, rep.errors


def test_unknown_fix_class_is_hard_error():
    rep = cl.validate_correction(_corr(fix_class="make_it_balance", template={}))
    assert not rep.ok
    assert any("fix_class" in e for e in rep.errors)


def test_template_extra_param_rejected():
    rep = cl.validate_correction(_corr(template={"match_fields": ["issuer_name"], "drop_everything": True}))
    assert not rep.ok
    assert any("unexpected param" in e for e in rep.errors)


def test_template_missing_required_param_rejected():
    rep = cl.validate_correction(_corr(
        mechanism="rate_scale", fix_class="rate_rescale", template={"field": "interest_rate"}))
    assert not rep.ok
    assert any("missing required param" in e for e in rep.errors)


def test_numeric_param_must_be_number():
    rep = cl.validate_correction(_corr(
        mechanism="rate_scale", fix_class="rate_rescale",
        template={"field": "interest_rate", "factor": "ten"}))
    assert not rep.ok
    assert any("factor must be a number" in e for e in rep.errors)


def test_enum_param_checked():
    rep = cl.validate_correction(_corr(
        mechanism="rate_scale", fix_class="rate_rescale",
        template={"field": "made_up_field", "factor": 0.1}))
    assert not rep.ok
    assert any("template.field must be one of" in e for e in rep.errors)


def test_template_sql_value_rejected():
    rep = cl.validate_correction(_corr(
        fix_class="subtotal_filter",
        template={"patterns": ["DELETE FROM holdings WHERE 1=1"], "match_mode": "contains"}))
    assert not rep.ok
    assert any("code/SQL" in e for e in rep.errors)


def test_template_path_value_rejected():
    rep = cl.validate_correction(_corr(
        fix_class="subtotal_filter",
        template={"patterns": ["data/output/private_markets_holdings.csv"]}))
    assert not rep.ok
    assert any("file path" in e for e in rep.errors)


def test_benign_issuer_slash_not_flagged():
    # "A/B Corp" must NOT trip the path scanner (no extension / output path / drive).
    rep = cl.validate_correction(_corr(
        fix_class="subtotal_filter", template={"patterns": ["Total A/B Holdings"], "match_mode": "contains"}))
    assert rep.ok, rep.errors


def test_row_selector_unknown_key_rejected():
    rep = cl.validate_correction(_corr(
        mechanism="rate_scale", fix_class="rate_rescale",
        template={"field": "pik_rate", "factor": 1.0, "row_selector": {"made_up": "x"}}))
    assert not rep.ok
    assert any("row_selector has unknown key" in e for e in rep.errors)


def test_no_evidence_citation_rejected():
    rep = cl.validate_correction(_corr(evidence_citations=[]))
    assert not rep.ok
    assert any("evidence_citations" in e for e in rep.errors)


def test_empty_source_review_ids_rejected():
    rep = cl.validate_correction(_corr(source_review_ids=[]))
    assert not rep.ok


def test_confidence_out_of_range():
    assert not cl.validate_correction(_corr(confidence=1.5)).ok


def test_stage_mismatch_rejected():
    # dedup is stage 1; claiming stage 2 is an error.
    rep = cl.validate_correction(_corr(stage=2))
    assert not rep.ok
    assert any("stage" in e for e in rep.errors)


def test_stage_for_helper():
    assert cl.stage_for("dedup") == 1
    assert cl.stage_for("rate_rescale") == 2
    assert cl.stage_for("rule_scope") == 3
    assert cl.stage_for("nope") == 0


def test_missing_position_add_validates_positions():
    # 2026-08-13: positions REQUIRE grounding (source_row_id + bdc_dimensions_raw +
    # report_date) -- anti-fabrication parity with agent_rule row_add.
    ok = cl.validate_correction(_corr(
        mechanism="extraction_gap", fix_class="missing_position_add",
        template={"positions": [{"issuer_name": "Acme Term Loan", "fair_value": 1000.0,
                                 "report_date": "2025-12-31", "source_row_id": "SRC-1",
                                 "bdc_dimensions_raw": "investmentidentifieraxis=Acme"}]}))
    assert ok.ok, ok.errors
    bad = cl.validate_correction(_corr(
        mechanism="extraction_gap", fix_class="missing_position_add",
        template={"positions": [{"fair_value": 1000.0}]}))  # no issuer_name
    assert not bad.ok
    ungrounded = cl.validate_correction(_corr(
        mechanism="extraction_gap", fix_class="missing_position_add",
        template={"positions": [{"issuer_name": "Acme Term Loan", "fair_value": 1000.0,
                                 "report_date": "2025-12-31"}]}))  # no source_row_id
    assert not ungrounded.ok
    assert any("source_row_id" in e for e in ungrounded.errors)


def test_bad_cik_rejected():
    assert not cl.validate_correction(_corr(cik="not-a-cik")).ok


def test_expected_fix_class_rejected_on_mismatch():
    rep = cl.validate_correction(_corr(fix_class="subtotal_filter",
                                      template={"patterns": ["total investments"]}),
                                 expected_fix_class="comparative_period_filter")
    assert not rep.ok
    assert any("does not match expected" in e for e in rep.errors)


def test_non_object_rejected():
    assert not cl.validate_correction(["not", "a", "dict"]).ok


def test_validate_dir(tmp_path):
    (tmp_path / "0001950803").mkdir()
    (tmp_path / "0001950803" / "dimension_double_count.json").write_text(
        json.dumps(_corr()), encoding="utf-8")
    (tmp_path / "0001950803" / "bad.json").write_text(
        json.dumps(_corr(fix_class="nope", template={})), encoding="utf-8")
    summary = cl.validate_dir(tmp_path)
    assert summary["n_files"] == 2
    assert summary["n_valid"] == 1
    assert not summary["ok"]


def test_stage2_requires_explicit_quarter_scope():
    # 2026-08-13 blast-radius lesson: unscoped value fixes rewrote correct history.
    base = dict(mechanism="rate_scale_error", fix_class="rate_rescale",
                template={"field": "interest_rate", "factor": 100,
                          "row_selector": {"issuer_name": "Alpha Corp"}})
    no_scope = cl.validate_correction(_corr(**base))
    assert not no_scope.ok
    assert any("scope.quarters" in e for e in no_scope.errors)
    with_scope = cl.validate_correction(_corr(**base, scope={"quarters": ["2025-12-31"]}))
    assert with_scope.ok, with_scope.errors
    all_scope = cl.validate_correction(_corr(**base, scope={"quarters": ["all"]}))
    assert not all_scope.ok
    assert any("explicit YYYY-MM-DD" in e for e in all_scope.errors)


# --------------------------------------------------------------------------- 2026-08-21 row_id selector


def test_row_selector_row_id_alone_is_valid():
    rep = cl.validate_correction(_corr(
        mechanism="rate_scale", fix_class="rate_rescale",
        scope={"quarters": ["2025-12-31"]},
        template={"field": "interest_rate", "factor": 0.1,
                  "row_selector": {"row_id": "ROW-0123456789abcdef"}}))
    assert rep.ok, rep.errors


def test_row_selector_malformed_row_id_rejected():
    # A row_id that is not ROW-<16 hex> can only be a typo or fabrication and
    # would silently select nothing -- the screen must reject it, not the gate.
    rep = cl.validate_correction(_corr(
        mechanism="rate_scale", fix_class="rate_rescale",
        scope={"quarters": ["2025-12-31"]},
        template={"field": "interest_rate", "factor": 0.1,
                  "row_selector": {"row_id": "ROW-notahexstring"}}))
    assert not rep.ok
    assert any("row_id must match" in e for e in rep.errors)


def test_row_selector_row_id_counts_as_identity_key():
    # row_id satisfies the identity-key requirement previously limited to
    # issuer_name/bdc_investment_identifier.
    rep = cl.validate_correction(_corr(
        mechanism="rate_scale", fix_class="rate_rescale",
        scope={"quarters": ["2025-12-31"]},
        template={"field": "interest_rate", "factor": 0.1,
                  "row_selector": {"row_id": "ROW-00000000000000aa",
                                   "report_date": "2025-12-31"}}))
    assert rep.ok, rep.errors


# --- selector lists + dedup row_selector + escalation leaf (2026-08-21) -----------


def test_row_selector_list_accepted():
    # q4b2r4an lesson: a leaf may bind EVERY cited row via a list of selectors
    # (OR-combined) instead of widening scope to a whole quarter.
    rep = cl.validate_correction(_corr(
        mechanism="rate_scale", fix_class="rate_rescale",
        scope={"quarters": ["2025-12-31"]},
        template={"field": "interest_rate", "factor": 0.1,
                  "row_selector": [{"row_id": "ROW-00000000000000aa"},
                                   {"row_id": "ROW-00000000000000bb"}]}))
    assert rep.ok, rep.errors


def test_row_selector_list_with_bad_entry_rejected():
    rep = cl.validate_correction(_corr(
        mechanism="rate_scale", fix_class="rate_rescale",
        scope={"quarters": ["2025-12-31"]},
        template={"field": "interest_rate", "factor": 0.1,
                  "row_selector": [{"row_id": "ROW-00000000000000aa"},
                                   {"report_date": "2025-12-31"}]}))
    assert not rep.ok
    assert any("row_selector[1]" in e for e in rep.errors)


def test_row_selector_empty_list_rejected():
    rep = cl.validate_correction(_corr(
        mechanism="rate_scale", fix_class="rate_rescale",
        scope={"quarters": ["2025-12-31"]},
        template={"field": "interest_rate", "factor": 0.1, "row_selector": []}))
    assert not rep.ok
    assert any("non-empty" in e for e in rep.errors)


def test_dedup_row_selector_accepted():
    # The 563-group blast-radius fix: dedup may scope droppable rows to the
    # grounded row_ids.
    rep = cl.validate_correction(_corr(template={
        "match_fields": ["issuer_name", "interest_rate", "report_date"],
        "keep": "first",
        "row_selector": [{"row_id": "ROW-00000000000000aa"},
                         {"row_id": "ROW-00000000000000bb"}]}))
    assert rep.ok, rep.errors


def _esc(**over):
    base = {
        "cik": "0001838126",
        "mechanism": "unit_scale",
        "fix_class": "unit_rescale",
        "diagnosis": "Filing NAV-per-share is 25.22; extracted fund-financials "
                     "nav_per_share is 1000.0. The defect is in fund financials, not "
                     "holdings; no unit_rescale field can express it.",
        "suggested_fix_class": "fund_financials_value_fix",
        "evidence_citations": [{"table_index": 54, "row_index": 6,
                                "quoted_text": "Net asset value per share | $ | 25.22"}],
        "confidence": 0.85,
        "rationale": "verified against staged holdings CSV and review bundle",
    }
    base.update(over)
    return base


def test_valid_escalation_leaf():
    rep = cl.validate_escalation(_esc(), expected_cik="0001838126",
                                 expected_fix_class="unit_rescale")
    assert rep.ok, rep.errors


def test_escalation_keeps_binding_fix_class():
    rep = cl.validate_escalation(_esc(fix_class="fund_financials_value_fix"),
                                 expected_fix_class="unit_rescale")
    assert not rep.ok
    assert any("requested class" in e for e in rep.errors)


def test_escalation_requires_substantive_diagnosis():
    rep = cl.validate_escalation(_esc(diagnosis="cannot fix"))
    assert not rep.ok
    assert any("diagnosis" in e for e in rep.errors)


def test_escalation_requires_citation():
    rep = cl.validate_escalation(_esc(evidence_citations=[]))
    assert not rep.ok
    assert any("evidence_citations" in e for e in rep.errors)


def test_validate_dir_skips_escalation_files(tmp_path):
    d = tmp_path / "corr" / "0001838126"
    d.mkdir(parents=True)
    (d / "dedup.json").write_text(json.dumps(_corr()), encoding="utf-8")
    (d / "unit_rescale.escalation.json").write_text(json.dumps(_esc()), encoding="utf-8")
    summary = cl.validate_dir(tmp_path / "corr")
    assert summary["n_files"] == 1          # the escalation is not a correction
    assert summary["ok"]


# --- identifier_rate_grammar (stage 3, rule_track) --------------------------------


def test_valid_identifier_rate_grammar_proposal():
    rep = cl.validate_correction(_corr(
        mechanism="rate_scale", fix_class="identifier_rate_grammar",
        template={"dialect_example": "Fixed + 1600",
                  "target_field": "interest_rate",
                  "observed_value": 1.6,
                  "expected_semantics": "spread in bps over the stated base"}))
    assert rep.ok, rep.errors


def test_identifier_rate_grammar_minimal_params_ok():
    rep = cl.validate_correction(_corr(
        mechanism="rate_scale", fix_class="identifier_rate_grammar",
        template={"dialect_example": "SOFR + 750", "target_field": "basis_spread"}))
    assert rep.ok, rep.errors


def test_identifier_rate_grammar_requires_dialect_example():
    rep = cl.validate_correction(_corr(
        mechanism="rate_scale", fix_class="identifier_rate_grammar",
        template={"target_field": "interest_rate"}))
    assert not rep.ok
    assert any("missing required param" in e for e in rep.errors)


def test_identifier_rate_grammar_target_field_enum_checked():
    rep = cl.validate_correction(_corr(
        mechanism="rate_scale", fix_class="identifier_rate_grammar",
        template={"dialect_example": "Fixed + 1600", "target_field": "spread"}))
    assert not rep.ok
    assert any("target_field" in e for e in rep.errors)


def test_identifier_rate_grammar_is_stage_3():
    assert cl.stage_for("identifier_rate_grammar") == 3


def test_identifier_rate_grammar_no_quarter_scope_required():
    # Stage-3 proposals are config-track, not scoped value fixes.
    rep = cl.validate_correction(_corr(
        mechanism="rate_scale", fix_class="identifier_rate_grammar",
        template={"dialect_example": "Fixed + 1600", "target_field": "interest_rate"}))
    assert rep.ok, rep.errors


# --- layer_exclusion (row provenance spec, 2026-08-30) ---------------------------------

def _le(**over):
    base = _corr(
        mechanism="dimension_double_count", fix_class="layer_exclusion",
        template={"scope_quarters": ["2026-03-31"],
                  "selector": {"axis_profile": "investmentidentifieraxis",
                               "source_table": None, "is_subsidiary": None},
                  "anchor_proof": {"kind": "named_anchor_gap", "cited_value": 1580000000.0,
                                   "tolerance_pct": 0.5,
                                   "citation": "companyfacts fv gap 2026-03-31"}})
    base.update(over)
    return base


def test_valid_layer_exclusion_leaf():
    rep = cl.validate_correction(_le())
    assert rep.ok, rep.errors


def test_layer_exclusion_selector_outside_whitelist_rejected():
    t = _le()["template"]
    t["selector"] = {"issuer_name": "JV Feeder LLC"}
    rep = cl.validate_correction(_le(template=t))
    assert not rep.ok
    assert any("selector" in e for e in rep.errors)


def test_layer_exclusion_requires_anchor_proof_and_scope():
    t = _le()["template"]
    del t["anchor_proof"]
    rep = cl.validate_correction(_le(template=t))
    assert not rep.ok
    t2 = _le()["template"]
    t2["scope_quarters"] = []
    rep2 = cl.validate_correction(_le(template=t2))
    assert not rep2.ok


def test_layer_exclusion_anchor_proof_shape_checked():
    t = _le()["template"]
    t["anchor_proof"] = {"kind": "filing_table", "cited_value": "lots",
                         "citation": ""}
    rep = cl.validate_correction(_le(template=t))
    assert not rep.ok
    assert any("cited_value" in e or "anchor_proof" in e for e in rep.errors)
