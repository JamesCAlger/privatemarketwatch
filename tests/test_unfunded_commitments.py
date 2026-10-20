"""Undrawn commitment rows netted by the commitment the filer tags (source_encodings.unfunded_rows)."""
import json

import pytest
from lxml import etree

from pipeline import unfunded_commitments as uc

XML = """<xbrl xmlns:us-gaap="http://fasb.org/us-gaap/2025">
  <us-gaap:InvestmentCompanyFinancialCommitmentToInvesteeFutureAmount contextRef="n1">1679000</us-gaap:InvestmentCompanyFinancialCommitmentToInvesteeFutureAmount>
  <us-gaap:InvestmentCompanyFinancialCommitmentToInvesteeFutureAmount contextRef="n2">31849000</us-gaap:InvestmentCompanyFinancialCommitmentToInvesteeFutureAmount>
  <us-gaap:InvestmentCompanyFinancialCommitmentToInvesteeFutureAmount contextRef="n3">500000</us-gaap:InvestmentCompanyFinancialCommitmentToInvesteeFutureAmount>
</xbrl>"""

CONTEXTS = {
    "n1": {"period": "2026-03-31", "investment_identifier": "AGS Health LLC 1"},
    "n2": {"period": "2026-03-31", "investment_identifier": "Sotheby's, Revolver"},
    "n3": {"period": "2026-03-31", "investment_identifier": "No Such Company LLC"},
    "c30": {"period": "2026-03-31", "investment_identifier": "AGS Health LLC | Software & Services 1"},
    "c32": {"period": "2026-03-31", "investment_identifier": "AGS Health LLC | Software & Services 3"},
    "c640": {"period": "2026-03-31", "investment_identifier": "Sotheby's, Revolver | Consumer Services"},
    "p640": {"period": "2025-12-31", "investment_identifier": "Sotheby's, Revolver | Consumer Services"},
}
META = {"cik": "0001930679", "accession_number": "0001628280-26-034545"}


def _facts():
    return {
        # funded tranche: same principal as the commitment, cost below it
        "c30": {"fair_value": 1628000.0, "cost": 1675000.0, "principal_amount": 1679000.0},
        "c32": {"fair_value": 1628000.0, "cost": 1679000.0, "principal_amount": 1679000.0},
        "c640": {"fair_value": 31849000.0, "cost": 31849000.0, "principal_amount": 31849000.0},
        "p640": {"fair_value": 31849000.0, "cost": 31849000.0, "principal_amount": 31849000.0},
    }


@pytest.fixture
def netting(monkeypatch):
    monkeypatch.setattr(uc, "_netting_ciks", lambda: frozenset({"0001930679"}))


def test_a_commitment_row_is_published_net_and_keeps_its_committed_principal(netting):
    facts = _facts()
    assert uc.net_unfunded_rows(etree.ElementTree(etree.fromstring(XML)), CONTEXTS, facts, META) == 2
    assert facts["c32"]["fair_value"] == -51000.0 and facts["c32"]["cost"] == 0.0
    assert facts["c32"]["principal_amount"] == 1679000.0
    assert facts["c640"]["fair_value"] == 0.0 and facts["c640"]["cost"] == 0.0
    recorded = json.loads(facts["c32"]["src_facts"])
    assert recorded["fair_value"] == {"r": 1628000.0, "x": ["net_of_commitment:1679000.0"]}
    assert uc.net_offset(recorded["cost"]["x"]) == 1679000.0


def test_a_funded_row_and_a_row_of_another_date_are_left_alone(netting):
    facts = _facts()
    uc.net_unfunded_rows(etree.ElementTree(etree.fromstring(XML)), CONTEXTS, facts, META)
    assert facts["c30"] == {"fair_value": 1628000.0, "cost": 1675000.0, "principal_amount": 1679000.0}
    assert facts["p640"]["fair_value"] == 31849000.0


