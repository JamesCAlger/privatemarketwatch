"""SP3 proper Tasks 5-6: inception converter (wrapper blocks, corrections, entries, stubs, build_document)."""
from __future__ import annotations

import copy

import pytest

from scripts.profile_pilot import envelope, profile
from scripts.profile_pilot import profile_document as pd
from scripts.profile_pilot import profile_inception as pi
from tests.test_profile_pilot_profile import mini_doc, outcome, single_dialect
from tests.test_profile_pilot_profile_families import ARES, STELLUS, wrapper_v3

NOW = "2026-10-01T12:00:00Z"
RUN = "sp3p-profile-test"
SHA = "d" * 64


def f(path, content, sha=SHA):
    return dict(path=path, sha256=sha, content=content)


def test_wrapper_block_keeps_key_order_and_identity():
    w = wrapper_v3(ARES)
    block = pi.wrapper_block(ARES, family="bdc_xbrl_wrapper", files=[f("bdc_xbrl_wrappers/" + ARES + ".json", w)],
                             recorded_at=NOW, attested_under=["signoff-2026-03-31"])
    assert block["block_id"] == ARES + ":wrapper:bdc_xbrl_wrapper:v1"
    assert list(block["content"]["dispatch"]["prefix_rules"]) == ["Second Lien", "First Lien"]
    assert block["valid_from"] is None and block["valid_to"] is None and block["attested_under"] == ["signoff-2026-03-31"]
    assert block["source_files"][0]["ordered_sha256"] == block["content_sha256"]
    flipped = copy.deepcopy(w)
    flipped["dispatch"]["prefix_rules"] = {"First Lien": "debt", "Second Lien": "debt"}
    other = pi.wrapper_block(ARES, family="bdc_xbrl_wrapper", files=[f("x", flipped)], recorded_at=NOW, attested_under=[])
    assert other["content_sha256"] != block["content_sha256"]   # order is behaviour


def test_wrapper_block_refuses_two_files_or_a_foreign_cik():
    with pytest.raises(pi.InceptionError, match="exactly one wrapper file"):
        pi.wrapper_block(ARES, family="bdc_xbrl_wrapper", files=[f("a", wrapper_v3(ARES)), f("b", wrapper_v3(ARES))],
                         recorded_at=NOW, attested_under=[])
    with pytest.raises(pi.InceptionError, match="wrapper cik"):
        pi.wrapper_block(ARES, family="bdc_xbrl_wrapper", files=[f("a", wrapper_v3(STELLUS))], recorded_at=NOW,
                         attested_under=[])


def test_rules_block_and_expressibility():
    excl = {"cik": "1287750", "rule_id": "x", "rule_type": "row_exclusion", "scope": {"quarters": ["2025-09-30"]},
            "predicate_sql": "report_date = '2025-09-30' AND row_id IN ('ROW-1', 'ROW-2')"}
    add = {"cik": "1287750", "rule_id": "y", "rule_type": "row_add", "scope": {"quarters": ["2023-06-30"]}}
    block = pi.wrapper_block(ARES, family="agent_investigate_rules",
                             files=[f("agent_investigate_rules/1287750/y.json", add),
                                    f("agent_investigate_rules/1287750/x.json", excl)],
                             recorded_at=NOW, attested_under=[])
    assert list(block["content"]["files"]) == ["agent_investigate_rules/1287750/x.json",
                                               "agent_investigate_rules/1287750/y.json"]
    exp = block["expressibility"]
    assert exp["agent_investigate_rules/1287750/x.json"]["expressible_as"] == "one_off_correction"
    assert exp["agent_investigate_rules/1287750/y.json"]["expressible_as"] is None


def b2(fix_class, **extra):
    leaf = {"cik": ARES, "mechanism": "extraction_gap", "fix_class": fix_class, "template": {},
            "confidence": 0.9}
    leaf.update(extra)
    return f("agent_b2_corrections/" + ARES + "/" + fix_class + ".json", leaf)


