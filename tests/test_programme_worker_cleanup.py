import psutil
import pytest

from pipeline.programme.core import ContractError,atomic_json
from pipeline.programme.runner import stop_owned_worker


class Worker:
    def __init__(self,created): self.created=created;self.killed=False;self.waited=False
    def create_time(self): return self.created
    def kill(self): self.killed=True
    def wait(self): self.waited=True


def test_cancellation_waits_for_exact_owned_process(tmp_path,monkeypatch):
    worker=Worker(12.5)
    atomic_json(tmp_path/'telemetry/worker.json',dict(pid=123,process_created=12.5))
    monkeypatch.setattr(psutil,'Process',lambda pid:worker)
    assert stop_owned_worker(tmp_path)
    assert worker.killed and worker.waited


def test_reused_pid_is_not_killed(tmp_path,monkeypatch):
    worker=Worker(19.5)
    atomic_json(tmp_path/'telemetry/worker.json',dict(pid=123,process_created=12.5))
    monkeypatch.setattr(psutil,'Process',lambda pid:worker)
    assert stop_owned_worker(tmp_path)
    assert not worker.killed


def test_missing_creation_identity_cannot_certify_cleanup(tmp_path,monkeypatch):
    worker=Worker(12.5)
    atomic_json(tmp_path/'telemetry/worker.json',dict(pid=123))
    monkeypatch.setattr(psutil,'Process',lambda pid:worker)
    with pytest.raises(ContractError,match='creation identity'): stop_owned_worker(tmp_path)
    assert not worker.killed
