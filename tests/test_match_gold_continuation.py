"""Tests for the build-independent continuation metric.

Sampler: scripts/match_gold/build_packets.sample_continuations
Scorer:  scripts/match_gold/score_continuation
"""
import json
from pathlib import Path

import pandas as pd
import pytest

from tests.test_match_quality import _holdings, _row
from scripts.match_gold import build_packets as bp
from scripts.match_gold import score_continuation as sc


def _three_quarter_fund():
    return _holdings([
        _row("0000000001", "2025-03-31", "Acme Corp", 100.0, "POS-1", "ROW-" + "a" * 16),
        _row("0000000001", "2025-06-30", "Acme Corp", 101.0, "POS-1", "ROW-" + "b" * 16),
        _row("0000000001", "2025-09-30", "Acme Corp", 102.0, "POS-1", "ROW-" + "c" * 16),
        _row("0000000001", "2025-03-31", "Beta LLC", 900.0, "POS-2", "ROW-" + "d" * 16),
        _row("0000000001", "2025-06-30", "Beta LLC", 905.0, "POS-2", "ROW-" + "e" * 16),
        _row("0000000001", "2025-09-30", "Beta LLC", 910.0, "POS-2", "ROW-" + "f" * 16),
    ])


class TestContinuationSampler:
    def test_is_deterministic(self):
        h = _three_quarter_fund()
        a = bp.sample_continuations(h, n_uniform=3, n_fv_weighted=3)
        b = bp.sample_continuations(h, n_uniform=3, n_fv_weighted=3)
        pd.testing.assert_frame_equal(a, b)

    def test_excludes_each_cik_last_quarter(self):
        """No continuation is observable from the last quarter a fund reported."""
        h = _three_quarter_fund()
        s = bp.sample_continuations(h, n_uniform=50, n_fv_weighted=50)
        last_rows = set(h[h["report_date"] == "2025-09-30"]["row_id"])
        assert not (set(s["anchor_row_id"]) & last_rows)

    def test_samples_rows_not_position_ids(self):
        """The anchor is a row; two quarters of one position are distinct draws."""
        h = _three_quarter_fund()
        s = bp.sample_continuations(h, n_uniform=50, n_fv_weighted=50)
        uni = s[s["stratum"] == "continuation_uniform"]
        assert len(uni) == 4          # 2 positions x 2 non-final quarters
        assert uni["anchor_row_id"].nunique() == 4
        assert (uni["position_id"] == "").all()

    def test_fv_weighting_prefers_the_larger_position(self):
        h = _three_quarter_fund()
        s = bp.sample_continuations(h, n_uniform=0, n_fv_weighted=1)
        big = set(h[h["issuer_name"] == "Beta LLC"]["row_id"])
        assert set(s["anchor_row_id"]) <= big

    def test_zero_fair_value_rows_are_eligible_for_the_uniform_stratum(self):
        """Undrawn commitments are part of the population being measured."""
        h = _holdings([
            _row("0000000001", "2025-03-31", "Acme Corp", 0.0, "POS-1", "ROW-" + "a" * 16),
            _row("0000000001", "2025-06-30", "Acme Corp", 500.0, "POS-2", "ROW-" + "b" * 16),
        ])
        s = bp.sample_continuations(h, n_uniform=10, n_fv_weighted=10)
        uni = s[s["stratum"] == "continuation_uniform"]
        assert "ROW-" + "a" * 16 in set(uni["anchor_row_id"])
        # ...but it carries no dollars, so it is not in the FV-weighted draw.
        fvw = s[s["stratum"] == "continuation_fv_weighted"]
        assert "ROW-" + "a" * 16 not in set(fvw["anchor_row_id"])


def _write_batch(tmp_path: Path, packets: list[dict]) -> Path:
    batch = tmp_path / "mgX"
    for sub in ("packets", "packets_meta", "verdicts"):
        (batch / sub).mkdir(parents=True, exist_ok=True)
    for p in packets:
        pid = p["packet_id"]
        (batch / "packets" / f"{pid}.json").write_text(
            json.dumps({"packet_id": pid, "packet_type": "chain",
                        "cik": p["cik"], "rows": [{"row_id": p["anchor"]}],
                        "edges": []}), encoding="utf-8")
        (batch / "packets_meta" / f"{pid}.json").write_text(
            json.dumps({"stratum": p.get("stratum", "continuation_uniform")}),
            encoding="utf-8")
        (batch / "verdicts" / f"{pid}.json").write_text(
            json.dumps(p["verdict"]), encoding="utf-8")
    return batch


def _verdict(pid, kind, anchor=None, target=None):
    if kind == "continues":
        return {"packet_id": pid, "packet_type": "chain", "verdict": "MISSED_LINK",
                "confidence": 0.9, "rationale": "same loan",
                "proposed_links": [{"row_id_a": anchor, "row_id_b": target}]}
    if kind == "ends":
        return {"packet_id": pid, "packet_type": "chain", "verdict": "CONFIRMED",
                "confidence": 0.9, "rationale": "repaid", "proposed_links": []}
    return {"packet_id": pid, "packet_type": "chain",
            "verdict": "INSUFFICIENT_EVIDENCE", "confidence": 0.2,
            "rationale": "cannot tell", "proposed_links": []}


