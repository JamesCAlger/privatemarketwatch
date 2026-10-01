"""SP3 proper Tasks 5-6: inception converter (wrapper blocks, corrections, entries, stubs, build_document)."""
from __future__ import annotations

import copy

import pytest

from scripts.profile_pilot import profile_inception as pi
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
    with pytest.raises(pi.InceptionError):
        pi.wrapper_block(ARES, family="bdc_xbrl_wrapper", files=[f("a", wrapper_v3(ARES)), f("b", wrapper_v3(ARES))],
                         recorded_at=NOW, attested_under=[])
    with pytest.raises(pi.InceptionError):
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
    with pytest.raises(pi.InceptionError):
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
