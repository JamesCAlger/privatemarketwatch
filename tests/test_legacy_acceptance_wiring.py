"""The real quarter gate must measure the inputs named by its receipts."""
import pytest

from pipeline import quarter_acceptance as qa, quarter_evidence
from pipeline.programme.core import ContractError, atomic_json, sha
from tests.test_quarter_acceptance import Q, _setup, _cons_row


@pytest.fixture
def gate(tmp_path, monkeypatch):
    kwargs = _setup(tmp_path, ledger_rows=[
        _cons_row("0000000001", "pass"),
        _cons_row("0000000002", "pass"),
        _cons_row("0000000003", "pass")])
    # This integration exercises legacy measurement and evidence binding.
    # Independent extension collectors have their own source-backed fixtures.
    monkeypatch.setattr(quarter_evidence, "collect", lambda *args, **kwargs: {})
    extension = tmp_path / "extension.json"
    atomic_json(extension, dict(version=100, calibration="test", checks=[]))
    kwargs["programme_thresholds"] = extension
    return kwargs


def receipt(tmp_path, gate, files):
    holdings_hash = sha(gate["holdings_path"])
    path = tmp_path / "evidence.json"
    atomic_json(path, dict(holdings_sha256=holdings_hash, files={
        "legacy_" + name: dict(path=str(source.resolve()), sha256=sha(source),
                              holdings_sha256=holdings_hash)
        for name, source in files.items()}))
    return path


@pytest.mark.parametrize("name", ["ledger", "queue", "audit"])
def test_quarter_gate_rejects_receipt_for_a_different_measured_file(tmp_path, gate, name):
    original = gate[name + "_path"]
    unrelated = tmp_path / ("other_" + name + ".csv")
    unrelated.write_bytes(original.read_bytes())
    evidence = receipt(tmp_path, gate, {name: unrelated})
    # Identical bytes and a valid candidate hash do not establish that this
    # receipt names the input actually supplied to the gate.
    with pytest.raises(ContractError, match="differs from its evidence record"):
        qa.compute_acceptance(target_quarter=Q, programme_evidence=evidence, **gate)


@pytest.mark.parametrize("bound", [True, False])
def test_real_legacy_measurement_is_assessable_only_with_its_receipt(tmp_path, gate, bound):
    evidence = receipt(tmp_path, gate,
                       {"ledger": gate["ledger_path"]} if bound else {})
    result = qa.compute_acceptance(target_quarter=Q, programme_evidence=evidence, **gate)
    check = next(row for row in result["checks"] if row["id"] == "reconcile_rate")
    assert check["actual"] == 100.0
    assert check["status"] == ("PASS" if bound else "UNASSESSABLE")
    assert result["release_approval"] == "not_granted"
