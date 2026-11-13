"""Round-2 retirement-campaign checks (scripts/v05_evidence/campaign_round2_check.py) on a synthetic
inline-XBRL filing: each mode passes on a real case and fails on the realistic plant for its rule."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "v05_evidence"))

import campaign_retirement_check as base  # noqa: E402
import campaign_round2_check as c2  # noqa: E402

RD = "2026-03-31"
CIK = "0000000002"
ACC = "0000000002-26-000001"
PAGE = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
 xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:xbrldi="http://xbrl.org/2006/xbrldi"
 xmlns:us-gaap="http://fasb.org/us-gaap/2025"><body>
<div style="display:none"><ix:header><ix:resources>{contexts}
<xbrli:unit id="usd"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>
<xbrli:unit id="eur"><xbrli:measure>iso4217:EUR</xbrli:measure></xbrli:unit>
</ix:resources></ix:header></div>
<table>
<tr><td>Delta Leasing SPV</td><td>Term Loan</td>
 <td><ix:nonFraction name="us-gaap:InvestmentInterestRate" contextRef="d1" scale="-2">3.00</ix:nonFraction> % Cash</td>
 <td><ix:nonFraction name="us-gaap:InvestmentInterestRatePaidInKind" contextRef="d1" scale="-2">7.00</ix:nonFraction> %</td>
 <td><ix:nonFraction name="us-gaap:InvestmentOwnedAtCost" unitRef="usd" contextRef="d1" scale="3">990</ix:nonFraction></td>
 <td><ix:nonFraction name="us-gaap:InvestmentOwnedAtFairValue" unitRef="usd" contextRef="d1" scale="3">1,000</ix:nonFraction></td></tr>
<tr><td>Euro Bidco</td><td>First Lien</td><td>EUR</td>
 <td><ix:nonFraction name="us-gaap:InvestmentOwnedBalancePrincipalAmount" unitRef="eur" contextRef="d2" scale="3">800</ix:nonFraction></td>
 <td><ix:nonFraction name="us-gaap:InvestmentOwnedAtCost" unitRef="usd" contextRef="d2" scale="3">850</ix:nonFraction></td>
 <td><ix:nonFraction name="us-gaap:InvestmentOwnedAtFairValue" unitRef="usd" contextRef="d2" scale="3">860</ix:nonFraction></td></tr>
<tr><td>Euro Two</td><td>First Lien</td><td>EUR</td>
 <td><ix:nonFraction name="us-gaap:InvestmentOwnedBalancePrincipalAmount" unitRef="eur" contextRef="d3" scale="3">400</ix:nonFraction></td>
 <td><ix:nonFraction name="us-gaap:InvestmentOwnedAtFairValue" unitRef="usd" contextRef="d3" scale="3">430</ix:nonFraction></td></tr>
</table></body></html>"""


def _ctx(cid, member):
    return ("<xbrli:context id=\"%s\"><xbrli:entity><xbrli:identifier scheme=\"x\">1</xbrli:identifier><xbrli:segment>"
            "<xbrldi:typedMember dimension=\"us-gaap:InvestmentIdentifierAxis\"><us-gaap:InvestmentIdentifierAxis.domain>"
            "%s</us-gaap:InvestmentIdentifierAxis.domain></xbrldi:typedMember></xbrli:segment></xbrli:entity>"
            "<xbrli:period><xbrli:instant>%s</xbrli:instant></xbrli:period></xbrli:context>" % (cid, member, RD))


@pytest.fixture
def fl(tmp_path, monkeypatch):
    p = tmp_path / "f.html"
    p.write_text(PAGE.replace("{contexts}", _ctx("d1", "Delta TL") + _ctx("d2", "Euro TL") + _ctx("d3", "Euro 2")),
                 encoding="utf-8")
    f = base.Filing(CIK, ACC, path=p)
    getter = lambda cik, acc: f if acc == ACC else base.Filing(cik, acc, path=tmp_path / "missing")  # noqa: E731
    monkeypatch.setattr(base, "filing", getter)
    monkeypatch.setattr(c2, "filing", getter)
    return f


