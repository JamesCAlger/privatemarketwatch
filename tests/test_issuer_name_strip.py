"""dispatch.issuer_name_strip_re and issuer_name_strip_to_instrument: one filer's trailing text on the issuer name."""
import json

import pandas as pd

from pipeline.staging_bdc import issuer_name_strip_to_instrument_ciks
from pipeline.unified_holdings import _strip_issuer_names

MONROE = "0001742313"
PATTERN = r"(?i)(?:\s*\(\s*(?:Delayed\s+Draw|Revolver)\))?(?:\s*,\s*(?:Senior\s+Secured\s+Loans?|Equity\s+Securities)\b.*|(?:\s+\d{1,2})?)$"


def _frame(names, instruments=None, cik=MONROE, source="bdc"):
    return pd.DataFrame({"source": source, "cik": cik, "issuer_name": names,
                         "instrument_description": instruments if instruments is not None else [None] * len(names)})


def test_strip_removes_trailing_text_and_keeps_other_names():
    out = _strip_issuer_names(_frame(["Acme, LLC, Senior Secured Loans (Delayed Draw) 1", "Acme, LLC (Revolver)", "Caerus US 1, Inc."]),
                              {MONROE: PATTERN})
    assert out["issuer_name"].tolist() == ["Acme, LLC", "Acme, LLC", "Caerus US 1, Inc."]
    assert out["instrument_description"].isna().all()


def test_removed_text_fills_a_blank_instrument_when_switched_on():
    out = _strip_issuer_names(
        _frame(["Acme, LLC, Senior Secured Loans (Delayed Draw) 1", "Acme, LLC (Revolver)", "Beta Inc., Equity Securities"],
               [None, "", "Class A units"]), {MONROE: PATTERN}, {MONROE})
    assert out["issuer_name"].tolist() == ["Acme, LLC", "Acme, LLC", "Beta Inc."]
    # a blank instrument takes the removed text without its leading separator; a filled one gets it in front
    assert out["instrument_description"].tolist() == ["Senior Secured Loans (Delayed Draw) 1", "(Revolver)",
                                                     "Equity Securities Class A units"]


def test_removed_text_already_in_the_instrument_is_not_repeated():
    out = _strip_issuer_names(_frame(["Acme, LLC, Senior Secured Loans"], ["Senior Secured Loans due 2030"]), {MONROE: PATTERN}, {MONROE})
    assert out["instrument_description"].tolist() == ["Senior Secured Loans due 2030"]


def test_removed_row_number_alone_is_not_an_instrument():
    out = _strip_issuer_names(_frame(["Riser Merger Sub, Inc. 2"]), {MONROE: PATTERN}, {MONROE})
    assert out["issuer_name"].tolist() == ["Riser Merger Sub, Inc."]
    assert out["instrument_description"].isna().all()


def test_other_funds_and_other_sources_are_untouched():
    frame = pd.concat([_frame(["Acme, LLC, Senior Secured Loans"], cik="0001111111"),
                       _frame(["Acme, LLC, Senior Secured Loans"], source="nport")], ignore_index=True)
    out = _strip_issuer_names(frame, {MONROE: PATTERN}, {MONROE})
    assert out["issuer_name"].tolist() == ["Acme, LLC, Senior Secured Loans"] * 2


def test_a_name_the_pattern_would_empty_is_left_as_filed():
    out = _strip_issuer_names(_frame([", Senior Secured Loans"]), {MONROE: PATTERN}, {MONROE})
    assert out["issuer_name"].tolist() == [", Senior Secured Loans"]
    assert out["instrument_description"].isna().all()


def test_switch_needs_the_pattern_and_a_true_value(tmp_path):
    def wrapper(name, cik, dispatch):
        (tmp_path / name).write_text(json.dumps({"cik": cik, "dispatch": dispatch}), encoding="utf-8")
    wrapper("a.json", "0000000001", {"issuer_name_strip_re": r"\s+\d$", "issuer_name_strip_to_instrument": True})
    wrapper("b.json", "0000000002", {"issuer_name_strip_to_instrument": True})
    wrapper("c.json", "0000000003", {"issuer_name_strip_re": r"\s+\d$", "issuer_name_strip_to_instrument": "yes"})
    wrapper("d.json", "0000000004", {"issuer_name_strip_re": r"\s+\d$"})
    assert issuer_name_strip_to_instrument_ciks(tmp_path) == {"0000000001"}


def _wrapper_dispatch(cik):
    from pipeline.staging_bdc import _WRAPPER_DEFINITIONS_DIR
    return json.loads((_WRAPPER_DEFINITIONS_DIR / ("%s.json" % cik)).read_text(encoding="utf-8"))["dispatch"]