def test_b2_corrections_kinds_and_targets():
    files = [b2("all_pik_normalization", scope={"quarters": ["2025-12-31"]},
                template={"row_selector": {"row_id": "ROW-62c1"}, "cash_rate": 0.0, "pik_rate": 14.0}),
             b2("column_remap", scope={"quarters": ["2025-12-31"]}, template={"from_field": "pik_rate", "to_field": "interest_rate"}),
             b2("comparative_period_filter", template={"report_date": "2025-12-31"}),
             b2("unit_rescale", scope={"quarters": ["2025-09-30", "2025-12-31"]}),
             b2("zero_fill")]
    out = {c["fix_class"]: c for c in pi.correction_records(ARES, b2_files=files, shared={}, recorded_at=NOW,
                                                            run_id=RUN)}
    pik = out["all_pik_normalization"]
    assert (pik["kind"], pik["report_date"], pik["valid_from"], pik["valid_to"]) == ("one_off",) + ("2025-12-31",) * 3
    assert pik["row_keyed"] is True and pik["target"] == {"row_id": "ROW-62c1"} and pik["state"] == "accepted"
    assert pik["pre_image"]["status"] == "unchecked" and pik["confidence"] == 0.9
    assert out["column_remap"]["target"] == {"report_dates": ["2025-12-31"]} and out["column_remap"]["row_keyed"] is False
    assert out["comparative_period_filter"]["report_date"] == "2025-12-31"
    assert (out["unit_rescale"]["kind"], out["unit_rescale"]["state"]) == ("multi_quarter", "candidate")
    assert (out["zero_fill"]["kind"], out["zero_fill"]["report_date"]) == ("undated", None)
    assert out["all_pik_normalization"]["value"] == files[0]["content"]


def test_b2_leaf_of_another_filer_is_refused():
    leaf = b2("column_remap", scope={"quarters": ["2025-12-31"]})
    leaf["content"]["cik"] = STELLUS
    with pytest.raises(pi.InceptionError, match="B2 leaf cik differs"):
        pi.correction_records(ARES, b2_files=[leaf], shared={}, recorded_at=NOW, run_id=RUN)


def test_shared_records_become_one_offs_with_recurrence():
    ivy = [[1 + i, {"cik": ARES, "report_date": d, "accession_number": "acc-" + d, "match_text": "Ivy Hill",
                    "match_mode": "exact", "action": "exclude"}]
           for i, d in enumerate(("2025-06-30", "2025-09-30", "2025-12-31"))]
    single = [[9, {"cik": ARES, "report_date": "2023-03-31", "accession_number": "acc", "match_text": "Other",
                   "match_mode": "exact", "action": "exclude"}]]
    shared = {"bdc_aggregate_row_overrides.json": {"sha256": SHA, "records": ivy + single}}
    out = pi.correction_records(ARES, b2_files=[], shared=shared, recorded_at=NOW, run_id=RUN)
    assert [c["correction_id"] for c in out] == [ARES + ":corr:aggregate_row:%03d" % n for n in (1, 2, 3, 4)]
    groups = {c["recurrence_group"] for c in out[:3]}
    assert len(groups) == 1 and None not in groups
    assert all(c["promotion"] == "proposed_recurring_owner_tier" for c in out[:3])
    assert out[3]["recurrence_group"] is None and out[3]["promotion"] is None
    assert out[0]["source"] == {"path": "bdc_aggregate_row_overrides.json", "sha256": SHA, "record_index": 1}
    assert out[0]["mechanism"] == "aggregate_row_exclusion" and out[0]["target"]["match_text"] == "Ivy Hill"


# ---------------------------------------------------------------- hardening carried from the Task 5 review

def test_wrapper_block_agent_investigate_rules_checks_cik_like_every_other_path():
    foreign = {"cik": STELLUS, "rule_id": "x", "rule_type": "row_exclusion", "scope": {"quarters": ["2025-09-30"]},
               "predicate_sql": "row_id IN ('ROW-1')"}
    with pytest.raises(pi.InceptionError, match="rule cik"):
        pi.wrapper_block(ARES, family="agent_investigate_rules",
                         files=[f("agent_investigate_rules/" + STELLUS + "/x.json", foreign)],
                         recorded_at=NOW, attested_under=[])


def test_b2_list_shaped_row_selector_is_refused_not_an_attributeerror():
    leaf = b2("list_selector", template={"row_selector": ["ROW-1", "ROW-2"]})
    with pytest.raises(pi.InceptionError, match="list_selector"):
        pi.correction_records(ARES, b2_files=[leaf], shared={}, recorded_at=NOW, run_id=RUN)


def test_unrelated_b2_one_offs_sharing_a_fix_class_are_grouped_known_limitation():
    # Known limitation (pinned, not fixed here): the B2 recurrence signature is fix_class alone
    # (plus family and mechanism). Two genuinely unrelated one-off fixes on different rows and
    # quarters still land in one recurrence_group and get flagged proposed_recurring_owner_tier.
    leaf_a = {"cik": ARES, "mechanism": "extraction_gap", "fix_class": "zero_fill",
             "scope": {"quarters": ["2025-09-30"]}, "template": {"row_selector": {"row_id": "ROW-A"}}}
    leaf_b = {"cik": ARES, "mechanism": "extraction_gap", "fix_class": "zero_fill",
             "scope": {"quarters": ["2025-12-31"]}, "template": {"row_selector": {"row_id": "ROW-B"}}}
    files = [f("agent_b2_corrections/" + ARES + "/zero_fill_a.json", leaf_a),
             f("agent_b2_corrections/" + ARES + "/zero_fill_b.json", leaf_b)]
    out = pi.correction_records(ARES, b2_files=files, shared={}, recorded_at=NOW, run_id=RUN)
    assert out[0]["kind"] == out[1]["kind"] == "one_off"
    assert out[0]["target"] != out[1]["target"]
    assert out[0]["recurrence_group"] == out[1]["recurrence_group"]
    assert out[0]["recurrence_group"] is not None
    assert all(c["promotion"] == "proposed_recurring_owner_tier" for c in out)


