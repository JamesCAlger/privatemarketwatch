"""ARES-VERIFY-PRINTED-RATES-001: direct source facts, never declared output values."""
import json
from pathlib import Path

import pandas as pd
import pytest
from lxml import etree

from pipeline import rate_verification_anchors as anchors
from pipeline.provenance_reverify import full_tier
from pipeline.source_encodings import load_encodings

CIK = "0001287750"
ACCESSION = "0001287750-23-000010"
CONTEXT = "i78933030503f48999e7a3beee50b881e_I20221231"
QUOTE = "First lien senior secured loan 13.23 % ( 2.00 % PIK)"


def entry(**updates):
    return dict({
        "accession": ACCESSION, "context": CONTEXT, "field": "interest_rate",
        "source_context": CONTEXT, "source_concept": "InvestmentInterestRatePaidInKind",
        "source_units": "fraction", "evidence": QUOTE,
    }, **updates)


def xml(source_context=CONTEXT, duplicate=False, include_source=True):
    # Cadence's actual concept inversion: total coupon in PaidInKind, PIK in plain rate.
    facts = (
        f'<g:InvestmentOwnedAtFairValue contextRef="{CONTEXT}">7600000</g:InvestmentOwnedAtFairValue>'
        f'<g:InvestmentInterestRate contextRef="{CONTEXT}">0.02</g:InvestmentInterestRate>'
    )
    if include_source:
        facts += f'<g:InvestmentInterestRatePaidInKind contextRef="{source_context}">0.1323</g:InvestmentInterestRatePaidInKind>'
    if duplicate:
        facts += f'<g:InvestmentInterestRatePaidInKind contextRef="{source_context}">0.14</g:InvestmentInterestRatePaidInKind>'
    return etree.ElementTree(etree.fromstring(('<xbrl xmlns:g="urn:test">' + facts + '</xbrl>').encode()))


def check(monkeypatch, declaration=None, tree=None, **updates):
    declaration = declaration or entry()
    monkeypatch.setattr(anchors, "load_anchors", lambda: {
        (CIK, ACCESSION, CONTEXT, declaration["field"]): declaration,
    })
    row = dict(
        row_id="ROW-d7562d98dc90994b", cik=CIK, accession_number=ACCESSION,
        src_context_id=CONTEXT, field="interest_rate", published=13.23,
        declared_raw=0.1323, cheap_status="fail", src_facts="{}",
        declared_events="interest_rate:pik_only;interest_rate:cash_plus_pik;interest_rate:rate_x100",
    )
    row.update(updates)
    result = full_tier(pd.DataFrame([row]), xml_loader=lambda c, a: tree if tree is not None else xml())
    return result.iloc[0]


@pytest.mark.parametrize("published,status", [
    (13.23, "raw_match"), (2.0, "published_mismatch"),
    (15.23, "published_mismatch"), (0.1323, "published_mismatch"),
])
def test_swapped_source_concept_verifies_only_printed_total(monkeypatch, published, status):
    assert check(monkeypatch, published=published).full_status == status


def test_component_and_total_are_separate_source_facts(monkeypatch):
    result = check(monkeypatch, entry(field="pik_rate", source_concept="InvestmentInterestRate"),
                   field="pik_rate", published=2.0, declared_raw=0.02)
    assert result.full_status == "raw_match"
    assert check(monkeypatch, entry(field="pik_rate", source_concept="InvestmentInterestRate"),
                 field="pik_rate", published=13.23).full_status == "published_mismatch"


def test_exact_adjacent_context_is_read_and_wrong_context_fails(monkeypatch):
    assert check(monkeypatch, entry(source_context="rate-only"),
                 tree=xml(source_context="rate-only")).full_status == "raw_match"
    assert check(monkeypatch, entry(source_context="wrong-context")).full_status == "anchor_missing"


def test_missing_or_conflicting_fact_never_uses_output_as_evidence(monkeypatch):
    assert check(monkeypatch, tree=xml(include_source=False)).full_status == "anchor_missing"
    assert check(monkeypatch, tree=xml(duplicate=True)).full_status == "source_unavailable"


def test_unlisted_filing_or_fund_retains_original_verification(monkeypatch):
    assert check(monkeypatch, accession_number="0001287750-23-000011",
                 declared_events="", published=13.23).full_status == "published_mismatch"
    assert check(monkeypatch, cik="0001803498",
                 declared_events="", published=13.23).full_status == "published_mismatch"


def test_stale_raw_metadata_is_not_silently_declared_verified(monkeypatch):
    assert check(monkeypatch, declared_raw=0.02).full_status == "raw_stale"


def test_loader_and_schema_validate_exact_coordinates(tmp_path):
    wrapper = {"cik": CIK, "schema_version": "bdc-xbrl-wrapper.v3",
               "source_encodings": {"rate_verification_anchors": [entry()]}}
    path = tmp_path / (CIK + ".json")
    path.write_text(json.dumps(wrapper))
    assert load_encodings(tmp_path)[CIK]["rate_verification_anchors"] == [entry()]
    import jsonschema
    schema = json.loads(Path("schemas/bdc_xbrl_wrapper/wrapper_v3.schema.json").read_text())
    jsonschema.validate(wrapper["source_encodings"]["rate_verification_anchors"],
                        schema["properties"]["source_encodings"]["properties"]["rate_verification_anchors"])


@pytest.mark.parametrize("update", [
    {"source_units": "percentage_points"}, {"value": 13.23},
    {"field": "fair_value"}, {"source_concept": "InvestmentOwnedAtFairValue"},
    {"source_context": "two contexts"}, {"evidence": ""},
])
def test_invalid_or_value_based_declarations_rejected(tmp_path, update):
    wrapper = {"cik": CIK, "schema_version": "bdc-xbrl-wrapper.v3",
               "source_encodings": {"rate_verification_anchors": [entry(**update)]}}
    (tmp_path / (CIK + ".json")).write_text(json.dumps(wrapper))
    with pytest.raises(ValueError, match="Invalid rate verification anchor"):
        load_encodings(tmp_path)


def test_duplicate_target_cannot_select_conflicting_anchors(tmp_path):
    wrapper = {"cik": CIK, "schema_version": "bdc-xbrl-wrapper.v3",
               "source_encodings": {"rate_verification_anchors": [
                   entry(), entry(source_context="other"),
               ]}}
    (tmp_path / (CIK + ".json")).write_text(json.dumps(wrapper))
    with pytest.raises(ValueError, match="Duplicate rate verification anchor"):
        load_encodings(tmp_path)