class TestContinuationScorer:
    A, B, C = "ROW-" + "a" * 16, "ROW-" + "b" * 16, "ROW-" + "c" * 16

    def _holdings_csv(self, tmp_path, pairs):
        """pairs: list of (row_id, report_date, position_id)."""
        df = pd.DataFrame([{"row_id": r, "cik": "0000000001", "position_id": p,
                            "report_date": d, "fair_value": 100.0}
                           for r, d, p in pairs])
        tmp_path.mkdir(parents=True, exist_ok=True)
        path = tmp_path / "holdings.csv"
        df.to_csv(path, index=False)
        return path

    def test_truth_is_read_from_the_verdicts(self, tmp_path):
        batch = _write_batch(tmp_path, [
            {"packet_id": "MGP-1", "cik": "0000000001", "anchor": self.A,
             "verdict": _verdict("MGP-1", "continues", self.A, self.B)},
            {"packet_id": "MGP-2", "cik": "0000000001", "anchor": self.C,
             "verdict": _verdict("MGP-2", "ends")},
        ])
        truth = sc.load_truth(batch)
        assert dict(zip(truth["packet_id"], truth["truth"])) == {
            "MGP-1": "continues", "MGP-2": "ends"}
        assert truth.set_index("packet_id").at["MGP-1", "truth_row_id"] == self.B

    def test_reversed_link_order_is_normalised(self, tmp_path):
        batch = _write_batch(tmp_path, [
            {"packet_id": "MGP-1", "cik": "0000000001", "anchor": self.A,
             "verdict": _verdict("MGP-1", "continues", self.B, self.A)},
        ])
        truth = sc.load_truth(batch)
        assert truth.at[0, "truth_row_id"] == self.B

    def test_scores_the_four_outcomes(self, tmp_path):
        batch = _write_batch(tmp_path, [
            {"packet_id": "MGP-1", "cik": "0000000001", "anchor": self.A,
             "verdict": _verdict("MGP-1", "continues", self.A, self.B)},
            {"packet_id": "MGP-2", "cik": "0000000001", "anchor": self.C,
             "verdict": _verdict("MGP-2", "ends")},
        ])
        truth = sc.load_truth(batch)

        # build 1: links A->B (right) and leaves C alone (right)
        good = self._holdings_csv(tmp_path / "g", [
            (self.A, "2025-03-31", "P1"), (self.B, "2025-06-30", "P1"),
            (self.C, "2025-03-31", "P2")])
        out = sc.score_build(truth, good)
        assert dict(zip(out["packet_id"], out["outcome"])) == {
            "MGP-1": "correct_link", "MGP-2": "correct_end"}

        # build 2: leaves A unchained (missing) and chains C forward (false link)
        bad = self._holdings_csv(tmp_path / "b", [
            (self.A, "2025-03-31", "P1"), (self.B, "2025-06-30", "P9"),
            (self.C, "2025-03-31", "P2"), ("ROW-" + "d" * 16, "2025-06-30", "P2")])
        out = sc.score_build(truth, bad)
        assert dict(zip(out["packet_id"], out["outcome"])) == {
            "MGP-1": "missing_link", "MGP-2": "false_link"}

    def test_wrong_link_is_distinguished_from_missing(self, tmp_path):
        batch = _write_batch(tmp_path, [
            {"packet_id": "MGP-1", "cik": "0000000001", "anchor": self.A,
             "verdict": _verdict("MGP-1", "continues", self.A, self.B)},
        ])
        truth = sc.load_truth(batch)
        hp = self._holdings_csv(tmp_path / "w", [
            (self.A, "2025-03-31", "P1"), (self.B, "2025-06-30", "P9"),
            (self.C, "2025-06-30", "P1")])
        out = sc.score_build(truth, hp)
        assert out.at[0, "outcome"] == "wrong_link"

    def test_undecided_packets_leave_the_rates_alone(self, tmp_path):
        batch = _write_batch(tmp_path, [
            {"packet_id": "MGP-1", "cik": "0000000001", "anchor": self.A,
             "verdict": _verdict("MGP-1", "continues", self.A, self.B)},
            {"packet_id": "MGP-9", "cik": "0000000001", "anchor": self.C,
             "verdict": _verdict("MGP-9", "unclear")},
        ])
        truth = sc.load_truth(batch)
        hp = self._holdings_csv(tmp_path / "u", [
            (self.A, "2025-03-31", "P1"), (self.B, "2025-06-30", "P1"),
            (self.C, "2025-03-31", "P2")])
        out = sc.score_build(truth, hp)
        rates = sc._rates(out)
        assert rates["n_decided"] == 1
        assert rates["undecided"] == 1
        assert rates["precision"] == pytest.approx(1.0)
        assert rates["recall"] == pytest.approx(1.0)

    def test_same_sample_scores_two_builds(self, tmp_path):
        """The point of the metric: one adjudication, many builds."""
        batch = _write_batch(tmp_path, [
            {"packet_id": "MGP-1", "cik": "0000000001", "anchor": self.A,
             "verdict": _verdict("MGP-1", "continues", self.A, self.B)},
        ])
        truth = sc.load_truth(batch)
        before = self._holdings_csv(tmp_path / "1", [
            (self.A, "2025-03-31", "P1"), (self.B, "2025-06-30", "P9")])
        after = self._holdings_csv(tmp_path / "2", [
            (self.A, "2025-03-31", "P1"), (self.B, "2025-06-30", "P1")])
        scored = {"before": sc.score_build(truth, before),
                  "after": sc.score_build(truth, after)}
        assert scored["before"].at[0, "outcome"] == "missing_link"
        assert scored["after"].at[0, "outcome"] == "correct_link"
        report = sc.render(scored)
        assert "before" in report and "after" in report
