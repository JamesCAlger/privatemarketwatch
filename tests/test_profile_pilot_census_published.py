"""SP3 Task 0 / Task 1 / Task 0b: census-side published-basis partition predicate (census-published.v1 and v2).

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

import pytest

from scripts.profile_pilot import census_published as cp
from tests.test_profile_pilot_contracts import Q1, debt, mk_doc, val

BCRED = "0001803498"
OTHER = "0001860424"
V1, V2 = "census-published.v1", "census-published.v2"
FIXTURE = Path(__file__).parent / "fixtures" / "census_published_v2_rows.csv"
REFERENCE_NAMES = {"R1_not_current_instant": "R1_own_period_instant"}   # rename only, same rule
EXTRA_FIELDS = ("cost", "principal_amount", "interest_rate", "pct_of_net_assets", "basis_spread",
                "interest_rate_floor", "pik_rate")


def fv_only(ctx, ident, fv, decimals="0"):
    return dict(ctx=ctx, ident=ident, fields=dict(fair_value=val(fv, "usd", decimals=decimals)))


def rules(doc, cik=OTHER):
    return {c: r["rule"] for c, r in cp.classify(doc, cik=cik)["rows"].items()}


def test_constants():
    assert cp.CENSUS_PUBLISHED_VERSION == V2
    assert cp.VERSIONS == (V1, V2)
    assert cp.REPORTING_ENTITIES == {BCRED: ("Emerald JV LP", "Verdelite JV LP")}
    assert cp.RULES_V1 == ("R1_own_period_instant", "R2_fv_not_reported", "R3_label_or_heading",
                           "R4_generic_cash_bucket", "R5_issuer_rollup_fv_only", "R6_reporting_entity_lookthrough")
    assert cp.RULES == ("R1_own_period_instant", "R2_fv_not_reported", "R3_label_or_heading",
                        "R4_generic_cash_bucket", "R5_issuer_rollup_fv_only", "R5b_hierarchical_rollup",
                        "R6_reporting_entity_lookthrough")
    out = cp.classify(mk_doc([debt(1)]), cik=OTHER)
    assert out["version"] == V2
    assert set(out) >= {"version", "period_end", "rows", "extra_fv_facts", "removed_by_rule",
                        "near_misses_r5b", "r5b_passes"}
    assert set(out["removed_by_rule"]) == set(cp.RULES)
    v1 = cp.classify(mk_doc([debt(1)]), cik=OTHER, version=V1)
    assert v1["version"] == V1 and set(v1["removed_by_rule"]) == set(cp.RULES_V1)
    assert "near_misses_r5b" not in v1 and "r5b_passes" not in v1


def test_unknown_version_is_refused():
    with pytest.raises(ValueError, match="census-published.v0"):
        cp.classify(mk_doc([debt(1)]), cik=OTHER, version="census-published.v0")


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


@pytest.mark.parametrize("version", [V1, V2])
def test_recorded_v2_rows_get_the_same_rule(version):
    """Fixture rows come from scratch/2026-10-01_census_published_basis/census_rule_assignments_v2.csv
    (sha256 1318d9684f3b854393685c589c6368428749ddc5ffe15a0b28d4dab0fd384f06, read-only source). The
    implementation differs from the investigation's reference rule on exactly one row: c-929 (Belfor, a
    reported FV of 0 that the reference rule removed by R2; the implementation keeps value 0, deliberate).
    The reference names R1 R1_not_current_instant; REFERENCE_NAMES maps it to the implementation's name.
    Under v2 the expectations are identical (asserted by the v2 parametrisation, not argued): the fixture
    rebuilds extra fields with the synthetic value 1, and the FV-only parents are already taken by R5.
    R5b fires on no fixture row."""
    seen = defaultdict(int)
    differs = set()
    for cik, doc, rows in recorded_docs():
        got = cp.classify(doc, cik=cik, version=version)["rows"]
        for r in rows:
            assert got[r["context_id"]]["rule"] == (r["rule"] or None), (cik, r["context_id"], r["typed_identifier"])
            ref = REFERENCE_NAMES.get(r["reference_rule"], r["reference_rule"]) or None
            if got[r["context_id"]]["rule"] != ref:
                differs.add(r["context_id"])
            seen[r["rule"]] += 1
    assert differs == {"c-929"}
    assert seen["R2_fv_not_reported"] == 48 and seen["R3_label_or_heading"] == 7
    assert seen["R4_generic_cash_bucket"] == 3 and seen["R5_issuer_rollup_fv_only"] == 33
    assert seen["R6_reporting_entity_lookthrough"] == 5 and seen["R1_own_period_instant"] == 2


def test_r7_cash_axis_with_other_axis_or_typed_dimension_emits_nothing():
    doc = fidelity_doc()
    for c in doc["contexts"]:
        if c["id"] == "cash1":
            c["dimensions"] = c["dimensions"] + [["abc:SomeAxis", "abc:YMember"]]
    doc["contexts"].append(dict(id="cash_typed", period=dict(kind="instant", instant=Q1),
                                typed_dimensions=[dict(axis="us-gaap:InvestmentIdentifierAxis", value="X")],
                                dimensions=[["us-gaap:CashAndCashEquivalentsAxis", "abc:ZMember"]]))
    doc["facts"].append(dict(i=len(doc["facts"]), qname="us-gaap:InvestmentOwnedAtFairValue", value="11",
                             context_id="cash_typed"))
    assert cp.classify(doc, cik="0001920453")["extra_fv_facts"] == []
    assert cp.published_fv_sum(doc, cik="0001920453") == Decimal("1000000")


def test_r5_unparsable_parent_fair_value_does_not_raise():
    kid = debt(1, ident="Apex Corp, First lien")
    assert rules(mk_doc([fv_only("p", "Apex Corp", "n/a"), kid]))["p"] is None


def test_r1_two_distinct_dei_period_end_dates_choose_the_max_and_record_the_source():
    doc = mk_doc([debt(1), debt(2)])
    doc["positions"][1]["period"]["instant"] = "2023-03-31"
    n = len(doc["facts"])
    doc["facts"] += [dict(i=n, qname="dei:DocumentPeriodEndDate", value="2023-03-31", context_id="d1"),
                     dict(i=n + 1, qname="dei:DocumentPeriodEndDate", value=Q1, context_id="d2")]
    out = cp.classify(doc, cik=OTHER)
    assert out["period_end"] == Q1 and out["period_end_source"] == "dei:DocumentPeriodEndDate"
    assert out["no_period_end"] is False
    assert out["rows"]["c1"]["rule"] is None and out["rows"]["c2"]["rule"] == "R1_own_period_instant"


def test_r5_near_miss_parent_is_counted_but_kept():
    kids = [debt(1, ident="Apex Corp, First lien"), debt(2, ident="Apex Corp, Second lien")]
    for k in kids:
        k["fields"]["fair_value"] = val("100", "usd", decimals="0")
    out = cp.classify(mk_doc([fv_only("p", "Apex Corp", "250")] + kids), cik=OTHER)
    assert out["rows"]["p"]["rule"] is None
    assert out["near_misses"] == {"n": 1, "fv": 250.0}
    rollup = cp.classify(mk_doc([fv_only("p", "Apex Corp", "200")] + copy.deepcopy(kids)), cik=OTHER)
    assert rollup["rows"]["p"]["rule"] == "R5_issuer_rollup_fv_only"
    assert rollup["near_misses"] == {"n": 0, "fv": 0.0}


def test_r7_agreeing_duplicate_facts_emit_once():
    doc = fidelity_doc()
    doc["facts"].append(dict(i=len(doc["facts"]), qname="us-gaap:InvestmentOwnedAtFairValue", value="179450525.0",
                             context_id="cash1"))
    out = cp.classify(doc, cik="0001920453")
    assert out["extra_fv_facts"] == [dict(context_id="cash1", fair_value=179450525.0, source="R7_cash_equivalent_axis")]
    assert out["r7_conflicts"] == []


def test_r7_disagreeing_facts_skip_the_context_and_record_a_conflict():
    doc = fidelity_doc()
    doc["facts"].append(dict(i=len(doc["facts"]), qname="us-gaap:InvestmentOwnedAtFairValue", value="1",
                             context_id="cash1"))
    out = cp.classify(doc, cik="0001920453")
    assert out["extra_fv_facts"] == []
    assert out["r7_conflicts"] == [dict(context_id="cash1", values=["179450525", "1"])]
    assert cp.published_fv_sum(doc, cik="0001920453") == Decimal("1000000")


def test_no_period_end_is_reported_and_fails_closed():
    doc = fidelity_doc()
    doc["document_metadata"]["document_period_end_dates"] = []
    doc["contexts"].append(dict(id="dur", period=dict(kind="duration", start="2026-01-01", end=Q1),
                                typed_dimensions=[], dimensions=[["us-gaap:CashAndCashEquivalentsAxis", "abc:M"]]))
    doc["facts"].append(dict(i=len(doc["facts"]), qname="us-gaap:InvestmentOwnedAtFairValue", value="3",
                             context_id="dur"))
    out = cp.classify(doc, cik="0001920453")
    assert out["period_end"] is None and out["no_period_end"] is True and out["period_end_source"] == "none"
    assert out["extra_fv_facts"] == [] and out["r7_conflicts"] == []
    assert all(not r["published"] for r in out["rows"].values())


# ---------------------------------------------------------------- v2: R5b hierarchical rollups (SP3 Task 0b)

ONEX_CAT_DEBT = "Non-controlled/Non-affiliated investments Debt Investments"
ONEX_CAT_EQ = "Non-controlled/Non-affiliated investments Equity Investments"


def full_row(ctx, ident, fv, cost=None, pct="0.0100", decimals="0", principal=None):
    fields = dict(fair_value=val(fv, "usd", decimals=decimals))
    if cost is not None:
        fields["cost"] = val(cost, "usd", decimals=decimals)
    if pct is not None:
        fields["pct_of_net_assets"] = val(pct)
    if principal is not None:
        fields["principal_amount"] = val(principal, "usd", decimals=decimals)
    return dict(ctx=ctx, ident=ident, fields=fields)


def onex_doc():
    """Onex 2023-06-30 shape: single-segment identifiers, category -> industry -> issuer, every row with
    fair value, cost and pct; subtotal rows equal their direct children's FV and cost sums."""
    hc, sw, ch = (ONEX_CAT_DEBT + " Healthcare & Pharmaceuticals", ONEX_CAT_DEBT + " Software",
                  ONEX_CAT_DEBT + " Chemicals")
    return mk_doc([
        full_row("cat_debt", ONEX_CAT_DEBT, "500", "480"),
        full_row("cat_eq", ONEX_CAT_EQ, "200", "180"),
        full_row("ind_hc", hc, "250", "235"),
        full_row("ind_sw", sw, "120", "118"),
        full_row("ind_ch", ch, "130", "127"),
        full_row("i1", hc + " Acme Health LLC First Lien Term Loan", "100", "95"),
        full_row("i2", hc + " Beta Pharma Inc First Lien Term Loan", "150", "140"),
        full_row("i3", sw + " Gamma Software LLC First Lien Term Loan", "120", "118"),
        full_row("i4", ch + " Delta Chemicals Corp Second Lien Term Loan", "130", "127"),
        full_row("i5", ONEX_CAT_EQ + " Wholesale IMB Holdco LLC Series P Units", "200", "180")])


