"""SP3 proper Task 8: consistency contract (spec 4.1) and the sub-project 3 exit test (spec 8 row 3).

Three post-brief decisions are exercised here (see profile_consistency.py's module docstring and
task-8-report.md for the full rationale): the legacy reporting_entity_identifier_suffixes counterpart (A4),
a token comparison where either side strips to empty is insufficient_evidence (representation_mismatch,
TCW/Onex-shaped), and the no_breach/holds distinction (zero breaches with some insufficient_evidence rows is
"no_breach", never "holds").

Final whole-branch review (C1, C2): a filer whose contract compared ZERO rows is "insufficient_evidence", which
fails; the exit test publishes two separately named fields, inception_gate (the CLI's exit code) and spec_exit
(the spec's criterion: every filer "holds").

Owner rulings 2026-10-04. Ruling 1: source_encodings.cash_identifiers and invariants.rate_sanity are PROCEDURE,
outside the contract -- not key rows, not counted as insufficient_evidence, published per filer in
procedure_keys_outside_contract with a named guard (independent_totals / production_rate_rules). Ruling 3: identity rows
(entity CIK, registrant name) do not satisfy the gate; a filer needs one SUBSTANTIVE compared row with zero
breaches; an identity-row breach is still a breach.
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
    # Zero breaches, but some counterpart keys have no accepted entry (insufficient_evidence), so the filer
    # verdict is "no_breach", not "holds". Both counts are published.
    assert out["counts"]["breach"] == 0
    assert out["verdict"] == "no_breach"
    assert out["counts"]["insufficient_evidence"] >= 1
    assert r["/identifier_format/delimiter"]["status"] == "holds"
    assert r["/source_encodings/reporting_entity_suffixes"]["status"] == "holds"
    assert r[pc.CODE_MIRROR_POINTER]["status"] == "holds"
    assert r["/invariants/fv_reconciliation/source_field"]["status"] == "not_applicable"
    # The legacy pointer is absent from the default fixture's wrapper -> not_applicable, not insufficient.
    assert r["/source_encodings/reporting_entity_identifier_suffixes"]["status"] == "not_applicable"
    # Ruling 1: the two procedure keys are not key rows of the contract.
    assert "/source_encodings/cash_identifiers" not in r and "/invariants/rate_sanity" not in r
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
    # Zero breaches with an empty code mirror, but still no_breach (not holds): counterpart keys with a stub.
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
    # Final review C1/C2: the CLI's gate (inception_gate) and the spec's exit criterion (spec_exit) are two
    # separately named fields. A no_breach filer WITH compared rows passes the gate; it does not meet the spec.
    assert out["verdict"] == "PASS" and out["inception_gate"] is True and out["inception_gate_reasons"] == []
    assert out["per_cik"][STELLUS]["resolver"] is True
    assert con[STELLUS]["verdict"] == "no_breach"
    assert out["per_cik"][STELLUS]["consistency"] is True
    assert out["per_cik"][STELLUS]["consistency_verdict"] == "no_breach"
    assert out["spec_exit"] is False
    assert [r["code"] for r in out["spec_exit_reasons"]] == ["consistency_not_holds"]
    assert out["spec_exit_reasons"][0]["verdicts"] == {STELLUS: "no_breach"}
    assert "holds on all" not in out["spec_exit_statement"] and out["spec_exit_statement"].startswith("NOT MET")
    assert out["consistency_verdict_counts"] == {"holds": 0, "no_breach": 1, "breach": 0,
                                                 "insufficient_evidence": 0}
    row_counts = out["per_cik"][STELLUS]["consistency_rows"]
    assert row_counts["compared"] == row_counts["holds"] + row_counts["breach"] >= 1
    assert row_counts["total"] == (row_counts["compared"] + row_counts["insufficient_evidence"]
                                   + row_counts["not_applicable"]) == len(con[STELLUS]["keys"])
    assert out["per_cik"][STELLUS]["resolved"] + out["per_cik"][STELLUS]["stubs"] == 56
    grid = out["per_cik"][STELLUS]["grid"]
    assert grid["accepted"] + grid["stubs"] == 56 and grid["candidate"] <= grid["stubs"]
    assert out["per_cik"][STELLUS]["published_basis"] == "accepted"
    missing = pc.exit_test({STELLUS: doc}, con, ok_rt, report_date=Q4, expected_ciks=(STELLUS, ARES))
    assert missing["missing_filers"] == [ARES] and missing["inception_gate"] is False
    assert "missing_filers" in [r["code"] for r in missing["inception_gate_reasons"]]
    no_rt = pc.exit_test({STELLUS: doc}, con, {"ok": False}, report_date=Q4, expected_ciks=(STELLUS,))
    assert no_rt["verdict"] == "FAIL" and no_rt["inception_gate"] is False
    assert [r["code"] for r in no_rt["inception_gate_reasons"]] == ["roundtrip_or_loader_parity"]
    holed = copy.deepcopy(doc)
    holed["stubs"] = [s for s in holed["stubs"] if s["key"] != "income_proofs.duration"]
    bad = pc.exit_test({STELLUS: holed}, con, ok_rt, report_date=Q4, expected_ciks=(STELLUS,))
    assert bad["verdict"] == "FAIL"
    assert bad["per_cik"][STELLUS]["coverage_missing"] == ["income_proofs.duration"]
    assert bad["per_cik"][STELLUS]["resolver_no_entry"] == ["income_proofs.duration"]


def test_verdict_vocabulary():
    def counts(holds=0, breach=0, insufficient=0, na=0):
        return {"holds": holds, "breach": breach, "insufficient_evidence": insufficient, "not_applicable": na}
    assert pc._verdict(counts(holds=3)) == "holds"
    assert pc._verdict(counts(holds=1, insufficient=2)) == "no_breach"
    assert pc._verdict(counts(holds=1, breach=1, insufficient=2)) == "breach"
    assert pc._verdict(counts(breach=1)) == "breach"
    # C1: nothing was compared. That is not a zero-breach outcome, it is no outcome.
    assert pc._verdict(counts(insufficient=9, na=5)) == "insufficient_evidence"
    assert pc._verdict(counts(na=14)) == "insufficient_evidence"
    assert pc._verdict(counts()) == "insufficient_evidence"


def zero_comparison_doc():
    """The real-data shape of NexPoint 0001588272 / TCW 0001715933: no Q4 census, so every wrapper key with
    a counterpart (even /cik) has no accepted entry; no reporting-entity list anywhere."""
    inputs = inception_inputs(q4=False, q1=False, wrapper=wrapper_v3(STELLUS))
    return pi.build_document(STELLUS, inputs=inputs, recorded_at=NOW, run_id=RUN, git_head="2a218e9")


def test_zero_comparison_filer_is_insufficient_evidence_and_fails_the_exit_test():
    doc = zero_comparison_doc()
    con = pc.consistency_contract(doc, report_date=Q4, code_mirror=())
    assert con["counts"]["holds"] == 0 and con["counts"]["breach"] == 0
    assert con["counts"]["insufficient_evidence"] >= 3
    assert rows(con)["/cik"]["status"] == "insufficient_evidence"
    assert con["verdict"] == "insufficient_evidence"
    out = pc.exit_test({STELLUS: doc}, {STELLUS: con}, {"ok": True}, report_date=Q4, expected_ciks=(STELLUS,))
    row = out["per_cik"][STELLUS]
    assert row["criterion_1"] is True and row["resolver"] is True      # every key still has a stub
    assert row["consistency"] is False and row["consistency_rows"]["compared"] == 0
    assert out["inception_gate"] is False and out["verdict"] == "FAIL" and out["spec_exit"] is False
    gate = {r["code"]: r for r in out["inception_gate_reasons"]}
    assert gate["consistency_insufficient_evidence"]["ciks"] == [STELLUS]
    assert out["consistency_verdict_counts"]["insufficient_evidence"] == 1


def test_no_live_wrapper_block_is_insufficient_evidence_and_fails_the_exit_test():
    doc = doc_with()
    doc["wrapper_section"]["blocks"] = []
    con = pc.consistency_contract(doc, report_date=Q4, code_mirror=ENTS)
    assert con["verdict"] == "insufficient_evidence" and con["block_id"] is None and con["keys"] == []
    assert con["counts"] == {s: 0 for s in pc.STATUSES}
    out = pc.exit_test({STELLUS: doc}, {STELLUS: con}, {"ok": True}, report_date=Q4, expected_ciks=(STELLUS,))
    assert out["inception_gate"] is False and out["verdict"] == "FAIL"
    assert out["per_cik"][STELLUS]["consistency_rows"] == {"total": 0, "compared": 0, "holds": 0, "breach": 0,
                                                          "insufficient_evidence": 0, "not_applicable": 0}


def test_spec_exit_is_true_only_when_every_filer_holds():
    """The spec criterion (4.1: a counterpart wrapper key MUST have an accepted entry) is verdict == holds for
    every filer. Since owner ruling 1 it is reachable in principle (the two procedure keys are outside the
    contract); this fixture's wrapper still has counterpart keys with a stub, so the all-holds case is built
    by hand to prove the field can be true."""
    doc = doc_with()
    real = pc.consistency_contract(doc, report_date=Q4, code_mirror=ENTS)
    keys = [r for r in real["keys"] if r["status"] in ("holds", "not_applicable")]
    counts = {s: sum(r["status"] == s for r in keys) for s in pc.STATUSES}
    assert counts["holds"] >= 1 and pc._verdict(counts) == "holds"
    holds = dict(real, keys=keys, counts=counts, verdict=pc._verdict(counts))
    out = pc.exit_test({STELLUS: doc}, {STELLUS: holds}, {"ok": True}, report_date=Q4, expected_ciks=(STELLUS,))
    assert out["spec_exit"] is True and out["spec_exit_reasons"] == []
    assert out["spec_exit_statement"] == pc.EXIT_TEST_TEXT
    assert out["inception_gate"] is True and out["verdict"] == "PASS"
    # one filer short of holds -> false, with the reason
    two = pc.exit_test({STELLUS: doc, ARES: doc}, {STELLUS: holds, ARES: real}, {"ok": True}, report_date=Q4,
                       expected_ciks=(STELLUS, ARES))
    assert two["spec_exit"] is False and two["inception_gate"] is True
    assert two["spec_exit_reasons"][0]["verdicts"] == {ARES: "no_breach"}
    assert "1 of 2" in two["spec_exit_statement"] and "holds on all" not in two["spec_exit_statement"]
    # the round trip is a precondition of both
    assert pc.exit_test({STELLUS: doc}, {STELLUS: holds}, {"ok": False}, report_date=Q4,
                        expected_ciks=(STELLUS,))["spec_exit"] is False


def test_exit_test_fails_when_a_filer_breaches():
    w = wrapper_v3(STELLUS, source_encodings={"reporting_entity_suffixes": ENTS})
    w["identifier_format"]["delimiter"] = "; "
    doc = doc_with(w)
    con = {STELLUS: pc.consistency_contract(doc, report_date=Q4, code_mirror=ENTS)}
    out = pc.exit_test({STELLUS: doc}, con, {"ok": True}, report_date=Q4, expected_ciks=(STELLUS,))
    assert con[STELLUS]["verdict"] == "breach"
    assert out["per_cik"][STELLUS]["consistency"] is False
    assert out["verdict"] == "FAIL" and out["spec_exit"] is False and out["inception_gate"] is False
    assert [r["code"] for r in out["inception_gate_reasons"]] == ["consistency_breach"]
    assert out["per_cik"][STELLUS]["consistency_rows"]["breach"] == 1


# ---------------------------------------------------------------- owner rulings 2026-10-04: rulings 1 and 3


def with_keys(contract, keys):
    """A hand-built contract over a subset (or an edited copy) of a real contract's key rows."""
    counts = {s: sum(r["status"] == s for r in keys) for s in pc.STATUSES}
    return dict(contract, keys=keys, counts=counts, verdict=pc._verdict(counts))