# ---------------------------------------------------------------- Task 6: census entries, admissions, stubs, build_document

Q4, Q1 = "2025-12-31", "2026-03-31"


def census(date, identifiers=None, delim="|"):
    doc = mini_doc(partition=[single_dialect(delim)], report_date=date, identifiers=identifiers)
    source = dict(cik=STELLUS, report_date=date, role="all:" + date,
                  census_relative="census/" + STELLUS + "/" + date + ".json", census_sha256="0" * 64,
                  fingerprint="f" * 64, accession_number="0000000000-23-000001", form_type="10-Q")
    return dict(doc=doc, source=source)


def inception_inputs(*, q4=True, q1=True, wrapper=None, extra_files=None, shared=None):
    w = wrapper or wrapper_v3(STELLUS, source_encodings={"reporting_entity_suffixes": ["Emerald JV LP"]})
    files = {"bdc_xbrl_wrappers": [f("bdc_xbrl_wrappers/" + STELLUS + ".json", w)],
             "rate_convention": [f("rate_convention/" + STELLUS + ".json",
                                   {"cik": STELLUS, "convention": "all_in", "target_quarter": Q1, "confidence": 0.8,
                                    "citations": [{"kind": "header", "quote": "Interest Rate (2)"}]})]}
    files.update(extra_files or {})
    action = {"bdc_xbrl_wrappers": "wrapper_block", "agent_investigate_rules": "wrapper_block",
              "agent_b2_corrections": "correction"}
    disposition = [dict(path=x["path"], family=fam,
                        cls="executable" if action.get(fam) == "wrapper_block" else "knowledge",
                        action=action.get(fam, "entry"), sha256=x["sha256"], ordered_sha256=None, targets=[],
                        reason=None, record_indexes=None)
                   for fam, items in files.items() for x in items]
    for name, s in (shared or {}).items():
        disposition.append(dict(path=name, family=name, cls="knowledge", action="correction", sha256=s["sha256"],
                                ordered_sha256=None, targets=[], reason=None,
                                record_indexes=[i for i, _ in s["records"]]))
    return dict(files=files, shared=shared or {}, disposition=disposition,
                attested_under={"bdc_xbrl_wrappers/" + STELLUS + ".json": ["signoff-2026-03-31"]},
                census_q4=census(Q4) if q4 else None,
                census_q4_unavailable=None if q4 else dict(census_run_id="stageb2-sp1census-20260930t2235z",
                                                           reason="unavailable",
                                                           detail="ambiguous_same_quarter_candidates"),
                census_q1=census(Q1) if q1 else None,
                detection={"fill_rate": dict(verdict="NO_POSITIVES", replay_run_id="sp1-replay-x"),
                           "source_concept_set": dict(verdict="PASS", replay_run_id="sp1-replay-x")},
                predicate=dict(version="census-published.v2", code_sha256="e" * 64),
                code_mirror=["Emerald JV LP"], overrides_root="tmp", replay_run_id="sp1-replay-x")


def build(**kw):
    return pi.build_document(STELLUS, inputs=inception_inputs(**kw), recorded_at=NOW, run_id=RUN, git_head="2a218e9")


def test_derive_profile_accepts_the_inception_era_without_changing_eras():
    assert profile.ERAS == ("q1", "same_era") and profile.INCEPTION_ERA == "inception"
    c = census(Q4)
    out = profile.derive_profile(c["doc"], source=c["source"], era=profile.INCEPTION_ERA, recorded_at=NOW, anchors=None)
    profile.validate_document(out)
    assert out["era"] == "inception"


