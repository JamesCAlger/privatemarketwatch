"""SP3 proper Task 8: consistency contract (spec 4.1) and the sub-project 3 exit test (spec 8 row 3).

Three post-brief decisions are exercised here (see profile_consistency.py's module docstring and
task-8-report.md for the full rationale): the legacy reporting_entity_identifier_suffixes counterpart (A4),
a token comparison where either side strips to empty is insufficient_evidence (representation_mismatch,
TCW/Onex-shaped), and the two unpaired semantic wrapper keys (source_encodings.cash_identifiers,
invariants.rate_sanity) that always appear as insufficient_evidence rows. Because those two unpaired keys
guarantee insufficient_evidence >= 2 on every contract built from a real wrapper_v3 fixture (none of which
populate them), an agreeing wrapper's verdict is "no_breach", never "holds" -- that is the reason the
no_breach/holds distinction exists at all.
"""
from __future__ import annotations

import copy

from scripts.profile_pilot import profile_consistency as pc
from scripts.profile_pilot import profile_inception as pi
from tests.test_profile_pilot_profile_families import ARES, STELLUS, wrapper_v3
from tests.test_profile_pilot_profile_inception import NOW, Q4, RUN, inception_inputs

ENTS = ["Emerald JV LP"]


def doc_with(wrapper=None):
    inputs = inception_inputs(wrapper=wrapper)
    return pi.build_document(STELLUS, inputs=inputs, recorded_at=NOW, run_id=RUN, git_head="2a218e9")


def rows(result):
    return {r["pointer"]: r for r in result["keys"]}


def test_agreeing_wrapper_is_no_breach_not_holds():
    out = pc.consistency_contract(doc_with(), report_date=Q4, code_mirror=ENTS)
    r = rows(out)
    # Zero breaches, but the two unpaired semantic keys (no profile_key counterpart at all) are always
    # insufficient_evidence, so the filer verdict is "no_breach", not "holds". Both counts are published.
    assert out["counts"]["breach"] == 0
    assert out["verdict"] == "no_breach"
    assert out["counts"]["insufficient_evidence"] >= 2
    assert r["/identifier_format/delimiter"]["status"] == "holds"
    assert r["/source_encodings/reporting_entity_suffixes"]["status"] == "holds"
    assert r[pc.CODE_MIRROR_POINTER]["status"] == "holds"
    assert r["/invariants/fv_reconciliation/source_field"]["status"] == "not_applicable"
    # The legacy pointer is absent from the default fixture's wrapper -> not_applicable, not insufficient.
    assert r["/source_encodings/reporting_entity_identifier_suffixes"]["status"] == "not_applicable"
    # The two unpaired keys appear explicitly, as insufficient_evidence, not omitted.
    assert r["/source_encodings/cash_identifiers"]["status"] == "insufficient_evidence"
    assert r["/source_encodings/cash_identifiers"]["wrapper_present"] is False
    assert r["/invariants/rate_sanity"]["status"] == "insufficient_evidence"
    assert out["evaluated_dates"] == [Q4] and out["unevaluated"]["block_valid"] == [None, None]


def test_delimiter_disagreement_is_a_breach():
    w = wrapper_v3(STELLUS, source_encodings={"reporting_entity_suffixes": ENTS})
    w["identifier_format"]["delimiter"] = "; "
    out = pc.consistency_contract(doc_with(w), report_date=Q4, code_mirror=ENTS)
    assert out["verdict"] == "breach"
    assert rows(out)["/identifier_format/delimiter"]["reason"] == "value_disagrees"


def test_code_mirror_disagreement_or_orphan_is_a_breach():
    out = pc.consistency_contract(doc_with(), report_date=Q4, code_mirror=["Other JV LP"])
    assert rows(out)[pc.CODE_MIRROR_POINTER]["status"] == "breach"
    bare = doc_with(wrapper_v3(STELLUS))           # no source_encodings -> no reporting-entities entry
    out = pc.consistency_contract(bare, report_date=Q4, code_mirror=ENTS)
    assert rows(out)[pc.CODE_MIRROR_POINTER]["status"] == "breach"
    # Zero breaches with an empty code mirror, but still no_breach (never holds): the two unpaired keys.
    assert pc.consistency_contract(bare, report_date=Q4, code_mirror=())["verdict"] == "no_breach"
    assert pc.consistency_contract(bare, report_date=Q4, code_mirror=())["counts"]["breach"] == 0


def test_reporting_entity_identifier_suffixes_is_also_checked():
    """A4: BCRED's wrapper carries both reporting_entity_suffixes and the legacy identifier_suffixes
    pointer; the entry reads only the former, but both must agree with it."""
    w = wrapper_v3(STELLUS, source_encodings={"reporting_entity_suffixes": ENTS,
                                              "reporting_entity_identifier_suffixes": ENTS})
    out = pc.consistency_contract(doc_with(w), report_date=Q4, code_mirror=ENTS)
    r = rows(out)
    assert r["/source_encodings/reporting_entity_suffixes"]["status"] == "holds"
    assert r["/source_encodings/reporting_entity_identifier_suffixes"]["status"] == "holds"
    assert out["counts"]["breach"] == 0