def compared(row):
    return row["status"] in ("holds", "breach")


def is_identity(row):
    return row["profile_key"] in pc.IDENTITY_PROFILE_KEYS


def gate(contract, doc):
    return pc.exit_test({STELLUS: doc}, {STELLUS: contract}, {"ok": True}, report_date=Q4,
                        expected_ciks=(STELLUS,))


def test_procedure_keys_are_outside_the_contract_and_published_with_named_guards():
    """Ruling 1, positive case: the two keys are not key rows, do not count as insufficient_evidence, and are
    published with the stated guards -- whether or not the wrapper populates them."""
    plain = pc.consistency_contract(doc_with(), report_date=Q4, code_mirror=ENTS)
    w = wrapper_v3(STELLUS, source_encodings={"reporting_entity_suffixes": ENTS, "cash_identifiers": ["Cash"]})
    w["invariants"] = {"rate_sanity": {"min_pct": 0.0, "max_pct": 30.0}}
    populated = pc.consistency_contract(doc_with(w), report_date=Q4, code_mirror=ENTS)
    for out in (plain, populated):
        assert "/source_encodings/cash_identifiers" not in rows(out) and "/invariants/rate_sanity" not in rows(out)
        assert not [r for r in out["keys"] if r["mode"] == "no_counterpart"]
        assert sum(out["counts"].values()) == len(out["keys"])
        listed = {r["pointer"]: r for r in out["procedure_keys_outside_contract"]}
        assert sorted(listed) == ["/invariants/rate_sanity", "/source_encodings/cash_identifiers"]
        assert all(r["classification"] == "procedure" for r in listed.values())
        cash, rate = listed["/source_encodings/cash_identifiers"], listed["/invariants/rate_sanity"]
        assert cash["guard"] == "independent_totals" and "0.5%" in cash["guard_note"]
        assert "B1/B2" in cash["guard_note"]
        # the guard's own state for this filer (fixture totals: holds at 0.25%)
        assert cash["guard_status_at_report_date"] == "within_tolerance"
        # owner correction (2026-10-04): the rate key's guard is the named production rate rules, with the
        # owner's note on what they do not cover; they are named, not evaluated here, and no per-filer
        # status is invented for them
        assert rate["guard"] == "production_rate_rules"
        assert rate["guard_rules"] == ["fmt_basis_spread", "fmt_pik_rate", "fmt_interest_rate",
                                       "agentA_spread_vs_xbrl", "oracle_D07_median_rate_shift_gt_300bps"]
        assert rate["guard_note"] == (
            "the pilot value_range contract itself detected 0 of 8 known cases in the back-test; D07 cannot "
            "distinguish a portfolio shift from a change of meaning; rate problems that no production rule "
            "flags remain unguarded")
        assert rate["guard_evaluated_here"] is False and "guard_status_at_report_date" not in rate
        assert "guard_rules" not in cash
    # populating the two keys changes nothing in the contract's counts or verdict
    assert populated["counts"] == plain["counts"] and populated["verdict"] == plain["verdict"]
    listed = {r["pointer"]: r for r in populated["procedure_keys_outside_contract"]}
    assert listed["/source_encodings/cash_identifiers"]["wrapper_value"] == ["Cash"]
    assert listed["/invariants/rate_sanity"]["wrapper_present"] is True
    listed = {r["pointer"]: r for r in plain["procedure_keys_outside_contract"]}
    assert listed["/source_encodings/cash_identifiers"]["wrapper_present"] is False


