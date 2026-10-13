"""A cost tagged in dollars and again in a foreign unit: the foreign fact is the par."""
import io
import json

import pytest
from lxml import etree

from pipeline import cost_in_two_units as ctu
from pipeline import page_labelled_contexts as plc

APOLLO = "0001837532"
META = {"cik": "1837532", "accession_number": "0001193125-26-102386"}


def _tree(facts):
    body = "".join('<us-gaap:%s contextRef="%s" unitRef="%s" decimals="-3">%s</us-gaap:%s>' % (name, ctx, unit, value, name)
                   for ctx, name, unit, value in facts)
    xml = ('<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:iso4217="http://www.xbrl.org/2003/iso4217" '
           'xmlns:us-gaap="http://fasb.org/us-gaap/2025">'
           '<xbrli:unit id="U_USD"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>'
           '<xbrli:unit id="U_EUR"><xbrli:measure>iso4217:EUR</xbrli:measure></xbrli:unit>'
           '<xbrli:unit id="U_shares"><xbrli:measure>xbrli:shares</xbrli:measure></xbrli:unit>'
           + body + '</xbrli:xbrl>')
    return etree.parse(io.BytesIO(xml.encode("utf-8")))


@pytest.fixture
def reading(monkeypatch):
    monkeypatch.setattr(ctx_module(), "_reading_ciks", lambda: frozenset({APOLLO}))


def ctx_module():
    return ctu


def test_foreign_cost_fact_becomes_the_par_and_the_dollar_fact_the_cost(reading):
    # JOA Joker Holdco 3, printed 'EUR 126,725 132,847 147,810': the extractor kept the first (euro) fact as cost
    tree = _tree([("C_1", "InvestmentOwnedAtCost", "U_EUR", "126725000"), ("C_1", "InvestmentOwnedAtCost", "U_USD", "132847000")])
    facts = {"C_1": {"cost": 126725000.0, "cost_unit": "U_EUR", "fair_value": 147810000.0}}
    assert ctu.settle_cost_in_two_units(tree, facts, META) == 1
    row = facts["C_1"]
    assert (row["cost"], row["cost_unit"], row["principal_amount"], row["principal_amount_unit"]) == (132847000.0, "U_USD", 126725000.0, "U_EUR")
    events = json.loads(row["src_facts"])
    assert events["cost"] == {"r": 132847000.0, "x": ["cost:of_two_units:U_USD"]}
    assert ctu.declared_unit("principal_amount", events["principal_amount"]["x"]) == "U_EUR"
    assert ctu.declared_unit("cost", events["cost"]["x"]) == "U_USD"
    assert ctu.declared_unit("fair_value", events["cost"]["x"]) is None


def test_a_tagged_principal_is_kept(reading):
    tree = _tree([("C_1", "InvestmentOwnedAtCost", "U_EUR", "500"), ("C_1", "InvestmentOwnedAtCost", "U_USD", "600")])
    facts = {"C_1": {"cost": 500.0, "principal_amount": 550.0, "principal_amount_unit": "U_EUR"}}
    assert ctu.settle_cost_in_two_units(tree, facts, META, record_events=False) == 1
    assert (facts["C_1"]["cost"], facts["C_1"]["principal_amount"]) == (600.0, 550.0)
    assert "src_facts" not in facts["C_1"]


def test_contexts_that_are_not_one_dollar_and_one_foreign_fact_are_left_alone(reading):
    tree = _tree([("C_1", "InvestmentOwnedAtCost", "U_USD", "100"),                                             # one fact
                  ("C_2", "InvestmentOwnedAtCost", "U_USD", "100"), ("C_2", "InvestmentOwnedAtCost", "U_USD", "100"),  # the same fact twice
                  ("C_3", "InvestmentOwnedAtCost", "U_USD", "100"), ("C_3", "InvestmentOwnedAtCost", "U_shares", "90"),  # not a currency
                  ("C_4", "InvestmentOwnedAtCost", "U_EUR", "90"), ("C_4", "InvestmentOwnedAtFairValue", "U_USD", "100")])  # another concept
    facts = {c: {"cost": 100.0} for c in ("C_1", "C_2", "C_3")} | {"C_4": {"cost": 90.0, "fair_value": 100.0}}
    before = json.dumps(facts, sort_keys=True)
    assert ctu.settle_cost_in_two_units(tree, facts, META) == 0
    assert json.dumps(facts, sort_keys=True) == before


def test_a_filer_without_the_setting_is_not_read_this_way(monkeypatch):
    monkeypatch.setattr(ctu, "_reading_ciks", lambda: frozenset())
    tree = _tree([("C_1", "InvestmentOwnedAtCost", "U_EUR", "126725000"), ("C_1", "InvestmentOwnedAtCost", "U_USD", "132847000")])
    facts = {"C_1": {"cost": 126725000.0}}
    assert ctu.settle_cost_in_two_units(tree, facts, META) == 0
    assert facts == {"C_1": {"cost": 126725000.0}}


def test_an_untagged_principal_can_carry_its_currency(monkeypatch):
    # SumUp, printed 'EUR 40,000 42,858 42,303': no principal fact; the par is in euros
    monkeypatch.setattr(plc, "_untagged_by_accession", lambda: {(APOLLO, "A"): {"C_1": {"principal_amount": 40000000.0},
                                                                                "C_2": {"principal_amount": 5.0}}})
    monkeypatch.setattr(plc, "_untagged_currency", lambda: {(APOLLO, "A", "C_1"): "EUR"})
    facts = {"C_1": {"cost": 42858000.0}, "C_2": {"cost": 5.0}}
    assert plc.fill_untagged_values(facts, {"cik": "1837532", "accession_number": "A"}) == 2
    assert facts["C_1"]["principal_amount_unit"] == "EUR"
    assert "principal_amount_unit" not in facts["C_2"]
    match = plc._UNTAGGED_RE.fullmatch("0000950170-24-094137 C_x principal_amount 40000000 EUR")
    assert match and match.group(5) == "EUR"
    assert plc._UNTAGGED_RE.fullmatch("0000950170-24-094137 C_x principal_amount 40000000").group(5) is None
