"""pipeline.issuer_instrument_split: the shared issuer / instrument cut of a BDC row's name."""
import json

import pandas as pd
import pytest

from pipeline.issuer_instrument_split import enabled, opted_out_ciks, shapes, split_issuer_instrument, split_name


@pytest.mark.parametrize("name, issuer, cut, number", [
    ("Auctane, Inc., First lien senior secured loan", "Auctane, Inc.", "First lien senior secured loan", ""),
    ("Pediatric Associates Holding Company, LLC, First lien senior secured loan 2", "Pediatric Associates Holding Company, LLC",
     "First lien senior secured loan 2", ""),
    ("Keel Platform, LLC, Senior Secured Loans (Delayed Draw)", "Keel Platform, LLC", "Senior Secured Loans (Delayed Draw)", ""),
    ("Midwest Veterinary Partners, LLC, Preferred stock 1", "Midwest Veterinary Partners, LLC", "Preferred stock 1", ""),
    ("Lido Advisors, LLC and LAL Group Holdings, LLC, Class A-0 common units", "Lido Advisors, LLC and LAL Group Holdings, LLC",
     "Class A-0 common units", ""),
    ("Ascent Midco, L L C, Equity Securities, Class A units", "Ascent Midco, L L C", "Equity Securities, Class A units", ""),
    ("Red Griffin ParentCo, LLC - Class A Common Units", "Red Griffin ParentCo, LLC", "Class A Common Units", ""),
    ("CH Buyer, LLC, Revolver", "CH Buyer, LLC", "Revolver", ""),
    ("Amalfi Midco, Warrants", "Amalfi Midco", "Warrants", ""),
    # row numbers are left to the fund's wrapper: the shared split does not cut them
    ("Plasma Buyer LLC 3", "Plasma Buyer LLC 3", "", ""),
    ("Rocket Software, Inc.2", "Rocket Software, Inc.2", "", ""),
    ("Midwest Veterinary Partners, LLC 2, Preferred stock", "Midwest Veterinary Partners, LLC 2", "Preferred stock", ""),
    # false positives: left as filed
    ("Senior Secured Holdings, Inc.", "Senior Secured Holdings, Inc.", "", ""),
    ("Caerus US 1, Inc.", "Caerus US 1, Inc.", "", ""),
    ("Broad River Ltd 2020-1", "Broad River Ltd 2020-1", "", ""),
    ("Pikes Peak CLO 10", "Pikes Peak CLO 10", "", ""),
    ("Aerosmith Bidco 1 Limited (dba Audiotonix)", "Aerosmith Bidco 1 Limited (dba Audiotonix)", "", ""),
    ("Mimecast Borrowerco, Inc. and Magnesium Co- Invest SCSp", "Mimecast Borrowerco, Inc. and Magnesium Co- Invest SCSp", "", ""),
    ("Class Valuation, LLC", "Class Valuation, LLC", "", ""),
    ("Common Sense Media, Inc.", "Common Sense Media, Inc.", "", ""),
    (", First lien senior secured loan", ", First lien senior secured loan", "", ""),
    # the issuer is at the end, after a section heading (cohort A/B 2026-10-14, 0001841514)
    ("Debt Investments, First Lien Senior Secured, Military Retail Solutions",
     "Debt Investments, First Lien Senior Secured, Military Retail Solutions", "", ""),
    ("Non-Controlled/Non-Affiliated Investments, Senior Secured First Lien Loans, Acme",
     "Non-Controlled/Non-Affiliated Investments, Senior Secured First Lien Loans, Acme", "", ""),
    # the cut text names a company: the cut would be inside the issuer
    ("Wilnat, Inc. - Revolving Credit Lin, LLC", "Wilnat, Inc. - Revolving Credit Lin, LLC", "", ""),
])
def test_split_name(name, issuer, cut, number):
    assert split_name(name) == (issuer, cut, number)


def test_shapes_name_what_is_left():
    assert shapes("Acme, Inc., First lien senior secured loan") == ["instrument_in_name"]
    assert shapes("Beta Holdings, LLC 2") == ["row_number_in_name"]
    assert shapes("Nouryon USA, LLC, Verdelite JV LP") == ["holder_label_in_name"]
    assert shapes("Blue Owl Credit SLF JV LLC") == []          # the joint venture is the issuer
    assert shapes("Acme, Inc.") == []


def _frame(names, instruments, cik="0001111111", source="bdc"):
    return pd.DataFrame({"source": source, "cik": cik, "issuer_name": names, "instrument_description": instruments})


def test_the_cut_fills_a_blank_instrument_or_goes_in_front():
    out = split_issuer_instrument(_frame(
        ["Acme, Inc., First lien senior secured loan", "Beta, LLC, Senior Secured Loans", "Gamma, LLC, Revolver", "Zeta Co"],
        [None, "Senior Secured Loans due 2030", "SOFR + 5.00%", "Term loan"]))
    assert out["issuer_name"].tolist() == ["Acme, Inc.", "Beta, LLC", "Gamma, LLC", "Zeta Co"]
    assert out["instrument_description"].tolist() == ["First lien senior secured loan", "Senior Secured Loans due 2030",
                                                      "Revolver SOFR + 5.00%", "Term loan"]


def test_numbered_rows_keep_their_names():
    # 0001792509 numbers tranches of one issuer, all 'Warrant Investments', and renumbers them
    # between quarters: the number stays in the name, where position matching relies on it
    out = split_issuer_instrument(_frame(["Appex Group, Inc. 1", "Appex Group, Inc. 2"], ["Warrant Investments", "Warrant Investments"]))
    assert out["issuer_name"].tolist() == ["Appex Group, Inc. 1", "Appex Group, Inc. 2"]
    assert out["instrument_description"].tolist() == ["Warrant Investments", "Warrant Investments"]


def test_opted_out_funds_and_other_sources_are_untouched(tmp_path):
    frame = pd.concat([_frame(["Acme, Inc., First lien"], [None]), _frame(["Acme, Inc., First lien"], [None], cik="0002222222"),
                       _frame(["Acme, Inc., First lien"], [None], source="nport")], ignore_index=True)
    out = split_issuer_instrument(frame, {"0002222222"})
    assert out["issuer_name"].tolist() == ["Acme, Inc.", "Acme, Inc., First lien", "Acme, Inc., First lien"]
    (tmp_path / "a.json").write_text(json.dumps({"cik": "0002222222", "dispatch": {"global_issuer_split": False}}), encoding="utf-8")
    (tmp_path / "b.json").write_text(json.dumps({"cik": "0003333333", "dispatch": {"global_issuer_split": "no"}}), encoding="utf-8")
    assert opted_out_ciks(tmp_path) == {"0002222222"}


def test_switch_reads_the_reference_file(tmp_path):
    ref = tmp_path / "split.json"
    assert enabled(ref) is False
    ref.write_text(json.dumps({"enabled": True}), encoding="utf-8")
    assert enabled(ref) is True
    ref.write_text(json.dumps({"enabled": "yes"}), encoding="utf-8")
    assert enabled(ref) is False
