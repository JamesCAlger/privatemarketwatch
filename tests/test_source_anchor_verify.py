"""Tests for source_anchored_value verification (synthetic filing + holdings)."""

from __future__ import annotations

import pandas as pd

from pipeline import source_anchor_verify as sav
from pipeline.correction_leaf import validate_correction

_ACCESSION = "0001628280-26-020206"

# A parsed-table-friendly synthetic filing: table 0 is the SOI slice. The AAM row's
# rate cell (index 2) shows 12.00 % which extraction misplaced into pik_rate; the
# principal/cost/fair-value cells are the row fingerprint (table in thousands).
_HTML = """
<html><body>
<table>
<tr><td>Company</td><td>Investment</td><td>Rate</td><td>Principal</td><td>Cost</td><td>Fair Value</td></tr>
<tr><td>AAM Series 1.1</td><td>First lien</td><td>12.00 %</td><td>58,702</td><td>58,650</td><td>58,702</td></tr>
<tr><td>Other Co</td><td>Loan</td><td>9.00 %</td><td>1,000</td><td>990</td><td>995</td></tr>
</table>
</body></html>
"""


def _holdings():
    return pd.DataFrame([
        {"cik": "0001812554", "row_id": "ROW-00000000000000aa",
         "issuer_name": "AAM Series 1.1", "report_date": "2025-12-31",
         "interest_rate": None, "pik_rate": 12.0,
         "principal_amount": 58702000.0, "cost": 58650000.0, "fair_value": 58702000.0},
        {"cik": "0001812554", "row_id": "ROW-00000000000000bb",
         "issuer_name": "Other Co", "report_date": "2025-12-31",
         "interest_rate": 9.0, "pik_rate": None,
         "principal_amount": 1000000.0, "cost": 990000.0, "fair_value": 995000.0},
    ])


def _leaf(**over):
    base = {
        "cik": "0001812554",
        "mechanism": "extraction_gap",
        "fix_class": "source_anchored_value",
        "scope": {"quarters": ["2025-12-31"]},
        "template": {"assertions": [{
            "row_selector": {"row_id": "ROW-00000000000000aa"},
            "field": "interest_rate",
            "source": {"accession_number": _ACCESSION, "table_index": 0,
                       "row_index": 1, "cell_index": 2,
                       "quoted_text": "12.00 %", "value": 12.00,
                       "unit_multiplier": 1},
            "witnesses": [
                {"cell_index": 3, "field": "principal_amount", "value": 58702},
                {"cell_index": 5, "field": "fair_value", "value": 58702},
            ],
        }]},
        "source_review_ids": ["RVQ_REV_07746b753ad5"],
        "evidence_citations": [{"table_index": 89, "row_index": 47,
                                "quoted_text": "AAM Series 1.1 | ... | 12.00 %"}],
        "confidence": 0.8,
        "rationale": "filing shows 12.00 cash rate, extracted interest_rate blank",
    }
    base.update(over)
    return base


def _verify(leaf, html=_HTML, holdings=None, bridge_dir=None, tmp_path=None):
    return sav.verify_leaf(
        leaf, holdings_df=holdings if holdings is not None else _holdings(),
        html_loader=lambda cik, acc: html,
        bridge_dir=bridge_dir if bridge_dir is not None else
        (tmp_path / "no_bridges" if tmp_path else None))


def test_schema_accepts_valid_source_anchored_leaf():
    rep = validate_correction(_leaf(), expected_cik="0001812554",
                              expected_fix_class="source_anchored_value")
    assert rep.ok, rep.errors


def test_schema_requires_two_witnesses():
    leaf = _leaf()
    leaf["template"]["assertions"][0]["witnesses"] = [
        {"cell_index": 3, "field": "principal_amount", "value": 58702}]
    rep = validate_correction(leaf)
    assert not rep.ok
    assert any("witnesses" in e for e in rep.errors)


def test_schema_rejects_circular_witness():
    leaf = _leaf()
    leaf["template"]["assertions"][0]["witnesses"][0]["field"] = "interest_rate"
    rep = validate_correction(leaf)
    assert not rep.ok
    assert any("circular" in e for e in rep.errors)


def test_schema_rejects_rate_multiplier():
    leaf = _leaf()
    leaf["template"]["assertions"][0]["source"]["unit_multiplier"] = 1000
    rep = validate_correction(leaf)
    assert not rep.ok
    assert any("must be 1 for rate field" in e for e in rep.errors)


