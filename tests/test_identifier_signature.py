"""Tests for pipeline.identifier_signature (Agent A / P0 deterministic layer)."""

import json

from pipeline.identifier_signature import (
    STARTER_ANCHORS,
    CikAccumulator,
    detect_regime,
    is_aggregate_candidate,
    keyword_signature,
    load_anchors,
    punctuation_shape,
    signature_for,
)


# --------------------------------------------------------------------------- #
# Punctuation shape (delimited regime) -- real Golub examples
# --------------------------------------------------------------------------- #
def test_punctuation_shape_golub_comma():
    # within-field tranche number folds into the content blob, so '...One stop 1/2/3'
    # all share one shape and cluster together
    assert punctuation_shape("CG Group Holdings, LLC, One stop 1") == "W , W , W"
    assert punctuation_shape("AmerCareRoyal LLC, Senior loan 1") == "W , W"


def test_punctuation_shape_golub_pipe():
    assert (
        punctuation_shape("Covercraft Parent III, Inc. | Senior secured 1 | Non-Affiliated Issuer")
        == "W , W | W | W -W"
    )


def test_punctuation_shape_collapses_word_runs_and_numbers():
    # multi-word issuer + trailing sequence number all collapse to one content blob
    assert punctuation_shape("Spartan Buyer Acquisition Co 2") == "W"


def test_punctuation_shape_empty():
    assert punctuation_shape("") == "(empty)"


# --------------------------------------------------------------------------- #
# Keyword signature (flattened regime) -- real Antares examples
# --------------------------------------------------------------------------- #
def test_keyword_signature_antares_debt():
    s = ("Investments - non-controlled/non-affiliated Secured Debt Diversified "
         "Consumer Services Apex Service Partners, LLC Asset Type First Lien "
         "Reference Rate and Spread SOFR + 5.75% Interest Rate 10.10% Maturity Date 02/02/28")
    assert keyword_signature(s) == "AFFIL SECDEBT ASSETTYPE REFRATE RATE MAT"


def test_keyword_signature_antares_revolver():
    s = ("Investments non-controlled/non-affiliated AB Centers Acquisition Corp. "
         "Commitment Type Revolver Commitment Expiration 03/15/29 Maturity Date 03/15/29")
    assert keyword_signature(s) == "AFFIL COMMIT COMMITEXP MAT"


def test_keyword_signature_position_ordered_not_definition_ordered():
    # RATE appears before MAT in the string; signature follows string position
    s = "Secured Debt 9.50% asset type first lien maturity date 01/01/30"
    sig = keyword_signature(s)
    assert sig.index("RATE") < sig.index("MAT")
    assert sig.startswith("SECDEBT")


def test_keyword_signature_none_when_no_anchor():
    assert keyword_signature("Retrieving data. Wait a few seconds and try again.") == "(none)"


def test_keyword_signature_fixed_rate_has_no_refrate():
    # MidCap-style fixed-rate loan (the canonical Automotive/Crowne case): a '%' rate
    # but NO reference token -> RATE present, REFRATE absent (must not invent floating)
    s = ("Automotive Crowne Automotive Vari-Form Group, LLC First Lien Secured Debt "
         "11.00% (7.00% Cash plus 4.00% PIK) Maturity Date 02/02/23")
    sig = keyword_signature(s)
    assert "RATE" in sig
    assert "REFRATE" not in sig
    assert "SECDEBT" in sig


# --------------------------------------------------------------------------- #
# Aggregate-candidate heuristic (free leaked-aggregate flag)
# --------------------------------------------------------------------------- #
def test_aggregate_candidate_category_without_position():
    # GICS-industry subtotal: category keyword, no issuer/position anchor
    assert is_aggregate_candidate(
        "Investments - non-controlled/non-affiliated Secured Debt Air Freight and Logistics"
    )


def test_aggregate_candidate_total_line():
    assert is_aggregate_candidate("Total Secured Debt Investments")


def test_equity_position_with_issuer_is_not_aggregate_candidate():
    # category anchor (EQUITY) + no rate/maturity anchor, BUT a real issuer (LLC) -> position
    assert not is_aggregate_candidate(
        "Equity Investments Retailing Palmetto Moon LLC Common Stock")
    assert not is_aggregate_candidate(
        "Non-controlled/Non-Affiliated Investments Automotive Gills Point S Holdings Inc. Equity Interest")


def test_real_position_is_not_aggregate_candidate():
    s = ("Investments - non-controlled/non-affiliated Secured Debt Diversified "
         "Consumer Services Apex Service Partners, LLC Asset Type First Lien "
         "Interest Rate 10.10% Maturity Date 02/02/28")
    assert not is_aggregate_candidate(s)


# --------------------------------------------------------------------------- #
# Regime detection
# --------------------------------------------------------------------------- #
def test_detect_regime_delimited_when_no_rate_no_anchor():
    assert detect_regime(rate_embed_pct=0.0, anchor_present_pct=2.0) == "delimited"


def test_detect_regime_flattened_on_embedded_rates():
    assert detect_regime(rate_embed_pct=67.0, anchor_present_pct=90.0) == "flattened"


def test_detect_regime_flattened_on_anchor_density_alone():
    # equity-heavy flattened filer: low embedded-rate but high keyword anchor presence
    assert detect_regime(rate_embed_pct=5.0, anchor_present_pct=80.0) == "flattened"


def test_signature_for_routes_by_regime():
    s = "CG Group Holdings, LLC, One stop 1"
    assert signature_for(s, "delimited") == "W , W , W"
    flat = ("Investments non-controlled/non-affiliated Secured Debt X Asset Type "
            "First Lien Interest Rate 9.00% Maturity Date 01/01/30")
    assert "ASSETTYPE" in signature_for(flat, "flattened")


# --------------------------------------------------------------------------- #
# Per-CIK accumulation (the report's clustering math)
# --------------------------------------------------------------------------- #
def test_load_anchors_falls_back_to_starter(tmp_path):
    # no per-CIK file -> global starter
    assert load_anchors("9999999999", anchor_dir=tmp_path) is STARTER_ANCHORS


def test_load_anchors_per_cik_dialect(tmp_path):
    # a MidCap-style dialect that recognizes a bps spread the global set would miss
    (tmp_path / "0001278752.json").write_text(json.dumps({
        "anchors": [
            {"label": "SECDEBT", "regex": "secured debt"},
            {"label": "REFRATE", "regex": r"(?:sofr|l)\s*\+\s*\d"},
            {"label": "MAT", "regex": r"\b\d{1,2}/\d{1,2}/\d{2,4}\b"},
        ]
    }), encoding="utf-8")
    anchors = load_anchors("0001278752", anchor_dir=tmp_path)
    s = "First Lien Secured Debt SOFR+400 Cash plus 2.00% PIK Maturity Date 09/22/27"
    assert keyword_signature(s, anchors) == "SECDEBT REFRATE MAT"


def test_accumulator_clusters_and_covers():
    acc = CikAccumulator(cik="0000000001")
    # 8 identical-shape delimited rows + 2 of another shape -> 2 shapes, cover80 = 1
    for i in range(8):
        acc.add("Test BDC", f"Issuer {i} Holdings, LLC, One stop {i}")
    for i in range(2):
        acc.add("Test BDC", f"Other Co {i}, Senior loan {i}")
    summary, detail = acc.summarize()
    assert summary["regime"] == "delimited"
    assert summary["distinct_signatures"] == 2
    assert summary["cover80"] == 1
    assert summary["n_rows"] == 10
    assert detail[0]["count"] == 8