def test_build_document_full():
    doc = build()
    pd.validate_document(doc)
    by_key = {e["key"]: e for e in doc["entries"]}
    delim = by_key["identifier_format.delimiter"]
    assert delim["value"] == " | "
    assert doc["admissions"][delim["entry_id"]]["state"] == "accepted"
    assert doc["admissions"][delim["entry_id"]]["basis"] == "census_confirmed_next_quarter"
    conv = by_key["meaning.interest_rate"]
    assert conv["valid_from"] is None and conv["provenance"] == "inherited" and conv["author"] == "agent"
    assert conv["support"]["kind"] == "inherited_file" and conv["value"]["convention"] == "all_in"
    assert doc["admissions"][conv["entry_id"]]["confidence"] == 0.8
    assert {"kind": "source_date", "field": "target_quarter", "value": Q1} in conv["evidence"]
    assert by_key["partition_structure.published_basis"]["value"] == {"predicate": "census-published.v2"}
    ents = by_key["partition_structure.reporting_entities"]
    assert ents["value"] == ["Emerald JV LP"]
    assert doc["partition_predicate"]["reporting_entities_entry_id"] == ents["entry_id"]
    assert doc["partition_predicate"]["code_mirror"]["value"] == ["Emerald JV LP"]
    [block] = doc["wrapper_section"]["blocks"]
    assert block["attested_under"] == ["signoff-2026-03-31"]
    assert doc["detection_claims"]["fill_rate"]["claim"] == "detection_not_claimed"
    assert doc["detection_claims"]["source_concept_set"]["claim"] == "claimed"
    targets = {d["path"]: d["targets"] for d in doc["disposition"]}
    assert targets["bdc_xbrl_wrappers/" + STELLUS + ".json"] == [ents["entry_id"], block["block_id"]]
    assert targets["rate_convention/" + STELLUS + ".json"] == [conv["entry_id"]]
    for key, cell in pd.coverage(doc, Q4).items():
        assert cell["accepted_entry_ids"] or cell["stub"], key
    assert pd.resolve(doc, "scale_unit.fair_value", Q4)["stub"]["cause"] == "no_source"
    assert all(e["evidence"] for e in doc["entries"])


def test_unconfirmed_census_entry_is_a_candidate_with_a_stub():
    inputs = inception_inputs()
    inputs["census_q1"] = census(Q1, identifiers=["Borrower %d LLC ; Term Loan" % i for i in range(12)], delim=";")
    doc = pi.build_document(STELLUS, inputs=inputs, recorded_at=NOW, run_id=RUN, git_head="2a218e9")
    delim = next(e for e in doc["entries"] if e["key"] == "identifier_format.delimiter")
    assert doc["admissions"][delim["entry_id"]]["state"] == "candidate"
    # pd.admission() special-cases confidence=None (the census path never has a confidence) so no
    # confidence_raw key is added; only alongside the next_quarter witness key (Task 7 carry-over fix).
    assert doc["admissions"][delim["entry_id"]]["witness"] == {"next_quarter": "q1_value_differs"}
    out = pd.resolve(doc, "identifier_format.delimiter", Q4)
    assert out["status"] == "stub" and out["stub"]["cause"] == "candidate_pending_confirmation"
    assert out["stub"]["entry_id"] == delim["entry_id"]


def test_census_unavailable_gives_census_unavailable_stubs():
    doc = build(q4=False, q1=False)
    assert not any(e["key"].startswith("column_contract.") for e in doc["entries"])
    stub = pd.resolve(doc, "column_contract.fair_value", Q4)["stub"]
    assert stub["cause"] == "census_unavailable" and "ambiguous_same_quarter_candidates" in stub["closing_evidence"]
    assert pd.resolve(doc, "income_proofs.duration", Q4)["stub"]["cause"] == "no_source"
    assert doc["ledger"][0]["detail"]["census_q4"] is None
    # A10: CENSUS_KEYS excludes these two (the census cannot derive them), so an unavailable
    # census must not be blamed for their absence -- they are no_source, like income_proofs.
    assert pd.resolve(doc, "subtotals_and_headings.non_private_markers", Q4)["stub"]["cause"] == "no_source"
    assert pd.resolve(doc, "subtotals_and_headings.prefix_rules", Q4)["stub"]["cause"] == "no_source"


def test_two_files_in_one_knowledge_family_are_refused():
    inputs = inception_inputs()
    inputs["files"]["rate_convention"].append(f("rate_convention/other.json", {"cik": STELLUS, "convention": "cash"}))
    with pytest.raises(pi.InceptionError, match="more than one"):
        pi.build_document(STELLUS, inputs=inputs, recorded_at=NOW, run_id=RUN, git_head="2a218e9")


def test_a_converted_file_that_produces_nothing_is_refused():
    inputs = inception_inputs()
    inputs["disposition"].append(dict(path="identifier_anchors/" + STELLUS + ".json", family="identifier_anchors",
                                      cls="knowledge", action="entry", sha256=SHA, ordered_sha256=None, targets=[],
                                      reason=None, record_indexes=None))
    with pytest.raises(pi.InceptionError, match="produced nothing"):
        pi.build_document(STELLUS, inputs=inputs, recorded_at=NOW, run_id=RUN, git_head="2a218e9")