ISSUERS = ["i1", "i2", "i3", "i4", "i5"]


def test_r5b_removes_industry_then_category_rollups_bottom_up():
    out = cp.classify(onex_doc(), cik=OTHER)
    got = {c: r["rule"] for c, r in out["rows"].items()}
    assert {c for c, r in got.items() if r is None} == set(ISSUERS)
    assert all(got[c] == "R5b_hierarchical_rollup" for c in ("cat_debt", "cat_eq", "ind_hc", "ind_sw", "ind_ch"))
    # deepest first: the industry rows (and the equity category, whose direct child is an issuer) go in
    # pass 1; the debt category only in pass 2, once its industry children are gone
    assert out["r5b_passes"] == [["cat_eq", "ind_hc", "ind_sw", "ind_ch"], ["cat_debt"]]
    assert out["removed_by_rule"]["R5b_hierarchical_rollup"] == {"n": 5, "fv": 1200.0}
    assert out["near_misses_r5b"] == {"n": 0, "fv": 0.0}
    assert cp.published_fv_sum(onex_doc(), cik=OTHER) == Decimal(700)
    assert [p["context_id"] for p in cp.published_positions(onex_doc(), cik=OTHER)] == ISSUERS


def test_same_onex_doc_under_v1_keeps_everything():
    out = cp.classify(onex_doc(), cik=OTHER, version=V1)
    assert all(r["rule"] is None for r in out["rows"].values())
    assert cp.published_fv_sum(onex_doc(), cik=OTHER, version=V1) == Decimal(1900)
    assert len(cp.published_positions(onex_doc(), cik=OTHER, version=V1)) == 10


