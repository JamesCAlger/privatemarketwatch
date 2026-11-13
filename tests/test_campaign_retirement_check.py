"""The verdict-retirement campaign check (scripts/v05_evidence/campaign_retirement_check.py), on a
synthetic inline-XBRL filing: each rule passes on a real case and fails on realistic plants."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "v05_evidence"))

import campaign_retirement_check as chk  # noqa: E402

RD = "2026-03-31"
CIK = "0000000001"
ACC = "0000000001-26-000001"

PAGE = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
 xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:xbrldi="http://xbrl.org/2006/xbrldi"
 xmlns:us-gaap="http://fasb.org/us-gaap/2025"><body>
<div style="display:none"><ix:header><ix:resources>
{contexts}
<xbrli:unit id="usd"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>
</ix:resources></ix:header></div>
<table>
<tr><td>Acme Corp</td><td>First Lien Term Loan</td>
 <td><ix:nonFraction name="us-gaap:InvestmentOwnedPercentOfNetAssets" contextRef="c1" scale="-2">1.2</ix:nonFraction> %</td>
 <td><ix:nonFraction name="us-gaap:InvestmentOwnedAtFairValue" unitRef="usd" contextRef="c1" scale="3">1,000</ix:nonFraction></td></tr>
<tr><td>Acme Corp</td><td>Common Stock</td>
 <td><ix:nonFraction name="us-gaap:InvestmentOwnedBalanceShares" contextRef="c2" scale="0">500</ix:nonFraction></td>
 <td><ix:nonFraction name="us-gaap:InvestmentOwnedPercentOfNetAssets" contextRef="c2" scale="-2">0.3</ix:nonFraction> %</td>
 <td><ix:nonFraction name="us-gaap:InvestmentOwnedAtFairValue" unitRef="usd" contextRef="c2" scale="3">300</ix:nonFraction></td></tr>
<tr><td>Total investments</td>
 <td><ix:nonFraction name="us-gaap:InvestmentOwnedAtFairValue" unitRef="usd" contextRef="c0" scale="3">1,300</ix:nonFraction></td></tr>
<tr><td>Money Market Fund</td>
 <td><ix:nonFraction name="us-gaap:InvestmentOwnedAtCost" unitRef="usd" contextRef="c3" scale="3">200</ix:nonFraction></td> <td><ix:nonFraction name="us-gaap:InvestmentOwnedAtFairValue" unitRef="usd" contextRef="c3" scale="3">200</ix:nonFraction></td></tr>
<tr><td>Cash equivalents</td>
 <td><ix:nonFraction name="us-gaap:CashEquivalentsAtCarryingValue" unitRef="usd" contextRef="c0" scale="3">200</ix:nonFraction></td></tr>
<tr><td>Acme Corp (December 31, 2025)</td><td>First Lien Term Loan</td>
 <td><ix:nonFraction name="us-gaap:InvestmentOwnedAtFairValue" unitRef="usd" contextRef="cp" scale="3">950</ix:nonFraction></td></tr>
<tr><td>Total non-controlled investments</td>
 <td><ix:nonFraction name="us-gaap:InvestmentOwnedAtFairValue" unitRef="usd" contextRef="cs" scale="3">1,000</ix:nonFraction></td></tr>
<tr><td>Gamma Holdings</td><td>Preferred</td>
 <td><ix:nonFraction name="us-gaap:InvestmentOwnedAtFairValue" unitRef="usd" contextRef="c5" scale="6">16.9</ix:nonFraction></td></tr>
</table>
<table>
<tr><td>Beta LLC (affiliate roll-forward)</td>
 <td><ix:nonFraction name="us-gaap:InvestmentOwnedAtFairValue" unitRef="usd" contextRef="c4p" scale="3">40</ix:nonFraction></td>
 <td><ix:nonFraction name="us-gaap:InvestmentOwnedAtFairValue" unitRef="usd" contextRef="c4" scale="3">45</ix:nonFraction></td></tr>
</table></body></html>"""

SUBTOTAL_CTX = ("<xbrli:context id=\"cs\"><xbrli:entity><xbrli:identifier scheme=\"x\">1</xbrli:identifier><xbrli:segment>"
                "<xbrldi:explicitMember dimension=\"us-gaap:InvestmentTypeAxis\">x:NonControlledMember</xbrldi:explicitMember>"
                "</xbrli:segment></xbrli:entity><xbrli:period><xbrli:instant>%s</xbrli:instant></xbrli:period></xbrli:context>" % "2026-03-31")


def _ctx(cid, instant, member=None):
    seg = ("<xbrli:segment><xbrldi:typedMember dimension=\"us-gaap:InvestmentIdentifierAxis\">"
           "<us-gaap:InvestmentIdentifierAxis.domain>%s</us-gaap:InvestmentIdentifierAxis.domain>"
           "</xbrldi:typedMember></xbrli:segment>" % member) if member else ""
    return ("<xbrli:context id=\"%s\"><xbrli:entity><xbrli:identifier scheme=\"x\">1</xbrli:identifier>%s"
            "</xbrli:entity><xbrli:period><xbrli:instant>%s</xbrli:instant></xbrli:period></xbrli:context>"
            % (cid, seg, instant))