def test_a_filer_without_the_setting_is_untouched(monkeypatch):
    monkeypatch.setattr(uc, "_netting_ciks", lambda: frozenset())
    facts = _facts()
    assert uc.net_unfunded_rows(etree.ElementTree(etree.fromstring(XML)), CONTEXTS, facts, META) == 0
    assert facts == _facts()


def test_reconciliation_nets_without_recording_events(netting):
    facts = _facts()
    uc.net_unfunded_rows(etree.ElementTree(etree.fromstring(XML)), CONTEXTS, facts, META, record_events=False)
    assert facts["c640"]["fair_value"] == 0.0 and "src_facts" not in facts["c640"]


def test_the_row_whose_principal_equals_the_commitment_is_preferred():
    rows = [{"investment_identifier": "A-Lign Assurance LLC | Software 1", "cost": 3287.0, "principal_amount": 3303.0},
            {"investment_identifier": "A-Lign Assurance LLC | Software 2", "cost": 3287.0, "principal_amount": 3287.0},
            {"investment_identifier": "A-Lign Assurance LLC Holdings | Software", "cost": 9.0, "principal_amount": 9.0}]
    matched, unmatched = uc.match_commitments([("A-Lign Assurance LLC 1", 3287.0), ("A-Lign Assurance LLC 2", 3287.0),
                                               ("A-Lign Assurance LLC 3", 77.0)], rows)
    assert [row["investment_identifier"][-1] for row, _ in matched] == ["2", "1"]
    assert unmatched == [("A-Lign Assurance LLC 3", 77.0)]


def test_net_offset_ignores_other_events():
    assert uc.net_offset(["decimals_rescale:10^-3"]) == 0.0
    assert uc.net_offset(None) == 0.0


def test_the_setting_admits_one_value(tmp_path):
    from pipeline.source_encodings import load_encodings
    wrapper = {"schema_version": "bdc-xbrl-wrapper.v3", "cik": "0001930679",
               "source_encodings": {"unfunded_rows": ["net_of_tagged_commitment"]}}
    (tmp_path / "0001930679.json").write_text(json.dumps(wrapper), encoding="utf-8")
    assert load_encodings(tmp_path)["0001930679"]["unfunded_rows"] == ["net_of_tagged_commitment"]
    wrapper["source_encodings"]["unfunded_rows"] = ["drop"]
    (tmp_path / "0001930679.json").write_text(json.dumps(wrapper), encoding="utf-8")
    with pytest.raises(ValueError, match="unfunded row handling"):
        load_encodings(tmp_path)


# --- net_of_other_commitment (Manulife Private Credit Fund, 0001988280; MLF-R1, owner ruling D-091) ---

MLF = "0001988280"
MLF_META = {"cik": MLF, "accession_number": "0001193125-26-219274", "report_date": "2026-03-31"}
OTHER_XML = """<xbrl xmlns:us-gaap="http://fasb.org/us-gaap/2025">
  <us-gaap:OtherCommitment contextRef="k_rev">528000</us-gaap:OtherCommitment>
  <us-gaap:OtherCommitment contextRef="k_ddtl">0</us-gaap:OtherCommitment>
  <us-gaap:OtherCommitment contextRef="l_ddtl">1500000</us-gaap:OtherCommitment>
  <us-gaap:OtherCommitment contextRef="p_rev">313433</us-gaap:OtherCommitment>
  <us-gaap:OtherCommitment contextRef="k_rev_prior">528000</us-gaap:OtherCommitment>
</xbrl>"""


def _commitment_context(entity, facility, period="2026-03-31"):
    return {"period": period, "investment_identifier": "", "is_investment": False,
            "dimensions_raw": "creditfacilityaxis=%sMember|legalentityaxis=%sMember|othercommitmentsaxis="
                              "UnfundedDebtAndEquityCommitmentsMember" % (facility, entity)}


def _row_context(name, period="2026-03-31"):
    return {"period": period, "investment_identifier": "Senior loans 238.9% | Leisure products 2.2% | " + name,
            "is_investment": True, "dimensions_raw": "investmentidentifieraxis=" + name}