def test_bcred_joint_venture_and_row_number_leave_the_issuer_name():
    bcred = "0001803498"
    dispatch = _wrapper_dispatch(bcred)
    names = ["Nouryon USA, LLC, Verdelite JV LP", "Trident TPI Holdings, Inc., Emerald JV LP 2",
             "Vision Solutions, Inc. Emerald JV LP", "Pigments Services, Inc. 2, Emerald JV LP",
             "Mitratech Holdings, Inc. 2 Emerald JV LP", "Emerald JV LP, Albireo Energy, LLC",
             "Rocket Software, Inc.2", "Project Ruby Ultimate Parent Corp.,1", "Caramel Bidco Limited 2",
             # false positives: a vintage or a number inside the name stays
             "Broad River Ltd 2020-1", "CEP V Investment 11 Sarl", "Balboa Bay Loan Funding 2021-2, Ltd."]
    out = _strip_issuer_names(_frame(names, cik=bcred), {bcred: dispatch["issuer_name_strip_re"]})
    assert out["issuer_name"].tolist() == [
        "Nouryon USA, LLC", "Trident TPI Holdings, Inc.", "Vision Solutions, Inc.", "Pigments Services, Inc.",
        "Mitratech Holdings, Inc.", "Albireo Energy, LLC", "Rocket Software, Inc.", "Project Ruby Ultimate Parent Corp.",
        "Caramel Bidco Limited", "Broad River Ltd 2020-1", "CEP V Investment 11 Sarl", "Balboa Bay Loan Funding 2021-2, Ltd."]


def test_bcred_joint_venture_name_is_not_an_instrument():
    from pipeline.unified_holdings import _strip_instrument_text
    bcred = "0001803498"
    dispatch = _wrapper_dispatch(bcred)
    assert dispatch["instrument_description_strip_may_empty"] is True
    frame = _frame(["Gen Digital, Inc.", "Rad Clo 25 Ltd", "X"], ["Emerald JV LP", "Subordinated Notes", "Term Loan, Verdelite JV LP"], cik=bcred)
    out = _strip_instrument_text(frame, {bcred: dispatch["instrument_description_strip_re"]}, {bcred})
    assert out["instrument_description"].isna().tolist() == [True, False, False]
    assert out["instrument_description"].tolist()[1:] == ["Subordinated Notes", "Term Loan"]


def test_instrument_strip_empties_only_when_switched_on():
    from pipeline.unified_holdings import _strip_instrument_text
    frame = _frame(["A"], ["Emerald JV LP"])
    assert _strip_instrument_text(frame.copy(), {MONROE: r"^Emerald JV LP$"})["instrument_description"].tolist() == ["Emerald JV LP"]
    assert _strip_instrument_text(frame.copy(), {MONROE: r"^Emerald JV LP$"}, {MONROE})["instrument_description"].isna().all()


def test_blue_owl_credit_income_instrument_leaves_the_issuer_name():
    owl = "0001812554"
    dispatch = _wrapper_dispatch(owl)
    assert dispatch["issuer_name_strip_to_instrument"] is True
    names = ["DCG ACQUISITION CORP. (dba DuBois Chemical), First lien senior secured loan",
             "Pediatric Associates Holding Company, LLC, First lien senior secured loan 2",
             "Peraton Corp., Second lien senior secured loan", "WMC Bidco, Inc. (dba West Monroe), Senior Preferred Stock",
             "Metis HoldCo, Inc. (dba Mavis Tire Express Services), Series A Convertible Preferred Stock",
             "Ineos US Finance LLC 2",
             # false positives: a lien word or number that is part of the company name stays
             "Senior Secured Holdings, Inc.", "Caerus US 1, Inc.", "Class Valuation, LLC"]
    out = _strip_issuer_names(_frame(names, cik=owl), {owl: dispatch["issuer_name_strip_re"]}, {owl})
    assert out["issuer_name"].tolist() == [
        "DCG ACQUISITION CORP. (dba DuBois Chemical)", "Pediatric Associates Holding Company, LLC", "Peraton Corp.",
        "WMC Bidco, Inc. (dba West Monroe)", "Metis HoldCo, Inc. (dba Mavis Tire Express Services)", "Ineos US Finance LLC",
        "Senior Secured Holdings, Inc.", "Caerus US 1, Inc.", "Class Valuation, LLC"]
    assert out["instrument_description"].tolist()[:5] == [
        "First lien senior secured loan", "First lien senior secured loan 2", "Second lien senior secured loan",
        "Senior Preferred Stock", "Series A Convertible Preferred Stock"]
    assert pd.isna(out["instrument_description"].tolist()[5])


def test_instrument_header_words_are_removed_for_one_fund_only():
    from pipeline.unified_holdings import _strip_instrument_text
    pattern = r"(?i)^\s*Type\s+|\s+(?:Reference\s+Rate\s+and\s+Spread|Interest\s+Rate|Maturity\s+Date)\b.*$"
    frame = pd.concat([
        _frame(["A", "B", "C", "D"], ["Type Term Loan Reference Rate and Spread SOFR + 5.25% Interest Rate 9.58% Maturity Date 12/18/2027",
                                      "Type Class A Units", "Revolving Credit Facility Maturity Date 01/11/2029", "Type"]),
        _frame(["E"], ["Type Term Loan Interest Rate 9%"], cik="0000000001"),
    ], ignore_index=True)
    out = _strip_instrument_text(frame, {MONROE: pattern})
    # the last of the fund's rows would be emptied, so it stays as filed; another fund is untouched
    assert out["instrument_description"].tolist() == ["Term Loan", "Class A Units", "Revolving Credit Facility", "Type", "Type Term Loan Interest Rate 9%"]
