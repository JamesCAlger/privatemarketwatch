"""Filer-profile pilot Task 4: bounded census collection and structure detectors.

Every instance here is synthetic XML written to tmp_path, except the one
`needs_cache` test at the bottom, which reads a cached Stellus instance through
PROFILE_PILOT_DATA_ROOT (set by the pilot launcher) and writes nothing.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from scripts.profile_pilot import census, census_collect, census_detect, census_run, envelope
from scripts.profile_pilot.protection import LeaseRefused
from tests.test_profile_pilot_paths import fake_paths, put_instance

CIK = "0001901037"
Q = "2023-03-31"
PRIOR = "2022-12-31"
IDENT = "us-gaap:InvestmentIdentifierAxis"
TYPE_AXIS = "us-gaap:InvestmentTypeAxis"
AFFIL_AXIS = "us-gaap:InvestmentIssuerAffiliationAxis"
SCOPE_AXIS = "srt:ConsolidatedEntitiesAxis"
NS = {
    "us-gaap": "http://fasb.org/us-gaap/2023",
    "dei": "http://xbrl.sec.gov/dei/2023",
    "srt": "http://fasb.org/srt/2023",
    "iso4217": "http://www.xbrl.org/2003/iso4217",
    "xbrli": "http://www.xbrl.org/2003/instance",
    "xbrldi": "http://xbrl.org/2006/xbrldi",
    "link": "http://www.xbrl.org/2003/linkbase",
    "xlink": "http://www.w3.org/1999/xlink",
    "xsi": "http://www.w3.org/2001/XMLSchema-instance",
    "fake": "http://fake.example.com/20230331",
}


# ---------------------------------------------------------------- synthetic instances

def _period(period) -> str:
    if isinstance(period, tuple):
        return "<xbrli:startDate>%s</xbrli:startDate><xbrli:endDate>%s</xbrli:endDate>" % period
    return "<xbrli:instant>%s</xbrli:instant>" % period


def _dims(dims) -> str:
    parts = []
    for kind, axis, value in dims:
        if kind == "explicit":
            parts.append('<xbrldi:explicitMember dimension="%s">%s</xbrldi:explicitMember>'
                         % (axis, value))
        else:
            parts.append('<xbrldi:typedMember dimension="%s"><us-gaap:InvestmentIdentifierAxis.domain>'
                         '%s</us-gaap:InvestmentIdentifierAxis.domain></xbrldi:typedMember>'
                         % (axis, value))
    return "<xbrli:segment>" + "".join(parts) + "</xbrli:segment>" if parts else ""


def ctx(cid, period=Q, dims=(), cik=CIK):
    return ('<xbrli:context id="%s"><xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">'
            '%s</xbrli:identifier>%s</xbrli:entity><xbrli:period>%s</xbrli:period></xbrli:context>'
            % (cid, cik, _dims(dims), _period(period)))


def fact(qname, cid, value, *, unit=None, decimals=None, nil=False, fid=None):
    attrs = ' contextRef="%s"' % cid
    if unit:
        attrs += ' unitRef="%s"' % unit
    if decimals is not None:
        attrs += ' decimals="%s"' % decimals
    if fid:
        attrs += ' id="%s"' % fid
    if nil:
        return '<%s%s xsi:nil="true"/>' % (qname, attrs)
    return "<%s%s>%s</%s>" % (qname, attrs, value, qname)


UNITS = ('<xbrli:unit id="usd"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>'
         '<xbrli:unit id="eur"><xbrli:measure>iso4217:EUR</xbrli:measure></xbrli:unit>'
         '<xbrli:unit id="pure"><xbrli:measure>xbrli:pure</xbrli:measure></xbrli:unit>'
         '<xbrli:unit id="shares"><xbrli:measure>xbrli:shares</xbrli:measure></xbrli:unit>')


def document(contexts, facts, *, dped=Q, extra="", doctype=""):
    namespaces = " ".join('xmlns:%s="%s"' % item for item in NS.items())
    body = ("".join(contexts) + ctx("dei_ctx", ("2023-01-01", Q)) + UNITS
            + fact("dei:DocumentPeriodEndDate", "dei_ctx", dped)
            + fact("dei:DocumentType", "dei_ctx", "10-Q") + "".join(facts) + extra)
    return ('<?xml version="1.0" encoding="utf-8"?>' + doctype
            + "<xbrli:xbrl %s>%s</xbrli:xbrl>" % (namespaces, body))


def write(tmp_path, text, name="instance.xml") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def collect(tmp_path, text, **kwargs):
    path = write(tmp_path, text)
    meta = dict(cik=CIK, report_date=Q, accession_number="0000000000-23-000001",
                form_type="10-Q", role="q1")
    return census.build_census(path, meta, **kwargs)


def position(cid, ident, fv, *, period=Q, dims=(), unit="usd", decimals="0", extra=()):
    return ([ctx(cid, period, [("typed", IDENT, ident), *dims])],
            [fact("us-gaap:InvestmentOwnedAtFairValue", cid, fv, unit=unit, decimals=decimals),
             *extra])


def assemble(*parts):
    contexts, facts = [], []
    for c, f in parts:
        contexts += c
        facts += f
    return contexts, facts


def outcomes(doc, detector):
    return doc["detectors"][detector]["outcomes"]


def by_finding(doc, detector, finding):
    return [o for o in outcomes(doc, detector) if o["finding"] == finding]


# ---------------------------------------------------------------- parse bounds and safety

def test_dtd_and_entity_expansion_are_refused(tmp_path):
    doctype = '<!DOCTYPE xbrli:xbrl [<!ENTITY boom "BOOMBOOMBOOM">]>'
    contexts, facts = position("p1", "&boom; Corp", "100")
    doc = collect(tmp_path, document(contexts, facts, doctype=doctype))
    assert doc["collection"]["state"] == "failed"
    assert "BOOM" not in json.dumps(doc)
    assert all(ch["state"] in ("failed", "not_collected", "unsupported")
               for ch in doc["channels"].values())


def test_byte_bound_fails_closed_before_parsing(tmp_path):
    contexts, facts = position("p1", "Acme Corp", "100")
    doc = collect(tmp_path, document(contexts, facts), bounds=census.Bounds(max_bytes=100))
    assert doc["collection"]["state"] == "failed"
    assert any("byte" in e for e in doc["collection"]["errors"])
    assert doc["facts"] == [] and doc["contexts"] == []


def test_source_hash_is_taken_before_and_after(tmp_path):
    contexts, facts = position("p1", "Acme Corp", "100")
    doc = collect(tmp_path, document(contexts, facts))
    assert doc["collection"]["state"] == "complete"
    src = doc["document"]
    assert len(src["sha256_before"]) == 64 and src["sha256_before"] == src["sha256_after"]


def test_fact_bound_truncates_and_invalidates_absence_claims(tmp_path):
    parts = [position("p%d" % i, "Borrower %d Term Loan" % i, "100") for i in range(6)]
    contexts, facts = assemble(*parts)
    doc = collect(tmp_path, document(contexts, facts), bounds=census.Bounds(max_facts=4))
    assert doc["collection"]["state"] == "incomplete"
    assert doc["channels"]["numeric_facts"]["state"] == "truncated"
    nd = outcomes(doc, "non_disclosure")
    assert nd and all(o["outcome"] != "resolved" or o["finding"] == "observed" for o in nd)
    assert not by_finding(doc, "non_disclosure", "not_observed_in_complete_instance")


def test_partial_xml_is_a_failed_collection_not_a_smaller_census(tmp_path):
    contexts, facts = position("p1", "Acme Corp", "100")
    text = document(contexts, facts)
    doc = collect(tmp_path, text[: len(text) // 2])
    assert doc["collection"]["state"] == "failed"
    for name in ("subtotal", "alternate_view", "non_disclosure", "partition"):
        assert all(o["outcome"] == "insufficient_evidence" for o in outcomes(doc, name))
    assert doc["detectors"]["partition"]["outcomes"][0]["finding"] == "collection_incomplete"


# ---------------------------------------------------------------- contexts and periods

def test_comparative_contexts_come_from_contexts_not_document_period_end(tmp_path):
    contexts, facts = assemble(
        position("cur", "Acme Corp Term Loan", "100"),
        position("old", "Acme Corp Term Loan", "90", period=PRIOR),
        ([ctx("inc_prior", ("2022-01-01", "2022-03-31"))],
         [fact("us-gaap:InvestmentIncomeInterest", "inc_prior", "7", unit="usd", decimals="0")]))
    doc = collect(tmp_path, document(contexts, facts, dped=Q))
    assert doc["document_metadata"]["document_period_end_dates"] == [Q]
    periods = {(p["kind"], p.get("instant") or p.get("end")): p["relation"] for p in doc["periods"]}
    assert periods[("instant", Q)] == "document_period_end"
    assert periods[("instant", PRIOR)] == "comparative"
    assert periods[("duration", "2022-03-31")] == "comparative"
    observed = {(p["context_id"], p["period"]["instant"]) for p in doc["positions"]}
    assert ("old", PRIOR) in observed and ("cur", Q) in observed


def test_dimensions_are_qname_pairs_and_typed_members_kept_apart(tmp_path):
    contexts, facts = position("p1", "Acme Corp", "100",
                               dims=[("explicit", TYPE_AXIS, "us-gaap:FirstLienMember")])
    doc = collect(tmp_path, document(contexts, facts))
    context = next(c for c in doc["contexts"] if c["id"] == "p1")
    assert context["dimensions"] == [[TYPE_AXIS, "us-gaap:FirstLienMember"]]
    assert context["typed_dimensions"] == [dict(axis=IDENT, value="Acme Corp")]
    assert context["role"] == "confirmed_position" and context["role_provenance"] == "inherited"


# ---------------------------------------------------------------- facts, values, mapping

def test_rate_spread_date_text_boolean_income_and_unknown_facts_are_retained(tmp_path):
    extra = [fact("us-gaap:InvestmentInterestRate", "p1", "0.105", unit="pure", decimals="4"),
             fact("us-gaap:InvestmentBasisSpreadVariableRate", "p1", "0.06", unit="pure", decimals="4"),
             fact("us-gaap:InvestmentInterestRatePaidInKind", "p1", "0.02", unit="pure", decimals="4"),
             fact("us-gaap:InvestmentMaturityDate", "p1", "2028-06-30"),
             fact("us-gaap:InvestmentIndustrySectorExtensibleEnumeration", "p1",
                  "http://fasb.org/us-gaap/2023#SoftwareSectorMember"),
             fact("us-gaap:InvestmentNonIncomeProducing", "p1", "false"),
             fact("fake:RevolverUnfundedCommitment", "p1", "25", unit="usd", decimals="0")]
    contexts, facts = assemble(
        position("p1", "Acme Corp Term Loan", "100", extra=extra),
        ([ctx("fund_dur", ("2023-01-01", Q))],
         [fact("us-gaap:InvestmentIncomeInterest", "fund_dur", "12", unit="usd", decimals="0"),
          fact("us-gaap:NetInvestmentIncome", "fund_dur", "8", unit="usd", decimals="0")]),
        ([ctx("fund_bs")], [fact("us-gaap:AssetsNet", "fund_bs", "500", unit="usd", decimals="0")]))
    doc = collect(tmp_path, document(contexts, facts))
    pos = next(p for p in doc["positions"] if p["context_id"] == "p1")
    fields = pos["fields"]
    assert fields["interest_rate"]["value"] == "0.105" and fields["interest_rate"]["unit_kind"] == "pure"
    assert fields["basis_spread"]["value"] == "0.06"
    assert fields["pik_rate"]["value"] == "0.02"
    assert fields["maturity_date"]["value"] == "2028-06-30"
    assert fields["industry"]["value"].endswith("#SoftwareSectorMember")
    assert fields["non_income_producing"]["value"] is False
    assert fields["principal_amount"]["status"] == "absent"
    income = {(i["field"], i["scope"]) for i in doc["fund_income"]}
    assert ("income_interest", "fund") in income and ("net_investment_income", "fund") in income
    unknown = [f for f in doc["facts"] if f["qname"] == "fake:RevolverUnfundedCommitment"]
    assert unknown and unknown[0]["field"] is None and unknown[0]["value"] == "25"
    kinds = {f["qname"]: f["value_kind"] for f in doc["facts"]}
    assert kinds["us-gaap:InvestmentMaturityDate"] == "date"
    assert kinds["us-gaap:InvestmentNonIncomeProducing"] == "boolean"
    assert kinds["us-gaap:InvestmentIndustrySectorExtensibleEnumeration"] == "enumeration"
    assert kinds["dei:DocumentType"] == "text"


def test_nil_absent_and_invalid_are_distinct(tmp_path):
    extra = [fact("us-gaap:InvestmentMaturityDate", "p1", "", nil=True),
             fact("us-gaap:InvestmentInterestRate", "p1", "n/a", unit="pure", decimals="4"),
             fact("us-gaap:InvestmentAcquisitionDate", "p1", "sometime")]
    contexts, facts = position("p1", "Acme Corp Term Loan", "100", extra=extra)
    doc = collect(tmp_path, document(contexts, facts))
    fields = doc["positions"][0]["fields"]
    assert fields["maturity_date"]["status"] == "nil" and fields["maturity_date"]["value"] is None
    assert fields["interest_rate"]["status"] == "invalid"
    assert fields["interest_rate"]["raw"] == ["n/a"]
    assert fields["acquisition_date"]["status"] == "invalid"
    assert fields["cost"]["status"] == "absent"


def test_absence_becomes_unobservable_when_the_channel_is_truncated(tmp_path):
    parts = [position("p%d" % i, "Borrower %d" % i, "100") for i in range(4)]
    contexts, facts = assemble(*parts)
    doc = collect(tmp_path, document(contexts, facts), bounds=census.Bounds(max_facts=3))
    for pos in doc["positions"]:
        assert pos["fields"]["cost"]["status"] == "unobservable"


def test_conflicting_same_field_facts_are_kept_as_conflicts(tmp_path):
    contexts = [ctx("u", Q, [("typed", IDENT, "Unit Clash Co")]),
                ctx("v", Q, [("typed", IDENT, "Value Clash Co")]),
                ctx("d", Q, [("typed", IDENT, "Decimals Clash Co")]),
                ctx("same", Q, [("typed", IDENT, "Consistent Co")])]
    fv = "us-gaap:InvestmentOwnedAtFairValue"
    facts = [fact(fv, "u", "100", unit="usd", decimals="0"), fact(fv, "u", "100", unit="eur", decimals="0"),
             fact(fv, "v", "100", unit="usd", decimals="0"), fact(fv, "v", "250", unit="usd", decimals="0"),
             fact(fv, "d", "1000", unit="usd", decimals="-3"), fact(fv, "d", "1000", unit="usd", decimals="0"),
             fact(fv, "same", "5", unit="usd", decimals="0"), fact(fv, "same", "5", unit="usd", decimals="0")]
    doc = collect(tmp_path, document(contexts, facts))
    got = {p["context_id"]: p["fields"]["fair_value"] for p in doc["positions"]}
    assert got["u"]["status"] == "conflict" and got["u"]["reason"] == "unit_differs"
    assert got["v"]["status"] == "conflict" and got["v"]["reason"] == "value_differs"
    assert got["d"]["status"] == "conflict" and got["d"]["reason"] == "decimals_differ"
    for key in ("u", "v", "d"):
        assert got[key]["value"] is None and len(got[key]["fact_indices"]) == 2
    assert got["same"]["status"] == "consistent_duplicate" and got["same"]["value"] == "5"
    assert {c["context_id"] for c in doc["conflicts"]} == {"u", "v", "d"}


def test_mappings_record_inherited_and_derived_dependencies(tmp_path):
    extra = [fact("us-gaap:InvestmentIndustrySectorExtensibleEnumeration", "p1",
                  "http://fasb.org/us-gaap/2023#SoftwareSectorMember")]
    contexts, facts = position("p1", "Acme Corp", "100", extra=extra)
    doc = collect(tmp_path, document(contexts, facts))
    mapping = doc["concept_mappings"]
    assert mapping["us-gaap:InvestmentOwnedAtFairValue"]["provenance"] == "inherited"
    assert "pipeline/bdc_filings.py" in mapping["us-gaap:InvestmentOwnedAtFairValue"]["inherited_from"]
    assert mapping["us-gaap:InvestmentIndustrySectorExtensibleEnumeration"]["provenance"] == "derived"
    deps = {d["name"]: d for d in doc["dependencies"]}
    for name in ("concept_map", "context_role_classifier", "explicit_identity_rules", "unit_definition"):
        assert deps[name]["provenance"] == "inherited" and len(deps[name]["sha256"]) == 64


# ---------------------------------------------------------------- footnotes

FOOTNOTE_LINK = (
    '<link:footnoteLink xlink:type="extended" xlink:role="http://www.xbrl.org/2003/role/link">'
    '<link:loc xlink:type="locator" xlink:href="#f_fv" xlink:label="loc1"/>'
    '<link:footnote xlink:type="resource" xlink:label="fn1" xlink:role="http://www.xbrl.org/2003/role/footnote"'
    ' xml:lang="en-US">Investment is on non-accrual status.</link:footnote>'
    '<link:footnoteArc xlink:type="arc" xlink:from="loc1" xlink:to="fn1"'
    ' xlink:arcrole="http://www.xbrl.org/2003/arcrole/fact-footnote"/></link:footnoteLink>')


def test_footnote_channel_is_unsupported_without_a_footnote_link(tmp_path):
    contexts, facts = position("p1", "Acme Corp", "100")
    doc = collect(tmp_path, document(contexts, facts))
    assert doc["channels"]["footnotes"]["state"] == "unsupported"
    nd = [o for o in outcomes(doc, "non_disclosure") if o["subject"]["field"] == "non_accrual"]
    assert nd[0]["outcome"] == "insufficient_evidence"


def test_footnote_arcs_are_recorded_when_present(tmp_path):
    contexts = [ctx("p1", Q, [("typed", IDENT, "Acme Corp")])]
    facts = [fact("us-gaap:InvestmentOwnedAtFairValue", "p1", "100", unit="usd", decimals="0",
                  fid="f_fv")]
    doc = collect(tmp_path, document(contexts, facts, extra=FOOTNOTE_LINK))
    assert doc["channels"]["footnotes"]["state"] == "complete"
    note = doc["footnotes"]["resources"][0]
    fv_index = next(f["i"] for f in doc["facts"] if f["id"] == "f_fv")
    assert note["fact_indices"] == [fv_index] and "non-accrual" in note["preview"]
    nd = [o for o in outcomes(doc, "non_disclosure") if o["subject"]["field"] == "non_accrual"]
    assert nd[0]["outcome"] == "candidate" and nd[0]["finding"] == "disclosed_outside_tagged_concept"


# ---------------------------------------------------------------- non-disclosure detector

def test_non_disclosure_positive_false_positive_and_insufficient(tmp_path):
    # PIK in the identifier text is disclosure, not absence (false-positive control).
    contexts, facts = position("p1", "Acme Corp Term Loan SOFR+6.00% 2.00% PIK", "100")
    doc = collect(tmp_path, document(contexts, facts, extra=FOOTNOTE_LINK.replace(
        "Investment is on non-accrual status.", "Valued using Level 3 inputs.")))
    nd = {o["subject"]["field"]: o for o in outcomes(doc, "non_disclosure")}
    assert nd["pik_rate"]["outcome"] == "candidate"
    assert nd["fair_value"]["outcome"] == "resolved" and nd["fair_value"]["finding"] == "observed"
    # Every channel complete and no term anywhere: the only resolved absence (positive control).
    assert nd["shares_held"]["outcome"] == "resolved"
    assert nd["shares_held"]["finding"] == "not_observed_in_complete_instance"
    assert "full_filing" not in json.dumps(nd["shares_held"])
    # Insufficient control: same instance without the footnote link.
    doc2 = collect(tmp_path, document(contexts, facts))
    nd2 = {o["subject"]["field"]: o for o in outcomes(doc2, "non_disclosure")}
    assert nd2["shares_held"]["outcome"] == "insufficient_evidence"
    assert "footnotes" in nd2["shares_held"]["evidence"]["unsupported_channels"]


# ---------------------------------------------------------------- subtotal detector

def _fl(cid, ident, fv, currency="usd"):
    return position(cid, ident, fv, unit=currency,
                    dims=[("explicit", TYPE_AXIS, "us-gaap:FirstLienMember")])


def test_subtotal_positive_structural_parent_with_heading_evidence(tmp_path):
    contexts, facts = assemble(
        _fl("a", "Alpha Corp", "60"), _fl("b", "Beta Corp", "40"),
        ([ctx("fl_total", Q, [("explicit", TYPE_AXIS, "us-gaap:FirstLienMember")])],
         [fact("us-gaap:InvestmentOwnedAtFairValue", "fl_total", "100", unit="usd", decimals="0")]),
        ([ctx("fund")], [fact("us-gaap:InvestmentOwnedAtFairValue", "fund", "100", unit="usd",
                              decimals="0")]))
    doc = collect(tmp_path, document(contexts, facts))
    resolved = {o["subject"]["context_id"]: o for o in outcomes(doc, "subtotal")
                if o["outcome"] == "resolved" and o["finding"] == "structural_subtotal"}
    assert set(resolved) == {"fl_total", "fund"}
    assert sorted(resolved["fl_total"]["evidence"]["children"]) == ["a", "b"]
    assert resolved["fl_total"]["evidence"]["heading"] == "category_only_dimensions"


def test_subtotal_false_positive_total_safety_and_coincidental_labelled_sum(tmp_path):
    contexts, facts = assemble(
        position("ts", "Total Safety U.S., Inc. First Lien Term Loan", "30"),
        position("x", "Xeno Corp", "10"), position("y", "Yolo Corp", "20"),
        position("z", "Zeta Corp", "5"))
    doc = collect(tmp_path, document(contexts, facts))
    ts = [o for o in outcomes(doc, "subtotal") if o["subject"]["context_id"] == "ts"]
    assert ts and ts[0]["outcome"] == "resolved" and ts[0]["finding"] == "not_subtotal"
    # 30 == 10 + 20 is a coincidental subset sum; no subset search is performed.
    assert not [o for o in outcomes(doc, "subtotal") if o["outcome"] == "candidate"]


def test_subtotal_insufficient_when_children_are_not_comparable(tmp_path):
    contexts, facts = assemble(
        _fl("a", "Alpha Corp", "60"), _fl("b", "Beta Corp", "40", currency="eur"),
        ([ctx("fl_total", Q, [("explicit", TYPE_AXIS, "us-gaap:FirstLienMember")])],
         [fact("us-gaap:InvestmentOwnedAtFairValue", "fl_total", "100", unit="usd", decimals="0")]))
    doc = collect(tmp_path, document(contexts, facts))
    got = [o for o in outcomes(doc, "subtotal") if o["subject"]["context_id"] == "fl_total"]
    assert got[0]["outcome"] == "insufficient_evidence"
    assert got[0]["finding"] == "children_not_comparable"


def test_wrapper_marker_is_inherited_corroboration_only(tmp_path):
    contexts, facts = assemble(
        position("a", "Alpha Corp", "60"), position("b", "Beta Corp", "40"),
        position("t", "Total Investments", "100"))
    marker = dict(markers=["total investments"], path="wrapper.json", sha256="0" * 64)
    doc = collect(tmp_path, document(contexts, facts), aggregate_markers=marker)
    got = [o for o in outcomes(doc, "subtotal") if o["subject"]["context_id"] == "t"][0]
    assert got["outcome"] == "candidate"
    corroboration = got["evidence"]["wrapper_marker"]
    assert corroboration["provenance"] == "inherited" and corroboration["marker"] == "total investments"
    # No census value is read from the wrapper: every position value points at instance facts.
    for pos in doc["positions"]:
        for index in pos["fields"]["fair_value"]["fact_indices"]:
            assert doc["facts"][index]["qname"] == "us-gaap:InvestmentOwnedAtFairValue"
    assert [d for d in doc["dependencies"] if d["name"] == "wrapper_aggregate_markers"][0][
        "provenance"] == "inherited"


# ---------------------------------------------------------------- alternate-view detector

def _tranche(cid, ident, fv, maturity, dims=()):
    extra = [fact("us-gaap:InvestmentMaturityDate", cid, maturity),
             fact("us-gaap:InvestmentInterestRate", cid, "0.1", unit="pure", decimals="4")]
    return position(cid, ident, fv, dims=dims, extra=extra)


def test_alternate_view_candidate_needs_tranche_evidence_and_a_presentation_axis(tmp_path):
    contexts, facts = assemble(
        _tranche("v1", "Acme Corp First Lien", "100", "2028-01-01"),
        _tranche("v2", "Acme Corp First Lien", "100", "2028-01-01",
                 dims=[("explicit", AFFIL_AXIS, "us-gaap:NoncontrolledAffiliatesMember")]))
    doc = collect(tmp_path, document(contexts, facts))
    got = outcomes(doc, "alternate_view")
    assert len(got) == 1 and got[0]["outcome"] == "candidate"
    assert got[0]["evidence"]["differing_axes"] == [AFFIL_AXIS]
    assert not {"canonical", "canonical_view", "selected_view", "winner"} & set(got[0]["evidence"])


def test_alternate_view_false_positive_same_value_distinct_tranches_and_scopes(tmp_path):
    contexts, facts = assemble(
        _tranche("t1", "Acme Corp First Lien", "100", "2028-01-01"),
        _tranche("t2", "Acme Corp First Lien", "100", "2029-06-30",
                 dims=[("explicit", TYPE_AXIS, "us-gaap:FirstLienMember")]),
        _tranche("s1", "Beta Corp Term Loan", "50", "2027-01-01"),
        _tranche("s2", "Beta Corp Term Loan", "50", "2027-01-01",
                 dims=[("explicit", SCOPE_AXIS, "srt:ParentCompanyMember")]))
    doc = collect(tmp_path, document(contexts, facts))
    got = {tuple(o["subject"]["context_ids"]): o for o in outcomes(doc, "alternate_view")}
    assert got[("t1", "t2")]["outcome"] == "resolved"
    assert got[("t1", "t2")]["finding"] == "distinct_tranches"
    assert got[("s1", "s2")]["outcome"] == "resolved"
    assert got[("s1", "s2")]["finding"] == "distinct_accounting_scope"
    # Different borrowers with equal balances are never compared.
    assert all(o["outcome"] != "candidate" for o in got.values())


def test_alternate_view_insufficient_when_only_balances_match(tmp_path):
    contexts, facts = assemble(
        position("b1", "Acme Corp", "100"),
        position("b2", "Acme Corp", "100",
                 dims=[("explicit", AFFIL_AXIS, "us-gaap:NoncontrolledAffiliatesMember")]))
    doc = collect(tmp_path, document(contexts, facts))
    got = outcomes(doc, "alternate_view")
    assert got[0]["outcome"] == "insufficient_evidence"
    assert got[0]["finding"] == "balances_only"


# ---------------------------------------------------------------- partition detector

def _many(prefix, texts, dims=()):
    return [position(prefix + str(i), text, str(10 + i), dims=dims) for i, text in enumerate(texts)]


def test_partition_true_mixed_format_emits_an_axis_member_predicate(tmp_path):
    pipe = ["Borrower%d | First Lien | SOFR+5.00%%" % i for i in range(6)]
    comma = ["Lender%d, Second Lien, 9.00%%" % i for i in range(6)]
    parts = (_many("a", pipe, dims=[("explicit", TYPE_AXIS, "us-gaap:FirstLienMember")])
             + _many("b", comma, dims=[("explicit", TYPE_AXIS, "us-gaap:SecondLienMember")]))
    doc = collect(tmp_path, document(*assemble(*parts)))
    got = outcomes(doc, "partition")
    assert got[0]["outcome"] == "resolved" and got[0]["finding"] == "evidenced_partition"
    predicates = got[0]["evidence"]["predicates"]
    kinds = {p["kind"] for p in predicates}
    assert "axis_member" in kinds
    for predicate in predicates:
        envelope.check_predicate(predicate)
        assert "row" not in json.dumps(predicate)
    axis = next(p for p in predicates if p["kind"] == "axis_member")
    assert (axis["axis"], axis["member"]) in {(TYPE_AXIS, "us-gaap:FirstLienMember"),
                                              (TYPE_AXIS, "us-gaap:SecondLienMember")}


def test_partition_false_positive_punctuation_inside_borrower_is_one_dialect(tmp_path):
    texts = ["Acme%d, Inc. - First Lien - SOFR+5" % i for i in range(5)] + \
            ["Beta%d LLC - Second Lien - SOFR+7" % i for i in range(5)]
    doc = collect(tmp_path, document(*assemble(*_many("p", texts))))
    got = outcomes(doc, "partition")
    assert got[0]["outcome"] == "resolved" and got[0]["finding"] == "single_dialect"


def test_partition_insufficient_without_a_structural_discriminator(tmp_path):
    # Two delimiters in disjoint rows, but segment counts vary inside each group and no
    # axis, concept or prefix separates them: nothing structural to partition on.
    forms = ("Co%d | First Lien", "Co%d | First Lien | L+5", "Co%d, First Lien", "Co%d, First Lien, 5%%")
    texts = [forms[i % 4] % i for i in range(12)]
    doc = collect(tmp_path, document(*assemble(*_many("p", texts))))
    got = outcomes(doc, "partition")
    assert got[0]["outcome"] == "insufficient_evidence"
    assert got[0]["finding"] == "no_structural_discriminator"
    stub = got[0]["evidence"]["packet_stub"]
    assert stub["groups"] and "question" in stub


# ---------------------------------------------------------------- schema, propagation, validation

def test_census_validates_against_schema_and_rejects_bad_outcomes(tmp_path):
    contexts, facts = assemble(_fl("a", "Alpha Corp", "60"), _fl("b", "Beta Corp", "40"))
    doc = collect(tmp_path, document(contexts, facts))
    assert census.validate_census(doc)["ok"] is True
    bad = json.loads(json.dumps(doc))
    bad["detectors"]["subtotal"]["outcomes"].append(dict(
        detector="subtotal", subject={}, outcome="maybe", finding="x", evidence={},
        provenance="derived", depends_on_channels=[]))
    assert census.validate_census(bad)["ok"] is False


def test_semantic_validation_rejects_absence_claim_on_incomplete_channel(tmp_path):
    contexts, facts = position("p1", "Acme Corp", "100")
    doc = collect(tmp_path, document(contexts, facts, extra=FOOTNOTE_LINK))
    claim = by_finding(doc, "non_disclosure", "not_observed_in_complete_instance")
    assert claim
    bad = json.loads(json.dumps(doc))
    bad["channels"]["text_facts"]["state"] = "truncated"
    report = census.validate_census(bad)
    assert report["ok"] is False and any("absence" in e for e in report["errors"])


def test_metrics_carry_channel_completeness(tmp_path):
    parts = [position("p%d" % i, "Borrower %d" % i, "100") for i in range(4)]
    doc = collect(tmp_path, document(*assemble(*parts)), bounds=census.Bounds(max_facts=3))
    metrics = {m["name"]: m for m in doc["metrics"]}
    assert metrics["position_observations"]["completeness"] == "incomplete"
    assert "numeric_facts" in metrics["position_observations"]["depends_on_channels"]


def test_serialised_census_is_ascii_and_bounded_text(tmp_path):
    blob = "Long policy text é " * 500
    contexts, facts = position("p1", "Acme Corp", "100")
    facts.append(fact("us-gaap:SignificantAccountingPoliciesTextBlock", "dei_ctx", blob))
    doc = collect(tmp_path, document(contexts, facts))
    text = census.dumps_census(doc)
    text.encode("ascii")
    block = next(f for f in doc["facts"] if f["qname"].endswith("TextBlock"))
    assert block["text_stored"] == "preview" and block["text_chars"] == len(blob.strip())
    assert len(block["text_sha256"]) == 64


# ---------------------------------------------------------------- stage runner and lease

def _entry(paths, cik, accession, text):
    path = put_instance(paths.main_repo_root, cik, accession, text)
    return dict(cik=cik, quarter=Q, role="q1", status="selected", accession_number=accession,
                form_type="10-Q", source_path=str(path))


def test_light_fund_quarter_runs_through_the_cached_stage(tmp_path):
    paths = fake_paths(tmp_path, run_id="stageb-test")
    contexts, facts = position("p1", "Acme Corp", "100")
    entry = _entry(paths, CIK, "0000000000-23-000001", document(contexts, facts))
    first = census_run.census_fund_quarter(paths, entry, lease_factory=None)
    assert first["status"] == "collected" and first["cache"] == "miss"
    written = json.loads((paths.run_root / "census" / CIK / (Q + ".json")).read_text(encoding="ascii"))
    assert written["complete"] is True
    assert census.validate_census(written["result"])["ok"] is True
    again = census_run.census_fund_quarter(paths, entry, lease_factory=None)
    assert again["cache"] == "hit"


def test_heavy_fund_quarter_without_a_lease_is_lease_refused_not_insufficient(tmp_path):
    paths = fake_paths(tmp_path, run_id="stageb-test")
    contexts, facts = position("p1", "Acme Corp", "100")
    entry = _entry(paths, "0001287750", "0001287750-23-000001",
                   document(contexts, facts).replace(CIK, "0001287750"))
    got = census_run.census_fund_quarter(paths, entry, lease_factory=None)
    assert got["status"] == "lease_refused"
    assert not (paths.run_root / "census" / "0001287750").exists()


def test_refused_lease_factory_propagates_as_lease_refused(tmp_path):
    paths = fake_paths(tmp_path, run_id="stageb-test")
    contexts, facts = position("p1", "Acme Corp", "100")
    entry = _entry(paths, "0001803498", "0001803498-23-000001",
                   document(contexts, facts).replace(CIK, "0001803498"))

    def refusing():
        raise LeaseRefused("another controller holds heavy.lock")

    got = census_run.census_fund_quarter(paths, entry, lease_factory=refusing)
    assert got["status"] == "lease_refused" and "heavy.lock" in got["reason"]


def test_after_a_refusal_heavy_items_are_not_retried(tmp_path):
    paths = fake_paths(tmp_path, run_id="stageb-test")
    contexts, facts = position("p1", "Acme Corp", "100")
    entry = _entry(paths, "0001287750", "0001287750-23-000001",
                   document(contexts, facts).replace(CIK, "0001287750"))

    def must_not_be_called():
        raise AssertionError("lease retried after a refusal")

    got = census_run.census_fund_quarter(paths, entry, lease_factory=must_not_be_called,
                                         refuse_heavy="refused earlier")
    assert got["status"] == "lease_refused" and got["reason"].startswith("not attempted")
    light = _entry(paths, CIK, "0000000000-23-000001", document(contexts, facts))
    assert census_run.census_fund_quarter(paths, light, lease_factory=must_not_be_called,
                                          refuse_heavy="refused earlier")["status"] == "collected"


def test_unavailable_fund_quarter_is_reported_not_collected(tmp_path):
    paths = fake_paths(tmp_path, run_id="stageb-test")
    got = census_run.census_fund_quarter(paths, dict(cik=CIK, quarter=Q, role="q2",
                                                 status="unavailable", reason="x"),
                                     lease_factory=None)
    assert got["status"] == "unavailable"


def test_duckdb_connect_is_only_in_the_factory():
    for module in (census, census_collect, census_detect, census_run):
        assert "duckdb.connect(" not in Path(module.__file__).read_text(encoding="ascii")


# ---------------------------------------------------------------- cached source (launcher only)

@pytest.mark.needs_cache
def test_cached_stellus_instance_census_is_complete_and_valid():
    data_root = os.environ.get("PROFILE_PILOT_DATA_ROOT")
    if not data_root:
        pytest.skip("PROFILE_PILOT_DATA_ROOT not set (run through the pilot launcher)")
    path = Path(data_root) / "raw" / "filings" / "bdc_xbrl" / "1901037" / "000155837022016375.xml"
    if not path.is_file():
        pytest.skip("cached Stellus instance missing")
    meta = dict(cik="0001901037", report_date="2022-09-30", accession_number="0001558370-22-016375",
                form_type="10-Q", role="q1")
    doc = census.build_census(path, meta)
    assert doc["collection"]["state"] == "complete"
    assert census.validate_census(doc)["ok"] is True
    relations = {p["relation"] for p in doc["periods"]}
    assert {"document_period_end", "comparative"} <= relations
    assert doc["summary"]["position_observations"] > 0