OTHER_CONTEXTS = {
    "k_rev": _commitment_context("FourMCapitalLtd", "Revolver"),
    "k_ddtl": _commitment_context("FourMCapitalLtd", "DelayedDrawTermLoan"),
    "l_ddtl": _commitment_context("LeapServicePartnersLLC", "DelayedDrawTermLoan"),
    "p_rev": _commitment_context("PakQualityFoodsAcquisitionLlc", "Revolver"),
    "k_rev_prior": _commitment_context("FourMCapitalLtd", "Revolver", "2025-12-31"),
    "r_k_rev": _row_context("4M Capital, Ltd., Revolver"),
    "r_k_tl": _row_context("4M Capital, Ltd., Term Loan (3 month CME Term SOFR + 5.000%)"),
    "r_l_dd": _row_context("Leap Service Partners LLC, Delayed Draw Term Loan (3 month CME Term SOFR + 5.250%)"),
    "r_l_ddb": _row_context("Leap Service Partners LLC, Delayed Draw Term Loan B (3 month CME Term SOFR + 5.250%)"),
    "r_l_dd_undrawn": _row_context("Leap Service Partners LLC, Delayed Draw Term Loan C"),
    "r_p_rev": _row_context("PAK Quality Foods Acquisition LLC, Revolver"),
    "r_k_rev_prior": _row_context("4M Capital, Ltd., Revolver", "2025-12-31"),
}

SCHEDULE_LABELS = [
    ("4M Capital, Ltd., Revolver (C)", "r_k_rev"),
    ("4M Capital, Ltd., Term Loan", "r_k_tl"),
    ("Leap Service Partners LLC, Delayed Draw Term Loan", "r_l_dd"),
    ("Leap Service Partners LLC, Delayed Draw Term Loan B (C)", "r_l_ddb"),
    ("Leap Service Partners LLC, Delayed Draw Term Loan C (C)", "r_l_dd_undrawn"),
    ("PAK Quality Foods Acquisition LLC, Revolver (C)", "r_p_rev"),
    ("4M Capital, Ltd., Revolver (C)", "r_k_rev_prior"),
]


def _note_row(issuer, *contexts):
    cells = "".join('<td><ix:nonFraction name="us-gaap:OtherCommitment" contextRef="%s">1</ix:nonFraction></td>' % c
                    for c in contexts)
    return "<tr><td><p>%s</p></td><td>-</td>%s</tr>" % (issuer, cells)


def _schedule_row(label, context):
    return ('<tr><td>%s</td><td>-</td><td><ix:nonFraction contextRef="%s" name="us-gaap:InvestmentOwnedAtFairValue">'
            '1</ix:nonFraction></td></tr>' % (label, context))


def _page(labels=SCHEDULE_LABELS):
    rows = [_note_row("4M Capital, Ltd.", "k_ddtl", "k_rev", "k_rev_prior"),
            _note_row("Leap Service Partners LLC", "l_ddtl"),
            _note_row("PAK Quality Foods Acqusition LLC", "p_rev")]
    rows += [_schedule_row(label, context) for label, context in labels]
    return "<html><body><table>%s</table></body></html>" % "".join(rows)


def _other_facts():
    return {
        "r_k_rev": {"fair_value": 527000.0, "principal_amount": 528000.0, "interest_rate": 0.0},
        "r_k_tl": {"fair_value": 3283933.0, "principal_amount": 3283933.0, "interest_rate": 0.087},
        "r_l_dd": {"fair_value": 1732700.0, "principal_amount": 1732700.0, "interest_rate": 0.0893},
        "r_l_ddb": {"fair_value": 2008810.0, "principal_amount": 2008810.0, "interest_rate": 0.0892},
        "r_l_dd_undrawn": {"fair_value": 498000.0, "principal_amount": 500000.0, "interest_rate": None},
        "r_p_rev": {"fair_value": 313433.0, "principal_amount": 313433.0, "interest_rate": 0.0},
        "r_k_rev_prior": {"fair_value": 528000.0, "principal_amount": 528000.0, "interest_rate": 0.0},
    }


