"""Guarded launcher: pilot pytest runs, the semantic-diff backstop, freezing, lease probe.

    python -m scripts.profile_pilot.verify test --main-root M --data-root D --run-id R tests/test_profile_pilot_paths.py ...
    python -m scripts.profile_pilot.verify freeze --main-root M --data-root D --run-id R
    python -m scripts.profile_pilot.verify measure-inventory --main-root M --data-root D --run-id R

    python -m scripts.profile_pilot.verify lease-check --main-root M --data-root D --run-id R

Every command writes only under <data_root>/pilot/filer_profile/<run_id>/ (lease-check
also makes the two permitted coordination writes: heavy.lock and the pseudo-candidate).
Exit codes: 0 ok, 1 tests failed, 3 preservation failed, 4 refused (busy/lease).

Lease exemption (controller ruling R9, deliberate): the launcher's pytest run and the
read-only semantic backstop do NOT take the shared programme lease. They are guarded
by the launcher's process check instead, which refuses to start when any
pytest/rebuild_outputs.py/pipeline.programme.bootstrap process exists or when process
discovery fails. Also deliberate: the string "pytest" is kept out of the backstop's
command line (its report path travels in PROFILE_PILOT_BACKSTOP_REPORT), because
heavy_lock treats any python command line containing "pytest" as a heavy job, and a
~13-minute read-only backstop must not block the programme controller's lease.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

from scripts.profile_pilot import protection
from scripts.profile_pilot.paths import (PathError, confined, default_run_id, discover_main_root,
                                         resolve_paths, write_json, write_once_json)

CODE_ROOT = Path(__file__).resolve().parents[2]
EXIT_TESTS_FAILED = 1
EXIT_PRESERVATION_FAILED = 3
EXIT_REFUSED = 4
EXIT_LEASE_REFUSED = 4
TEST_TARGET = re.compile(r"tests/test_profile_pilot_[a-z0-9_]+\.py(::[A-Za-z0-9_\[\]-]+)?")
BACKSTOP_TIMEOUT = 3600
PYTEST_TIMEOUT = 1800


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _ascii(text: str) -> str:
    return text.encode("ascii", "backslashreplace").decode("ascii")


def plugin_env(paths, receipt) -> dict:
    return {"PROFILE_PILOT_MAIN_ROOT": str(paths.main_repo_root),
            "PROFILE_PILOT_DATA_ROOT": str(paths.data_root),
            "PROFILE_PILOT_CODE_ROOT": str(paths.code_root),
            "PROFILE_PILOT_RECEIPT": str(receipt)}


def validate_test_targets(targets) -> list[str]:
    targets = [t.replace("\\", "/") for t in targets]
    if not targets or not all(TEST_TARGET.fullmatch(t) for t in targets):
        raise SystemExit("launcher runs only tests/test_profile_pilot_*.py targets, got "
                         + repr(targets))
    return targets


def _write_text(paths, relative: str, text: str) -> Path:
    target = confined(paths, relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="ascii", newline="\n") as stream:
        stream.write(_ascii(text))
    return target


# ---------------------------------------------------------------- semantic-diff backstop

def run_backstop(paths, relative_dir: str, *, label: str) -> dict:
    """Existing diff script, read-only, cwd = main root; logs under the run root."""
    report = confined(paths, relative_dir + "/" + label + "_semantic_diff_report.json")
    report.parent.mkdir(parents=True, exist_ok=True)
    # The report path travels in the environment: heavy_lock treats any python command
    # line containing "pytest" as a heavy job, and a ten-minute backstop must never
    # block the programme controller's lease (temporary test paths contain "pytest").
    command = [sys.executable, str(paths.code_root / "scripts" / "profile_pilot" / "backstop_shim.py")]
    if any("pytest" in part for part in command):
        raise PathError("backstop command line must not contain 'pytest'")
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="ascii:backslashreplace",
               PROFILE_PILOT_BACKSTOP_REPORT=str(report))
    started = time.perf_counter()
    try:
        done = subprocess.run(command, cwd=paths.main_repo_root, env=env, capture_output=True,
                              text=True, encoding="ascii", errors="backslashreplace",
                              timeout=BACKSTOP_TIMEOUT)
        exit_code, stdout, stderr = done.returncode, done.stdout, done.stderr
    except subprocess.TimeoutExpired as exc:
        exit_code, stdout, stderr = None, str(exc.stdout or ""), "timeout after %ss" % BACKSTOP_TIMEOUT
    seconds = round(time.perf_counter() - started, 1)
    out = _write_text(paths, relative_dir + "/" + label + "_backstop_stdout.txt", stdout)
    err = _write_text(paths, relative_dir + "/" + label + "_backstop_stderr.txt", stderr)
    lines = stdout.splitlines()
    at = next((i for i, line in enumerate(lines)
               if line.startswith(("Diff clean", "Diff failed", "Missing manifest"))), None)
    summary = None if at is None else lines[at]
    # Semantic lines ("- holdings: N semantic delta row(s)") precede the summary line;
    # divergent-artifact lines ("- <path>: differs ...") follow it.
    semantic = [line[2:] for line in lines[:at or 0] if line.startswith("- ")]
    differences = sorted({line[2:].split(": ", 1)[0] for line in lines[(at or 0) + 1:]
                          if at is not None and line.startswith("- ")})
    count = None
    if summary and summary.startswith("Diff failed"):
        count = int(summary.split()[2])
    inspection_ok = exit_code in (0, 1) and summary is not None and not summary.startswith("Missing")
    return dict(label=label, logical_command="python scripts/diff_outputs.py --semantic",
                command=command + ["--semantic"], cwd=str(paths.main_repo_root),
                exit_code=exit_code, seconds=seconds, summary=summary,
                divergent_count=count if count is not None else (0 if exit_code == 0 else None),
                baseline_differences=differences, semantic_summary=semantic,
                inspection_ok=inspection_ok,
                report_path=str(report), stdout_path=str(out), stderr_path=str(err),
                baseline_refreshed=False)


def backstop_verdict(pre, post) -> dict:
    """Baseline divergence is reported separately; only NEW divergence fails preservation."""
    if post is None or not post["inspection_ok"]:
        return dict(ok=False, reason="backstop inspection failed",
                    preexisting_baseline_differences=[], new_differences=[])
    if pre is None:
        return dict(ok=True, reason="no pre-run backstop; differences unattributed",
                    preexisting_baseline_differences=[], new_differences=[],
                    unattributed_differences=post["baseline_differences"])
    if not pre["inspection_ok"]:
        return dict(ok=False, reason="pre-run backstop inspection failed",
                    preexisting_baseline_differences=[], new_differences=[])
    new = sorted(set(post["baseline_differences"]) - set(pre["baseline_differences"]))
    grew = (post["divergent_count"] or 0) > (pre["divergent_count"] or 0)
    return dict(ok=not new and not grew,
                reason="new baseline divergence during the run" if (new or grew) else "unchanged",
                preexisting_baseline_differences=sorted(pre["baseline_differences"]),
                preexisting_divergent_count=pre["divergent_count"], new_differences=new,
                divergent_count_grew=grew)


# ---------------------------------------------------------------- commands

def _paths(args):
    main = args.main_root or discover_main_root(CODE_ROOT)
    return resolve_paths(main_repo_root=main, data_root=args.data_root,
                         code_root=args.code_root or CODE_ROOT, run_id=args.run_id)


def cmd_test(args) -> int:
    paths = _paths(args)
    targets = validate_test_targets(args.targets)
    folder = "verification/" + _stamp() + "_tests"  # never "pytest": heavy_lock greps cmdlines
    started = datetime.now(timezone.utc).isoformat()
    try:
        conflicts = protection.process_conflicts()
    except Exception as exc:  # discovery failure is a refusal, never an empty list
        write_json(paths, folder + "/refused.json", dict(reason="process discovery failed: "
                                                          + protection.format_exception(exc)))
        print("REFUSED: process discovery failed")
        return EXIT_REFUSED
    if conflicts:
        write_json(paths, folder + "/refused.json", dict(reason="other heavy jobs", conflicts=conflicts))
        print("REFUSED: other pytest/rebuild processes: " + _ascii(json.dumps(conflicts)))
        return EXIT_REFUSED
    specs = protection.root_specs(paths)
    before = protection.inventory(specs)
    pre = None if args.no_pre_backstop else run_backstop(paths, folder, label="pre")
    receipt = confined(paths, folder + "/plugin_receipt.json")
    command = [sys.executable, "-m", "pytest", "-p", "scripts.profile_pilot.pytest_plugin",
               "-p", "no:cacheprovider", "-q", "-rs", "--durations=10", *targets]
    env = dict(os.environ, **plugin_env(paths, receipt))
    t0 = time.perf_counter()
    try:
        done = subprocess.run(command, cwd=paths.code_root, env=env, capture_output=True, text=True,
                              encoding="ascii", errors="backslashreplace", timeout=PYTEST_TIMEOUT)
    except subprocess.TimeoutExpired as exc:  # still take the after-inventory and backstop
        done = subprocess.CompletedProcess(command, None, str(exc.stdout or ""),
                                           "timeout after %ss" % PYTEST_TIMEOUT)
    pytest_seconds = round(time.perf_counter() - t0, 1)
    _write_text(paths, folder + "/pytest_stdout.txt", done.stdout)
    _write_text(paths, folder + "/pytest_stderr.txt", done.stderr)
    post = run_backstop(paths, folder, label="post")
    after = protection.inventory(specs)
    comparison = protection.compare(before, after)
    plugin = json.loads(receipt.read_text(encoding="ascii")) if receipt.is_file() else None
    backstop = backstop_verdict(pre, post)
    preservation_ok = (comparison["ok"] and plugin is not None and plugin.get("verdict") == "PASS"
                       and backstop["ok"])
    tail = [line for line in done.stdout.splitlines() if line.strip()][-1:] or [""]
    body = dict(run_id=paths.run_id, started_utc=started,
                finished_utc=datetime.now(timezone.utc).isoformat(),
                pytest=dict(command=command, cwd=str(paths.code_root), exit_code=done.returncode,
                            seconds=pytest_seconds, summary=tail[0]),
                plugin_receipt=str(receipt), plugin_verdict=plugin and plugin.get("verdict"),
                launcher_inventory=protection.summarize(before, after, comparison),
                protected_roots=[str(r) for r in paths.protected_roots],
                backstop_pre=pre, backstop_post=post, backstop_verdict=backstop,
                preservation="PASS" if preservation_ok else "FAIL")
    target = write_json(paths, folder + "/receipt.json", body)
    print("pytest: exit " + str(done.returncode) + " | " + _ascii(tail[0]))
    print("plugin: " + str(body["plugin_verdict"]) + " | launcher inventory: "
          + ("PASS" if comparison["ok"] else "FAIL") + " (" + str(after["file_count"]) + " entries, "
          + str(after["seconds"]) + " s)")
    print("backstop: exit " + str(post["exit_code"]) + " | " + _ascii(str(post["summary"]))
          + " | verdict " + backstop["reason"])
    print("preservation: " + body["preservation"] + " | receipt " + str(target))
    if not preservation_ok:
        return EXIT_PRESERVATION_FAILED
    return 0 if done.returncode == 0 else EXIT_TESTS_FAILED


def _materialise_slices(paths) -> list[dict]:
    """Pinned 8-CIK slices of the holdings CSVs (ruling R3: light DuckDB reads)."""
    import duckdb
    from scripts.profile_pilot import cohort, manifest
    out = []
    for name in ("bdc_holdings", "private_markets_holdings"):
        source = paths.output_root / (name + ".csv")
        before = manifest.file_record(source, "output/" + name + ".csv")
        target = confined(paths, "inputs/" + name + "_pilot8.parquet")
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise PathError("refusing to overwrite frozen slice: " + str(target))
        con = duckdb.connect(config={"threads": 2, "memory_limit": "2GB"})
        try:
            con.execute("COPY (SELECT * FROM read_csv(?, all_varchar=true, header=true) "
                        "WHERE lpad(cik, 10, '0') IN (SELECT unnest(?))) TO '"
                        + target.as_posix().replace("'", "''") + "' (FORMAT parquet)",
                        [str(source), list(cohort.PILOT_CIKS)])
            rows = con.execute("SELECT lpad(cik, 10, '0'), count(*) FROM read_parquet(?) "
                               "GROUP BY 1 ORDER BY 1", [str(target)]).fetchall()
        finally:
            con.close()
        manifest.assert_inputs_unchanged([before], "while slicing " + name)
        record = manifest.file_record(target, "run/inputs/" + name + "_pilot8.parquet")
        record.update(source=before, rows_by_cik={c: n for c, n in rows})
        out.append(record)
    return out


def cmd_freeze(args) -> int:
    from scripts.profile_pilot import cohort, manifest
    paths = _paths(args)
    stamp = _stamp()
    with protection.protected_session(paths, receipt="verification/" + stamp + "_freeze_preservation.json"):
        t0 = time.perf_counter()
        primary = cohort.primary_quarter_inventory(paths)
        manifest.freeze_inventory(paths, "primary_quarter_inventory", primary)
        manifest.freeze_inventory(paths, "wrapper_key_inventory",
                                  manifest.wrapper_key_inventory(paths.code_root))
        built = manifest.build_manifest(paths, primary_inventory=primary)
        built["materialised"] = (manifest.materialise_verified_era_wrappers(paths, built["verified_era"])
                                 + _materialise_slices(paths))
        built["inventories"] = manifest.inventory_states(paths)
        built["input_verification"] = manifest.verify_inputs(built)
        built["frozen_utc"] = datetime.now(timezone.utc).isoformat()
        built["seconds"] = round(time.perf_counter() - t0, 1)
        target = write_once_json(paths, "manifest.json", built)
    print("manifest: " + str(target))
    print("primary quarters: " + json.dumps(primary["counts"], sort_keys=True))
    print("input verification ok: " + str(built["input_verification"]["ok"]))
    return 0 if built["input_verification"]["ok"] else EXIT_PRESERVATION_FAILED


def cmd_measure_inventory(args) -> int:
    paths = _paths(args)
    full = [protection.RootSpec(r, "full") for r in paths.protected_roots]
    measured = {}
    for spec in full + protection.root_specs(paths):
        listing = protection.inventory([spec])
        measured.setdefault(str(spec.path), {})[spec.mode] = dict(
            entries=listing["file_count"], seconds=listing["seconds"], errors=len(listing["errors"]))
    target = write_json(paths, "verification/" + _stamp() + "_inventory_measurement.json",
                        dict(measured=measured, boundary=protection.MAIN_OUTPUT_MODE))
    print(_ascii(json.dumps(measured, indent=1, sort_keys=True)))
    print("written: " + str(target))
    return 0


def cmd_lease_probe(args) -> int:
    """Child-process probe: try the real lease with real psutil against the given roots."""
    main = os.environ["PROFILE_PILOT_PROBE_MAIN_ROOT"]
    data = os.environ["PROFILE_PILOT_PROBE_DATA_ROOT"]
    paths = resolve_paths(main_repo_root=main, data_root=data, code_root=CODE_ROOT,
                          run_id="probe-" + str(os.getpid()))
    try:
        with protection.shared_heavy_lease(paths, head="probe"):
            print(json.dumps(dict(status="acquired")))
            return 0
    except protection.LeaseRefused as exc:
        print(json.dumps(dict(status="refused", reason=_ascii(str(exc)))))
        return EXIT_LEASE_REFUSED


def cmd_lease_check(args) -> int:
    """Acquire and release the REAL shared lease once; record the coordination path."""
    from scripts.profile_pilot import manifest
    paths = _paths(args)
    relative = "verification/" + _stamp() + "_lease_check.json"
    candidates_dir = paths.main_repo_root / "data" / "programme" / "candidates"
    lock_path = paths.main_repo_root / "data" / "programme" / "heavy.lock"
    head = manifest.git_head(paths.code_root)
    body = dict(run_id=paths.run_id, main_repo_root=str(paths.main_repo_root), git_head=head,
                expected_candidate=str(candidates_dir / paths.candidate_name),
                expected_lock=str(lock_path), lock_present_before=lock_path.exists())
    status = 0
    with protection.protected_session(paths, receipt=relative.replace(".json", "_preservation.json")):
        try:
            with protection.shared_heavy_lease(paths, head=head) as lease:
                body.update(status="acquired", acquired_utc=lease.acquired_utc,
                            candidate=str(lease.candidate), lock_path=str(lease.lock_path),
                            heavy_lock_contents=json.loads(lease.lock_path.read_text(encoding="utf-8")),
                            candidate_entries=sorted(p.name for p in lease.candidate.iterdir()),
                            pilot_json=json.loads((lease.candidate / "pilot.json").read_text(encoding="ascii")))
                protection.assert_lease_held(lease)
            body["released_utc"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except protection.LeaseRefused as exc:
            body.update(status="refused", reason=_ascii(str(exc)))
            status = EXIT_LEASE_REFUSED
    body.update(lock_present_after=lock_path.exists(),
                pilot_candidates_after=sorted(p.name for p in candidates_dir.glob("pilot-filer-profile-*")))
    target = write_json(paths, relative, body)
    print("lease-check: " + body["status"] + " | lock after: " + str(body["lock_present_after"])
          + " | pilot candidates after: " + str(body["pilot_candidates_after"]))
    print("receipt: " + str(target))
    ours_left = False
    if lock_path.exists():  # another controller may legitimately hold it now; ours must not
        try:
            ours_left = json.loads(lock_path.read_text(encoding="utf-8")).get("controller_pid") == os.getpid()
        except (OSError, ValueError):
            ours_left = True
    if ours_left or paths.candidate_name in body["pilot_candidates_after"]:
        return EXIT_PRESERVATION_FAILED
    return status


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="ascii", errors="backslashreplace")
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("test", "freeze", "measure-inventory", "lease-check"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--main-root", type=Path, default=None,
                         help="main checkout; default = git common dir of the code root (validated)")
        cmd.add_argument("--data-root", type=Path, required=True)
        cmd.add_argument("--code-root", type=Path, default=None)
        cmd.add_argument("--run-id", default=None)
        if name == "test":
            cmd.add_argument("--no-pre-backstop", action="store_true")
            cmd.add_argument("targets", nargs="*")
    sub.add_parser("lease-probe")
    args = parser.parse_args(argv)
    if args.command == "lease-probe":
        return cmd_lease_probe(args)
    args.run_id = args.run_id or default_run_id()
    try:
        return {"test": cmd_test, "freeze": cmd_freeze,
                "measure-inventory": cmd_measure_inventory,
                "lease-check": cmd_lease_check}[args.command](args)
    except PathError as exc:
        print("PATH ERROR: " + _ascii(str(exc)))
        return EXIT_REFUSED


if __name__ == "__main__":
    raise SystemExit(main())
