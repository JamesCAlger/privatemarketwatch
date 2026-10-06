"""Blue Owl Credit Income (CIK 1812554): commitment total lines are aggregates.

The wrapper lists 'total portfolio company commitments' as an aggregate marker, but a line with no
instrument word matched no family, so the marker never applied and the reconciliation read the
line as a missing position (2024-12-31 to 2026-03-31, -9.8M to -33.8M). Real filing identifiers.
"""
import pytest

from pipeline.bdc_xbrl_wrapper import classify_identifier

CIK = "0001812554"


@pytest.mark.parametrize("identifier", [
    "Total Portfolio Company Commitments",
    "Total non-controlled/non-affiliated - debt commitments",
    "Total non-controlled/affiliated - debt commitments",
])
def test_commitment_totals_are_not_positions(identifier):
    disposition = classify_identifier(CIK, identifier)["wrapper_disposition"]
    assert disposition == "aggregate" or disposition.endswith("_total_rollup")


@pytest.mark.parametrize("identifier,family", [
    ("Notorious Topco, LLC (dba Beauty Industry Group) | First lien senior secured revolving loan", "debt"),
    ("LSI Financing LLC | Specialty finance equity investment", "specialty_finance"),
])
def test_positions_keep_their_leaf_disposition(identifier, family):
    assert classify_identifier(CIK, identifier)["wrapper_disposition"] == family + "_position_leaf"
