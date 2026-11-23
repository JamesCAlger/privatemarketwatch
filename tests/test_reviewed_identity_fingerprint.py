import pandas as pd

from pipeline import reviewed_position_identity as reviewed
from pipeline.holdings_finalizer import _identity_input_fingerprint


CIK = "0001918712"
ACC = "0001918712-25-000001"


def test_config_only_reviewed_identity_change_changes_release_digest(monkeypatch):
    holdings = pd.DataFrame(dict(cik=[CIK], source=["bdc"]))
    inputs = {"working_sha256": "unchanged-prepared-csv", "raw_matching_sha256": "unchanged-raw"}
    config = {CIK: {"position_identity_contexts": [f"{ACC} c-1 => loan"]}}
    monkeypatch.setattr(reviewed, "load_encodings", lambda: config)
    before = _identity_input_fingerprint(holdings, inputs)
    config[CIK]["position_identity_contexts"] = [f"{ACC} c-1 => warrant"]
    after = _identity_input_fingerprint(holdings, inputs)
    assert before != after
    assert "holdings-" + before != "holdings-" + after
    assert inputs == {"working_sha256": "unchanged-prepared-csv", "raw_matching_sha256": "unchanged-raw"}


def test_inactive_fund_config_and_declaration_order_do_not_change_digest(monkeypatch):
    holdings = pd.DataFrame(dict(cik=[CIK, "123"], source=["bdc", "nport"]))
    declarations = [f"{ACC} c-1 => loan", f"{ACC} c-2 => warrant"]
    config = {CIK: {"position_identity_contexts": declarations.copy()}}
    monkeypatch.setattr(reviewed, "load_encodings", lambda: config)
    before = _identity_input_fingerprint(holdings, {"working_sha256": "same"})
    config[CIK]["position_identity_contexts"].reverse()
    config["0000000123"] = {"position_identity_contexts": [f"{ACC} c-1 => inactive"]}
    assert _identity_input_fingerprint(holdings, {"working_sha256": "same"}) == before
    assert _identity_input_fingerprint(holdings.iloc[::-1], {"working_sha256": "same"}) == before


def test_adding_first_active_mapping_changes_digest(monkeypatch):
    holdings = pd.DataFrame(dict(cik=[1918712], source=["bdc"]))
    config = {}
    monkeypatch.setattr(reviewed, "load_encodings", lambda: config)
    before = _identity_input_fingerprint(holdings, {})
    config[CIK] = {"position_identity_contexts": [f"{ACC} c-1 => loan"]}
    assert _identity_input_fingerprint(holdings, {}) != before
