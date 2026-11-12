"""pipeline.decision_store: append-only decisions, who may write them, and the facts they give."""
import datetime
import json

import pytest

from pipeline import decision_store as ds
from pipeline import finding_status as fs

CIK = "0001234567"
RID = "RVQ_BLK_0123456789ab"


def verdict(**over):
    entry = {"type": "verdict", "cik": CIK, "engine": "oracle", "rule_name": "A01",
             "quarters": ["2025-12-31"], "finding_ids": [RID], "statement": "Subtotal equals its rows.",
             "evidence": [{"source": "filing", "accession": "0000000000-26-000001",
                           "quote": "Total Software 1,234 1,250 3.1 %"}],
             "conclusion": "false_alarm", "reviewed_by": "reviewer-x", "review_outcome": "supported",
             "decided_by": "agent:fund-agent-x", "decided_on": "2026-11-12"}
    entry.update(over)
    return entry


def ruling(**over):
    entry = {"type": "owner_ruling", "cik": "", "finding_ids": [], "quarters": [],
             "statement": "Reason ruled.", "evidence": [], "ruling": "reject", "reason_key": "a01-x",
             "words": "not a disposition", "decided_by": "owner", "decided_on": "2026-11-12"}
    entry.update(over)
    return entry


def request(**over):
    entry = {"type": "check_repair_request", "cik": CIK, "finding_ids": [RID], "quarters": [],
             "statement": "A01 counts children twice.", "evidence": [], "request_id": "REQ-1",
             "check": "pipeline/oracle_checks.py A01", "resolution": "open",
             "decided_by": "agent:fund-agent-x", "decided_on": "2026-11-12"}
    entry.update(over)
    return entry


def owner_question(**over):
    entry = {"type": "owner_request", "cik": CIK, "finding_ids": [RID], "quarters": [],
             "statement": "Does the printed filer industry count as covered?", "evidence": [],
             "request_id": "REQ-2", "resolution": "open",
             "decided_by": "agent:fund-agent-x", "decided_on": "2026-11-12"}
    entry.update(over)
    return entry


def fix(**over):
    entry = {"type": "fix_record", "cik": CIK, "finding_ids": [RID], "quarters": [],
             "statement": "Wrapper strips the industry label.", "evidence": [],
             "expects": {"finding_ids": [RID], "ciks": [CIK]}, "files": ["data/overrides/x.json"],
             "tested_in": "sbx1", "decided_by": "agent:fund-agent-x", "decided_on": "2026-11-12"}
    entry.update(over)
    return entry


def at(hour):
    return datetime.datetime(2026, 11, 12, hour, 0, 0)


def test_each_native_type_appends_and_reads_back(tmp_path):
    for entry in (verdict(), ruling(), request(), owner_question(), fix()):
        ds.append(entry, actor=entry["decided_by"], directory=tmp_path)
    loaded = ds.load_native(tmp_path)
    assert sorted(e["type"] for e in loaded) == sorted(ds.NATIVE_TYPES)
    assert all(e["decision_id"].startswith("DC-") and e["recorded_at"] for e in loaded)
    assert (tmp_path / (CIK + ".jsonl")).exists() and (tmp_path / ds.SHARED_FILE).exists()


@pytest.mark.parametrize("change, message", [
    ({"type": "note"}, "type must be"),
    ({"statement": ""}, "missing statement"),
    ({"decided_on": "12/11/2026"}, "decided_on"),
    ({"decided_by": "somebody"}, "decided_by must be"),
    ({"cik": "123"}, "cik must be"),
    ({"conclusion": "looks fine"}, "conclusion"),
    ({"finding_ids": []}, "names its finding_ids"),
    ({"review_outcome": "supported", "reviewed_by": ""}, "needs reviewed_by"),
    ({"evidence": [{"source": "filing", "quote": "Total Software 1,234"}]}, "needs an accession"),
    ({"quarters": ["2025-12-31 00:00:00"]}, "quarters"),
])
def test_invalid_entries_are_refused(tmp_path, change, message):
    entry = verdict(**change)
    assert any(message in p for p in ds.validate(entry)), ds.validate(entry)
    with pytest.raises((ValueError, PermissionError)):
        ds.append(entry, actor=str(entry.get("decided_by")), directory=tmp_path)
    assert not list(tmp_path.glob("*.jsonl"))


