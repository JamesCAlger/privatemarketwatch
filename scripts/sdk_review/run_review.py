"""Run one SDK review agent over one fund's "needs agent review" findings.

    python scripts/sdk_review/run_review.py --cik 0001786108 --label <sandbox> --dry-run
    python scripts/sdk_review/run_review.py --cik 0001786108 --label <sandbox> [--model claude-opus-5-5]
        [--effort high] [--max-budget-usd 5] [--max-turns 150] [--subscription]

What it does:
  1. Packet: the fund's rows of docs/investigations/findings_status.csv with status
     needs_agent_review, joined with the current batch ledger (data/output/batches/latest.json).
  2. Runs the agent with its own system prompt (prompt.md), no project settings (so no
     CLAUDE.md/AGENTS.md), no shell, read-only evidence tools (tools.py) and a PreToolUse hook
     (guards.py) that confines writes to the run folder scratch/sdk_review/<cik>_<stamp>/.
  3. Checks the agent's verdicts.json with the decision store's own validation and the cached-page
     quote check, and logs cost to scratch/sdk_review/usage_log.csv.
It never records a decision: the orchestrator reviews the output and runs
    python scripts/decide.py append <run>/verdicts.json --actor <actor>
Billing: uses ANTHROPIC_API_KEY (API credits). --subscription uses the logged-in Claude account.
ASCII-only output.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import dataclasses
import datetime as dt
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from guards import check_call  # noqa: E402

STATUS_CSV = ROOT / "docs/investigations/findings_status.csv"
OUT_ROOT = ROOT / "scratch/sdk_review"
csv.field_size_limit(10**9)


def build_packet(cik10: str, run_dir: Path) -> tuple[Path, list[dict], str]:
    batch = json.loads((ROOT / "data/output/batches/latest.json").read_text(encoding="utf-8"))["batch_id"]
    with open(STATUS_CSV, newline="", encoding="utf-8-sig") as fh:
        rows = [r for r in csv.DictReader(fh) if r["cik"].zfill(10) == cik10 and r["status"] == "needs_agent_review"]
    ids = {r["review_id"] for r in rows}
    ledger = {}
    with open(ROOT / "data/output/batches" / batch / "findings_ledger.csv", newline="", encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            if r["review_id"] in ids:
                ledger[r["review_id"]] = r
    keep = ("state", "lane", "verdict_status", "verdict_detail", "fv_at_risk_m", "fund_quarter_fv_m", "population_origin")
    out = [dict(r, **{k: ledger.get(r["review_id"], {}).get(k, "") for k in keep}) for r in rows]
    path = run_dir / "packet.csv"
    if out:
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(out[0].keys()))
            w.writeheader()
            w.writerows(out)
    return path, out, batch


def render_prompt(**kw) -> str:
    return (Path(__file__).resolve().parent / "prompt.md").read_text(encoding="utf-8").format(**kw)


def validate_output(run_dir: Path, packet: list[dict], actor: str) -> dict:
    from pipeline import decision_store
    from scripts.decide import page_quote_ok
    path = run_dir / "verdicts.json"
    if not path.exists():
        return {"ok": False, "problems": ["no verdicts.json written"], "covered": 0, "missing": len(packet)}
    entries = json.loads(path.read_text(encoding="utf-8-sig"))
    entries = entries if isinstance(entries, list) else [entries]
    packet_ids = {r["review_id"] for r in packet}
    problems, covered, by_conclusion = [], set(), {}
    for n, e in enumerate(entries, 1):
        errs = decision_store.validate(e)
        if e.get("decided_by") != actor:
            errs.append("decided_by is not %s" % actor)
        for item in e.get("evidence", []) if isinstance(e.get("evidence"), list) else []:
            if item.get("source") == "filing" and not page_quote_ok(str(e.get("cik") or ""), item.get("accession", ""), item.get("quote", "")):
                errs.append("quote not on page: %s %r" % (item.get("accession"), str(item.get("quote"))[:60]))
        unknown = set(e.get("finding_ids", [])) - packet_ids
        if unknown:
            errs.append("finding ids not in the packet: %s" % sorted(unknown)[:3])
        covered |= set(e.get("finding_ids", [])) & packet_ids
        by_conclusion[e.get("conclusion")] = by_conclusion.get(e.get("conclusion"), 0) + len(e.get("finding_ids", []))
        if errs:
            problems.append("entry %d: %s" % (n, "; ".join(errs)))
    missing = sorted(packet_ids - covered)
    return {"ok": not problems and not missing, "entries": len(entries), "covered": len(covered),
            "missing": len(missing), "missing_ids": missing[:50], "by_conclusion": by_conclusion, "problems": problems}


def _jsonable(msg) -> dict:
    body = dataclasses.asdict(msg) if dataclasses.is_dataclass(msg) else {"repr": repr(msg)}
    return {"kind": type(msg).__name__, **body}


async def run_agent(args, cik10: str, run_dir: Path, prompt: str, actor: str) -> dict:
    from claude_agent_sdk import ClaudeAgentOptions, HookMatcher, ResultMessage, query
    from tools import build_server

    sql_dir = run_dir / "sql"
    sql_dir.mkdir(exist_ok=True)
    server, tool_names = build_server(cik10, args.label, sql_dir)

    async def guard(input_data, tool_use_id, context):
        reason = check_call(input_data.get("tool_name", ""), input_data.get("tool_input", {}) or {}, run_dir=run_dir)
        if reason:
            with open(run_dir / "refusals.log", "a", encoding="utf-8") as fh:
                fh.write("%s\t%s\n" % (input_data.get("tool_name"), reason))
            return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                           "permissionDecisionReason": reason}}
        return {}

    env = {}
    if not args.subscription:
        env["ANTHROPIC_API_KEY"] = os.environ["ANTHROPIC_API_KEY"]
    options = ClaudeAgentOptions(
        system_prompt=prompt,                        # our prompt only; not Claude Code's
        setting_sources=[],                          # load no settings: no CLAUDE.md / AGENTS.md / user hooks
                                                     # (None would let the CLI load all of them in SDK 0.2.x)
        tools=["Read", "Grep", "Glob", "Write"],     # the only built-in tools that exist for this agent
        allowed_tools=["Read", "Grep", "Glob", "Write"] + tool_names,
        disallowed_tools=["Bash", "PowerShell", "WebFetch", "WebSearch", "Task", "Agent", "Edit", "NotebookEdit"],
        mcp_servers={"evidence": server},
        hooks={"PreToolUse": [HookMatcher(matcher=None, hooks=[guard])]},
        permission_mode="default",
        cwd=str(ROOT),
        model=args.model,
        effort=args.effort,
        max_turns=args.max_turns,
        max_budget_usd=args.max_budget_usd,
        env=env,
    )
    result = None
    task = ("Review every finding in %s for CIK %s and write %s/verdicts.json as instructed."
            % ((run_dir / "packet.csv").as_posix(), cik10, run_dir.as_posix()))
    with open(run_dir / "transcript.jsonl", "w", encoding="utf-8") as log:
        async for msg in query(prompt=task, options=options):
            log.write(json.dumps(_jsonable(msg), default=str, ensure_ascii=True) + "\n")
            log.flush()
            if isinstance(msg, ResultMessage):
                result = msg
    if result is None:
        return {"error": "no result message"}
    return {"subtype": result.subtype, "is_error": result.is_error, "num_turns": result.num_turns,
            "total_cost_usd": result.total_cost_usd, "duration_s": round(result.duration_ms / 1000),
            "usage": result.usage, "summary": (result.result or "")[:2000]}


def log_usage(row: dict) -> None:
    path = OUT_ROOT / "usage_log.csv"
    new = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(row.keys()))
        if new:
            w.writeheader()
        w.writerow(row)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cik", required=True)
    ap.add_argument("--label", required=True, help="an existing sandbox for this fund (scratch/fund_sandbox/<label>)")
    ap.add_argument("--model", default="claude-opus-5-5")
    ap.add_argument("--effort", default="high", choices=["low", "medium", "high", "xhigh", "max"])
    ap.add_argument("--key-file", type=Path, default=Path.home() / ".anthropic_api_key",
                    help="file holding the API key, used when ANTHROPIC_API_KEY is not set")
    ap.add_argument("--max-budget-usd", type=float, default=5.0)
    ap.add_argument("--max-turns", type=int, default=150)
    ap.add_argument("--subscription", action="store_true", help="bill the logged-in Claude account, not API credits")
    ap.add_argument("--dry-run", action="store_true", help="build packet and prompt; no API call")
    args = ap.parse_args(argv)

    cik10 = args.cik.zfill(10)
    if not (ROOT / "scratch/fund_sandbox" / args.label / "findings_ledger.csv").exists():
        print("sandbox %s has no findings_ledger.csv" % args.label)
        return 2
    if not args.dry_run and not args.subscription and not os.environ.get("ANTHROPIC_API_KEY"):
        dotenv = ROOT / ".env"
        if dotenv.exists():
            for line in dotenv.read_text(encoding="utf-8-sig").splitlines():
                if line.strip().startswith("ANTHROPIC_API_KEY="):
                    os.environ["ANTHROPIC_API_KEY"] = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not args.dry_run and not args.subscription and not os.environ.get("ANTHROPIC_API_KEY"):
        if args.key_file.exists():
            os.environ["ANTHROPIC_API_KEY"] = args.key_file.read_text(encoding="utf-8").strip()
        else:
            print("No API key: set ANTHROPIC_API_KEY, put the key in %s, or pass --subscription." % args.key_file)
            return 2
    stamp = dt.datetime.now().strftime("%Y%m%dT%H%M%S")
    run_dir = OUT_ROOT / ("%s_%s" % (cik10, stamp))
    run_dir.mkdir(parents=True, exist_ok=True)
    actor = "agent:sdk-review-%s-%s" % (cik10[-6:], stamp)
    packet_path, packet, batch = build_packet(cik10, run_dir)
    print("batch %s: %d findings need agent review for %s; run folder %s" % (batch, len(packet), cik10, run_dir))
    if not packet:
        return 0
    prompt = render_prompt(cik=cik10, label=args.label, packet=packet_path.as_posix(), run_dir=run_dir.as_posix(),
                           actor=actor, today=dt.date.today().isoformat())
    (run_dir / "system_prompt.md").write_text(prompt, encoding="utf-8")
    if args.dry_run:
        print("dry run: wrote packet.csv and system_prompt.md; model %s, effort %s, budget $%.2f"
              % (args.model, args.effort, args.max_budget_usd))
        return 0

    outcome = asyncio.run(run_agent(args, cik10, run_dir, prompt, actor))
    check = validate_output(run_dir, packet, actor)
    (run_dir / "outcome.json").write_text(json.dumps({"run": outcome, "validation": check}, indent=2, default=str), encoding="utf-8")
    cost = outcome.get("total_cost_usd") or 0.0
    log_usage({"run": run_dir.name, "batch": batch, "cik": cik10, "model": args.model, "effort": args.effort,
               "findings": len(packet), "covered": check["covered"], "valid": check["ok"],
               "cost_usd": round(cost, 4), "cost_per_finding": round(cost / len(packet), 4),
               "turns": outcome.get("num_turns"), "duration_s": outcome.get("duration_s")})
    print("cost $%.2f ($%.3f per finding), %s turns; covered %d/%d; valid %s"
          % (cost, cost / len(packet), outcome.get("num_turns"), check["covered"], len(packet), check["ok"]))
    for p in check["problems"][:10]:
        print("  " + p)
    print("Nothing recorded. After review: python scripts/decide.py append %s --actor %s"
          % ((run_dir / "verdicts.json").as_posix(), actor))
    return 0 if check["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