def test_procedure_classification_does_not_swallow_counterpart_keys_or_claim_a_guard_that_did_not_run():
    """Ruling 1, false-positive guard: a COUNTERPART key with no accepted entry is still insufficient_evidence
    (only the two named keys left the contract), and a filer with no totals outcome has a named guard whose
    status says it did not run."""
    doc = zero_comparison_doc()
    con = pc.consistency_contract(doc, report_date=Q4, code_mirror=())
    assert rows(con)["/cik"]["status"] == "insufficient_evidence"
    assert rows(con)["/identifier_format/delimiter"]["status"] == "insufficient_evidence"
    assert con["counts"]["insufficient_evidence"] >= 3 and con["verdict"] == "insufficient_evidence"
    no_totals = pi.build_document(STELLUS, inputs=inception_inputs(totals=None), recorded_at=NOW, run_id=RUN,
                                  git_head="2a218e9")
    out = pc.consistency_contract(no_totals, report_date=Q4, code_mirror=ENTS)
    cash = {r["pointer"]: r for r in out["procedure_keys_outside_contract"]}["/source_encodings/cash_identifiers"]
    assert cash["guard"] == "independent_totals" and cash["guard_status_at_report_date"] == "no_outcome"
    # exit_test carries the per-filer list and the classification itself
    body = gate(out, no_totals)
    assert body["per_cik"][STELLUS]["procedure_keys_outside_contract"] == out["procedure_keys_outside_contract"]
    assert [(r["pointer"], r["guard"]) for r in body["procedure_keys_outside_contract"]] == [
        ("/source_encodings/cash_identifiers", "independent_totals"),
        ("/invariants/rate_sanity", "production_rate_rules")]
    assert "fmt_pik_rate" in body["procedure_keys_outside_contract"][1]["guard_rules"]
    # no live wrapper block: still listed, presence unknown
    doc = doc_with()
    doc["wrapper_section"]["blocks"] = []
    listed = pc.consistency_contract(doc, report_date=Q4, code_mirror=ENTS)["procedure_keys_outside_contract"]
    assert [r["wrapper_present"] for r in listed] == [None, None]