def test_type_specific_fields():
    assert any("ruling must be" in p for p in ds.validate(ruling(ruling="maybe")))
    assert any("records the words" in p for p in ds.validate(ruling(words="")))
    assert any("names a reason_key" in p for p in ds.validate(ruling(reason_key="")))
    assert any("resolution" in p for p in ds.validate(request(resolution="later")))
    assert any("expects" in p for p in ds.validate(fix(expects={"finding_ids": [], "ciks": []})))
    assert any("commit or the files" in p for p in ds.validate(fix(files=[])))
    assert any("tested" in p for p in ds.validate(fix(tested_in="")))


def test_an_agent_cannot_record_an_owner_ruling(tmp_path):
    entry = ruling(decided_by="agent:fund-agent-x")
    with pytest.raises(PermissionError):
        ds.append(entry, actor="agent:fund-agent-x", directory=tmp_path)
    with pytest.raises(PermissionError):  # nor write in the owner's name
        ds.append(ruling(), actor="agent:fund-agent-x", directory=tmp_path)
    ds.append(ruling(decided_by="delegate:2026-11-12"), actor="delegate:2026-11-12", directory=tmp_path)
    ds.append(ruling(words="second"), actor="owner", directory=tmp_path)
    assert len(ds.load_native(tmp_path)) == 2


def test_filing_quote_must_be_on_the_page(tmp_path):
    seen = []

    def quote_ok(cik, accession, quote):
        seen.append((cik, accession))
        return "1,234" in quote and accession.endswith("000001")

    ds.append(verdict(), actor="agent:fund-agent-x", directory=tmp_path, quote_ok=quote_ok)
    bad = verdict(evidence=[{"source": "filing", "accession": "0000000000-26-000009", "quote": "Total Software 9,999"}])
    with pytest.raises(ValueError, match="not found on the cached page"):
        ds.append(bad, actor="agent:fund-agent-x", directory=tmp_path, quote_ok=quote_ok)
    assert seen[0] == (CIK, "0000000000-26-000001") and len(ds.load_native(tmp_path)) == 1


def test_append_never_rewrites_earlier_lines_and_refuses_a_repeat(tmp_path):
    first = ds.append(verdict(), actor="agent:fund-agent-x", directory=tmp_path, now=at(9))
    path = tmp_path / (CIK + ".jsonl")
    before = path.read_bytes()
    ds.append(request(), actor="agent:fund-agent-x", directory=tmp_path, now=at(10))
    assert path.read_bytes().startswith(before)
    with pytest.raises(ValueError, match="already recorded"):
        ds.append(verdict(), actor="agent:fund-agent-x", directory=tmp_path, now=at(11))
    assert first["decision_id"] == ds.decision_id(verdict())


def test_supersession(tmp_path):
    old = ds.append(verdict(), actor="agent:fund-agent-x", directory=tmp_path, now=at(9))
    new = ds.append(verdict(conclusion="confirmed_error", supersedes=old["decision_id"]),
                    actor="agent:fund-agent-x", directory=tmp_path, now=at(10))
    entries = ds.load_native(tmp_path)
    assert len(entries) == 2
    assert [e["decision_id"] for e in ds.standing(entries)] == [new["decision_id"]]
    with pytest.raises(ValueError, match="unknown decision"):
        ds.append(verdict(statement="other", supersedes="DC-nope"), actor="agent:fund-agent-x", directory=tmp_path)


