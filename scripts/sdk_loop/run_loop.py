"""SDK fund loop driver (spec: docs/superpowers/specs/2026-11-14-sdk-fund-loop-design.md).

    python scripts/sdk_loop/run_loop.py --pick 3 --dry-run                 # no API calls
    python scripts/sdk_loop/run_loop.py --ciks 0001786108 0001993402 --run-cap 40 --fund-cap 30
    python scripts/sdk_loop/run_loop.py --run-id <id>                      # resume a run
    python scripts/sdk_loop/run_loop.py --pick 3 --observations            # also Loop 2

--dry-run prepares each fund (packet, worktree, snapshots), renders every role's prompt into the
run folder, removes the worktrees and stops: no agent is called and nothing is recorded.
A real run bills ANTHROPIC_API_KEY (from the environment or .env), never the Claude login.
Nothing is merged: the summary lists a branch per recorded fund. ASCII-only output.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import AGENT_CAP_USD, MIN_FREE_GB, REPO, RUN_ROOT, STATUS_CSV  # noqa: E402
from state import Budget, Run  # noqa: E402

V05 = {"0001803498", "0001812554", "0001287750", "0001838126", "0001837532"}


def load_key() -> bool:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return True
    dotenv = REPO / ".env"
    if dotenv.exists():
        for line in dotenv.read_text(encoding="utf-8-sig").splitlines():
            if line.strip().startswith("ANTHROPIC_API_KEY="):
                os.environ["ANTHROPIC_API_KEY"] = line.split("=", 1)[1].strip().strip('"').strip("'")
                return True
    return False


def _ps(command: str) -> str:
    return subprocess.run(["powershell", "-NoProfile", "-Command", command], capture_output=True, text=True, timeout=120).stdout


def preconditions() -> list[str]:
    problems = []
    busy = _ps("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -match "
               "'run_batch|rebuild_outputs|fund_ledger_trial|build_fund|pipeline.main|pytest' -and $_.ProcessId -ne %d } | "
               "ForEach-Object { $_.CommandLine.Substring(0,[Math]::Min(80,$_.CommandLine.Length)) }" % os.getpid())
    if busy.strip():
        problems.append("another build, batch or test run is running: " + busy.strip().splitlines()[0])
    free_kb = _ps("(Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory").strip()
    if free_kb.isdigit() and int(free_kb) / 1024 / 1024 < MIN_FREE_GB:
        problems.append("free memory %.1f GB is below %.1f GB" % (int(free_kb) / 1024 / 1024, MIN_FREE_GB))
    return problems


def pick_funds(n: int) -> list[str]:
    """Mid-sized funds: 15 to 30 outstanding findings, not the v0.5 five, largest first."""
    counts: dict[str, int] = {}
    with open(STATUS_CSV, newline="", encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            if r["status"] in ("needs_agent_review", "needs_data_fix"):
                counts[r["cik"].zfill(10)] = counts.get(r["cik"].zfill(10), 0) + 1
    sys.path.insert(0, str(REPO))
    from pipeline.cohort_guard import load_cohort_ciks
    cohort = {c.zfill(10) for c in load_cohort_ciks()}
    pool = sorted((c for c, k in counts.items() if 15 <= k <= 30 and c not in V05 and c in cohort), key=lambda c: -counts[c])
    return pool[:n]


def render_prompts(run: Run, cik: str, fs) -> None:
    """Dry run: write each role's prompt to the run folder so it can be read before paying."""
    from agents import load_prompt
    from config import BRIEF_DIR, MAX_BUILDS_PER_ROUND, MAX_ROUNDS
    rd = run.round_dir(cik, 1)
    common = {"cik": cik, "round": 1, "max_rounds": MAX_ROUNDS, "worktree": fs.worktree}
    texts = {
        "fund_agent": load_prompt("fund_agent", **common, builds_left=MAX_BUILDS_PER_ROUND, batch=run.meta["batch"],
                                  packet=(run.fund_dir(cik) / "packet.csv").as_posix(),
                                  label_prefix=run.meta["label_prefix"][cik], before=fs.before or "none",
                                  report=(rd / "report.json").as_posix(), verdicts=(rd / "verdicts.json").as_posix(),
                                  returned="", actor="agent:sdk-fundagent-%s-%s" % (cik[-6:], run.meta["run_id"][-6:]),
                                  today=run.meta["today"],
                                  brief=(BRIEF_DIR / "fund-agent-brief.md").read_text(encoding="utf-8"),
                                  investigation_contract=(BRIEF_DIR / "investigation-review.md").read_text(encoding="utf-8")),
        "reviewer": load_prompt("reviewer", **common, mode="full", label="<label>", report=(rd / "report.json").as_posix(),
                                verdicts=(rd / "verdicts.json").as_posix(), digest="<computed after the fund agent>",
                                review=(rd / "review.json").as_posix(), actor="agent:sdk-reviewer", change_only="",
                                investigation_contract=(BRIEF_DIR / "investigation-review.md").read_text(encoding="utf-8")),
    }
    for role, text in texts.items():
        (rd / ("prompt_%s.md" % role)).write_text(text, encoding="utf-8")
        if "{{" in text:
            raise RuntimeError("unfilled placeholder in %s prompt" % role)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ciks", nargs="*")
    ap.add_argument("--pick", type=int, help="pick N mid-sized funds (15-30 outstanding, not the v0.5 five)")
    ap.add_argument("--run-id")
    ap.add_argument("--run-cap", type=float, default=40.0)
    ap.add_argument("--fund-cap", type=float, default=30.0)
    ap.add_argument("--observations", action="store_true", help="also run Loop 2 after the funds")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--ignore-dirty", action="store_true",
                    help="dry run only: report uncommitted conflicting files and continue")
    args = ap.parse_args(argv)
    if args.ignore_dirty and not args.dry_run:
        print("--ignore-dirty is allowed only with --dry-run")
        return 2

    from agents import check_sdk
    sdk = check_sdk()
    problems = preconditions()
    if problems:
        print("not started: " + "; ".join(problems))
        return 3

    if args.run_id:
        run = Run(RUN_ROOT / args.run_id)
        if not run.meta:
            print("no run %s" % args.run_id)
            return 2
        ciks = run.meta["ciks"]
    else:
        ciks = [c.zfill(10) for c in (args.ciks or [])] or pick_funds(args.pick or 3)
        if not ciks:
            print("no funds to run")
            return 2
        stamp = dt.datetime.now().strftime("%Y%m%dT%H%M%S")
        base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True).stdout.strip()
        batch = json.loads((REPO / "data/output/batches/latest.json").read_text(encoding="utf-8"))["batch_id"]
        run = Run.create(RUN_ROOT / stamp, {
            "run_id": stamp, "ciks": ciks, "base_commit": base, "batch": batch, "sdk": sdk,
            "today": dt.date.today().isoformat(), "run_cap": args.run_cap, "fund_cap": args.fund_cap,
            "dry_run": args.dry_run, "observations": args.observations, "ignore_dirty": args.ignore_dirty,
            "label_prefix": {c: "y%s%s" % (c[-4:], stamp[-2:]) for c in ciks}})
    print("run %s: funds %s; base %s; batch %s; caps run $%.0f fund $%.0f" % (
        run.meta["run_id"], ", ".join(ciks), run.meta["base_commit"][:8], run.meta["batch"], run.meta["run_cap"], run.meta["fund_cap"]))

    from env_real import RealEnv
    env = RealEnv(dry_run=args.dry_run)
    if args.dry_run:
        import worktree as wt
        for cik in ciks:
            fs = run.load_fund(cik)
            info = env.prepare(run, fs)
            if info.get("skip"):
                print("  %s: would skip: %s" % (cik, info["skip"]))
                continue
            fs.worktree, fs.branch, fs.before = info["worktree"], info["branch"], info.get("before")
            env.new_round(run, fs)
            render_prompts(run, cik, fs)
            print("  %s: %d findings; before %s; worktree ok; prompts in %s" % (cik, info["findings"], fs.before, run.round_dir(cik, 1)))
            wt.remove(Path(fs.worktree))
            subprocess.run(["git", "branch", "-D", fs.branch], cwd=REPO, capture_output=True)
        print("dry run done: no agent called, nothing recorded, worktrees removed")
        return 0

    if not load_key():
        print("no ANTHROPIC_API_KEY in the environment or .env")
        return 2
    from agents import SdkRunner
    from driver import Driver
    budget = Budget(run, run.meta["run_cap"], run.meta["fund_cap"], AGENT_CAP_USD)
    summary = Driver(run, SdkRunner(), env, budget, today=run.meta["today"]).run_all(ciks, observations=run.meta.get("observations", False))
    print(json.dumps(summary, indent=1, default=str))
    print("Nothing merged. Owner questions: %s. Passing every check is not data correct." % (run.folder / "owner_questions.md"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
