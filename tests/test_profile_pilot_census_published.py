"""SP3 Task 0 / Task 1: census-side published-basis partition predicate (census-published.v1).

Synthetic docs use the mk_doc/debt/val helpers from the contracts tests. The recorded test rebuilds
minimal positions from tests/fixtures/census_published_v2_rows.csv (rows the 2026-10-01 investigation
assigned a rule, plus the Ares rollup children R5 needs) and asserts classify assigns the same rule.
"""
from __future__ import annotations

import copy
import csv
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

from scripts.profile_pilot import census_published as cp
from tests.test_profile_pilot_contracts import Q1, debt, mk_doc, val

BCRED = "0001803498"
OTHER = "0001860424"
FIXTURE = Path(__file__).parent / "fixtures" / "census_published_v2_rows.csv"
EXTRA_FIELDS = ("cost", "principal_amount", "interest_rate", "pct_of_net_assets", "basis_spread",
                "interest_rate_floor", "pik_rate")


def fv_only(ctx, ident, fv, decimals="0"):
    return dict(ctx=ctx, ident=ident, fields=dict(fair_value=val(fv, "usd", decimals=decimals)))


def rules(doc, cik=OTHER):
    return {c: r["rule"] for c, r in cp.classify(doc, cik=cik)["rows"].items()}


def test_constants():
    assert cp.CENSUS_PUBLISHED_VERSION == "census-published.v1"
    assert cp.REPORTING_ENTITIES == {BCRED: ("Emerald JV LP", "Verdelite JV LP")}
    assert cp.RULES == ("R1_own_period_instant", "R2_fv_not_reported", "R3_label_or_heading",
                        "R4_generic_cash_bucket", "R5_issuer_rollup_fv_only", "R6_reporting_entity_lookthrough")
    out = cp.classify(mk_doc([debt(1)]), cik=OTHER)
    assert out["version"] == "census-published.v1"
    assert set(out) >= {"version", "period_end", "rows", "extra_fv_facts", "removed_by_rule"}


def test_r1_comparative_instant_removed_and_dei_fact_preferred():
    doc = mk_doc([debt(1), debt(2)])
    doc["positions"][1]["period"]["instant"] = "2023-03-31"
    doc["document_metadata"]["document_period_end_dates"] = ["2023-03-31", "2023-12-31"]
    doc["facts"].append(dict(i=len(doc["facts"]), qname="dei:DocumentPeriodEndDate", value=Q1, context_id="d"))
    out = cp.classify(doc, cik=OTHER)
    assert out["period_end"] == Q1 and out["period_end_source"] == "dei:DocumentPeriodEndDate"
    assert out["rows"]["c1"] == dict(published=True, underlying=False, rule=None)
    assert out["rows"]["c2"] == dict(published=False, underlying=False, rule="R1_own_period_instant")


def test_r1_falls_back_to_max_metadata_date():
    doc = mk_doc([debt(1)])
    doc["document_metadata"]["document_period_end_dates"] = ["2023-03-31", Q1]
    out = cp.classify(doc, cik=OTHER)
    assert out["period_end"] == Q1 and out["period_end_source"] == "document_metadata.max"


def test_r2_missing_fair_value_removed_zero_kept():
    a = debt(1); a["fields"].pop("fair_value")
    b = debt(2); b["fields"]["fair_value"] = val("0", "usd", decimals="0")
    c = debt(3); c["fields"]["fair_value"] = "NIL"
    r = rules(mk_doc([a, b, c]))
    assert r == {"c1": "R2_fv_not_reported", "c2": None, "c3": "R2_fv_not_reported"}


def test_r3_label_and_heading_rows_and_near_misses():
    rows = [debt(1, ident="Warrants | Total Investments"), debt(2, ident="Net Assets"),
            debt(3, ident="Sub-total First Lien"), debt(4, ident="Controlled Affiliated Investments"),
            debt(5, ident="Non-Controlled Affiliated Investments"),
            debt(6, ident="Non-controlled/Non-affiliated investments"),
            # near misses: issuer names and Onex-style positions that merely start with the words
            debt(7, ident="Totalplay Telecommunications | First Lien"),
            debt(8, ident="Non-controlled/Non-affiliated investments Equity Wholesale IMB Holdco LLC Series P Units"),
            debt(9, ident="Net Assets Holdings LLC | Term Loan")]
    r = rules(mk_doc(rows))
    assert [r["c%d" % i] for i in range(1, 7)] == ["R3_label_or_heading"] * 6
    assert [r["c%d" % i] for i in (7, 8, 9)] == [None, None, None]