def test_shared_records_land_as_recurring_one_offs():
    rows = [[0, {"cik": STELLUS, "report_date": "2025-09-30", "oracle_reason": "rate_outliers_detected", "confidence": 0.9}],
            [1, {"cik": STELLUS, "report_date": "2025-12-31", "oracle_reason": "rate_outliers_detected", "confidence": 0.9}]]
    doc = build(shared={"bdc_xbrl_oracle_exceptions.json": {"sha256": SHA, "records": rows}})
    assert [c["kind"] for c in doc["corrections"]] == ["one_off", "one_off"]
    assert doc["corrections"][0]["recurrence_group"] == doc["corrections"][1]["recurrence_group"]
    assert doc["corrections"][0]["recurrence_group"] is not None


# ---------------------------------------------------------------- Fix round 1 (Task 6 review)

def test_build_document_full_collected_no_observation_and_determinism():
    doc = build()
    # item 5: a CENSUS_KEYS key the (present, complete) Q4 census ran over but derived nothing for
    # (column_contract.cost -- mini_doc only ever reports fair_value) is no_source with the
    # collected_no_observation text/detail, not the generic CLOSING_EVIDENCE prose.
    cost_stub = pd.resolve(doc, "column_contract.cost", Q4)["stub"]
    assert cost_stub["cause"] == "no_source" and cost_stub["detail"] == {"census": "collected_no_observation"}
    assert "collected no observation" in cost_stub["closing_evidence"]
    # item 6: determinism -- building twice from the same inputs gives byte-for-byte equal output.
    doc2 = build()
    assert doc == doc2


def test_qualitative_confidence_is_kept_in_confidence_raw_not_dropped():
    # item 1: a qualitative confidence ("high") must survive into witness.confidence_raw, not be
    # silently dropped by passing it through _number() before pd.admission() ever sees it.
    inputs = inception_inputs()
    inputs["files"]["rate_convention"] = [f("rate_convention/" + STELLUS + ".json",
                                           {"cik": STELLUS, "convention": "all_in", "target_quarter": Q1,
                                            "confidence": "high"})]
    doc = pi.build_document(STELLUS, inputs=inputs, recorded_at=NOW, run_id=RUN, git_head="2a218e9")
    conv = next(e for e in doc["entries"] if e["key"] == "meaning.interest_rate")
    admission = doc["admissions"][conv["entry_id"]]
    assert admission["confidence"] is None and admission["witness"]["confidence_raw"] == "high"


def test_rate_convention_witness_carries_verify_tier_and_n_reconciled_when_present():
    # item 13
    inputs = inception_inputs()
    inputs["files"]["rate_convention"] = [f("rate_convention/" + STELLUS + ".json",
                                           {"cik": STELLUS, "convention": "all_in", "target_quarter": Q1,
                                            "confidence": 0.8, "verify_tier": "A", "verify_n_reconciled": 12})]
    doc = pi.build_document(STELLUS, inputs=inputs, recorded_at=NOW, run_id=RUN, git_head="2a218e9")
    conv = next(e for e in doc["entries"] if e["key"] == "meaning.interest_rate")
    witness = doc["admissions"][conv["entry_id"]]["witness"]
    assert witness["verify_tier"] == "A" and witness["verify_n_reconciled"] == 12


def test_inherited_knowledge_file_cik_mismatch_is_refused():
    # item 8
    inputs = inception_inputs()
    inputs["files"]["rate_convention"][0]["content"]["cik"] = ARES
    with pytest.raises(pi.InceptionError, match="rate_convention file cik"):
        pi.build_document(STELLUS, inputs=inputs, recorded_at=NOW, run_id=RUN, git_head="2a218e9")


def test_file_evidence_keeps_report_date_as_a_source_date():
    # item 3: grammar/anchor files carry report_date (not target_quarter/first_seen_quarter/updated_at)
    content = {"cik": STELLUS, "dialect": "pipe", "report_date": Q4}
    evidence = pi.file_evidence("identifier_rate_grammars/" + STELLUS + ".json", SHA, content)
    assert {"kind": "source_date", "field": "report_date", "value": Q4} in evidence


def test_census_q1_for_another_filer_is_refused():
    # item 2
    inputs = inception_inputs()
    bad = dict(inputs["census_q1"])
    bad["source"] = dict(bad["source"], cik=ARES)
    inputs["census_q1"] = bad
    with pytest.raises(pi.InceptionError, match="census_q1 belongs to another filer"):
        pi.build_document(STELLUS, inputs=inputs, recorded_at=NOW, run_id=RUN, git_head="2a218e9")


def test_census_q4_passed_twice_as_q1_is_refused():
    # item 2
    inputs = inception_inputs()
    inputs["census_q1"] = inputs["census_q4"]
    with pytest.raises(pi.InceptionError, match="not later than"):
        pi.build_document(STELLUS, inputs=inputs, recorded_at=NOW, run_id=RUN, git_head="2a218e9")


