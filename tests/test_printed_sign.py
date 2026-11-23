"""Cost and fair value take the printed bracket sign in filings a wrapper lists (pipeline/printed_sign.py)."""
import json

import pytest

from pipeline import printed_sign

CIK = "0001766037"
ACC = "0001766037-26-000009"


def _fact(name, ctx, value, sign=False):
    attr = ' sign="-"' if sign else ""
    return ('<ix:nonFraction name="us-gaap:%s" contextRef="%s" unitRef="usd" decimals="-3" scale="3"'
            ' format="ixt:num-dot-decimal"%s>%s</ix:nonFraction>' % (name, ctx, attr, value))


def _row(cells):
    return "<tr>" + "".join("<td><span>%s</span></td>" % c for c in cells) + "</tr>"


PAGE = "<html><body><table>" + "".join([
    # undrawn line printed in brackets, tagged with no sign (the defect)
    _row(["DigiCert, Inc.", "First Lien(3)(4) - Undrawn", "512",
          "(" + _fact("InvestmentOwnedAtCost", "c-463", "3") + ")",
          "(" + _fact("InvestmentOwnedAtFairValue", "c-463", "4") + ")"]),
    # printed positive and tagged negative (the other direction)
    _row(["OEConnection LLC", "First Lien(4) - Undrawn", "$ 1,847", "$ -",
          "$ " + _fact("InvestmentOwnedAtFairValue", "c-391", "3", sign=True)]),
    # a funded loan, printed positive and tagged positive: untouched
    _row(["Anaplan, Inc.", "First Lien", "29,514", _fact("InvestmentOwnedAtCost", "c-10", "29,392"),
          _fact("InvestmentOwnedAtFairValue", "c-10", "28,942")]),
    # printed in brackets and tagged negative: already right, untouched
    _row(["Bonterra LLC", "First Lien - Undrawn", "525",
          "(" + _fact("InvestmentOwnedAtCost", "c-20", "1", sign=True) + ")",
          "(" + _fact("InvestmentOwnedAtFairValue", "c-20", "10", sign=True) + ")"]),
]) + "</table></body></html>"


def _records():
    return {
        "c-463": {"_context_id": "c-463", "cost": 3000.0, "fair_value": 4000.0, "src_facts": ""},
        "c-391": {"_context_id": "c-391", "cost": None, "fair_value": -3000.0, "src_facts": ""},
        "c-10": {"_context_id": "c-10", "cost": 29392000.0, "fair_value": 28942000.0, "src_facts": ""},
        "c-20": {"_context_id": "c-20", "cost": -1000.0, "fair_value": -10000.0, "src_facts": ""},
    }


@pytest.fixture
def page_dir(tmp_path, monkeypatch):
    folder = tmp_path / CIK.lstrip("0")
    folder.mkdir()
    (folder / (ACC.replace("-", "") + ".html")).write_text(PAGE, encoding="utf-8")
    monkeypatch.setattr(printed_sign, "_listed", lambda: {CIK: frozenset([ACC])})
    return tmp_path


def test_bracketed_unsigned_values_take_the_printed_sign(page_dir):
    records = _records()
    changed = printed_sign.apply_printed_signs(records, {"cik": CIK, "accession_number": ACC}, html_cache_dir=page_dir)
    assert changed == 3
    assert records["c-463"]["cost"] == -3000.0 and records["c-463"]["fair_value"] == -4000.0
    assert records["c-391"]["fair_value"] == 3000.0
    facts = json.loads(records["c-463"]["src_facts"])
    assert facts["fair_value"] == {"r": 4000.0, "x": [printed_sign.SIGN_EVENT]}


def test_source_reading_takes_the_sign_without_events(page_dir):
    records = {"c-463": {"cost": 3000.0, "fair_value": 4000.0}}
    printed_sign.apply_printed_signs(records, {"cik": CIK, "accession_number": ACC}, html_cache_dir=page_dir,
                                     record_events=False)
    assert records == {"c-463": {"cost": -3000.0, "fair_value": -4000.0}}


def test_rows_whose_tag_agrees_with_the_page_are_untouched(page_dir):
    records = _records()
    printed_sign.apply_printed_signs(records, {"cik": CIK, "accession_number": ACC}, html_cache_dir=page_dir)
    assert records["c-10"] == _records()["c-10"]
    assert records["c-20"] == _records()["c-20"]


def test_unlisted_filing_or_fund_changes_nothing(page_dir):
    records = _records()
    assert printed_sign.apply_printed_signs(records, {"cik": CIK, "accession_number": "0001766037-25-000018"},
                                            html_cache_dir=page_dir) == 0
    assert printed_sign.apply_printed_signs(records, {"cik": "0001925531", "accession_number": ACC},
                                            html_cache_dir=page_dir) == 0
    assert records == _records()


def test_magnitude_must_match_the_record(page_dir):
    records = _records()
    records["c-463"]["fair_value"] = 4500.0  # a value the page does not print for this context
    printed_sign.apply_printed_signs(records, {"cik": CIK, "accession_number": ACC}, html_cache_dir=page_dir)
    assert records["c-463"]["fair_value"] == 4500.0


@pytest.mark.needs_cache
def test_gs_private_credit_2024q3_flips_only_esperanto_cost():
    """GS Private Credit Corp. 10-Q 2024-09-30 prints Esperanto BidCo's undrawn CHF line
    'CHF 24,087 $ ( 407 ) $ ( 249 )' and tags the cost +407 with no sign. Listing the filing flips
    that one fact (Total Switzerland cost 20,602 = -407 + 10,530 + 7,507 + 2,972) and no other."""
    from pathlib import Path
    from pipeline.config import BDC_HTML_CACHE_DIR
    printed_sign._listed.cache_clear()
    acc = "0000950170-24-126294"
    assert acc in printed_sign.listed_accessions("0001920145")
    page = Path(BDC_HTML_CACHE_DIR) / "1920145" / (acc.replace("-", "") + ".html")
    found = printed_sign.printed_signs(page.read_text(encoding="utf-8", errors="replace"))
    mismatched = [(ctx, col, m) for (ctx, col), facts in found.items() for m, b, s in facts if b != s and m]
    assert mismatched == [("C_5e13e8a0-d85f-466f-b867-855dc7713293", "cost", 407000.0)]
    records = {"C_5e13e8a0-d85f-466f-b867-855dc7713293": {"cost": 407000.0, "fair_value": -249000.0}}
    assert printed_sign.apply_printed_signs(records, {"cik": "0001920145", "accession_number": acc},
                                            record_events=False) == 1
    assert records["C_5e13e8a0-d85f-466f-b867-855dc7713293"] == {"cost": -407000.0, "fair_value": -249000.0}


def test_reverifier_multiplier_reads_the_event():
    from pipeline.provenance_reverify import _extractor_multiplier
    assert _extractor_multiplier([printed_sign.SIGN_EVENT]) == -1.0


def test_loader_rejects_a_non_accession(tmp_path):
    from pipeline.source_encodings import load_encodings
    wrapper = {"schema_version": "bdc-xbrl-wrapper.v3", "cik": CIK, "source_encodings": {"bracketed_unsigned_values": ["2026-03-31"]}}
    (tmp_path / (CIK + ".json")).write_text(json.dumps(wrapper), encoding="utf-8")
    with pytest.raises(ValueError):
        load_encodings(tmp_path)
    wrapper["source_encodings"]["bracketed_unsigned_values"] = [ACC]
    (tmp_path / (CIK + ".json")).write_text(json.dumps(wrapper), encoding="utf-8")
    assert load_encodings(tmp_path)[CIK]["bracketed_unsigned_values"] == [ACC]