def test_reporting_entity_identifier_suffixes_disagreement_is_a_breach():
    w = wrapper_v3(STELLUS, source_encodings={"reporting_entity_suffixes": ENTS,
                                              "reporting_entity_identifier_suffixes": ["Other JV LP"]})
    out = pc.consistency_contract(doc_with(w), report_date=Q4, code_mirror=ENTS)
    r = rows(out)
    assert r["/source_encodings/reporting_entity_suffixes"]["status"] == "holds"
    assert r["/source_encodings/reporting_entity_identifier_suffixes"]["status"] == "breach"
    assert r["/source_encodings/reporting_entity_identifier_suffixes"]["reason"] == "value_disagrees"
    assert out["verdict"] == "breach"


def test_token_disagreement_with_an_empty_strip_is_insufficient_evidence_not_holds_or_breach():
    """A one-space delimiter (TCW 0001715933, Onex 0001860424 shape) is not an evaluable token."""
    assert pc._compare("token", " ", " ") == "insufficient_evidence"   # both sides empty: not a trivial holds
    assert pc._compare("token", " ", "|") == "insufficient_evidence"   # wrapper side empty
    assert pc._compare("token", "|", "") == "insufficient_evidence"    # converted side empty
    w = wrapper_v3(STELLUS, source_encodings={"reporting_entity_suffixes": ENTS})
    w["identifier_format"]["delimiter"] = " "
    out = pc.consistency_contract(doc_with(w), report_date=Q4, code_mirror=ENTS)
    r = rows(out)["/identifier_format/delimiter"]
    assert r["status"] == "insufficient_evidence" and r["reason"] == "representation_mismatch"
    assert out["verdict"] == "no_breach" and out["counts"]["breach"] == 0


def test_compare_modes():
    assert pc._compare("token", " | ", "|") == "holds"
    assert pc._compare("token", " | ", " ; ") == "breach"
    assert pc._compare("exact_set", ["b", "a"], ["a", "b"]) == "holds"
    assert pc._compare("representation", ["total investments"], ["Total Investments"]) == "insufficient_evidence"
    assert pc._compare("exact", "0001901037", "0001901038") == "breach"


def test_exit_test_pass_and_failures():
    doc = doc_with()
    con = {STELLUS: pc.consistency_contract(doc, report_date=Q4, code_mirror=ENTS)}
    ok_rt = {"ok": True}
    out = pc.exit_test({STELLUS: doc}, con, ok_rt, report_date=Q4, expected_ciks=(STELLUS,))
    assert out["verdict"] == "PASS" and out["spec_exit"] is True and out["per_cik"][STELLUS]["resolver"] is True
    # The no_breach verdict still counts as "consistency holds" for the exit test's zero-breach criterion.
    assert con[STELLUS]["verdict"] == "no_breach"
    assert out["per_cik"][STELLUS]["consistency"] is True
    assert out["per_cik"][STELLUS]["resolved"] + out["per_cik"][STELLUS]["stubs"] == 56
    assert pc.exit_test({STELLUS: doc}, con, ok_rt, report_date=Q4,
                        expected_ciks=(STELLUS, ARES))["missing_filers"] == [ARES]
    assert pc.exit_test({STELLUS: doc}, con, {"ok": False}, report_date=Q4,
                        expected_ciks=(STELLUS,))["verdict"] == "FAIL"
    holed = copy.deepcopy(doc)
    holed["stubs"] = [s for s in holed["stubs"] if s["key"] != "income_proofs.duration"]
    bad = pc.exit_test({STELLUS: holed}, con, ok_rt, report_date=Q4, expected_ciks=(STELLUS,))
    assert bad["verdict"] == "FAIL"
    assert bad["per_cik"][STELLUS]["coverage_missing"] == ["income_proofs.duration"]
    assert bad["per_cik"][STELLUS]["resolver_no_entry"] == ["income_proofs.duration"]


def test_exit_test_fails_when_a_filer_breaches():
    w = wrapper_v3(STELLUS, source_encodings={"reporting_entity_suffixes": ENTS})
    w["identifier_format"]["delimiter"] = "; "
    doc = doc_with(w)
    con = {STELLUS: pc.consistency_contract(doc, report_date=Q4, code_mirror=ENTS)}
    out = pc.exit_test({STELLUS: doc}, con, {"ok": True}, report_date=Q4, expected_ciks=(STELLUS,))
    assert con[STELLUS]["verdict"] == "breach"
    assert out["per_cik"][STELLUS]["consistency"] is False
    assert out["verdict"] == "FAIL" and out["spec_exit"] is False
