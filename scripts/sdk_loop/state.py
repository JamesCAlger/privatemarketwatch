"""Run and fund state on disk, the cost ledger and the budget. Every write is whole-file and
written to a temp file first, so a cut-off run never leaves half a state file."""
from __future__ import annotations

import csv
import datetime as dt
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

STAGES = ("queued", "fund_agent", "checks", "review", "sample", "recorded", "parked", "failed")
TERMINAL = ("recorded", "parked", "failed")


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, path)


@dataclass
class FundState:
    cik: str
    stage: str = "queued"
    round: int = 1
    builds: dict = field(default_factory=dict)        # round -> builds used
    labels: list = field(default_factory=list)        # sandbox labels, in order
    before: str | None = None                         # sandbox the first build is compared with
    worktree: str | None = None
    branch: str | None = None
    cost_usd: float = 0.0
    errors: dict = field(default_factory=dict)        # stage -> consecutive errors
    rejections: dict = field(default_factory=dict)    # item key -> [reason fingerprints]
    stop_reason: str = ""
    returned: list = field(default_factory=list)      # items returned to the agent this round
    notes: list = field(default_factory=list)         # orchestrator guidance for the next round
    history: list = field(default_factory=list)       # (time, from, to, why)

    def move(self, to: str, why: str = "") -> None:
        assert to in STAGES, to
        self.history.append([dt.datetime.now().isoformat(timespec="seconds"), self.stage, to, why])
        self.stage = to
        if to in ("parked", "failed"):
            self.stop_reason = why

    @property
    def done(self) -> bool:
        return self.stage in TERMINAL


class Run:
    """One run folder: run.json, funds/<cik>/state.json, ledger.csv, orchestrator.jsonl."""

    def __init__(self, folder: Path):
        self.folder = Path(folder)
        self.meta = json.loads((self.folder / "run.json").read_text(encoding="utf-8")) if (self.folder / "run.json").exists() else {}

    @classmethod
    def create(cls, folder: Path, meta: dict) -> "Run":
        if (Path(folder) / "run.json").exists():
            raise FileExistsError("run exists: %s (resume it with --run-id)" % folder)
        _write_json(Path(folder) / "run.json", meta)
        return cls(folder)

    def save_meta(self) -> None:
        _write_json(self.folder / "run.json", self.meta)

    def fund_dir(self, cik: str) -> Path:
        return self.folder / "funds" / cik

    def round_dir(self, cik: str, n: int) -> Path:
        d = self.fund_dir(cik) / ("round_%d" % n)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def load_fund(self, cik: str) -> FundState:
        path = self.fund_dir(cik) / "state.json"
        if not path.exists():
            return FundState(cik=cik)
        return FundState(**json.loads(path.read_text(encoding="utf-8")))

    def save_fund(self, fs: FundState) -> None:
        _write_json(self.fund_dir(fs.cik) / "state.json", asdict(fs))

    # --- ledger -----------------------------------------------------------
    LEDGER_FIELDS = ("time", "role", "cik", "round", "model", "cost_usd", "input_tokens", "output_tokens",
                     "cache_read_tokens", "cache_write_tokens", "turns", "duration_s", "exit")

    def log_call(self, row: dict) -> None:
        path = self.folder / "ledger.csv"
        new = not path.exists()
        with open(path, "a", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=self.LEDGER_FIELDS, extrasaction="ignore")
            if new:
                w.writeheader()
            w.writerow({"time": dt.datetime.now().isoformat(timespec="seconds"), **row})

    def calls(self) -> list[dict]:
        path = self.folder / "ledger.csv"
        if not path.exists():
            return []
        with open(path, newline="", encoding="utf-8") as fh:
            return list(csv.DictReader(fh))

    def spent(self) -> float:
        return sum(float(r["cost_usd"] or 0) for r in self.calls())

    def log_decision(self, entry: dict) -> None:
        with open(self.folder / "orchestrator.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"time": dt.datetime.now().isoformat(timespec="seconds"), **entry}, default=str) + "\n")

    def add_owner_question(self, cik: str, text: str) -> None:
        with open(self.folder / "owner_questions.md", "a", encoding="utf-8") as fh:
            fh.write("- [%s] %s\n" % (cik, text.replace("\n", " ")))


class Budget:
    """Run cap, per-fund cap and expected cost per role from the ledger (mean of the last entries)."""

    def __init__(self, run: Run, run_cap: float, fund_cap: float, agent_caps: dict):
        self.run, self.run_cap, self.fund_cap, self.agent_caps = run, run_cap, fund_cap, agent_caps

    def expected(self, role: str) -> float:
        costs = [float(r["cost_usd"] or 0) for r in self.run.calls() if r["role"] == role]
        if len(costs) >= 3:
            return sum(costs[-5:]) / len(costs[-5:])
        return self.agent_caps[role] / 2   # no history yet: half the agent cap

    def allows(self, role: str, fs: FundState | None) -> tuple[bool, str]:
        need = self.expected(role)
        left = self.run_cap - self.run.spent()
        if need > left:
            return False, "run budget: %.2f left, %s expected %.2f" % (left, role, need)
        if fs is not None and fs.cost_usd + need > self.fund_cap:
            return False, "fund budget: %.2f spent of %.2f, %s expected %.2f" % (fs.cost_usd, self.fund_cap, role, need)
        return True, ""

    def agent_cap(self, role: str, fs: FundState | None) -> float:
        """Never let one agent spend past the run or fund cap."""
        cap = min(self.agent_caps[role], self.run_cap - self.run.spent())
        if fs is not None:
            cap = min(cap, self.fund_cap - fs.cost_usd)
        return max(cap, 0.0)
