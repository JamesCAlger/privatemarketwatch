"""The owner-approved X11 repair requires exact observation and page evidence."""
import copy
import hashlib
import html
import json

import pandas as pd
import pytest

from pipeline import source_unit_loans as units
from pipeline.column_validation import validate_column_contracts
from tests.test_column_validation import _make_unified_df


@pytest.fixture
def evidence(tmp_path, monkeypatch):
    document = json.loads(units.EVIDENCE_FILE.read_text(encoding="utf-8"))
    cache = tmp_path / "pages"
    paths = []
    for entry in document["entries"]:
        path = cache / str(int(entry["cik"])) / (entry["accession_number"].replace("-", "") + ".html")
        path.parent.mkdir(parents=True, exist_ok=True)
        page = ('<html><table><tr><td><ix:nonfraction contextRef="' + entry["src_context_id"]
                + '">' + html.escape(entry["quote"]) + '</ix:nonfraction></td></tr></table></html>').encode()
        path.write_bytes(page)
        entry["page_sha256"] = hashlib.sha256(page).hexdigest()
        paths.append(path)
    file = tmp_path / "evidence.json"
    file.write_text(json.dumps(document), encoding="utf-8")
    monkeypatch.setattr(units, "EVIDENCE_FILE", file)
    monkeypatch.setattr(units.config, "BDC_HTML_CACHE_DIR", cache)
    return document, file, paths


def row(entry):
    return {**{name: entry[name] for name in units.IDENTITY + units.TEXT + units.VALUES},
            "source": "bdc", "asset_category": "LOAN", "principal_amount": "", "src_facts": "{}"}


def x11(frame):
    issues, _ = validate_column_contracts(frame)
    return issues[issues.rule_id.eq("X11")]


@pytest.mark.parametrize("number", [0, 1, 2])
def test_three_approved_printed_unit_loans_clear_only_their_x11(evidence, number):
    document, _, _ = evidence
    frame = _make_unified_df([row(document["entries"][number])])
    original = frame.copy(deep=True)
    assert x11(frame).empty
    pd.testing.assert_frame_equal(frame, original)


@pytest.mark.parametrize("change", [
    {"cik": "0001838126"}, {"report_date": "2025-09-30"},
    {"accession_number": "0001918712-25-000066"}, {"src_context_id": "c-1013"},
    {"row_id": "ROW-nearby-same-issuer"}, {"issuer_name": "Other Funding LLC"},
    {"instrument_description": "First Lien Loan"}, {"shares_held": 5301},
    {"cost": 5851301}, {"fair_value": 6115901}, {"src_facts": "invalid"},
    {"src_facts": '{"principal_amount":{"r":5300}}'},
])
def test_wrong_identity_values_or_principal_evidence_still_fires(evidence, change):
    document, _, _ = evidence
    frame = _make_unified_df([{**row(document["entries"][0]), **change}])
    assert len(x11(frame)) == 1


def test_timestamp_date_is_the_same_exact_quarter(evidence):
    document, _, _ = evidence
    frame = _make_unified_df([{**row(document["entries"][0]), "report_date": pd.Timestamp("2025-06-30")}])
    assert x11(frame).empty


@pytest.mark.parametrize("failure", ["missing_page", "changed_page", "wrong_quote", "wrong_context_row",
                                      "missing_metadata", "duplicate_metadata", "wrong_quantity"])
def test_missing_stale_or_unbound_source_fails_closed(evidence, failure):
    document, file, paths = evidence
    frame = _make_unified_df([row(document["entries"][0])])
    if failure == "missing_page":
        paths[0].unlink()
    elif failure == "changed_page":
        paths[0].write_bytes(paths[0].read_bytes() + b"<!-- changed source -->")
    elif failure == "wrong_quote":
        document["entries"][0]["quote"] = "CFC Funding LLC Loan instrument units 5,300 wrong amounts"
        file.write_text(json.dumps(document), encoding="utf-8")
    elif failure == "wrong_context_row":
        entry = document["entries"][0]
        page = ('<html><p>' + html.escape(entry["quote"]) + '</p><table><tr><td contextref="'
                + entry["src_context_id"] + '">Other borrower monetary par 5,300</td></tr></table></html>').encode()
        paths[0].write_bytes(page)
        entry["page_sha256"] = hashlib.sha256(page).hexdigest()
        file.write_text(json.dumps(document), encoding="utf-8")
    elif failure == "missing_metadata":
        file.unlink()
    elif failure == "duplicate_metadata":
        document["entries"] = [document["entries"][0], copy.deepcopy(document["entries"][0])]
        file.write_text(json.dumps(document), encoding="utf-8")
    elif failure == "wrong_quantity":
        document["entries"][0]["shares_held"] = 5301
        file.write_text(json.dumps(document), encoding="utf-8")
    assert len(x11(frame)) == 1


def test_real_missing_principal_and_hps_units_as_par_remain_findings(evidence):
    document, _, _ = evidence
    frame = _make_unified_df([
        {**row(document["entries"][0]), "src_context_id": "c-generic", "shares_held": ""},
        {**row(document["entries"][0]), "cik": "0001838126", "fair_value": 443558000,
         "shares_held": 439167000},
    ])
    assert len(x11(frame)) == 2