def _write_page(html_dir, page):
    (html_dir / "1988280").mkdir(exist_ok=True)
    (html_dir / "1988280" / "000119312526219274.html").write_text(page, encoding="utf-8")


@pytest.fixture
def other_reading(monkeypatch, tmp_path):
    monkeypatch.setattr(uc, "_netting_ciks", lambda: frozenset())
    monkeypatch.setattr(uc, "_other_commitment_ciks", lambda: frozenset({MLF}))
    monkeypatch.setattr(uc, "_note_aliases_by_cik", lambda: {
        MLF: (("PAK Quality Foods Acqusition LLC", "PAK Quality Foods Acquisition LLC"),)})
    _write_page(tmp_path, _page())
    return tmp_path


def _run_other(html_dir, facts, contexts=OTHER_CONTEXTS, record_events=True):
    return uc.net_other_commitment_rows(etree.ElementTree(etree.fromstring(OTHER_XML)), contexts, facts, MLF_META,
                                        record_events=record_events, html_cache_dir=html_dir)


def test_other_commitment_goes_to_the_wholly_undrawn_row_by_par(other_reading):
    facts = _other_facts()
    _run_other(other_reading, facts)
    # 4M revolver: printed '4M Capital, Ltd., Revolver (C) - 06-18-27 528,000 528,000', note 528,000
    assert facts["r_k_rev"]["fair_value"] == -1000.0
    assert facts["r_k_rev"]["principal_amount"] == 528000.0
    recorded = json.loads(facts["r_k_rev"]["src_facts"])
    assert recorded["fair_value"] == {"r": 527000.0, "x": ["net_of_commitment:528000.0"]}
    assert uc.net_offset(recorded["fair_value"]["x"]) == 528000.0
    # no per-row cost printed: none is invented
    assert "cost" not in facts["r_k_rev"] and "cost" not in recorded
    # the funded term loan of the same issuer is another facility
    assert facts["r_k_tl"]["fair_value"] == 3283933.0 and "src_facts" not in facts["r_k_tl"]


def test_the_remainder_goes_to_the_single_c_marked_drawn_row(other_reading):
    facts = _other_facts()
    _run_other(other_reading, facts)
    # Leap DDTL 1,500,000: the undrawn row takes its par 500,000; of two drawn rows the one marked (C) takes 1,000,000
    assert facts["r_l_dd_undrawn"]["fair_value"] == -2000.0
    assert facts["r_l_ddb"]["fair_value"] == 1008810.0
    assert facts["r_l_dd"]["fair_value"] == 1732700.0 and "src_facts" not in facts["r_l_dd"]


def test_the_remainder_goes_to_the_single_drawn_row(other_reading):
    contexts = {k: v for k, v in OTHER_CONTEXTS.items() if k != "r_l_ddb"}
    facts = _other_facts()
    del facts["r_l_ddb"]
    _run_other(other_reading, facts, contexts)
    assert facts["r_l_dd"]["fair_value"] == 732700.0


def test_a_remainder_with_no_single_row_is_logged_not_forced(other_reading, caplog):
    # Manulife 2025-12-31: Leap and OIS each have several drawn delayed-draw rows marked (C)
    labels = [(label + " (C)" if context == "r_l_dd" else label, context) for label, context in SCHEDULE_LABELS]
    _write_page(other_reading, _page(labels))
    facts = _other_facts()
    with caplog.at_level("WARNING", logger="pipeline.unfunded_commitments"):
        _run_other(other_reading, facts)
    assert facts["r_l_dd"]["fair_value"] == 1732700.0 and facts["r_l_ddb"]["fair_value"] == 2008810.0
    assert facts["r_l_dd_undrawn"]["fair_value"] == -2000.0
    assert "unplaced Leap Service Partners LLC / delayed draw 1000000" in caplog.text