def _row(rid, ctx, fv, **kw):
    import hashlib
    rid = "ROW-" + hashlib.md5(("bdc|%s|%s" % (ACC, ctx)).encode()).hexdigest()[:16]   # bound to its context
    r = {"row_id": rid, "cik": CIK, "accession_number": ACC, "src_context_id": ctx, "report_date": RD,
         "fair_value": fv, "shares_held": None, "pct_of_net_assets": None, "asset_category": "FIRST_LIEN",
         "index_classification": "DIRECT_LENDING", "record_class": "parent_schedule", "issuer_name": "",
         "instrument_description": "", "asset_class": "PRIVATE_CREDIT", "cost": None, "interest_rate": None,
         "basis_spread": None, "pik_rate": None, "principal_amount": None, "principal_amount_currency": None,
         "principal_amount_usd": None, "fair_value_currency": "USD"}
    r.update(kw)
    return r


@pytest.fixture
def rows():
    eur = c2.h10_rate("EUR", RD)
    assert eur, "the H.10 reference covers EUR at the test date"
    return [_row("A", "d1", 1_000_000.0, issuer_name="Delta Leasing SPV", cost=990_000.0, interest_rate=10.0, pik_rate=7.0),
            _row("B", "d2", 860_000.0, issuer_name="Euro Bidco", cost=850_000.0, principal_amount=800_000.0,
                 principal_amount_currency="EUR", principal_amount_usd=800_000.0 * eur),
            _row("C", "d3", 430_000.0, issuer_name="Euro Two", principal_amount=400_000.0,
                 principal_amount_currency="EUR", principal_amount_usd=400_000.0 * eur)]


def test_pik_all_in_passes_and_cash_leg_fails(fl, rows):
    spec = {"rate": [{"issuer": "Delta Leasing"}]}
    assert c2.check("pik_le_interest_rate", spec, None, "", CIK, RD, rows=rows)["ok"]
    cash = [dict(r, interest_rate=3.0) if r["src_context_id"] == "d1" else r for r in rows]
    assert not c2.check("pik_le_interest_rate", spec, None, "", CIK, RD, rows=cash)["ok"]
    for name, p in c2.plants("pik_le_interest_rate", spec, rows):
        assert not c2.check("pik_le_interest_rate", spec, None, "", CIK, RD, rows=p)["ok"], name


def test_fx01_passes_and_plants_fail(fl, rows):
    assert c2.check("FX01", {}, None, "", CIK, RD, rows=rows)["ok"]
    for name, p in c2.plants("FX01", {}, rows):
        assert not c2.check("FX01", {}, None, "", CIK, RD, rows=p)["ok"], name


def test_fx01_with_no_foreign_line_is_not_confirmed(fl, rows):
    assert not c2.check("FX01", {}, None, "", CIK, RD, rows=[rows[0]])["ok"]


def test_fx02_foreign_unit_fails(fl, rows):
    assert c2.check("FX02", {}, None, "", CIK, RD, rows=rows)["ok"]
    for name, p in c2.plants("FX02", {}, rows):
        assert not c2.check("FX02", {}, None, "", CIK, RD, rows=p)["ok"], name


def test_x07_cost_must_be_its_own_printed_cost(fl, rows):
    assert c2.check("X07", {}, None, "", CIK, RD, rows=rows)["ok"]
    for name, p in c2.plants("X07", {}, rows):
        assert not c2.check("X07", {}, None, "", CIK, RD, rows=p)["ok"], name


def test_printed_currency_ignores_benchmark_names():
    assert c2.printed_currency("Flexera | EURIBOR + 4.50 % | 2,836") is None
    assert c2.printed_currency("Total Power | CORRA + 450 | C$ | 8,690") == "CAD"
    assert c2.printed_currency("X | GBP | 1 | EUR | 2") == "AMBIGUOUS"


def test_fx02_context_swap_between_equal_values_fails(fl, rows):
    same = [dict(r, fair_value=430_000.0) if r["src_context_id"] == "d2" else r for r in rows]
    a, b = same[1], same[2]
    swapped = [dict(r, src_context_id="d3") if r is a else dict(r, src_context_id="d2") if r is b else r for r in same]
    assert not c2.check("FX02", {}, None, "", CIK, RD, rows=swapped)["ok"]


def test_pik_without_a_cash_label_fails_closed(fl, rows, monkeypatch):
    # the stated rate is not labelled cash on the line: it may be the all-in coupon, so no expectation
    monkeypatch.setattr(base, "row_line", lambda r: "Delta Leasing SPV Term Loan 3.00 % 7.00 % 990 1,000")
    exp, why = c2.all_in_expected(rows[0])
    assert exp is None and "does not label" in why
