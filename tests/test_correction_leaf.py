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
        template={"field": "interest_rate", "factor": 0.1,
                  "row_selector": {"issuer_name": "InFarm Technologies Limited"}}))
    assert rep.ok, rep.errors


def test_valid_all_pik_normalization():
    rep = cl.validate_correction(_corr(
        mechanism="genuine_value_defect", fix_class="all_pik_normalization",
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