def test_census_q1_without_a_usable_later_date_is_refused_even_with_no_q4_census():
    # item 2: the date check does not depend on a Q4 census being present, and a missing date is refused
    # with InceptionError rather than a TypeError from comparing None.
    for bad_date in (Q4, None):
        inputs = inception_inputs(q4=False)
        inputs["census_q1"] = dict(inputs["census_q1"], source=dict(inputs["census_q1"]["source"],
                                                                    report_date=bad_date))
        with pytest.raises(pi.InceptionError, match="not later than"):
            pi.build_document(STELLUS, inputs=inputs, recorded_at=NOW, run_id=RUN, git_head="2a218e9")


def test_open_census_outcome_demotes_the_entry_in_the_built_document():
    # item 4 (controller ruling), end to end: Q1 would confirm the value, but an open Q4 detector outcome
    # bears on the key, so the entry is a candidate with cause open_census_outcomes, the outcome ids are in
    # the witness, and the grid answers with a candidate_pending_confirmation stub (never an accepted entry).
    key = "subtotals_and_headings.aggregate_labels"
    inputs = inception_inputs()
    inputs["census_q4"] = census_with_subtotal(Q4, [
        _subtotal_outcome("Total Investments"),
        _subtotal_outcome("Total Investments", state="candidate", context_id="t2")])
    inputs["census_q1"] = census_with_subtotal(Q1, [_subtotal_outcome("Total Investments")])
    doc = pi.build_document(STELLUS, inputs=inputs, recorded_at=NOW, run_id=RUN, git_head="2a218e9")
    entry = next(e for e in doc["entries"] if e["key"] == key)
    admission = doc["admissions"][entry["entry_id"]]
    assert admission["state"] == "candidate" and admission["basis"] == "census_unconfirmed"
    assert admission["witness"]["next_quarter"] == "open_census_outcomes"
    opened = admission["witness"]["open_census_outcomes"]
    assert opened["q1"] == [] and [set(s) for s in opened["q4"]] == [{"stub_id", "cause"}]
    out = pd.resolve(doc, key, Q4)
    assert out["status"] == "stub" and out["stub"]["cause"] == "candidate_pending_confirmation"
    assert out["stub"]["entry_id"] == entry["entry_id"]
    assert out["stub"]["detail"] == {"next_quarter": "open_census_outcomes"}
    # false-positive guard: a key no open outcome bears on is still confirmed by Q1.
    delim = next(e for e in doc["entries"] if e["key"] == "identifier_format.delimiter")
    assert doc["admissions"][delim["entry_id"]]["state"] == "accepted"


def test_census_q4_with_a_wrong_report_date_is_refused():
    # item 2
    inputs = inception_inputs()
    inputs["census_q4"] = dict(inputs["census_q4"],
                               source=dict(inputs["census_q4"]["source"], report_date="2025-09-30"))
    with pytest.raises(pi.InceptionError, match="census_q4 does not match"):
        pi.build_document(STELLUS, inputs=inputs, recorded_at=NOW, run_id=RUN, git_head="2a218e9")


def test_census_q4_present_and_unavailable_both_set_is_refused():
    # item 5: the mutual-exclusivity invariant
    inputs = inception_inputs()
    inputs["census_q4_unavailable"] = dict(census_run_id="x", reason="unavailable", detail="d")
    with pytest.raises(pi.InceptionError, match="exactly one of census_q4"):
        pi.build_document(STELLUS, inputs=inputs, recorded_at=NOW, run_id=RUN, git_head="2a218e9")


def test_census_q4_and_unavailable_both_none_is_refused():
    inputs = inception_inputs()
    inputs["census_q4"] = None
    with pytest.raises(pi.InceptionError, match="exactly one of census_q4"):
        pi.build_document(STELLUS, inputs=inputs, recorded_at=NOW, run_id=RUN, git_head="2a218e9")


def test_predicate_version_mismatching_the_adoption_evidence_is_refused():
    # item 7
    inputs = inception_inputs()
    inputs["predicate"] = dict(version="census-published.v1", code_sha256="e" * 64)
    with pytest.raises(pi.InceptionError, match="does not match the adoption evidence"):
        pi.build_document(STELLUS, inputs=inputs, recorded_at=NOW, run_id=RUN, git_head="2a218e9")


def test_reporting_entity_suffixes_must_be_a_list_of_strings():
    # item 11
    inputs = inception_inputs(wrapper=wrapper_v3(STELLUS, source_encodings={"reporting_entity_suffixes": "Emerald JV LP"}))
    with pytest.raises(pi.InceptionError, match="must be a list of strings"):
        pi.build_document(STELLUS, inputs=inputs, recorded_at=NOW, run_id=RUN, git_head="2a218e9")
    inputs2 = inception_inputs(wrapper=wrapper_v3(STELLUS, source_encodings={"reporting_entity_suffixes": None}))
    with pytest.raises(pi.InceptionError, match="must be a list of strings"):
        pi.build_document(STELLUS, inputs=inputs2, recorded_at=NOW, run_id=RUN, git_head="2a218e9")


