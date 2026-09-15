"""Regressions for malformed promoted classifications and added-row identity."""
import json

import pandas as pd
import pytest

from pipeline import agent_promoted, rule_admission
from pipeline.agent_b2_appliers import apply_classification_fix
from pipeline.correction_leaf import validate_correction


def leaf(field, value):
    return dict(cik="123", mechanism="extraction_gap", fix_class="classification_fix",
        template=dict(field=field, value=value, row_selector={"issuer_name": "Loan"}),
        scope={"quarters": ["2025-12-31"]}, source_review_ids=["review-1"],
        evidence_citations=[dict(table_index=1, row_index=2, quoted_text="Loan")],
        confidence=.8)


@pytest.mark.parametrize("field,value", [
    ("asset_class", "Debt"), ("asset_class", "debt"),
    ("index_classification", "SOFR"), ("index_classification", "Non-accrual"),
    ("exposure_type", "Senior Secured First Lien Loans"),
    ("exposure_type", "lookthrough"), ("exposure_type", "INDIRECT"),
    ("asset_class", "CASH_EQUIVALENT"), ("asset_class", ["PRIVATE_CREDIT"]),
])
def test_wrong_field_vocabulary_rejected_before_any_assignment(field, value):
    correction = leaf(field, value)
    report = validate_correction(correction)
    assert not report.ok
    assert any("not valid for" in error for error in report.errors)
    frame = pd.DataFrame([
        dict(issuer_name="Loan", asset_class="PRIVATE_CREDIT", exposure_type="DIRECT",
             index_classification="DIRECT_LENDING", fair_value=100),
        dict(issuer_name="Cash", asset_class="CASH", exposure_type="LIQUID",
             index_classification="CASH", fair_value=20),
    ])
    before = frame.copy(deep=True)
    result, audit = apply_classification_fix(frame, correction["template"])
    pd.testing.assert_frame_equal(result, before)
    assert audit["status"] == "error" and audit["rows_changed"] == 0


@pytest.mark.parametrize("field,value", [
    ("asset_class", "PRIVATE_CREDIT"), ("asset_class", "PRIVATE_EQUITY"),
    ("asset_class", "CASH"), ("asset_class", "OTHER"),
    ("index_classification", "DIRECT_LENDING"), ("index_classification", "UNCLASSIFIED"),
    ("index_classification", "CASH"), ("exposure_type", "DIRECT"),
    ("exposure_type", "FUND"), ("exposure_type", "LIQUID"),
])
def test_valid_column_values_remain_admissible(field, value):
    report = validate_correction(leaf(field, value))
    assert report.ok, report.errors


def test_loader_retains_rejection_identity_and_valid_correction(tmp_path):
    base = tmp_path / "corrections"
    folder = base / "123"
    folder.mkdir(parents=True)
    invalid = folder / "invalid.json"
    invalid.write_text(json.dumps(leaf("index_classification", "SOFR")))
    valid = folder / "valid.json"
    valid.write_text(json.dumps(leaf("index_classification", "DIRECT_LENDING")))

    @rule_admission.capture_inputs(lambda: tmp_path / "audit")
    def load():
        loaded = agent_promoted.load_promoted_corrections(base)
        assert len(loaded) == 1
        assert loaded[0]["template"]["value"] == "DIRECT_LENDING"
        return pd.DataFrame()

    load()
    audit = pd.read_csv(tmp_path / "audit/input_admission_audit.csv").set_index("path")
    assert audit.loc[str(invalid), "admission_status"] == "rejected_contract"
    assert not audit.loc[str(invalid), "loaded"]
    assert "legacy_unverified" in audit.loc[str(invalid), "reason"]
    assert audit.loc[str(valid), "loaded"]
    assert audit.loc[str(valid), "admission_status"] == "legacy_unverified"
    assert invalid.is_file() and valid.is_file()


def source_frame():
    return pd.DataFrame([
        dict(cik="0000000123", source="bdc", report_date="2025-12-31",
             entity_name="Fund A", issuer_name="Existing", fair_value=100,
             bdc_dimensions_raw="investmentidentifieraxis=Existing"),
        dict(cik="0000000123", source="nport", report_date="2025-12-31",
             entity_name="Fund A", issuer_name="NPORT control", fair_value=200,
             bdc_dimensions_raw=None),
    ])


def add_rule(**position_identity):
    position = dict(report_date="2025-12-31", issuer_name="Recovered", fair_value=745000,
        bdc_dimensions_raw="investmentidentifieraxis=Recovered", source_row_id="staging row 17")
    position.update(position_identity)
    return dict(cik="123", rule_id="recover", rule_type="row_add", action="add",
        scope={"quarters": ["2025-12-31"]}, positions=[position],
        evidence=[dict(source="filing", quote="Recovered")],
        rationale="Recover the identified source observation", confidence=.9)


@pytest.mark.parametrize("identity", [{}, {"cik": "123"}, {"cik": "0000000123"},
                                      {"cik": "123", "source": ""}])
def test_added_position_with_supplied_cik_still_inherits_bdc_source(identity):
    frame = source_frame()
    result, audits = agent_promoted.apply_promoted_rules(frame, {"0000000123": [add_rule(**identity)]})
    added = result.loc[result.issuer_name == "Recovered"].iloc[0]
    assert added.cik == "0000000123" and added.source == "bdc"
    assert added.entity_name == "Fund A"
    assert added.fair_value == 745000
    assert audits[0]["status"] == "ok" and audits[0]["rows_changed"] == 1
    control = result.loc[result.issuer_name == "NPORT control"].iloc[0]
    assert control.source == "nport" and control.fair_value == 200


@pytest.mark.parametrize("identity,error", [
    ({"cik": "456"}, "CIK conflicts"),
    ({"cik": "123", "source": "nport"}, "source conflicts"),
])
def test_added_position_cannot_override_rule_scope(identity, error):
    with pytest.raises(ValueError, match=error):
        agent_promoted.apply_promoted_rules(source_frame(), {"0000000123": [add_rule(**identity)]})