def test_a_note_spelling_reaches_its_row_through_the_alias(other_reading, monkeypatch):
    facts = _other_facts()
    _run_other(other_reading, facts)
    assert facts["r_p_rev"]["fair_value"] == 0.0
    monkeypatch.setattr(uc, "_note_aliases_by_cik", lambda: {})
    facts = _other_facts()
    _run_other(other_reading, facts)
    assert facts["r_p_rev"]["fair_value"] == 313433.0


def test_an_alias_is_not_used_where_the_note_spelling_names_a_row():
    rows = [{"label": "WWEC Holdings II Corp., Revolver", "principal_amount": 100.0, "interest_rate": 0.0},
            {"label": "WWEC Holdings III Corp., Revolver", "principal_amount": 100.0, "interest_rate": 0.0}]
    placed, left = uc.allocate_other_commitments([("WWEC Holdings II Corp.", "revolver", 100.0)], rows,
                                                 (("WWEC Holdings II Corp.", "WWEC Holdings III Corp."),))
    assert [row["label"] for row, _ in placed] == ["WWEC Holdings II Corp., Revolver"] and left == []


def test_a_row_belongs_to_the_longest_issuer_name():
    rows = [{"label": "Acme LLC Holdings, Revolver", "principal_amount": 50.0, "interest_rate": 0.0},
            {"label": "Acme LLC, Revolver", "principal_amount": 70.0, "interest_rate": 0.0}]
    placed, left = uc.allocate_other_commitments([("Acme LLC", "revolver", 50.0),
                                                  ("Acme LLC Holdings", "revolver", 50.0)], rows)
    # 'Acme LLC' 50 does not fit its own undrawn row of par 70, and is not put on Acme LLC Holdings' row
    assert [(row["label"], amount) for row, amount in placed] == [("Acme LLC Holdings, Revolver", 50.0)]
    assert left == [("Acme LLC", "revolver", 50.0)]


def test_the_comparative_column_is_not_read(other_reading):
    facts = _other_facts()
    _run_other(other_reading, facts)
    assert facts["r_k_rev_prior"] == _other_facts()["r_k_rev_prior"]


def test_a_redated_context_carrying_the_fair_value_is_netted_with_its_dated_row(other_reading):
    # Manulife 10-K 2024-12-31, Integrated Openings DDTL: par on the dated context, fair value on a re-dated one
    contexts = dict(OTHER_CONTEXTS)
    contexts["r_k_rev_redated"] = dict(contexts["r_k_rev"])
    facts = _other_facts()
    facts["r_k_rev"] = {"principal_amount": 528000.0, "interest_rate": 0.0}
    facts["r_k_rev_redated"] = {"fair_value": 527000.0}
    _run_other(other_reading, facts, contexts)
    assert facts["r_k_rev_redated"]["fair_value"] == -1000.0 and "fair_value" not in facts["r_k_rev"]
    # both contexts carry the event, so whichever the deduplication keeps replays it
    for context in ("r_k_rev", "r_k_rev_redated"):
        assert json.loads(facts[context]["src_facts"])["fair_value"] == {"r": 527000.0,
                                                                          "x": ["net_of_commitment:528000.0"]}


def test_other_reading_without_events_for_reconciliation(other_reading):
    facts = _other_facts()
    _run_other(other_reading, facts, record_events=False)
    assert facts["r_k_rev"]["fair_value"] == -1000.0 and "src_facts" not in facts["r_k_rev"]


def test_a_missing_page_nets_nothing(other_reading, tmp_path_factory):
    facts = _other_facts()
    assert _run_other(tmp_path_factory.mktemp("empty"), facts) == 0
    assert facts == _other_facts()


