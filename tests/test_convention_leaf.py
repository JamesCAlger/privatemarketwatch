"""Tests for pipeline.convention_leaf (Convention Adjudicator leaf schema)."""

import json

from pipeline.convention_leaf import load_convention_leaf, validate_convention_leaf


def _leaf(**kw):
    base = {
        "cik": "1812554", "target_quarter": "2025-12-31",
        "convention": "all_in",
        "citations": [
            {"kind": "header", "quote": "Interest Rate (2)", "where": "SOI p.12"},
            {"kind": "position", "issuer": "Acme Corp",
             "quote": "12.50% (incl. 3.00% PIK)",
             "printed_total": 12.50, "printed_pik": 3.00},
            {"kind": "position", "issuer": "Beta LLC",
             "quote": "10.00% (incl. 2.00% PIK)",
             "printed_total": 10.00, "printed_pik": 2.00},
        ],
        "rationale": "single rate column with incl-PIK parentheticals",
        "confidence": 0.9,
    }
    base.update(kw)
    return base


def test_valid_decided_leaf_passes():
    assert validate_convention_leaf(_leaf()) == []


def test_missing_required_field():
    leaf = _leaf()
    del leaf["rationale"]
    assert any("rationale" in e for e in validate_convention_leaf(leaf))


def test_bad_convention_value():
    errs = validate_convention_leaf(_leaf(convention="mixed"))
    assert any("convention" in e for e in errs)


def test_confidence_out_of_range():
    errs = validate_convention_leaf(_leaf(confidence=1.5))
    assert any("confidence" in e for e in errs)


def test_decided_needs_two_position_citations():
    leaf = _leaf()
    leaf["citations"] = [c for c in leaf["citations"] if c["kind"] != "position"][:1] + \
        [c for c in leaf["citations"] if c["kind"] == "position"][:1]
    errs = validate_convention_leaf(leaf)
    assert any("position" in e for e in errs)


def test_position_citation_pik_only_is_valid():
    # PIK-only instruments (PIK notes, PIK preferred) print no cash rate; the
    # verifier counts these as pik-only partial evidence, so the schema must
    # not reject them (2026-07-22: 15/66 conv_full leaves were wrongly refused).
    leaf = _leaf()
    del leaf["citations"][1]["printed_total"]
    assert validate_convention_leaf(leaf) == []


def test_position_citation_still_needs_printed_pik():
    leaf = _leaf()
    del leaf["citations"][1]["printed_pik"]
    errs = validate_convention_leaf(leaf)
    assert any("printed_pik" in e for e in errs)


def test_position_citation_rejects_non_numeric_total_or_cash():
    # present-but-non-numeric would crash _fits() in the verifier
    leaf = _leaf()
    leaf["citations"][1]["printed_total"] = "N/A"
    errs = validate_convention_leaf(leaf)
    assert any("printed_total must be numeric when present" in e for e in errs)

    leaf2 = _leaf()
    leaf2["citations"][2]["printed_cash"] = "6.7%"
    errs2 = validate_convention_leaf(leaf2)
    assert any("printed_cash must be numeric when present" in e for e in errs2)


def test_position_citation_accepts_printed_cash_instead_of_total():
    leaf = _leaf(convention="cash_leg")
    for c in leaf["citations"]:
        if c["kind"] == "position":
            del c["printed_total"]
            c["printed_cash"] = 6.7
    assert validate_convention_leaf(leaf) == []


def test_indeterminate_requires_search_trail():
    leaf = _leaf(convention="indeterminate", citations=[])
    errs = validate_convention_leaf(leaf)
    assert any("search_trail" in e for e in errs)
    leaf["search_trail"] = ["SOI rate column has no PIK annotation",
                            "notes to financials silent on PIK in stated rates"]
    assert validate_convention_leaf(leaf) == []


def test_applies_from_format_checked():
    errs = validate_convention_leaf(_leaf(applies_from="Q1 2022"))
    assert any("applies_from" in e for e in errs)


def test_load_tolerates_bom(tmp_path):
    p = tmp_path / "leaf.json"
    p.write_bytes(b"\xef\xbb\xbf" + json.dumps(_leaf()).encode("utf-8"))
    leaf = load_convention_leaf(p)
    assert leaf is not None and leaf["convention"] == "all_in"


def test_load_missing_or_broken_returns_none(tmp_path):
    assert load_convention_leaf(tmp_path / "nope.json") is None
    p = tmp_path / "broken.json"
    p.write_text("{not json", encoding="utf-8")
    assert load_convention_leaf(p) is None
