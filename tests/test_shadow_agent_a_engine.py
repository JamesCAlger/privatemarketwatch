"""Tests for the Agent A shadow engine verdict->status + cohort derivation."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import shadow_agent_a_engine as eng  # noqa: E402


def test_verdict_to_status_mapping():
    # 'neither' (internally-inconsistent filing) is the strongest flag -> fail
    assert eng._STATUS["neither"] == "fail"
    # all other verdicts are advisory warns (B prioritises via the mechanism)
    for v in ("agentA", "xbrl", "both", "undeterminable"):
        assert eng._STATUS[v] == "warn"


def test_seed_targets_documented():
    # the original hand-verified four are retained as a regression anchor
    assert {c for c, _ in eng.SEED_TARGETS} == {
        "0001993402", "0001278752", "0001655050", "0001633336"}


def test_candidate_grammars_have_rate_signatures():
    # runs over the real committed grammar dir (JSON-only, no parquet)
    candidates, skipped = eng.candidate_grammars()
    assert candidates, "expected committed rate grammars to exist"
    # every candidate declares a non-empty flattened signature
    assert all(sig for _, sig, _ in candidates)
    # the cohort is genuinely wider than the original four
    assert len(candidates) > len(eng.SEED_TARGETS)
    # every skipped entry explains itself (no silent drops)
    assert all(reason for *_, reason in skipped)


def test_build_cohort_gates_on_held_out_pass(tmp_path):
    # synthetic grammars: one flattened-PASS, one flattened-FAIL, one non-rate
    (tmp_path / "0000000001.json").write_text(
        json.dumps({"applies_to": {"regime": "flattened", "signature": "SIG A"}}),
        encoding="utf-8")
    (tmp_path / "0000000002.json").write_text(
        json.dumps({"applies_to": {"regime": "flattened", "signature": "SIG B"}}),
        encoding="utf-8")
    (tmp_path / "0000000003.json").write_text(
        json.dumps({"applies_to": {"regime": "delimited"}}), encoding="utf-8")

    class _V:
        def __init__(self, verdict, confidence="high"):
            self.verdict, self.confidence, self.reasons = verdict, confidence, ["because"]

    def fake_gate(cik, sig, parquet):
        return _V("PASS", "narrow") if cik == "0000000001" else _V("FAIL")

    cohort, excluded, skipped = eng.build_cohort("x", gate=fake_gate, grammar_dir=tmp_path)
    assert cohort == [("0000000001", "SIG A", "narrow")]            # PASS enrolled w/ confidence
    assert [c for c, *_ in excluded] == ["0000000002"]              # held-out FAIL excluded
    assert [c for c, *_ in skipped] == ["0000000003"]               # non-flattened skipped
