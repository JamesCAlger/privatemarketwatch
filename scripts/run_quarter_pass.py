"""One remediation pass over a target quarter, as a checkpointed runbook.

Codifies the sequence that has so far been run by hand (Wave 1, recal1 prep):

  PRE-DISPATCH (deterministic, cache-only):
    rebuild -> oracle -> nonaccrual -> validate -> shadow -> queue
            -> acceptance -> select
  [ STOP: operator dispatches the Codex fleet from an admin terminal --
    B1/B2/anchor/B3 via the existing chain scripts; see the printed guidance.
    One fleet per machine; MaxParallel <= 2. ]
  POST-DISPATCH (after promotions land in the override stores):
    rebuild_post -> oracle_post -> nonaccrual_post -> validate_post
                 -> shadow_post -> queue_post -> acceptance_post -> summary

Each stage is checkpointed in ``data/output/quarter_pass/<pass_id>/state.json``;
re-running skips completed stages (``--force`` re-runs). ``--until select``
runs the pre-dispatch half; ``--from rebuild_post`` resumes after promotion.
``--dry-run`` prints the commands without executing anything.

The acceptance stages snapshot ``quarter_acceptance.json`` into the pass dir
(acceptance_pre.json / acceptance_post.json); ``summary`` diffs them -- that
delta IS the measured effect of the pass. Acceptance verdict exit codes
(1=FAIL, 2=NOT_ASSESSABLE) are recorded, not treated as stage errors: the
contract measures the quarter, it does not abort the pass.

This script NEVER dispatches Codex workers itself (interactive-terminal
constraint). ASCII-only output.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from pipeline import config  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("run_quarter_pass")

PASS_BASE = config.OUTPUT_DIR / "quarter_pass"

DISPATCH_GUIDANCE = """\
================ DISPATCH (operator step -- not run by this script) ================
Candidates ranked by fund FV: {candidates}
From an ADMIN terminal (conda-activated, codex login, OUTSIDE any Codex session),
with NO other Codex fleet running on this machine (MaxParallel <= 2):

  1. archive stale staged rules for each target CIK
     (data/output/agent_investigate/<cik>/rules -> archive before re-investigating)
  2. prepare + adjudicate + remediate, e.g.:
       python -m scripts.prepare_fresh_batch --batch-id <id> --n <n> [--exclude-cik ...]
       scripts/dispatch_agent_b_workers.ps1 -BatchId <id> -MaxParallel 2
       scripts/run_full_remediation_canary.ps1 -B1BatchId <id>
  3. gate + promote per the chain output (b3_gate_summary*.csv), then resume:
       python scripts/run_quarter_pass.py --pass-id {pass_id} --quarter {quarter} --from rebuild_post