@pytest.fixture
def fl(tmp_path, monkeypatch):
    contexts = "\n".join([_ctx("c0", RD), _ctx("c1", RD, "Acme TL"), _ctx("c2", RD, "Acme CS"),
                          _ctx("c3", RD, "MMF"), _ctx("cp", "2025-12-31", "Acme TL"), _ctx("c4", RD, "Beta RF"),
                          _ctx("c4p", "2025-12-31", "Beta RF"), _ctx("c5", RD, "Gamma"), SUBTOTAL_CTX])
    p = tmp_path / "f.html"
    p.write_text(PAGE.replace("{contexts}", contexts), encoding="utf-8")
    f = chk.Filing(CIK, ACC, path=p)
    monkeypatch.setattr(chk, "filing", lambda cik, acc: f if acc == ACC else chk.Filing(cik, acc, path=tmp_path / "x"))
    return f


def _row(rid, ctx, fv, cat="FIRST_LIEN", ic="debt", shares=None, pct=None):
    return {"row_id": rid, "cik": CIK, "accession_number": ACC, "src_context_id": ctx, "report_date": RD,
            "fair_value": fv, "shares_held": shares, "pct_of_net_assets": pct, "asset_category": cat,
            "index_classification": ic, "record_class": "parent_schedule", "issuer_name": "Acme Corp",
            "instrument_description": ""}


@pytest.fixture
def rows():
    return [_row("R1", "c1", 1_000_000.0, pct=1.2),
            _row("R2", "c2", 300_000.0, cat="EQUITY_COMMON", ic="equity", shares=500.0, pct=0.3),
            _row("R3", "c3", 200_000.0, cat="CASH", ic="cash")]


def test_parse_scale_sign_and_lines(fl):
    assert fl.fv_facts("c1")[0]["value"] == 1_000_000.0
    assert fl.facts[("InvestmentOwnedPercentOfNetAssets", "c1")][0]["value"] == pytest.approx(0.012)
    assert fl.printed_line("c1").startswith("Acme Corp First Lien Term Loan 1.2 %")
    assert fl.undimensioned_total(RD)["value"] == 1_300_000.0
    # the line of a fact is the <tr> it sits in, not a neighbour's
    assert fl.facts[("InvestmentOwnedBalanceShares", "c2")][0]["tr"] == fl.fv_facts("c2")[0]["tr"]
    assert fl.fv_facts("c1")[0]["tr"] != fl.fv_facts("c2")[0]["tr"]


@pytest.mark.parametrize("rule", ["PP03", "fv_conservation", "B01", "C04", "A07"])
def test_real_case_passes(fl, rows, rule):
    rws = [r for r in rows if r["row_id"] != "R3"] if rule == "A07" else rows
    res = chk.check_quarter(rule, rws, CIK, RD)
    assert res["ok"], res["fails"]


def test_total_basis_is_non_cash_when_cash_rows_sit_outside_the_total(fl, rows):
    ok, info = chk.quarter_total(rows, CIK, RD)
    assert ok and info["basis"] == "non-CASH rows"


@pytest.mark.parametrize("rule", ["PP03", "fv_conservation", "B01", "C04", "A07"])
def test_every_plant_fails(fl, rows, rule):
    rws = [r for r in rows if r["row_id"] != "R3"] if rule == "A07" else rows
    planted = chk.plants(rule, rws, CIK, RD)
    assert planted
    names = {n for n, _ in planted}
    assert {"comparative_row_added", "row_on_prior_context", "row_from_other_filing"} <= names
    for name, p in planted:
        assert not chk.check_quarter(rule, p, CIK, RD)["ok"], name


def test_cash_leak_fails(fl, rows):
    # the money-market row counted as an investment (verdict mechanism cash_equivalent_leak)
    leak = [dict(r, asset_category="OTHER") if r["row_id"] == "R3" else r for r in rows]
    assert not chk.check_quarter("fv_conservation", leak, CIK, RD)["ok"]


def test_b01_requires_a_fair_value_fact(fl, rows):
    extra = rows + [_row("R9", "c0", None)]   # a published row on a context with no position fact
    assert not chk.check_quarter("B01", extra, CIK, RD)["ok"]


def test_c04_shares_fail_when_published_value_is_the_fair_value_or_missing(fl, rows):
    for bad in (None, 300_000.0, 501.0, 500_000.0):
        p = [dict(r, shares_held=bad) if r["row_id"] == "R2" else r for r in rows]
        assert not chk.check_quarter("C04", p, CIK, RD)["ok"], bad