def test_an_unreadable_line_raises(tmp_path):
    ds.append(verdict(), actor="agent:fund-agent-x", directory=tmp_path)
    with open(tmp_path / (CIK + ".jsonl"), "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"type": "verdict"}) + "\n")
    with pytest.raises(ValueError, match="Invalid decision"):
        ds.load_native(tmp_path)


# ---------------------------------------------------------------- facts

ROW = {"review_id": RID, "cik": CIK, "engine": "oracle", "rule_name": "A01", "report_date": "2025-12-31"}


def proposal(klass, *, ready=True, reason="a01-x"):
    return {"type": "disposition_proposal", "decision_id": "PD-1", "ciks": [CIK], "engine": "oracle",
            "rule_name": "A01", "quarters": ["2025-12-31"], "class": klass, "reason_key": reason,
            "ready": ready, "finding_ids": []}


def facts(entries, build_time=""):
    return ds.facts_by_finding(entries, [ROW], build_time=build_time)[RID]


def test_no_decisions_no_facts():
    assert facts([]) == fs.Facts()


def test_verdict_gives_the_conclusion_and_latest_wins(tmp_path):
    ds.append(verdict(), actor="agent:fund-agent-x", directory=tmp_path, now=at(9))
    ds.append(verdict(conclusion="confirmed_error", review_outcome="", reviewed_by="", statement="later"),
              actor="agent:fund-agent-x", directory=tmp_path, now=at(10))
    got = facts(ds.load_native(tmp_path))
    assert (got.conclusion, got.conclusion_supported) == ("confirmed_error", False)


def test_fix_is_queued_only_after_the_build(tmp_path):
    ds.append(fix(), actor="agent:fund-agent-x", directory=tmp_path, now=at(12))
    entries = ds.load_native(tmp_path)
    assert facts(entries, "2026-11-12T08:00:00").fix_queued
    assert not facts(entries, "2026-11-12T13:00:00").fix_queued
    assert not facts(entries, "").fix_queued


def test_check_repair_request_stands_until_implemented(tmp_path):
    ds.append(request(), actor="agent:fund-agent-x", directory=tmp_path, now=at(9))
    assert facts(ds.load_native(tmp_path)).check_repair
    ds.append(request(resolution="implemented", statement="done in abc123", decided_by="owner"),
              actor="owner", directory=tmp_path, now=at(10))
    assert not facts(ds.load_native(tmp_path)).check_repair


def test_owner_request_waits_for_the_owner(tmp_path):
    ds.append(owner_question(), actor="agent:fund-agent-x", directory=tmp_path, now=at(9))
    got = facts(ds.load_native(tmp_path))
    assert got.owner_request and not got.check_repair
    assert fs.status_of("open", got) == fs.NEEDS_OWNER_RULING
    ds.append(owner_question(resolution="declined", statement="owner said no", decided_by="owner"),
              actor="owner", directory=tmp_path, now=at(10))
    assert not facts(ds.load_native(tmp_path)).owner_request


def test_proposal_classes_and_rulings():
    assert facts([proposal("as_filed")]).proposal_class == "as_filed"
    assert facts([proposal("as_filed", ready=False)]).proposal_class == ds.INCOMPLETE
    assert facts([proposal("rule_problem")]).proposal_class == "rule_problem"
    rejected = ruling()
    assert facts([proposal("as_filed"), rejected]).proposal_class == ""
    # a rejected misfire proposal still says the check needs repair
    assert facts([proposal("false_alarm"), rejected]).proposal_class == "false_alarm"
    assert facts([proposal("as_filed"), ruling(ruling="more")]).proposal_class == ds.INCOMPLETE
    assert facts([proposal("as_filed"), ruling(ruling="accept")]).proposal_class == ""
    # a proposal for another quarter does not bear on this finding
    other = dict(proposal("as_filed"), quarters=["2025-09-30"])
    assert facts([other]).proposal_class == ""
    # misfire outranks a store-class proposal on the same finding
    assert facts([proposal("as_filed"), dict(proposal("rule_problem"), reason_key="b")]).proposal_class == "rule_problem"


def test_facts_feed_status():
    assert fs.status_of("open", facts([proposal("as_filed")])) == fs.NEEDS_OWNER_RULING
    assert fs.status_of("open", facts([proposal("false_alarm"), ruling()])) == fs.NEEDS_CHECK_REPAIR
    assert fs.status_of("open", facts([])) == fs.NEEDS_AGENT_REVIEW


def test_adapters_expose_the_existing_stores(tmp_path):
    proposals = tmp_path / "proposed"
    proposals.mkdir()
    (proposals / "fund_x.json").write_text(json.dumps({"dispositions": [
        {"disposition_id": "PD-A01-1", "class": "rule_problem", "engine": "oracle", "rule_name": "A01",
         "ciks": ["1234567"], "quarters": ["2025-12-31"], "statement": "s", "evidence": [], "reason_key": "k"}]}),
        encoding="utf-8")
    empty = tmp_path / "none"
    entries = ds.load_all(tmp_path / "decisions", dispositions_dir=empty, retirements_dir=empty, proposals=proposals)
    assert [e["type"] for e in entries] == ["disposition_proposal"]
    assert entries[0]["ciks"] == [CIK] and entries[0]["origin"] == "proposals:fund_x.json"
    assert facts(entries).proposal_class == "rule_problem"