====================================================================================
"""


@dataclass
class Stage:
    name: str
    argv: list[str] | None = None       # subprocess stages
    func: str | None = None             # function stages (method name on Runner)
    # exit codes that are valid stage OUTCOMES (recorded, not errors)
    allowed_exit: tuple[int, ...] = (0,)
    note: str = ""
    post_copy: tuple[Path, str] | None = None  # (src, dest-name-in-pass-dir)


def _stages(quarter: str) -> list[Stage]:
    py = sys.executable
    acceptance_argv = [py, "-m", "pipeline.quarter_acceptance", "--quarter", quarter]

    def battery(suffix: str) -> list[Stage]:
        return [
            Stage(f"rebuild{suffix}", [py, "scripts/rebuild_outputs.py", "--unified"],
                  note="unified rebuild from cached inputs (applies promoted rules + audit)"),
            Stage(f"oracle{suffix}", [py, "-m", "pipeline.oracle_runner"]),
            Stage(f"nonaccrual{suffix}", [py, "-m", "pipeline.extract_nonaccrual_flags"]),
            Stage(f"validate{suffix}", [py, "-m", "pipeline.main", "--validate"]),
            Stage(f"shadow{suffix}", [py, "scripts/shadow_validation_runner.py"]),
            Stage(f"queue{suffix}", [py, "-m", "pipeline.review_queue", "--emit-bdc-worklist"]),
            Stage(
                f"acceptance{suffix}",
                acceptance_argv,
                allowed_exit=(0, 1, 2),
                note="verdict exit codes 1/2 are outcomes, not errors",
                post_copy=(config.QUARTER_ACCEPTANCE_FILE,
                           f"acceptance_{'post' if suffix else 'pre'}.json"),
            ),
        ]

    return (
        battery("")
        + [Stage("select", func="select_candidates",
                 note="rank under-review funds by FV; STOP for operator dispatch")]
        + battery("_post")
        + [Stage("summary", func="summarize_pass")]
    )


class Runner:
    def __init__(self, pass_id: str, quarter: str, *, dry_run: bool = False,
                 run_cmd=None, pass_base: Path | None = None) -> None:
        self.pass_id = pass_id
        self.quarter = quarter
        self.dry_run = dry_run
        self.pass_dir = (pass_base or PASS_BASE) / pass_id
        self.state_path = self.pass_dir / "state.json"
        self.stages = _stages(quarter)
        self._run_cmd = run_cmd or self._subprocess_run

    # ---------------------------------------------------------------- state
    def load_state(self) -> dict:
        if self.state_path.exists():
            return json.loads(self.state_path.read_text(encoding="utf-8-sig"))
        return {"pass_id": self.pass_id, "quarter": self.quarter, "stages": {}}

    def save_state(self, state: dict) -> None:
        self.pass_dir.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")

    # ---------------------------------------------------------------- exec
    def _subprocess_run(self, argv: list[str], log_path: Path) -> int:
        with log_path.open("w", encoding="utf-8") as log:
            proc = subprocess.run(argv, cwd=REPO_ROOT, stdout=log,
                                  stderr=subprocess.STDOUT, text=True)
        return proc.returncode

    def run_stage(self, stage: Stage, state: dict) -> bool:
        """Run one stage; True to continue the pass, False to abort."""
        rec = {"started_utc": _now(), "argv": stage.argv, "note": stage.note}
        if self.dry_run:
            logger.info("[dry-run] %-16s %s", stage.name,
                        " ".join(stage.argv) if stage.argv else f"<{stage.func}>")
            return True
        self.pass_dir.mkdir(parents=True, exist_ok=True)
        if stage.func is not None:
            try:
                getattr(self, stage.func)()
                code = 0
            except Exception as exc:  # noqa: BLE001 -- recorded, aborts the pass
                logger.error("stage %s raised: %s", stage.name, exc)
                code = -1
        else:
            log_path = self.pass_dir / f"{stage.name}.log"
            logger.info("stage %-16s -> %s", stage.name, " ".join(stage.argv))
            code = self._run_cmd(stage.argv, log_path)
        rec["exit_code"] = code
        rec["finished_utc"] = _now()
        ok = code in stage.allowed_exit
        rec["status"] = "completed" if ok else "failed"
        if ok and stage.post_copy is not None:
            src, dest = stage.post_copy
            if Path(src).exists():
                shutil.copy2(src, self.pass_dir / dest)
                rec["snapshot"] = dest
        state["stages"][stage.name] = rec
        self.save_state(state)
        if not ok:
            logger.error("stage %s FAILED (exit %s); pass halted. Log: %s",
                         stage.name, code, self.pass_dir / f"{stage.name}.log")
        return ok

    # ------------------------------------------------------------ functions
    def select_candidates(self) -> None:
        """Rank under-review cohort funds by FV into candidates.csv + guidance."""
        funds_path = config.QUARTER_ACCEPTANCE_FUNDS_FILE
        if not funds_path.exists():
            raise FileNotFoundError(f"acceptance funds artifact missing: {funds_path}")
        with funds_path.open(newline="", encoding="utf-8-sig") as f:
            rows = [r for r in csv.DictReader(f) if r.get("tier") == "under_review"]
        rows.sort(key=lambda r: -_f(r.get("fund_fv_m")))
        out = self.pass_dir / "candidates.csv"
        with out.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else
                               ["cik", "entity_name", "fund_fv_m", "tier"])
            w.writeheader()
            for r in rows:
                w.writerow(r)
        logger.info("select: %d under-review funds -> %s", len(rows), out)
        print(DISPATCH_GUIDANCE.format(candidates=out, pass_id=self.pass_id,
                                       quarter=self.quarter))

    def summarize_pass(self) -> None:
        """Diff acceptance_pre vs acceptance_post: the measured effect of the pass."""
        pre_p = self.pass_dir / "acceptance_pre.json"
        post_p = self.pass_dir / "acceptance_post.json"
        if not (pre_p.exists() and post_p.exists()):
            raise FileNotFoundError("need both acceptance_pre.json and acceptance_post.json")
        pre = json.loads(pre_p.read_text(encoding="utf-8-sig"))
        post = json.loads(post_p.read_text(encoding="utf-8-sig"))

        def _flat(d: dict, prefix: str = "") -> dict[str, float]:
            out: dict[str, float] = {}
            for k, v in d.items():
                key = f"{prefix}{k}"
                if isinstance(v, dict):
                    out.update(_flat(v, key + "."))
                elif isinstance(v, (int, float)):
                    out[key] = float(v)
            return out

        fpre, fpost = _flat(pre.get("metrics", {})), _flat(post.get("metrics", {}))
        deltas = {k: round(fpost[k] - fpre[k], 3)
                  for k in sorted(set(fpre) & set(fpost)) if fpost[k] != fpre[k]}
        summary = {
            "pass_id": self.pass_id,
            "quarter": self.quarter,
            "verdict_pre": pre.get("verdict"),
            "verdict_post": post.get("verdict"),
            "metric_deltas": deltas,
            "checks_pre_fail": [c["id"] for c in pre.get("checks", []) if not c["pass"]],
            "checks_post_fail": [c["id"] for c in post.get("checks", []) if not c["pass"]],
        }
        out = self.pass_dir / "pass_summary.json"
        out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        logger.info("pass %s: verdict %s -> %s; %d metric deltas; wrote %s",
                    self.pass_id, summary["verdict_pre"], summary["verdict_post"],
                    len(deltas), out)

    # ---------------------------------------------------------------- drive
    def run(self, *, from_stage: str | None = None, until_stage: str | None = None,
            force: bool = False) -> int:
        names = [s.name for s in self.stages]
        for label, val in (("--from", from_stage), ("--until", until_stage)):
            if val is not None and val not in names:
                logger.error("%s %s is not a stage; stages: %s", label, val, ", ".join(names))
                return 2
        state = self.load_state()
        started = from_stage is None
        for stage in self.stages:
            if not started:
                started = stage.name == from_stage
                if not started:
                    continue
            done = state["stages"].get(stage.name, {}).get("status") == "completed"
            if done and not force:
                logger.info("stage %-16s already completed; skipping (--force to re-run)",
                            stage.name)
            else:
                if not self.run_stage(stage, state):
                    return 1
            if until_stage is not None and stage.name == until_stage:
                logger.info("stopped after --until %s", until_stage)
                return 0
        return 0


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _f(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run one checkpointed remediation pass over a target quarter.")
    parser.add_argument("--pass-id", required=True, help="short id, e.g. w2q4 (MAX_PATH)")
    parser.add_argument("--quarter", required=True, help="target report_date YYYY-MM-DD")
    parser.add_argument("--from", dest="from_stage", default=None,
                        help="resume from this stage (e.g. rebuild_post)")
    parser.add_argument("--until", dest="until_stage", default=None,
                        help="stop after this stage (e.g. select)")
    parser.add_argument("--force", action="store_true", help="re-run completed stages")
    parser.add_argument("--dry-run", action="store_true", help="print commands only")
    parser.add_argument("--list", action="store_true", help="list stages and exit")
    args = parser.parse_args(argv)

    runner = Runner(args.pass_id, args.quarter, dry_run=args.dry_run)
    if args.list:
        for s in runner.stages:
            kind = "cmd " if s.argv else "func"
            print(f"  {s.name:<16} [{kind}] {s.note}")
        return 0
    return runner.run(from_stage=args.from_stage, until_stage=args.until_stage,
                      force=args.force)


if __name__ == "__main__":
    sys.exit(main())