def test_total_must_be_a_total_the_verdict_quotes(fl, rows):
    # the verdict quotes 1,300 (thousands): confirmed; a quote of another figure confirms nothing
    assert chk.quarter_total(rows, CIK, RD, anchors=(1_300_000.0, 1300.0))[0]
    ok, info = chk.quarter_total(rows, CIK, RD, anchors=(9_999_000.0,))
    assert not ok and "no filed total" in info["why"]


def test_unscaled_reading_of_a_quoted_total_does_not_pick_a_small_fact(fl, rows):
    # '1,000' read in dollars (1000.0) is within no tolerance of a fact; the larger true total wins
    ok, info = chk.quarter_total(rows, CIK, RD, anchors=(1000.0, 1_000_000.0, 1_300_000.0))
    assert ok and info["total"] == 1_300_000.0


def test_a07_null_percent_fails(fl, rows):
    p = [dict(r, pct_of_net_assets=None) for r in rows if r["row_id"] != "R3"]
    res = chk.check_quarter("A07", p, CIK, RD)
    assert not res["ok"]


def test_a07_row_without_a_percent_fact_cannot_be_confirmed(fl, rows):
    # the money-market context carries no percent fact: not confirmable, so the quarter fails
    assert not chk.check_quarter("A07", rows, CIK, RD)["ok"]


def test_parenthesised_unsigned_fact_reads_negative(tmp_path):
    contexts = "\n".join([_ctx("c0", RD), _ctx("c1", RD, "Acme TL"), _ctx("c2", RD, "Acme CS"),
                          _ctx("c3", RD, "MMF"), _ctx("cp", "2025-12-31", "Acme TL")])
    old = ('<td><ix:nonFraction name="us-gaap:InvestmentOwnedAtFairValue" unitRef="usd" contextRef="c1" '
           'scale="3">1,000</ix:nonFraction></td>')
    assert old in PAGE
    page = PAGE.replace("{contexts}", contexts).replace(old, old.replace("<td><ix", "<td>(<ix").replace(
        "</ix:nonFraction></td>", "</ix:nonFraction>)</td>"))
    p = tmp_path / "g.html"
    p.write_text(page, encoding="utf-8")
    f = chk.Filing(CIK, ACC, path=p)
    fact = f.fv_facts("c1")[0]
    assert fact["paren"] and chk.printed_value(f, fact) == -1_000_000.0
    assert not f.fv_facts("c2")[0]["paren"]   # an unparenthesised figure stays positive


def test_rollforward_only_row_fails_pp03(fl, rows):
    assert fl.is_rollforward_line(fl.fv_facts("c4")[0]["tr"])
    assert fl.schedule_line("c4") is None and fl.schedule_line("c1")
    planted = rows + [_row("RF", "c4", 45_000.0)]
    assert not chk.check_quarter("PP03", planted, CIK, RD)["ok"]
    assert "rollforward_only_row" in {n for n, _ in chk.plants("PP03", rows, CIK, RD)}


def test_subtotal_stored_as_total_fails(fl, rows):
    # rows summing to the non-controlled subtotal, with the subtotal handed in as the total
    sub = [r for r in rows if r["row_id"] == "R1"]
    ok, info = chk.quarter_total(sub, CIK, RD, total_ctx="cs")
    assert not ok and "top-level" in info["why"]
    # the true rows with the subtotal context handed in: the top-level total ties and is used instead
    ok, info = chk.quarter_total(rows, CIK, RD, total_ctx="cs")
    assert ok and info["total"] == 1_300_000.0


def test_scale_fallback_only_when_the_tag_reading_does_not_tie(fl):
    f = fl.fv_facts("c5")[0]
    assert chk.printed_value(fl, f) == 16_900_000.0
    assert chk.match_printed(fl, [f], 16_900_000.0, 1.0)[:2] == (True, 16_900_000.0)
    ok, v, note = chk.match_printed(fl, [f], 16_900.0, 1.0)
    assert ok and "scale fallback used" in note     # the digits at the schedule scale tie too, and it says so
    assert not chk.match_printed(fl, [f], 17_000_000.0, 1.0)[0]


def test_cash_line_rejects_loans_paying_part_cash():
    assert chk.CASH_LINE.search("Goldman Sachs Financial Square Government Fund Institutional Shares")
    assert chk.NOT_CASH_LINE.search("Panzura, LLC One stop N/A 4.00 % cash/ 15.00 % PIK 08/2027 54 49 - 48")


def test_cash_rows_must_equal_filed_cash_equivalents(fl, rows):
    # a CASH row the filer does not print as a cash equivalent: the non-CASH basis no longer holds
    extra = rows + [_row("R4", "c3", 0.0, cat="CASH", ic="cash")]
    bigger = [dict(r, fair_value=350_000.0) if r["row_id"] == "R3" else r for r in rows]
    ok, info = chk.quarter_total(bigger, CIK, RD)
    assert not ok
