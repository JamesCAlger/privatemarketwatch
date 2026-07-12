"""Tests for pipeline.identifier_rate (Agent A / P1 rate-grammar applier + gate)."""

import pytest

from pipeline.identifier_rate import (
    apply_grammar,
    evaluate_invariants,
    load_grammar,
)

CIK = "0001993402"

# Real Antares strings (from bdc_holdings).
APEX = ("Investments - non-controlled/non-affiliated Secured Debt Diversified Consumer "
        "Services Apex Service Partners, LLC Asset Type First Lien Term Loan Reference "
        "Rate and Spread S + 5.00% Interest Rate Floor 1.00% Interest Rate 12.30% "
        "(Incl. 2.00% PIK) Maturity Date 10/24/2030")

BLUECAT_ONE = ("Investments - non-controlled/non-affiliated Secured Debt Software Bluecat "
               "Networks (USA) Inc. Asset Type One First Lien Term Loan Reference Rate and "
               "Spread S + 5.00% Interest Rate 10.30% (Incl. 1.00% PIK) Maturity Date 8/8/2028")


@pytest.fixture(scope="module")
def grammar():
    return load_grammar(CIK)


def test_apply_extracts_all_fields_apex(grammar):
    p = apply_grammar(APEX, grammar)
    assert p["reference_rate_type"] == "SOFR"      # "S" mapped
    assert p["basis_spread"] == 5.00
    assert p["interest_rate_floor"] == 1.00
    assert p["interest_rate_all_in"] == 12.30      # NOT the 1.00% floor
    assert p["pik_rate"] == 2.00
    assert p["maturity_date"] == "2030-10-24"
    assert p["instrument_type"].lower().startswith("first lien")


def test_all_in_not_confused_with_floor(grammar):
    # the negative lookahead must skip "Interest Rate Floor 1.00%"
    p = apply_grammar(APEX, grammar)
    assert p["interest_rate_all_in"] == 12.30
    assert p["interest_rate_floor"] == 1.00


def test_inclusive_pik_cash_leg_derivation(grammar):
    # Antares states ALL-IN incl PIK -> cash leg = all_in - pik = 12.30 - 2.00 = 10.30
    p = apply_grammar(APEX, grammar)
    assert p["interest_rate_cash_leg"] == 10.30


def test_coupon_type_floating_when_reference_present(grammar):
    assert apply_grammar(APEX, grammar)["coupon_type"] == "FLOATING"


def test_one_prefix_stripped_in_instrument(grammar):
    p = apply_grammar(BLUECAT_ONE, grammar)
    # "Asset Type One First Lien Term Loan" -> "One" prefix dropped
    assert p["instrument_type"].lower().startswith("first lien")
    assert p["interest_rate_all_in"] == 10.30
    assert p["pik_rate"] == 1.00


def test_coupon_type_fixed_when_no_reference(grammar):
    # a fixed-rate string with no reference token must NOT invent floating
    fixed = "Asset Type Common Interest Rate 10.50% Maturity Date 01/01/30"
    p = apply_grammar(fixed, grammar)
    assert p["reference_rate_type"] is None
    assert p["coupon_type"] == "FIXED"


# --------------------------------------------------------------------------- #
# Gate / invariant logic
# --------------------------------------------------------------------------- #
def test_invariants_pass_against_matching_twins(grammar):
    p = apply_grammar(APEX, grammar)
    twins = {"interest_rate": 0.123, "basis_spread": 0.05, "pik_rate": 0.02,
             "maturity_date": "2030-10-24"}
    verd = evaluate_invariants(p, twins, grammar)
    assert verd["all_in_vs_twin"] == "pass"
    assert verd["spread_vs_twin"] == "pass"
    assert verd["pik_vs_twin"] == "pass"
    assert verd["maturity_vs_twin"] == "pass"
    assert verd["floating_has_reference"] == "pass"


def test_invariant_flags_spread_disagreement(grammar):
    # Alert Media case: string says spread 0.00 but structured twin says 5.78 -> FAIL (flag)
    p = apply_grammar(APEX, grammar)
    p["basis_spread"] = 0.00
    twins = {"interest_rate": 0.123, "basis_spread": 0.0578, "pik_rate": 0.02,
             "maturity_date": "2030-10-24"}
    verd = evaluate_invariants(p, twins, grammar)
    assert verd["spread_vs_twin"] == "fail"


def test_invariant_na_when_twin_missing(grammar):
    p = apply_grammar(APEX, grammar)
    twins = {"interest_rate": None, "basis_spread": None, "pik_rate": None,
             "maturity_date": None}
    verd = evaluate_invariants(p, twins, grammar)
    assert verd["all_in_vs_twin"] == "na"
    assert verd["maturity_vs_twin"] == "na"


# --------------------------------------------------------------------------- #
# MidCap-style engine features: additive PIK, bps spread, sum_identity
# (the gate that holds when the structured twins are themselves mis-binned)
# --------------------------------------------------------------------------- #
_MIDCAP_ADDITIVE = {
    "pik_convention": "additive",
    "extractors": [
        {"field": "interest_rate_total", "regex": r"Debt\s+([0-9.]+)%\s*\(", "group": 1, "type": "pct"},
        {"field": "interest_rate_cash_leg", "regex": r"([0-9.]+)%\s*Cash", "group": 1, "type": "pct"},
        {"field": "pik_rate", "regex": r"plus\s+([0-9.]+)%\s*PIK", "group": 1, "type": "pct"},
        {"field": "maturity_date", "regex": r"Maturity Date\s+([0-9/]+)", "group": 1, "type": "date_mdy"},
    ],
    "derivations": {"coupon_type": "floating_if_reference_rate_else_fixed"},
    "invariants": [
        {"name": "sum_identity", "kind": "sum_identity",
         "total": "interest_rate_total", "parts": ["interest_rate_cash_leg", "pik_rate"], "tol": 0.05},
        {"name": "pik_vs_twin", "kind": "pct_agree", "parsed": "pik_rate", "twin": "pik_rate", "tol": 0.05},
    ],
}

