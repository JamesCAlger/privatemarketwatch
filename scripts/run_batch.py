"""One batch: every queued fix into one production build, then the ledger that build produces.

    python scripts/run_batch.py --batch-id b1112a --quarters 2026-06-30 2026-03-31
    python scripts/run_batch.py --batch-id b1112a --dry-run                # print the stages, run nothing
    python scripts/run_batch.py --batch-id r1 --output-dir scratch/fund_sandbox/nbgpe/output --from ledger
                                                                         # rehearsal on a fund sandbox

A batch is the only thing that produces finding status. Stages, in order (the 2026-11-10 fold-back
chain, then the check stages, then the ledger):

    extract fieldstatus highlights financials unified returns refresh frontend
    nonaccrual validate oracle provenance shadow queue
    ledger compare gate reattest

Run it on the owner's go only; about six hours from ``extract``; needs ~14 GB free for ``unified``.
No fund build, pytest or code edit in this checkout while it runs. It stops at the first failing
stage. Until the ``ledger`` and ``compare`` stages have both succeeded nothing under
``<output>/batches/latest.json`` changes, so a failed batch leaves the previous ledger current.
Every batch keeps its own folder ``<output>/batches/<batch_id>/`` (ledger CSV and Parquet,
comparison, gate verdicts, stage log, batch.json); nothing here deletes one.

``gate`` and ``reattest`` are recorded, not fatal: a failing gate is a result. ASCII-only output.
"""
from __future__ import annotations

import argparse
import csv
import datetime
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PY = sys.executable
# name, argv tail (after the interpreter), free GB needed, fatal on failure
BUILD_STAGES = (
    ("extract", ["scripts/rebuild_outputs.py", "--bdc-holdings", "--cohort"], 8, True),
    ("fieldstatus", ["scripts/refresh_ixbrl_field_status.py", "--published", "--ciks", "{cohort}"], 8, True),
    ("highlights", ["scripts/rebuild_outputs.py", "--highlights"], 8, True),
    ("financials", ["scripts/rebuild_outputs.py", "--financials"], 8, True),
    ("unified", ["scripts/rebuild_outputs.py", "--unified"], 14, True),
    ("returns", ["scripts/rebuild_outputs.py", "--returns"], 12, True),
    ("refresh", ["scripts/rebuild_outputs.py", "--derivatives", "--sector-breakdown", "--income",
                 "--pik-status", "--pik-proxy"], 8, True),
    ("frontend", ["scripts/rebuild_outputs.py", "--frontend"], 8, True),
    ("nonaccrual", ["-m", "pipeline.extract_nonaccrual_flags"], 8, True),
    ("validate", ["-m", "pipeline.main", "--validate"], 8, True),
    ("oracle", ["-m", "pipeline.oracle_runner"], 8, True),
    ("provenance", ["-m", "pipeline.provenance_reverify", "--cohort"], 8, True),
    ("shadow", ["scripts/shadow_validation_runner.py"], 8, True),
    ("queue", ["-m", "pipeline.review_queue", "--emit-bdc-worklist"], 8, True),
)
TAIL_STAGES = ("ledger", "compare", "gate", "reattest")
STAGE_NAMES = tuple(s[0] for s in BUILD_STAGES) + TAIL_STAGES


def free_gb() -> float | None:
    """Free physical memory in GB, or None when it cannot be read."""
    try:
        import ctypes

        class _Mem(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong),
                        ("total", ctypes.c_ulonglong), ("avail", ctypes.c_ulonglong),
                        ("total_page", ctypes.c_ulonglong), ("avail_page", ctypes.c_ulonglong),
                        ("total_virtual", ctypes.c_ulonglong), ("avail_virtual", ctypes.c_ulonglong),
                        ("avail_extended", ctypes.c_ulonglong)]
        mem = _Mem()
        mem.length = ctypes.sizeof(_Mem)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(mem)):
            return round(mem.avail / 2 ** 30, 1)
    except (AttributeError, OSError, ImportError):
        pass
    return None


def other_python_running() -> bool:
    """Another python.exe besides this one (Windows tasklist); False when it cannot be told."""
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq python.exe", "/FO", "CSV", "/NH"],
                             capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    pids = {line.split(",")[1].strip('"') for line in out.splitlines() if line.lower().startswith('"python')}
    return bool(pids - {str(os.getpid()), str(os.getppid())})


def cohort_ciks() -> list[str]:
    from pipeline.cohort_guard import load_cohort_ciks
    return sorted(str(c).zfill(10) for c in load_cohort_ciks())