def test_verify_passes_grounded_assertion(tmp_path):
    rep = _verify(_leaf(), tmp_path=tmp_path)
    assert rep["ok"], rep["errors"]
    assert rep["checks"][0]["witnesses_passed"] == 2
    assert rep["checks"][0]["inferred_table_multiplier"] == 1000.0
    assert rep["checks"][0]["bridge"] == "not_covered"


def test_verify_refuses_fabricated_cell_value(tmp_path):
    leaf = _leaf()
    leaf["template"]["assertions"][0]["source"]["value"] = 14.5   # filing says 12.00
    rep = _verify(leaf, tmp_path=tmp_path)
    assert not rep["ok"]
    assert any("does not contain the asserted value" in e for e in rep["errors"])


def test_verify_refuses_wrong_quoted_text(tmp_path):
    leaf = _leaf()
    leaf["template"]["assertions"][0]["source"]["quoted_text"] = "no such text"
    rep = _verify(leaf, tmp_path=tmp_path)
    assert not rep["ok"]
    assert any("quoted_text not found" in e for e in rep["errors"])


def test_verify_refuses_witness_mismatch_against_extracted(tmp_path):
    # The parse-corruption defense: witness cells parse fine but do NOT match the
    # selected position's extracted values (agent anchored on the wrong row).
    leaf = _leaf()
    leaf["template"]["assertions"][0]["row_selector"] = {"row_id": "ROW-00000000000000bb"}
    rep = _verify(leaf, tmp_path=tmp_path)
    assert not rep["ok"]
    assert any("table scale" in e or "row fingerprint" in e for e in rep["errors"])


def test_verify_refuses_missing_filing(tmp_path):
    rep = sav.verify_leaf(_leaf(), holdings_df=_holdings(),
                          html_loader=lambda cik, acc: None,
                          bridge_dir=tmp_path / "none")
    assert not rep["ok"]
    assert any("cached filing missing" in e for e in rep["errors"])


def test_verify_refuses_selector_no_match(tmp_path):
    leaf = _leaf()
    leaf["template"]["assertions"][0]["row_selector"] = {"row_id": "ROW-00000000000000ff"}
    rep = _verify(leaf, tmp_path=tmp_path)
    assert not rep["ok"]
    assert any("matched no in-scope holdings rows" in e for e in rep["errors"])


def test_verify_scaled_field_requires_declared_mult_to_match_table_scale(tmp_path):
    # Asserting fair_value with multiplier 1 while the witnesses prove the table is
    # in thousands must refuse (the declared applier multiplication is wrong).
    leaf = _leaf()
    a = leaf["template"]["assertions"][0]
    a["field"] = "fair_value"
    a["source"]["cell_index"] = 5
    a["source"]["quoted_text"] = "58,702"
    a["source"]["value"] = 58702
    a["source"]["unit_multiplier"] = 1
    a["witnesses"] = [
        {"cell_index": 3, "field": "principal_amount", "value": 58702},
        {"cell_index": 4, "field": "cost", "value": 58650},
    ]
    rep = _verify(leaf, tmp_path=tmp_path)
    assert not rep["ok"]
    assert any("witness-inferred table scale" in e for e in rep["errors"])
    a["source"]["unit_multiplier"] = 1000
    rep = _verify(leaf, tmp_path=tmp_path)
    assert rep["ok"], rep["errors"]


def test_table_health_refuses_mangled_parse(tmp_path):
    # Rows with wildly inconsistent widths = a parse the verifier must not trust.
    bad_html = "<table>" + "".join(
        f"<tr>{'<td>x</td>' * n}</tr>" for n in (2, 9, 3, 14, 2, 11, 5, 16)
    ) + "</table>"
    rep = _verify(_leaf(), html=bad_html, tmp_path=tmp_path)
    assert not rep["ok"]
    assert any("parse-health" in e for e in rep["errors"])


def test_norm_number_variants():
    assert sav._norm_number("12.00 %") == 12.0
    assert sav._norm_number("$ 58,702") == 58702.0
    assert sav._norm_number("( 42 )") == -42.0
    assert sav._norm_number("—") is None
    assert sav._norm_number("") is None
    assert sav._norm_number("S+") is None