def apex_doc(parent_fv, parent_cost, *, pct="0.0100", principal=None):
    return mk_doc([full_row("p", "Apex Corp", parent_fv, parent_cost, pct=pct, principal=principal),
                   full_row("k1", "Apex Corp First Lien Term Loan", "100", "100"),
                   full_row("k2", "Apex Corp Second Lien Term Loan", "100", "90")])


def test_r5b_fv_match_cost_mismatch_is_kept_and_counted_as_near_miss():
    out = cp.classify(apex_doc("200", "150"), cik=OTHER)
    assert out["rows"]["p"]["rule"] is None and out["rows"]["p"]["published"] is True
    assert out["near_misses_r5b"] == {"n": 1, "fv": 200.0}
    out = cp.classify(apex_doc("260", "190"), cik=OTHER)          # cost matches, FV does not
    assert out["rows"]["p"]["rule"] is None and out["near_misses_r5b"] == {"n": 1, "fv": 260.0}


def test_r5b_real_position_prefixing_two_tranches_with_other_fv_is_kept():
    doc = mk_doc([full_row("p", "Zeta Holdings Term Loan", "300", "300"),
                  full_row("k1", "Zeta Holdings Term Loan Delayed Draw Tranche A", "100", "100"),
                  full_row("k2", "Zeta Holdings Term Loan Delayed Draw Tranche B", "150", "150")])
    out = cp.classify(doc, cik=OTHER)
    assert {c: r["rule"] for c, r in out["rows"].items()} == {"p": None, "k1": None, "k2": None}
    assert out["near_misses_r5b"] == {"n": 0, "fv": 0.0}
    assert out["r5b_passes"] == []