def test_overrides_git_head_lands_in_the_ledger():
    # item 9
    inputs = inception_inputs()
    inputs["overrides_git_head"] = "deadbeefmainhead"
    doc = pi.build_document(STELLUS, inputs=inputs, recorded_at=NOW, run_id=RUN, git_head="2a218e9")
    assert doc["ledger"][0]["detail"]["overrides_git_head"] == "deadbeefmainhead"


def _subtotal_outcome(label, *, state="resolved", context_id="t1"):
    return outcome("subtotal", "structural_subtotal" if state == "resolved" else "ambiguous_heading", state=state,
                   subject=dict(context_id=context_id, label=label),
                   evidence=dict(heading="category_only_dimensions",
                                 matched_sets=[dict(set="leaf_positions", children=["p1"], sum="1")]))


def census_with_subtotal(date, subtotal_outcomes, delim="|"):
    doc = mini_doc(partition=[single_dialect(delim)], subtotal=list(subtotal_outcomes), report_date=date)
    source = dict(cik=STELLUS, report_date=date, role="all:" + date,
                  census_relative="census/" + STELLUS + "/" + date + ".json", census_sha256="0" * 64,
                  fingerprint="f" * 64, accession_number="0000000000-23-000001", form_type="10-Q")
    return dict(doc=doc, source=source)


def _derive(c):
    return profile.derive_profile(c["doc"], source=c["source"], era=profile.INCEPTION_ERA, recorded_at=NOW,
                                  anchors=None)


def test_confirmation_accepts_when_no_open_outcomes():
    # item 4 (a)
    q4 = census_with_subtotal(Q4, [_subtotal_outcome("Total Investments")])
    q1 = census_with_subtotal(Q1, [_subtotal_outcome("Total Investments")])
    derived_q4 = _derive(q4)
    out = pi.confirmations(derived_q4["entries"], q1, census_stubs=derived_q4["packet_stubs"], recorded_at=NOW)
    entry = next(e for e in derived_q4["entries"] if e["key"] == "subtotals_and_headings.aggregate_labels")
    result = out[entry["entry_id"]]
    assert result["ok"] is True and result["reason"] == "q1_value_equal" and result["open"] is None


def test_confirmation_is_a_candidate_on_a_q4_open_outcome():
    # item 4 (b)
    q4 = census_with_subtotal(Q4, [_subtotal_outcome("Total Investments"),
                                   _subtotal_outcome("Total Investments", state="candidate", context_id="t2")])
    q1 = census_with_subtotal(Q1, [_subtotal_outcome("Total Investments")])
    derived_q4 = _derive(q4)
    out = pi.confirmations(derived_q4["entries"], q1, census_stubs=derived_q4["packet_stubs"], recorded_at=NOW)
    entry = next(e for e in derived_q4["entries"] if e["key"] == "subtotals_and_headings.aggregate_labels")
    result = out[entry["entry_id"]]
    assert result["ok"] is False and result["reason"] == "open_census_outcomes"
    assert result["open"]["q4"] and result["open"]["q1"] == []
    assert all({"stub_id", "cause"} <= set(s) for s in result["open"]["q4"])


def test_confirmation_is_a_candidate_on_a_q1_open_outcome():
    # item 4 (c)
    q4 = census_with_subtotal(Q4, [_subtotal_outcome("Total Investments")])
    q1 = census_with_subtotal(Q1, [_subtotal_outcome("Total Investments"),
                                   _subtotal_outcome("Total Investments", state="candidate", context_id="t2")])
    derived_q4 = _derive(q4)
    out = pi.confirmations(derived_q4["entries"], q1, census_stubs=derived_q4["packet_stubs"], recorded_at=NOW)
    entry = next(e for e in derived_q4["entries"] if e["key"] == "subtotals_and_headings.aggregate_labels")
    result = out[entry["entry_id"]]
    assert result["ok"] is False and result["reason"] == "open_census_outcomes"
    assert result["open"]["q4"] == [] and result["open"]["q1"]


def test_q1_missing_makes_every_census_entry_a_candidate_with_the_right_reason():
    # item 6: Q4 present, Q1 missing
    doc = build(q1=False)
    census_entries_ = [e for e in doc["entries"] if e["author"] == "census"]
    assert census_entries_
    for e in census_entries_:
        a = doc["admissions"][e["entry_id"]]
        assert a["state"] == "candidate" and a["witness"]["next_quarter"] == "q1_census_unavailable"