def test_a_fund_not_opted_in_is_untouched_by_other_commitment_facts(monkeypatch):
    monkeypatch.setattr(uc, "_netting_ciks", lambda: frozenset())
    monkeypatch.setattr(uc, "_other_commitment_ciks", lambda: frozenset())
    facts = _other_facts()
    assert uc.net_unfunded_rows(etree.ElementTree(etree.fromstring(OTHER_XML)), OTHER_CONTEXTS, facts, MLF_META) == 0
    assert facts == _other_facts()


def test_a_tagged_commitment_fund_ignores_other_commitment_facts(netting, monkeypatch):
    # KKR's reading is unchanged: OtherCommitment facts in its filing change nothing
    monkeypatch.setattr(uc, "_other_commitment_ciks", lambda: frozenset({MLF}))
    xml = XML.replace("</xbrl>", '<us-gaap:OtherCommitment contextRef="n2">999</us-gaap:OtherCommitment></xbrl>')
    facts = _facts()
    assert uc.net_unfunded_rows(etree.ElementTree(etree.fromstring(xml)), CONTEXTS, facts, META) == 2
    expected = _facts()
    uc.net_unfunded_rows(etree.ElementTree(etree.fromstring(XML)), CONTEXTS, expected, META)
    assert facts == expected


def test_reading_signature_keeps_the_tagged_reading_and_names_the_other(monkeypatch):
    monkeypatch.setattr(uc, "_netting_ciks", lambda: frozenset({"0001930679"}))
    monkeypatch.setattr(uc, "_other_commitment_ciks", lambda: frozenset({MLF}))
    monkeypatch.setattr(uc, "_note_aliases_by_cik", lambda: {MLF: (("A Co", "B Co"),)})
    assert uc.reading_signature("1930679") == ["unfunded:net_of_tagged_commitment"]
    assert uc.reading_signature(MLF) == ["unfunded:net_of_other_commitment", "unfunded_alias:A Co => B Co"]
    assert uc.reading_signature("0001287750") == []


def test_the_setting_admits_the_other_reading_and_its_aliases(tmp_path):
    from pipeline.source_encodings import load_encodings
    wrapper = {"schema_version": "bdc-xbrl-wrapper.v3", "cik": MLF,
               "source_encodings": {"unfunded_rows": ["net_of_other_commitment"],
                                    "unfunded_note_aliases": ["PAK Quality Foods Acqusition LLC => "
                                                              "PAK Quality Foods Acquisition LLC"]}}
    path = tmp_path / (MLF + ".json")
    path.write_text(json.dumps(wrapper), encoding="utf-8")
    assert load_encodings(tmp_path)[MLF]["unfunded_rows"] == ["net_of_other_commitment"]
    wrapper["source_encodings"]["unfunded_note_aliases"] = ["no arrow here"]
    path.write_text(json.dumps(wrapper), encoding="utf-8")
    with pytest.raises(ValueError, match="NOTE NAME => SCHEDULE NAME"):
        load_encodings(tmp_path)
    wrapper["source_encodings"] = {"unfunded_rows": ["net_of_tagged_commitment"],
                                   "unfunded_note_aliases": ["A => B"]}
    path.write_text(json.dumps(wrapper), encoding="utf-8")
    with pytest.raises(ValueError, match="needs unfunded_rows net_of_other_commitment"):
        load_encodings(tmp_path)


def test_the_wrappers_set_each_reading():
    from pipeline.source_encodings import load_encodings
    encodings = load_encodings()
    assert encodings[MLF]["unfunded_rows"] == ["net_of_other_commitment"]
    assert "PAK Quality Foods Acqusition LLC => PAK Quality Foods Acquisition LLC" in encodings[MLF]["unfunded_note_aliases"]
    assert encodings["0001930679"]["unfunded_rows"] == ["net_of_tagged_commitment"]
    assert encodings["0001975736"]["unfunded_rows"] == ["net_of_tagged_commitment"]
    assert sorted(cik for cik, e in encodings.items() if e.get("unfunded_rows")) == ["0001930679", "0001975736", MLF]