def test_a_filer_compared_only_on_identity_rows_fails_the_gate():
    """Ruling 3: the real shape of Ares / Onex / Stellus / StepStone (only /cik compared) and Fidelity (/cik and
    /entity_name): compared rows exist, zero breaches, nothing substantive. The gate fails."""
    doc = doc_with()
    real = pc.consistency_contract(doc, report_date=Q4, code_mirror=ENTS)
    assert rows(real)["/cik"]["status"] == "holds" and rows(real)["/cik"]["identity"] is True
    assert rows(real)["/identifier_format/delimiter"]["identity"] is False
    thin = with_keys(real, [r for r in real["keys"] if is_identity(r) or not compared(r)])
    assert thin["counts"]["holds"] >= 1 and thin["verdict"] == "no_breach"
    out = gate(thin, doc)
    row = out["per_cik"][STELLUS]
    assert row["compared_total"] >= 1 and row["compared_substantive"] == 0
    assert row["substantive_keys_compared"] == [] and "/cik" in row["identity_keys_compared"]
    assert row["consistency"] is False and row["substantive_comparison"] is False
    assert row["consistency_verdict"] == "no_breach"            # the verdict word is unchanged; the gate is not
    assert out["inception_gate"] is False and out["verdict"] == "FAIL" and out["spec_exit"] is False
    assert [(r["code"], r["ciks"]) for r in out["inception_gate_reasons"]] == [
        ("consistency_no_substantive_comparison", [STELLUS])]
    # an all-identity "holds" contract does not meet the gate or the spec exit either
    only = with_keys(real, [r for r in real["keys"] if is_identity(r) and compared(r)])
    assert only["verdict"] == "holds"
    out = gate(only, doc)
    assert out["inception_gate"] is False and out["spec_exit"] is False
    assert "consistency_no_substantive_comparison" in [r["code"] for r in out["spec_exit_reasons"]]
    assert out["spec_exit_statement"].startswith("NOT MET")