def test_r5b_parent_without_cost_needs_no_pct_for_the_fv_only_fallback():
    # no cost, pct reported: kept even though FV equals the children's sum
    assert cp.classify(apex_doc("200", None), cik=OTHER)["rows"]["p"]["rule"] is None
    # no cost, no pct (principal only, so not an R5 FV-only row): the FV test alone decides
    out = cp.classify(apex_doc("200", None, pct=None, principal="200"), cik=OTHER)
    assert out["rows"]["p"]["rule"] == "R5b_hierarchical_rollup"
    assert cp.classify(apex_doc("250", None, pct=None, principal="200"), cik=OTHER)["rows"]["p"]["rule"] is None


def test_r5b_whole_word_prefix_only():
    doc = mk_doc([full_row("p", "Apex Corp", "200", "190"),
                  full_row("k1", "Apex Corporation First Lien", "100", "100"),
                  full_row("k2", "Apex Corporation Second Lien", "100", "90")])
    assert cp.classify(doc, cik=OTHER)["rows"]["p"]["rule"] is None


def test_r5b_tolerance_follows_reported_decimals():
    doc = mk_doc([full_row("p", "Apex Corp", "200000", "190000", decimals="-3"),
                  full_row("k1", "Apex Corp First Lien Term Loan", "100400", "100400", decimals="-3"),
                  full_row("k2", "Apex Corp Second Lien Term Loan", "100400", "90400", decimals="-3")])
    assert cp.classify(doc, cik=OTHER)["rows"]["p"]["rule"] == "R5b_hierarchical_rollup"
    doc = mk_doc([full_row("p", "Apex Corp", "200", "190"),
                  full_row("k1", "Apex Corp First Lien Term Loan", "100", "100"),
                  full_row("k2", "Apex Corp Second Lien Term Loan", "102", "90")])
    assert cp.classify(doc, cik=OTHER)["rows"]["p"]["rule"] is None