# --- issuer-only commitments (Manulife 10-Q 2026-06-30, Founders Table Holdings LLC; D-222 review) ---

FT_META = {"cik": MLF, "accession_number": "0001193125-26-348951", "report_date": "2026-06-30"}
FT = "Founders Table Holdings LLC"


def _ft_xml(*amounts):
    facts = "".join('<us-gaap:OtherCommitment contextRef="f_iss">%s</us-gaap:OtherCommitment>' % a for a in amounts)
    return '<xbrl xmlns:us-gaap="http://fasb.org/us-gaap/2025">%s</xbrl>' % facts


FT_CONTEXTS = {
    # the filer's context carries the issuer only: no CreditFacilityAxis, no OtherCommitmentsAxis
    "f_iss": {"period": "2026-06-30", "investment_identifier": "", "is_investment": False,
              "dimensions_raw": "legalentityaxis=FoundersTableHoldingsLLCMember"},
    "r_f_dd": _row_context(FT + ", Delayed Draw Term Loan", "2026-06-30"),
    "r_f_rev": _row_context(FT + ", Revolver", "2026-06-30"),
    "r_f_tl": _row_context(FT + ", Term Loan (1 month CME Term SOFR + 6.250%)", "2026-06-30"),
}


def _ft_facts():
    # printed: DDTL (C) - 06-12-31 156,661 155,094; Revolver (C) - 06-12-31 156,661 153,527
    return {
        "r_f_dd": {"fair_value": 155094.0, "principal_amount": 156661.0, "interest_rate": 0.0},
        "r_f_rev": {"fair_value": 153527.0, "principal_amount": 156661.0, "interest_rate": 0.0},
        "r_f_tl": {"fair_value": 2000000.0, "principal_amount": 2000000.0, "interest_rate": 0.09894},
    }


def _ft_page(*cells):
    note = "".join('<td><ix:nonFraction name="us-gaap:OtherCommitment" contextRef="f_iss">%s</ix:nonFraction></td>'
                   % cell for cell in cells)
    rows = ["<tr><td><p>%s</p></td><td>$</td>%s</tr>" % (FT, note)]
    rows += [_schedule_row(label, context) for label, context in (
        (FT + ", Delayed Draw Term Loan (C)", "r_f_dd"), (FT + ", Revolver (C)", "r_f_rev"),
        (FT + ", Term Loan (1 month CME Term SOFR + 6.250%) (D)", "r_f_tl"))]
    return "<html><body><table>%s</table></body></html>" % "".join(rows)


def _run_ft(monkeypatch, tmp_path, xml, page, facts):
    monkeypatch.setattr(uc, "_netting_ciks", lambda: frozenset())
    monkeypatch.setattr(uc, "_other_commitment_ciks", lambda: frozenset({MLF}))
    monkeypatch.setattr(uc, "_note_aliases_by_cik", lambda: {})
    (tmp_path / "1988280").mkdir(exist_ok=True)
    (tmp_path / "1988280" / "000119312526348951.html").write_text(page, encoding="utf-8")
    return uc.net_other_commitment_rows(etree.ElementTree(etree.fromstring(xml)), FT_CONTEXTS, facts, FT_META,
                                        html_cache_dir=tmp_path)


def test_an_issuer_only_commitment_nets_the_undrawn_rows_it_sums_to(monkeypatch, tmp_path):
    facts = _ft_facts()
    assert _run_ft(monkeypatch, tmp_path, _ft_xml(156661, 156661), _ft_page("156,661", "156,661"), facts) == 2
    assert facts["r_f_dd"]["fair_value"] == 155094.0 - 156661.0
    assert facts["r_f_rev"]["fair_value"] == 153527.0 - 156661.0
    assert facts["r_f_dd"]["principal_amount"] == 156661.0
    assert json.loads(facts["r_f_rev"]["src_facts"])["fair_value"] == {"r": 153527.0,
                                                                      "x": ["net_of_commitment:156661.0"]}
    # the drawn term loan of the same issuer is not touched
    assert facts["r_f_tl"] == _ft_facts()["r_f_tl"]