def test_one_substantive_holds_row_passes_the_gate():
    """Ruling 3, the other direction: one substantive compared row with zero breaches is enough (no minimum
    share yet), with or without identity rows beside it."""
    doc = doc_with()
    real = pc.consistency_contract(doc, report_date=Q4, code_mirror=ENTS)
    delimiter = rows(real)["/identifier_format/delimiter"]
    assert delimiter["status"] == "holds"
    rest = [r for r in real["keys"] if is_identity(r) or not compared(r)]
    for keys in (rest + [delimiter], [r for r in rest if not compared(r)] + [delimiter]):
        out = gate(with_keys(real, keys), doc)
        row = out["per_cik"][STELLUS]
        assert row["compared_substantive"] == 1
        assert row["substantive_keys_compared"] == ["/identifier_format/delimiter"]
        assert row["compared_total"] == 1 + len(row["identity_keys_compared"])
        assert row["consistency"] is True and out["inception_gate"] is True and out["verdict"] == "PASS"
        assert out["inception_gate_reasons"] == []
    # the real contract publishes the same counts itself, and the totals
    assert real["compared_total"] == real["counts"]["holds"] + real["counts"]["breach"]
    assert real["compared_substantive"] == len(real["substantive_keys_compared"]) >= 1
    out = gate(real, doc)
    assert out["consistency_rows"]["compared_substantive"] == real["compared_substantive"]
    assert out["identity_profile_keys"] == ["fund_level_concepts.entity_cik",
                                           "fund_level_concepts.entity_registrant_name"]


def test_an_identity_row_breach_is_still_a_breach():
    """Ruling 3: identity rows are excluded from what SATISFIES the gate, never from what breaches it."""
    doc = doc_with()
    real = pc.consistency_contract(doc, report_date=Q4, code_mirror=ENTS)
    keys = [dict(r, status="breach", reason="value_disagrees") if r["pointer"] == "/cik" else r
            for r in real["keys"]]
    bad = with_keys(real, keys)
    assert bad["verdict"] == "breach"
    out = gate(bad, doc)
    row = out["per_cik"][STELLUS]
    assert row["compared_substantive"] >= 1                     # substantive rows hold; it fails anyway
    assert row["consistency"] is False and [b["pointer"] for b in row["breaches"]] == ["/cik"]
    assert out["inception_gate"] is False
    assert [r["code"] for r in out["inception_gate_reasons"]] == ["consistency_breach"]


def test_the_minimum_share_hook_is_named_and_not_implemented(monkeypatch):
    assert pc.MIN_SUBSTANTIVE_COMPARED_ROWS == 1 and pc.MIN_SUBSTANTIVE_COMPARED_SHARE is None
    assert pc.meets_substantive_minimum(1) is True and pc.meets_substantive_minimum(0) is False
    doc = doc_with()
    out = gate(pc.consistency_contract(doc, report_date=Q4, code_mirror=ENTS), doc)
    assert out["substantive_minimum"] == {"rows": 1, "share": None}
    monkeypatch.setattr(pc, "MIN_SUBSTANTIVE_COMPARED_SHARE", 0.5)
    try:
        pc.meets_substantive_minimum(3)
    except NotImplementedError:
        pass
    else:
        raise AssertionError("a share threshold must not be silently ignored")