def run_command(argv: list[str], *, log_path: Path, output_dir: Path) -> int:
    env = dict(os.environ, PM_OUTPUT_DIR=str(output_dir), PYTHONIOENCODING="utf-8")
    with open(log_path, "w", encoding="utf-8", errors="replace") as log:
        return subprocess.run(argv, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT).returncode


def _git_head() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True,
                              text=True, timeout=30).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def decisions_hash(directory: Path | None = None) -> str:
    from pipeline import decision_store
    directory = Path(directory) if directory is not None else decision_store.default_dir()
    digest = hashlib.sha256()
    for path in sorted(directory.glob("*.jsonl")) if directory.exists() else []:
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


def _read_csv(path: Path) -> list[dict]:
    csv.field_size_limit(10 ** 9)
    with open(path, newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def holdings_build_time(output_dir: Path) -> str:
    """When the holdings in ``output_dir`` were built (file time), '' when there are none."""
    for name in ("private_markets_holdings.parquet", "private_markets_holdings.csv"):
        path = Path(output_dir) / name
        if path.exists():
            return datetime.datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%dT%H:%M:%S")
    return ""


def latest(output_dir: Path) -> dict:
    pointer = Path(output_dir) / "batches" / "latest.json"
    return json.loads(pointer.read_text(encoding="utf-8")) if pointer.exists() else {}


def _ledger_stage(batch_dir: Path, output_dir: Path, build_time: str, run) -> int:
    validity = batch_dir / "disposition_validity.csv"
    checked = run([PY, "-m", "pipeline.disposition_validity", "--output-dir", str(output_dir), "--out", str(validity)],
                  log_path=batch_dir / "disposition_validity.log", output_dir=output_dir)
    argv = [PY, "scripts/findings_ledger.py", "--queue", str(output_dir / "review_queue" / "review_queue.csv"),
            "--out", str(batch_dir / "findings_ledger.csv"), "--build-time", build_time]
    if checked == 0 and validity.exists():
        argv += ["--validity", str(validity)]
    code = run(argv, log_path=batch_dir / "ledger.log", output_dir=output_dir)
    return 0 if code in (0, 1) else code  # 1 = findings remain, which is a result


def _compare_stage(batch_dir: Path, output_dir: Path, decisions_dir: Path | None) -> dict:
    from pipeline import batch_compare, decision_store
    current = _read_csv(batch_dir / "findings_ledger.csv")
    previous = latest(output_dir)
    prior_path = Path(output_dir) / "batches" / previous["batch_id"] / "findings_ledger.csv" if previous else None
    prior = _read_csv(prior_path) if prior_path and prior_path.exists() else []
    since = previous.get("build_time", "") if previous else ""
    fixes = [e for e in decision_store.standing(decision_store.load_native(decisions_dir))
             if e["type"] == "fix_record" and (not since or e.get("recorded_at", "") > since)]
    rows = batch_compare.compare(prior, current, fixes) if previous else []
    with open(batch_dir / "compare.csv", "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=batch_compare.COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    summary = batch_compare.summarize(rows)
    summary.update(previous_batch=previous.get("batch_id", ""), fix_records=len(fixes), first_batch=not previous)
    return summary


def _write_parquet(batch_dir: Path) -> bool:
    try:
        import duckdb
    except ImportError:
        return False
    source = (batch_dir / "findings_ledger.csv").as_posix()
    target = (batch_dir / "findings_ledger.parquet").as_posix()
    con = duckdb.connect()
    try:
        con.execute("COPY (SELECT * FROM read_csv('%s', header=true, all_varchar=true, sample_size=-1)) "
                    "TO '%s' (FORMAT PARQUET)" % (source, target))
    finally:
        con.close()
    return True


def run_batch(*, batch_id: str, output_dir: Path, quarters: list[str], start: str | None = None,
              until: str | None = None, skip: tuple[str, ...] = (), dry_run: bool = False,
              decisions_dir: Path | None = None, run=run_command, memory=free_gb,
              busy=other_python_running, cohort=cohort_ciks, say=print) -> int:
    output_dir = Path(output_dir)
    batch_dir = output_dir / "batches" / batch_id
    first = STAGE_NAMES.index(start) if start else 0
    last = STAGE_NAMES.index(until) if until else len(STAGE_NAMES) - 1
    wanted = [n for n in STAGE_NAMES[first:last + 1] if n not in skip]
    if dry_run:
        for name, tail, need, _fatal in BUILD_STAGES:
            if name in wanted:
                say("%-12s (needs %2d GB free) python %s" % (name, need, " ".join(tail)))
        for name in TAIL_STAGES:
            if name in wanted:
                say("%-12s -> %s" % (name, batch_dir))
        return 0
    if batch_dir.exists():
        say("refused: batch %s already exists (%s); a batch is never overwritten" % (batch_id, batch_dir))
        return 2
    if busy():
        say("refused: another Python process is running")
        return 3
    batch_dir.mkdir(parents=True)
    meta = {"batch_id": batch_id, "git": _git_head(), "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "output_dir": str(output_dir), "quarters": quarters, "from": start or STAGE_NAMES[0],
            "skipped": list(skip), "decisions_hash": decisions_hash(decisions_dir), "stages": []}

    def record(name, code, seconds, note=""):
        meta["stages"].append({"stage": name, "exit": code, "seconds": round(seconds, 1), "note": note})
        (batch_dir / "batch.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
        say("  %-12s exit %s  %6.0f s %s" % (name, code, seconds, note))

    def stop(name):
        say("STOPPED at %s; previous ledger stays current. Logs: %s" % (name, batch_dir))
        return 1

    cohort_list = None
    for name, tail, need, _fatal in BUILD_STAGES:
        if name not in wanted:
            continue
        have = memory()
        if have is not None and have < need:
            record(name, "not run", 0, "free %.1f GB < %d GB" % (have, need))
            return stop(name)
        if "{cohort}" in tail:
            cohort_list = cohort_list or cohort()
            tail = [t for t in tail if t != "{cohort}"] + cohort_list
        t0 = time.time()
        code = run([PY] + tail, log_path=batch_dir / (name + ".log"), output_dir=output_dir)
        record(name, code, time.time() - t0)
        if code != 0:
            return stop(name)
    build_time = holdings_build_time(output_dir)
    meta["build_time"] = build_time
    if "ledger" in wanted:
        t0 = time.time()
        code = _ledger_stage(batch_dir, output_dir, build_time, run)
        record("ledger", code, time.time() - t0)
        if code != 0 or not (batch_dir / "findings_ledger.csv").exists():
            return stop("ledger")
        meta["ledger_parquet"] = _write_parquet(batch_dir)
    if "compare" in wanted:
        if not (batch_dir / "findings_ledger.csv").exists():
            record("compare", "not run", 0, "no ledger in this batch")
            return stop("compare")
        t0 = time.time()
        meta["compare"] = _compare_stage(batch_dir, output_dir, decisions_dir)
        record("compare", 0, time.time() - t0, json.dumps(meta["compare"]["outcomes"], sort_keys=True))
        # Only now is this batch the current one.
        pointer = {"batch_id": batch_id, "build_time": build_time, "git": meta["git"],
                   "decisions_hash": meta["decisions_hash"], "finished": time.strftime("%Y-%m-%dT%H:%M:%S")}
        (output_dir / "batches" / "latest.json").write_text(json.dumps(pointer, indent=1), encoding="utf-8")
    if "gate" in wanted:
        for quarter in quarters:
            t0 = time.time()
            code = run([PY, "-m", "pipeline.quarter_acceptance", "--quarter", quarter,
                        "--findings-ledger", str(batch_dir / "findings_ledger.csv"),
                        "--out", str(batch_dir / ("acceptance_%s.json" % quarter)),
                        "--funds-out", str(batch_dir / ("acceptance_%s_funds.csv" % quarter))],
                       log_path=batch_dir / ("gate_%s.log" % quarter), output_dir=output_dir)
            record("gate " + quarter, code, time.time() - t0, "0 pass, 1 fail, 2 not assessable")
    if "reattest" in wanted:
        t0 = time.time()
        code = run([PY, "scripts/reattest_quarters.py", "check"], log_path=batch_dir / "reattest.log",
                   output_dir=output_dir)
        record("reattest", code, time.time() - t0, "non-zero is a regression of a signed-off quarter: read it")
    meta["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    (batch_dir / "batch.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    say("batch %s done: %s" % (batch_id, batch_dir))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--batch-id", required=True, help="short id, letters digits and underscore")
    parser.add_argument("--quarters", nargs="*", default=[], help="quarters the gate reads (YYYY-MM-DD)")
    parser.add_argument("--output-dir", type=Path, default=None, help="default: the production output dir")
    parser.add_argument("--from", dest="start", choices=STAGE_NAMES)
    parser.add_argument("--until", choices=STAGE_NAMES)
    parser.add_argument("--skip", nargs="*", default=[], choices=STAGE_NAMES)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if not args.batch_id.replace("_", "").isalnum():
        parser.error("--batch-id: letters, digits and underscore only")
    if args.output_dir is None:
        from pipeline import config
        args.output_dir = config.OUTPUT_DIR
    return run_batch(batch_id=args.batch_id, output_dir=args.output_dir.resolve(), quarters=args.quarters,
                     start=args.start, until=args.until, skip=tuple(args.skip), dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