def test_an_issuer_only_commitment_that_is_not_exact_is_left_whole(monkeypatch, tmp_path, caplog):
    facts = _ft_facts()
    with caplog.at_level("WARNING", logger="pipeline.unfunded_commitments"):
        netted = _run_ft(monkeypatch, tmp_path, _ft_xml(100000, 100000), _ft_page("100,000", "100,000"), facts)
    assert netted == 0 and facts == _ft_facts()
    assert "unplaced Founders Table Holdings LLC / no facility 200000" in caplog.text


def test_an_issuer_only_commitment_that_matches_one_row_of_two_is_left_whole(monkeypatch, tmp_path):
    # 156,661 alone: not the two rows' sum, and its one cell matches two rows of that par
    facts = _ft_facts()
    assert _run_ft(monkeypatch, tmp_path, _ft_xml(156661), _ft_page("156,661"), facts) == 0
    assert facts == _ft_facts()


def test_the_printed_cells_place_an_issuer_only_commitment_when_the_rows_do_not_sum():
    rows = [{"label": "X LLC, Revolver", "principal_amount": 100.0, "interest_rate": 0.0},
            {"label": "X LLC, Delayed Draw Term Loan", "principal_amount": 50.0, "interest_rate": None},
            {"label": "X LLC, Delayed Draw Term Loan B", "principal_amount": 70.0, "interest_rate": 0.0}]
    placed, left = uc.allocate_other_commitments([], rows, (), [("X LLC", 150.0, (100.0, 50.0))])
    assert [(row["label"], amount) for row, amount in placed] == [("X LLC, Delayed Draw Term Loan", 50.0),
                                                                    ("X LLC, Revolver", 100.0)]
    assert left == []
    # cells that do not determine the rows (two cells of 100, three rows of par 100) place nothing
    rows = [{"label": "X LLC, Revolver %d" % n, "principal_amount": 100.0, "interest_rate": 0.0} for n in range(3)]
    placed, left = uc.allocate_other_commitments([], rows, (), [("X LLC", 200.0, (100.0, 100.0))])
    assert placed == [] and left == [("X LLC", uc.NO_FACILITY, 200.0)]


def test_an_issuer_only_commitment_counts_only_revolver_and_delayed_draw_rows():
    rows = [{"label": "X LLC, Class A Units", "principal_amount": 100.0, "interest_rate": None},
            {"label": "X LLC, Revolver", "principal_amount": 100.0, "interest_rate": 0.0}]
    placed, left = uc.allocate_other_commitments([], rows, (), [("X LLC", 100.0, ())])
    assert [row["label"] for row, _ in placed] == ["X LLC, Revolver"] and left == []


def test_an_issuer_only_commitment_takes_no_row_a_facility_commitment_took():
    rows = [{"label": "X LLC, Revolver", "principal_amount": 100.0, "interest_rate": 0.0},
            {"label": "X LLC, Delayed Draw Term Loan", "principal_amount": 40.0, "interest_rate": 0.0}]
    placed, left = uc.allocate_other_commitments([("X LLC", "revolver", 100.0)], rows, (), [("X LLC", 40.0, ())])
    assert [(row["label"], amount) for row, amount in placed] == [("X LLC, Revolver", 100.0),
                                                                    ("X LLC, Delayed Draw Term Loan", 40.0)]
    assert left == []


def test_note_row_values_reads_the_printed_cells_of_one_row():
    page = _ft_page("156,661", "156,661")
    assert uc.note_row_values(page) == {"f_iss": (156661.0, 156661.0)}
    # the same context on two rows is not read
    twice = page.replace("</table>", "<tr><td>Other</td><td><ix:nonFraction name=\"us-gaap:OtherCommitment\" "
                                     "contextRef=\"f_iss\">5</ix:nonFraction></td></tr></table>")
    assert uc.note_row_values(twice) == {}