def test_r4_generic_cash_bucket_removed_money_market_kept():
    rows = [debt(1, ident="Other Cash and Cash Equivalents"),
            debt(2, ident="Other Cash and Cash Equivalents, Emerald JV LP | Non-Affiliated Issuer"),
            debt(3, ident="Cash and cash equivalents"),
            debt(4, ident="State Street Institutional U.S. Government Money Market Fund - Premier Class"),
            debt(5, ident="Acme Corp | Cash Interest Rate / PIK Rate | 8.90%"),
            debt(6, ident="Cash and Cash Equivalents | Goldman Sachs Money Market Fund")]
    r = rules(mk_doc(rows))
    assert [r["c%d" % i] for i in (1, 2, 3)] == ["R4_generic_cash_bucket"] * 3
    assert r["c4"] is None and r["c5"] is None and r["c6"] is None


def test_r5_issuer_rollup_removed_when_fv_only_prefix_and_sum_match():
    rows = [fv_only("p", "Shoes For crews Global, LLC", "300"),
            debt(1, ident="Shoes for Crews Global, LLC, First lien senior secured loan"),
            debt(2, ident="Shoes For Crews Global, LLC, Preferred units")]
    rows[1]["fields"]["fair_value"] = val("100", "usd", decimals="0")
    rows[2]["fields"]["fair_value"] = val("200", "usd", decimals="0")
    assert rules(mk_doc(rows)) == {"p": "R5_issuer_rollup_fv_only", "c1": None, "c2": None}


def test_r5_near_misses_kept():
    kids = [debt(1, ident="Apex Corp, First lien"), debt(2, ident="Apex Corp, Second lien")]
    for k in kids:
        k["fields"]["fair_value"] = val("100", "usd", decimals="0")
    # sum mismatch
    assert rules(mk_doc([fv_only("p", "Apex Corp", "250")] + copy.deepcopy(kids)))["p"] is None
    # more than fair value reported (not an FV-only rollup)
    p = fv_only("p", "Apex Corp", "200")
    p["fields"]["cost"] = val("190", "usd", decimals="0")
    assert rules(mk_doc([p] + copy.deepcopy(kids)))["p"] is None
    # prefix without a token boundary ("Apex Corporation" is not a child of "Apex Corp")
    k2 = copy.deepcopy(kids)
    k2[0]["ident"] = "Apex Corporation, First lien"
    k2[1]["ident"] = "Apex Corporation, 2L"
    assert rules(mk_doc([fv_only("p", "Apex Corp", "200")] + k2))["p"] is None
    # no children at all
    assert rules(mk_doc([fv_only("p", "Lonely Equity LLC", "200")]))["p"] is None


def test_r5_rounding_tolerance_scales_with_decimals():
    kids = [debt(1, ident="ESCP PPG Holdings, LLC, Class A units"),
            debt(2, ident="ESCP PPG Holdings, LLC, Class B units")]
    for k in kids:
        k["fields"]["fair_value"] = val("100000", "usd", decimals="-5")
    doc = mk_doc([fv_only("p", "ESCP PPG Holdings, LLC", "100000", "-5")] + kids)
    assert rules(doc)["p"] == "R5_issuer_rollup_fv_only"


def bcred_doc():
    return mk_doc([debt(1, ident="Acme Senior Loan | Emerald JV LP"),
                   debt(2, ident="Beta Term Loan | Non-Affiliated Issuer | verdelite jv lp."),
                   debt(3, ident="Emerald JV LP | Equity Interest"),
                   debt(4, ident="Gamma Term Loan | Non-Affiliated Issuer")])


def test_r6_reporting_entity_suffix_marks_underlying():
    out = cp.classify(bcred_doc(), cik=BCRED)["rows"]
    assert out["c1"] == dict(published=False, underlying=True, rule="R6_reporting_entity_lookthrough")
    assert out["c2"]["underlying"] is True and out["c2"]["published"] is False
    assert out["c3"] == dict(published=True, underlying=False, rule=None)   # first segment is the holding
    assert out["c4"]["published"] is True


def test_r6_filer_without_list_marks_nothing():
    out = cp.classify(bcred_doc(), cik=OTHER)["rows"]
    assert all(r["published"] and not r["underlying"] for r in out.values())