def test_q1_no_entry_for_a_key_q4_has():
    # item 6: q1_no_entry
    q4 = census_with_subtotal(Q4, [_subtotal_outcome("Total Investments")])
    q1 = census_with_subtotal(Q1, [])
    derived_q4 = _derive(q4)
    out = pi.confirmations(derived_q4["entries"], q1, census_stubs=derived_q4["packet_stubs"], recorded_at=NOW)
    entry = next(e for e in derived_q4["entries"] if e["key"] == "subtotals_and_headings.aggregate_labels")
    result = out[entry["entry_id"]]
    assert result["ok"] is False and result["reason"] == "q1_no_entry" and result["open"] is None


def test_confirmation_flags_q1_ambiguous_when_q1_has_two_entries_for_one_key(monkeypatch):
    # item 6: q1_ambiguous -- unreachable through one real derive_profile call (each section asserts
    # a key at most once), so this exercises confirmations()'s own guard directly via a monkeypatched
    # Q1 derivation that returns two live entries sharing one key.
    key = "subtotals_and_headings.aggregate_labels"
    q4_entry = dict(entry_id=STELLUS + ":fake:q4", key=key, value=["a"], applies_to=None)
    dup_a = dict(entry_id=STELLUS + ":fake:q1a", key=key, value=["a"], applies_to=None)
    dup_b = dict(entry_id=STELLUS + ":fake:q1b", key=key, value=["b"], applies_to=None)

    def fake_derive(doc, *, source, era, recorded_at, anchors):
        return dict(entries=[dup_a, dup_b], packet_stubs=[])

    monkeypatch.setattr(pi.profile, "derive_profile", fake_derive)
    out = pi.confirmations([q4_entry], {"doc": {}, "source": {}}, census_stubs=[], recorded_at=NOW)
    result = out[q4_entry["entry_id"]]
    assert result["ok"] is False and result["reason"] == "q1_ambiguous" and result["open"] is None


def test_build_document_refuses_two_entries_for_one_key(monkeypatch):
    # item 6: the duplicate live-key guard. Realistic collision: the census somehow also asserts
    # meaning.interest_rate (today it never does), which collides with the inherited rate_convention
    # entry for the same key.
    real_census_entries = pi.census_entries

    def fake_census_entries(census, *, recorded_at):
        events, stubs = real_census_entries(census, recorded_at=recorded_at)
        extra = envelope.make_assertion(
            events, cik=STELLUS, key="meaning.interest_rate", value={"convention": "cash"}, valid_from=Q4,
            recorded_at=recorded_at, support=dict(kind="context_count", count=1), evidence=[dict(kind="test")])
        return extra, stubs

    monkeypatch.setattr(pi, "census_entries", fake_census_entries)
    with pytest.raises(pi.InceptionError, match="two inception entries"):
        build()


def test_open_q4_subtotal_outcome_gives_a_census_stub():
    # item 6: a census_stub cause asserted. Q4 has only an OPEN subtotal outcome bearing on
    # aggregate_labels (no resolved+labelled outcome), so no entry and no admission exist for the
    # key -- grid_stubs must fall back to the census_stub cause, not no_source.
    inputs = inception_inputs()
    inputs["census_q4"] = census_with_subtotal(Q4, [_subtotal_outcome("Total Investments", state="candidate")])
    doc = pi.build_document(STELLUS, inputs=inputs, recorded_at=NOW, run_id=RUN, git_head="2a218e9")
    stub = pd.resolve(doc, "subtotals_and_headings.aggregate_labels", Q4)["stub"]
    assert stub["cause"] == "census_stub"


def test_wrapper_only_filer_validates_with_only_stubs_and_the_wrapper_block():
    # item 6: a wrapper-only filer with no census and no knowledge files
    w = wrapper_v3(STELLUS)
    wfile = f("bdc_xbrl_wrappers/" + STELLUS + ".json", w)
    inputs = dict(
        files={"bdc_xbrl_wrappers": [wfile]}, shared={},
        disposition=[dict(path=wfile["path"], family="bdc_xbrl_wrappers", cls="executable", action="wrapper_block",
                          sha256=wfile["sha256"], ordered_sha256=None, targets=[], reason=None, record_indexes=None)],
        attested_under={}, census_q4=None,
        census_q4_unavailable=dict(census_run_id="x", reason="unavailable", detail="no_census"), census_q1=None,
        detection={}, predicate=dict(version="census-published.v2", code_sha256="e" * 64),
        code_mirror=[], overrides_root="tmp", replay_run_id="r")
    doc = pi.build_document(STELLUS, inputs=inputs, recorded_at=NOW, run_id=RUN, git_head="2a218e9")
    pd.validate_document(doc)
    assert [b["family"] for b in doc["wrapper_section"]["blocks"]] == ["bdc_xbrl_wrapper"]
    assert doc["corrections"] == []
    assert {e["key"] for e in doc["entries"]} == {"partition_structure.published_basis"}
    assert len(doc["stubs"]) == len(pd.GRID_KEYS) - 1
