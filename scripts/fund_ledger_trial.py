"""Fund sandbox: the real build and the real check stages for a few funds, ending in a ledger.

Creates ``scratch/fund_sandbox/<label>/output`` holding only the chosen funds' inputs, then runs
the production commands unchanged with ``PM_OUTPUT_DIR`` pointing at it:

    fund highlights -> fund financials -> unified rebuild -> oracle -> non-accrual -> validate
    -> provenance -> shadow -> queue -> ledger

So the ledger is produced by the same code as the official one, for those funds only. Verdicts
and promoted corrections are read from their production stores (read-only), so dispositions
already recorded carry over. The published ``data/output`` is snapshotted before and after; the
run fails if anything there changed.

Not the same as the official ledger in two respects: values computed across all funds (entity
ids, industry labels) come from the subset, and durable identities are allocated fresh.

    python scripts/fund_ledger_trial.py --label hps --ciks 0001838126
    python scripts/fund_ledger_trial.py --label hps --ciks 0001838126 --from oracle   # reuse the build
    python scripts/fund_ledger_trial.py --label hps --summary                         # print the ledger
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SANDBOX_ROOT = ROOT / "scratch" / "fund_sandbox"
PRODUCTION = ROOT / "data" / "output"
PAD = "lpad(regexp_replace(cast(cik AS VARCHAR),'[^0-9]','','g'),10,'0')"
# Rebuilt inside the sandbox, or meaningless there: never seeded.
NOT_SEEDED = ("private_markets_holdings", "position_matches", "position_id_edges", "position_returns",
              "position_pik_status", "position_match_residuals", "identity_registry", "identity_aliases",
              "cost_donor_audit", "provenance_ledger", "row_validation_issues", "pipeline.log",
              "quarter_acceptance", "pass_preflight")
SEEDED_DIRS = ("linkbase_analysis",)
RESOLVED = frozenset({"adjudicated_false_alarm", "remediated_promoted", "resolved_upstream",
                      "gone_unadjudicated"})
PY = sys.executable
STAGES = (
    ("highlights", [PY, "scripts/rebuild_outputs.py", "--highlights"]),
    ("financials", [PY, "scripts/rebuild_outputs.py", "--financials"]),
    ("rebuild", [PY, "scripts/rebuild_outputs.py", "--unified"]),
    ("oracle", [PY, "-m", "pipeline.oracle_runner"]),
    ("nonaccrual", [PY, "-m", "pipeline.extract_nonaccrual_flags"]),
    ("validate", [PY, "-m", "pipeline.main", "--validate"]),
    ("provenance", [PY, "-m", "pipeline.provenance_reverify", "--cohort"]),
    ("shadow", [PY, "scripts/shadow_validation_runner.py"]),
    ("queue", [PY, "-m", "pipeline.review_queue", "--emit-bdc-worklist"]),
    ("ledger", None),
)
STAGE_NAMES = tuple(name for name, _ in STAGES)


def _production_state() -> dict:
    """mtime and size of the published files a stage could plausibly overwrite."""
    state = {}
    for folder in (PRODUCTION, PRODUCTION / "shadow", PRODUCTION / "oracle", PRODUCTION / "review_queue",
                   PRODUCTION / "agent_b2", PRODUCTION / "provenance"):
        if not folder.is_dir():
            continue
        for path in folder.iterdir():
            if path.is_file():
                stat = path.stat()
                state[str(path.relative_to(PRODUCTION))] = (stat.st_mtime_ns, stat.st_size)
    return state


def seed(output: Path, ciks: list[str]) -> dict:
    """Copy the published inputs into the sandbox, cut down to the chosen funds where a file has a cik column."""
    import duckdb

    output.mkdir(parents=True, exist_ok=True)
    counts = Counter()
    con = duckdb.connect(config={"threads": 4, "memory_limit": "4GB"})
    con.execute("CREATE TEMP TABLE subset AS SELECT unnest(?) AS cik", [ciks])
    for path in sorted(PRODUCTION.iterdir()):
        if not path.is_file() or path.name.startswith(NOT_SEEDED) or path.name.startswith("."):
            continue
        target = output / path.name
        source = str(path).replace("\\", "/")
        dest = str(target).replace("\\", "/")
        reader = None
        if path.suffix == ".csv":
            reader = f"read_csv('{source}', header=true, all_varchar=true, sample_size=-1)"
        elif path.suffix == ".parquet":
            reader = f"read_parquet('{source}')"
        if reader is not None:
            try:
                columns = [r[0] for r in con.execute(f"DESCRIBE SELECT * FROM {reader}").fetchall()]
            except duckdb.Error:
                columns = []
            if "cik" in columns:
                fmt = "(HEADER, DELIMITER ',')" if path.suffix == ".csv" else "(FORMAT PARQUET)"
                con.execute(f"COPY (SELECT * FROM {reader} WHERE {PAD} IN (SELECT cik FROM subset)) TO '{dest}' {fmt}")
                counts["filtered"] += 1
                continue
        shutil.copy2(path, target)
        counts["copied"] += 1
    for name in SEEDED_DIRS:
        if (PRODUCTION / name).is_dir():
            shutil.copytree(PRODUCTION / name, output / name, dirs_exist_ok=True)
            counts["dirs"] += 1
    con.close()
    return dict(counts)


def run_stage(name: str, argv: list[str] | None, sandbox: Path, quarter: str | None) -> dict:
    output = sandbox / "output"
    logs = sandbox / "logs"
    logs.mkdir(exist_ok=True)
    if name == "ledger":
        argv = [PY, "scripts/findings_ledger.py", "--queue", str(output / "review_queue" / "review_queue.csv"),
                "--out", str(sandbox / "findings_ledger.csv")]
        if quarter:
            argv += ["--quarter", quarter]
    env = dict(os.environ, PM_OUTPUT_DIR=str(output), PYTHONIOENCODING="utf-8")
    t0 = time.time()
    with open(logs / (name + ".log"), "w", encoding="utf-8", errors="replace") as log:
        code = subprocess.run(argv, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT).returncode
    return dict(stage=name, exit=code, seconds=round(time.time() - t0, 1))


def summarize(sandbox: Path, ciks: list[str] | None, since: str) -> dict:
    csv.field_size_limit(10**9)
    with open(sandbox / "findings_ledger.csv", newline="", encoding="utf-8-sig") as fh:
        rows = [r for r in csv.DictReader(fh) if r["report_date"][:10] >= since
                and (not ciks or r["cik"].zfill(10) in ciks)]
    out = [r for r in rows if r["state"] not in RESOLVED]
    return dict(findings=len(rows), outstanding=len(out),
                by_fund=dict(Counter(r["cik"].zfill(10) for r in out)),
                by_state=dict(Counter(r["state"] for r in out)),
                by_rule=dict(Counter((r["engine"], r["rule_name"]) for r in out).most_common()),
                rows=out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--label", required=True)
    parser.add_argument("--ciks", nargs="*")
    parser.add_argument("--from", dest="start", choices=STAGE_NAMES, help="reuse the sandbox and resume here")
    parser.add_argument("--until", choices=STAGE_NAMES)
    parser.add_argument("--quarter", help="restrict the ledger to one report date")
    parser.add_argument("--since", default="2022-01-01")
    parser.add_argument("--summary", action="store_true", help="print the existing sandbox ledger and exit")
    args = parser.parse_args(argv)
    sandbox = SANDBOX_ROOT / args.label
    meta_file = sandbox / "run.json"
    if args.summary:
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        ciks = meta["ciks"]
    else:
        if not args.ciks and not args.start:
            parser.error("give --ciks (or --from to resume an existing sandbox)")
        ciks = (sorted({"".join(ch for ch in c if ch.isdigit()).zfill(10) for c in args.ciks}) if args.ciks
                else json.loads(meta_file.read_text(encoding="utf-8"))["ciks"])
        before = _production_state()
        meta = dict(label=args.label, ciks=ciks, stages=[])
        if not args.start:
            if sandbox.exists():
                shutil.rmtree(sandbox)
            t0 = time.time()
            meta["seed"] = seed(sandbox / "output", ciks)
            meta["seed_seconds"] = round(time.time() - t0, 1)
            print("seeded %s in %.0f s: %s" % (sandbox, meta["seed_seconds"], meta["seed"]), flush=True)
        else:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
            meta["stages"] = [s for s in meta.get("stages", [])
                              if STAGE_NAMES.index(s["stage"]) < STAGE_NAMES.index(args.start)]
        first = STAGE_NAMES.index(args.start) if args.start else 0
        last = STAGE_NAMES.index(args.until) if args.until else len(STAGES) - 1
        failed = None
        for name, command in STAGES[first:last + 1]:
            result = run_stage(name, command, sandbox, args.quarter)
            meta["stages"].append(result)
            meta_file.write_text(json.dumps(meta, indent=2), encoding="utf-8")
            print("  %-10s exit %d  %6.0f s" % (name, result["exit"], result["seconds"]), flush=True)
            if result["exit"] != 0 and not (name == "ledger" and result["exit"] == 1):  # 1 = findings remain
                failed = name
                break
        after = _production_state()
        touched = sorted(n for n in set(before) | set(after) if before.get(n) != after.get(n))
        if touched:
            raise RuntimeError("fund sandbox changed published files: " + ", ".join(touched[:20]))
        print("published files touched: none")
        if failed:
            print("STOPPED at stage %s; see %s" % (failed, sandbox / "logs" / (failed + ".log")))
            return 1
        if last < len(STAGES) - 1:
            return 0
    report = summarize(sandbox, ciks, args.since)
    print("ledger for %s since %s: %d findings, %d outstanding" % (
        ",".join(ciks), args.since, report["findings"], report["outstanding"]))
    print("  by fund : %s" % report["by_fund"])
    print("  by state: %s" % report["by_state"])
    print("  engine | rule | outstanding")
    for (engine, rule), n in report["by_rule"].items():
        print("     %s | %s | %d" % (engine, rule, n))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