def fidelity_doc():
    doc = mk_doc([debt(1)])
    cash = ["us-gaap:CashAndCashEquivalentsAxis", "abc:FidelityFloatingRateCentralFundMember"]
    doc["contexts"] = [
        dict(id="cash1", period=dict(kind="instant", instant=Q1), typed_dimensions=[], dimensions=[cash]),
        dict(id="cash_old", period=dict(kind="instant", instant="2023-03-31"), typed_dimensions=[], dimensions=[cash]),
        dict(id="c1", period=dict(kind="instant", instant=Q1), typed_dimensions=[], dimensions=[cash]),
        dict(id="other", period=dict(kind="instant", instant=Q1), typed_dimensions=[],
             dimensions=[["abc:SomeAxis", "abc:YMember"]])]
    n = len(doc["facts"])
    doc["facts"] += [dict(i=n, qname="us-gaap:InvestmentOwnedAtFairValue", value="179450525", context_id="cash1"),
                     dict(i=n + 1, qname="us-gaap:InvestmentOwnedBalanceShares", value="1909454", context_id="cash1"),
                     dict(i=n + 2, qname="us-gaap:InvestmentOwnedAtFairValue", value="5", context_id="cash_old"),
                     dict(i=n + 3, qname="us-gaap:InvestmentOwnedAtFairValue", value="7", context_id="c1"),
                     dict(i=n + 4, qname="us-gaap:InvestmentOwnedAtFairValue", value="9", context_id="other")]
    return doc


def test_r7_cash_equivalent_axis_fact_emitted_once():
    out = cp.classify(fidelity_doc(), cik="0001920453")
    assert out["extra_fv_facts"] == [dict(context_id="cash1", fair_value=179450525.0,
                                          source="R7_cash_equivalent_axis")]


def test_published_fv_sum_and_positions():
    doc = fidelity_doc()
    doc["positions"] += mk_doc([debt(2, ident="Net Assets")])["positions"]
    assert [p["context_id"] for p in cp.published_positions(doc, cik="0001920453")] == ["c1"]
    assert cp.published_fv_sum(doc, cik="0001920453") == Decimal("1000000") + Decimal("179450525")
    rem = cp.classify(doc, cik="0001920453")["removed_by_rule"]
    assert rem["R3_label_or_heading"] == {"n": 1, "fv": 1000000.0}
    assert rem["R5_issuer_rollup_fv_only"] == {"n": 0, "fv": 0.0}


def test_doc_without_typed_identifiers_passes_r3_to_r6_untouched():
    doc = mk_doc([debt(1), debt(2)])
    for p in doc["positions"]:
        p["identity"]["typed_identifier"] = None
    out = cp.classify(doc, cik=BCRED)
    assert all(r == dict(published=True, underlying=False, rule=None) for r in out["rows"].values())
    assert out["extra_fv_facts"] == []


def recorded_docs():
    by_cik = defaultdict(list)
    with open(FIXTURE, encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            by_cik[r["cik"]].append(r)
    for cik, rows in by_cik.items():
        specs = []
        for r in rows:
            fields, n = {}, int(r["n_reported_fields"] or 0)
            if r["fv_status"] == "reported":
                fields["fair_value"] = val(r["fv_value"], "usd", decimals=r["fv_decimals"])
                n -= 1
            for name in EXTRA_FIELDS[:max(n, 0)]:
                fields[name] = val("1", "usd", decimals="0")
            specs.append(dict(ctx=r["context_id"], ident=r["typed_identifier"], fields=fields))
        doc = mk_doc(specs, date=rows[0]["period_end"])
        for p, r in zip(doc["positions"], rows):
            p["period"]["instant"] = r["instant"]
            if r["fv_status"] == "consistent_duplicate":
                p["fields"]["fair_value"] = dict(status="consistent_duplicate", value=r["fv_value"],
                                                 decimals=r["fv_decimals"])
        yield cik, doc, rows


def test_recorded_v2_rows_get_the_same_rule():
    seen = defaultdict(int)
    for cik, doc, rows in recorded_docs():
        got = cp.classify(doc, cik=cik)["rows"]
        for r in rows:
            assert got[r["context_id"]]["rule"] == (r["rule"] or None), (cik, r["context_id"], r["typed_identifier"])
            seen[r["rule"]] += 1
    assert seen["R2_fv_not_reported"] == 48 and seen["R3_label_or_heading"] == 7
    assert seen["R4_generic_cash_bucket"] == 3 and seen["R5_issuer_rollup_fv_only"] == 33
    assert seen["R6_reporting_entity_lookthrough"] == 5 and seen["R1_own_period_instant"] == 2