# The user's canonical case -- and the structured twins are MIS-BINNED (11% total in
# basis_spread, 7% cash in interest_rate).
AUTOMOTIVE = ("Automotive Crowne Automotive Vari-Form Group, LLC First Lien Secured Debt "
              "11.00% (7.00% Cash plus 4.00% PIK Maturity Date 02/02/23")


def test_additive_pik_sum_identity_holds():
    p = apply_grammar(AUTOMOTIVE, _MIDCAP_ADDITIVE)
    assert p["interest_rate_total"] == 11.00
    assert p["interest_rate_cash_leg"] == 7.00
    assert p["pik_rate"] == 4.00
    # 11 == 7 + 4 -- self-contained gate passes even though the XBRL twins are wrong
    verd = evaluate_invariants(p, {"pik_rate": 0.04}, _MIDCAP_ADDITIVE)
    assert verd["sum_identity"] == "pass"
    assert verd["pik_vs_twin"] == "pass"


def test_sum_identity_fails_on_bad_parse():
    p = apply_grammar(AUTOMOTIVE, _MIDCAP_ADDITIVE)
    p["pik_rate"] = 9.00  # 7 + 9 != 11
    verd = evaluate_invariants(p, {"pik_rate": None}, _MIDCAP_ADDITIVE)
    assert verd["sum_identity"] == "fail"


def test_bom_zero_width_normalization(grammar):
    from pipeline.identifier_rate import normalize_identifier_text
    # BOM/ZWNBSP between "Interest Rate" and the number breaks \s-based extractors
    raw = "Reference Rate and Spread S + 5.00% Interest Rate Floor 1.00% Interest Rate﻿ 7.06% Maturity Date 10/31/2030"
    assert "﻿" not in normalize_identifier_text(raw)
    p = apply_grammar(raw, grammar)
    assert p["interest_rate_all_in"] == 7.06   # recovered after normalization
    # non-breaking space also normalized
    assert normalize_identifier_text("a b") == "a b"


def test_bps_spread_coercion():
    g = {"extractors": [
        {"field": "reference_rate_type", "regex": r"(SOFR|L|P|E)\s*\+", "group": 1,
         "type": "ref_code", "map": {"L": "LIBOR"}},
        {"field": "basis_spread", "regex": r"(?:SOFR|L|P|E)\s*\+\s*([0-9]+)", "group": 1, "type": "bps"},
    ]}
    p = apply_grammar("Interest Rate SOFR+400 Cash plus 2.00% PIK", g)
    assert p["reference_rate_type"] == "SOFR"
    assert p["basis_spread"] == 4.00          # 400 bps -> 4.00%
    p2 = apply_grammar("Interest Rate L+600 Cash", g)
    assert p2["reference_rate_type"] == "LIBOR"
    assert p2["basis_spread"] == 6.00


def test_derivations_as_list_does_not_crash():
    # Regression: agents sometimes emit "derivations": [] (a list); apply_grammar did
    # derivs.get(...) -> AttributeError, aborting the screen/gate. A non-dict derivations
    # must be ignored, not raise.
    g = {"extractors": [{"field": "basis_spread", "regex": r"\+\s*([0-9]+)", "group": 1, "type": "bps"}],
         "derivations": []}
    p = apply_grammar("SOFR +400", g)
    assert p["basis_spread"] == 4.00


def test_malformed_invariant_missing_keys_does_not_crash():
    # Regression: an agent wrote a pct_agree invariant with no "parsed"/"twin" key; the worker's
    # own validate step (and the parent gate) KeyError'd over the whole population. A malformed
    # invariant must resolve to 'na', not raise.
    g = {"invariants": [
        {"name": "spread_vs_twin", "kind": "pct_agree"},            # missing parsed/twin
        {"name": "matures", "kind": "date_agree", "parsed": "maturity_date"},  # missing twin
        {"name": "floaty", "kind": "implication"},                  # missing if/then
        {"name": "sums", "kind": "sum_identity"},                   # missing total/parts
        {"kind": "pct_agree", "parsed": "basis_spread", "twin": "basis_spread"},  # no name
    ]}
    res = evaluate_invariants({"basis_spread": 5.0}, {"basis_spread": 0.05}, g)
    assert res == {"spread_vs_twin": "na", "matures": "na", "floaty": "na", "sums": "na"}


def test_malformed_extractor_group_index_does_not_crash():
    # Regression: a worker-proposed extractor declaring "group": 1 on a regex with only a
    # non-capturing '(?:...)' group (0 capture groups) raised IndexError and aborted the whole
    # staged batch (CIK 0001987221, pik_terms_flag). The engine must treat it as no extraction.
    g = {"extractors": [
        {"field": "pik_terms_flag", "type": "text", "group": 1,
         "regex": r"Interest Rate\s+[0-9]+(?:\.[0-9]+)?%\s+PIK\b"},
        {"field": "basis_spread", "regex": r"\+\s*([0-9]+)", "group": 1, "type": "bps"},
    ]}
    p = apply_grammar("Interest Rate 12.50% PIK +400", g)
    assert p["pik_terms_flag"] is None      # malformed extractor no-ops instead of crashing
    assert p["basis_spread"] == 4.00         # a well-formed extractor alongside it still works