def test_r5b_ignores_rows_removed_by_earlier_rules():
    # a comparative-period copy of a child (R1) does not count toward the parent's sums
    doc = apex_doc("200", "190")
    doc["positions"].append(copy.deepcopy(doc["positions"][1]))
    doc["positions"][-1]["context_id"] = "old"
    doc["positions"][-1]["period"]["instant"] = "2023-03-31"
    out = cp.classify(doc, cik=OTHER)
    assert out["rows"]["old"]["rule"] == "R1_own_period_instant"
    assert out["rows"]["p"]["rule"] == "R5b_hierarchical_rollup"


def test_r5b_piped_parent_must_end_on_a_segment_boundary():
    # TCW 2026-03-31 shape: the same position tagged twice, the second identifier ending '... | 5/30/2031 One';
    # identical FV and cost, production publishes both -> not a rollup
    base = "Debt | First Lien | Rep Tec Holdings Term Loan | SOFR + 4.75% | 5/30/2031"
    doc = mk_doc([full_row("p", base, "8610000", "8624000"), full_row("k", base + " One", "8610000", "8624000")])
    assert rules(doc) == {"p": None, "k": None}
    # NexPoint 2023-09-30 shape: 'Common Stocks | Real Estate' is not a parent of the REIT segment
    doc = mk_doc([full_row("re", "Common Stocks | Real Estate", "300", None, pct=None),
                  full_row("a", "Common Stocks | Real Estate | Alpha REF Inc.", "100", "90", pct=None),
                  full_row("b", "Common Stocks | Real Estate | IQHQ Inc.", "200", "150", pct=None),
                  full_row("r", "Common Stocks | Real Estate Investment Trust (REIT) | Beta Trust", "50", "40", pct=None)])
    assert rules(doc) == {"re": "R5b_hierarchical_rollup", "a": None, "b": None, "r": None}
    # a piped parent whose children add whole segments is still a rollup
    doc = mk_doc([full_row("p", "Debt | Software", "250", "235"),
                  full_row("k1", "Debt | Software | Acme LLC | First Lien", "100", "95"),
                  full_row("k2", "Debt | Software | Beta Inc | First Lien", "150", "140")])
    assert rules(doc) == {"p": "R5b_hierarchical_rollup", "k1": None, "k2": None}


def test_r5b_cost_of_an_unfunded_negative_fv_child_may_count_negative():
    # Onex 2023-06-30 shape: the subtotal's cost carries the unfunded revolver's cost negative, the tagged fact
    # is positive; the FV sum matches either way
    doc = mk_doc([full_row("p", "Debt Investments Wholesale", "16017998", "17022370"),
                  full_row("k1", "Debt Investments Wholesale IMB Midco LLC Initial Term Loan", "16077525", "17034042"),
                  full_row("k2", "Debt Investments Wholesale IMB Midco LLC Revolving Loan", "-59527", "11672")])
    out = cp.classify(doc, cik=OTHER)
    assert out["rows"]["p"]["rule"] == "R5b_hierarchical_rollup" and out["near_misses_r5b"]["n"] == 0
    # the sign flip applies only to a negative-FV child: a positive-FV child's cost is never negated
    doc["positions"][2]["fields"]["fair_value"]["value"] = "59527"
    doc["positions"][0]["fields"]["fair_value"]["value"] = "16137052"
    assert cp.classify(doc, cik=OTHER)["rows"]["p"]["rule"] is None
