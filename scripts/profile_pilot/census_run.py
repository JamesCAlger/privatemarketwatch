"""Task 4 stage runner: census each frozen fund-quarter through manifest.run_cached_stage.

Heavy work (Ares/BCRED instances, estimates above 60 s / 2 GiB) runs only inside
protection.shared_heavy_lease; a refused lease stops the heavy work and is reported
as `lease_refused`. Incomplete collections are never cached; their receipts go to
census_failures/.

    python -m scripts.profile_pilot.census_run run --data-root D --run-id stageb-... [--scope light|heavy|all]
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import time

from scripts.profile_pilot.census import (CENSUS_VERSION, Bounds, CensusIncomplete, _ascii,
                                          build_census, validate_census)

LARGE = ("0001287750", "0001803498")
CODE_DEPENDENCIES = ("scripts/profile_pilot/census.py", "scripts/profile_pilot/census_collect.py",
                     "scripts/profile_pilot/census_detect.py", "scripts/profile_pilot/census_run.py",
                     "scripts/profile_pilot/schemas/census_v0.schema.json",
                     "pipeline/bdc_filings.py", "pipeline/context_inventory.py",
                     "pipeline/explicit_contexts.py", "pipeline/monetary_units.py")


class CensusInvalid(RuntimeError):
    """A complete collection whose document fails schema or semantic validation."""


def estimate(source_bytes: int) -> tuple[float, int]:
    """Conservative wall/peak-memory estimate for one instance (calibrated in the report)."""
    return 5.0 + source_bytes / 1_500_000, 400_000_000 + 20 * source_bytes


def _wrapper_markers(paths, cik: str, role: str) -> dict | None:
    from scripts.profile_pilot.manifest import file_record
    if role == "verified_era":
        path = paths.run_root / "inputs" / "verified_era_wrappers" / (cik + ".json")
    else:
        path = paths.code_root / "data" / "overrides" / "bdc_xbrl_wrappers" / (cik + ".json")
    record = file_record(path, "wrapper/" + cik + "/" + role)
    if record["status"] != "present":
        return None
    body = json.loads(path.read_text(encoding="utf-8"))
    markers = [str(m).lower() for m in (body.get("dispatch", {}) or {}).get("aggregate_markers", []) or []]
    return dict(markers=markers, path=str(path), sha256=record["sha256"], record=record)


class _PeakMemory:
    """Sample this process's RSS while the census runs (lxml memory is not in tracemalloc)."""

    def __init__(self, interval: float = 0.05):
        import threading
        import psutil
        self.process = psutil.Process()
        self.interval = interval
        self.start_rss = self.process.memory_info().rss
        self.peak = self.start_rss
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        while not self._stop.wait(self.interval):
            self.peak = max(self.peak, self.process.memory_info().rss)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join()
        self.peak = max(self.peak, self.process.memory_info().rss)
        return False


def census_fund_quarter(paths, entry: dict, *, lease_factory, bounds: Bounds = Bounds(),
                        refuse_heavy: str | None = None) -> dict:
    """One fund-quarter through manifest.run_cached_stage (heavy work only under the lease).

    `refuse_heavy` (set after a refusal earlier in the run) reports a heavy item as
    `lease_refused` without touching the lease again: a refusal is never retried.
    """
    from scripts.profile_pilot import manifest
    from scripts.profile_pilot.paths import PathError
    from scripts.profile_pilot.protection import LeaseRefused
    base = dict(cik=entry["cik"], report_date=entry["quarter"], role=entry.get("role"),
                accession_number=entry.get("accession_number"))
    if entry.get("status") != "selected":
        return dict(base, status="unavailable", reason=entry.get("reason"))
    source = Path(entry["source_path"])
    source_record = manifest.file_record(source, "xml/" + entry["cik"] + "/" + entry["accession_number"])
    if source_record["status"] != "present":
        return dict(base, status="unavailable", reason="source_not_cached")
    markers = _wrapper_markers(paths, entry["cik"], entry.get("role") or "")
    deps = dict(source=source_record,
                code=[manifest.file_record(paths.code_root / rel, "code/" + rel) for rel in CODE_DEPENDENCIES],
                wrapper=markers["record"] if markers else dict(status="absent_no_wrapper"),
                bounds=asdict(bounds))
    identity = manifest.cache_identity("census", deps, collector_version=CENSUS_VERSION)
    est_seconds, est_bytes = estimate(source_record["bytes"])
    workload = dict(ciks=[entry["cik"]], instance_count=1, full_cache_scan=False, pipeline_cik_count=0,
                    est_seconds=est_seconds, est_bytes=est_bytes)
    relative = "census/" + entry["cik"] + "/" + entry["quarter"] + ".json"
    measured: dict = {}
    marker_input = None if markers is None else {k: markers[k] for k in ("markers", "path", "sha256")}

    def compute():
        started = time.perf_counter()
        with _PeakMemory() as memory:
            doc = build_census(source, dict(cik=entry["cik"], report_date=entry["quarter"],
                                            accession_number=entry["accession_number"],
                                            form_type=entry.get("form_type"), role=entry.get("role")),
                               bounds=bounds, aggregate_markers=marker_input)
        measured.update(wall_seconds=round(time.perf_counter() - started, 2),
                        peak_rss_bytes=memory.peak, start_rss_bytes=memory.start_rss)
        if doc["collection"]["state"] != "complete":
            raise CensusIncomplete(doc)
        report = validate_census(doc)
        if not report["ok"]:
            raise CensusInvalid("census failed validation: " + "; ".join(report["errors"][:5]))
        doc["measurement"] = dict(measured, estimate_seconds=est_seconds, estimate_bytes=est_bytes)
        return doc

    lease_state: dict = {}

    def lease():
        if lease_factory is None:
            raise LeaseRefused("no lease factory supplied")
        handle = lease_factory()
        return _RecordingLease(handle, lease_state)

    heavy = manifest.classify_workload(workload)
    if heavy and refuse_heavy:
        return dict(base, status="lease_refused", reason="not attempted: " + refuse_heavy, heavy=True,
                    lease=None)
    try:
        result = manifest.run_cached_stage(paths, relative, identity, compute, workload=workload,
                                           lease=lease if (heavy and lease_factory is not None) else None)
    except LeaseRefused as exc:
        return dict(base, status="lease_refused", reason=_ascii(str(exc)), heavy=heavy,
                    lease=lease_state or None)
    except CensusIncomplete as exc:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        receipt = "census_failures/" + entry["cik"] + "/" + entry["quarter"] + "-" + stamp + ".json"
        from scripts.profile_pilot.paths import write_json
        failed = exc.doc
        write_json(paths, receipt, dict(collection=failed["collection"], channels=failed["channels"],
                                        document=failed["document"], measured=measured))
        return dict(base, status="incomplete", reason=str(exc), receipt=receipt, heavy=heavy)
    except (PathError, manifest.StageInvalidated) as exc:
        return dict(base, status="stage_invalidated", reason=_ascii(str(exc)), heavy=heavy)
    except CensusInvalid as exc:
        return dict(base, status="validation_failed", reason=_ascii(str(exc))[:1000], heavy=heavy,
                    lease=lease_state or None)
    doc = result["result"]
    return dict(base, status="collected", cache=result["cache"], path=result["path"], heavy=heavy,
                lease=lease_state or None, measurement=doc.get("measurement"),
                channels={k: v["state"] for k, v in doc["channels"].items()},
                summary=doc["summary"])


class _RecordingLease:
    """Wrap shared_heavy_lease so the runner records acquire/release times and paths."""

    def __init__(self, manager, state: dict):
        self.manager, self.state = manager, state

    def __enter__(self):
        handle = self.manager.__enter__()
        self.state.update(candidate=str(handle.candidate), lock_path=str(handle.lock_path),
                          acquired_utc=handle.acquired_utc)
        return handle

    def __exit__(self, *exc):
        try:
            return self.manager.__exit__(*exc)
        finally:
            self.state["released_utc"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


LIGHT_SCOPE_CIKS = ("0001901037", "0001588272", "0001920453", "0001715933", "0001860424", "0001950803")


def run(paths, *, scope: str, bounds: Bounds = Bounds()) -> dict:
    """Census every frozen fund-quarter in scope; light first, then heavy under the lease."""
    from scripts.profile_pilot import manifest, protection
    inventory = manifest.load_inventory(paths, "primary_quarter_inventory")
    entries = inventory["fund_quarters"]
    light = [e for e in entries if e["cik"] in LIGHT_SCOPE_CIKS]
    heavy = [e for e in entries if e["cik"] in LARGE]
    ordered = (light if scope in ("light", "all") else []) + (heavy if scope in ("heavy", "all") else [])
    head = manifest.git_head(paths.code_root)
    results, stopped = [], None
    for entry in ordered:
        got = census_fund_quarter(paths, entry, bounds=bounds, refuse_heavy=stopped,
                                  lease_factory=lambda: protection.shared_heavy_lease(paths, head=head))
        results.append(got)
        print(_ascii("census " + got["cik"] + " " + got["report_date"] + " " + str(got.get("role"))
                     + ": " + got["status"] + (" (" + str(got.get("reason"))[:120] + ")"
                                                if got["status"] != "collected" else
                                                " cache=" + got["cache"] + " "
                                                + json.dumps(got.get("measurement")))), flush=True)
        if got["status"] == "lease_refused" and not stopped:
            stopped = "lease refused earlier in this run: " + str(got.get("reason"))[:200]
    counts: dict[str, int] = {}
    for item in results:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    return dict(run_id=paths.run_id, scope=scope, git_head=head, census_version=CENSUS_VERSION,
                counts=counts, results=results)


def main(argv=None) -> int:
    import argparse
    import sys
    from scripts.profile_pilot import protection
    from scripts.profile_pilot.paths import PathError, discover_main_root, resolve_paths, write_json
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="ascii", errors="backslashreplace")
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    cmd = sub.add_parser("run")
    cmd.add_argument("--main-root", type=Path, default=None)
    cmd.add_argument("--data-root", type=Path, required=True)
    cmd.add_argument("--run-id", required=True)
    cmd.add_argument("--scope", choices=("light", "heavy", "all"), default="light")
    args = parser.parse_args(argv)
    if not args.run_id.startswith("stageb-"):
        print("run id must start with stageb- (ruling R18)")
        return 4
    code_root = Path(__file__).resolve().parents[2]
    try:
        paths = resolve_paths(main_repo_root=args.main_root or discover_main_root(code_root),
                              data_root=args.data_root, code_root=code_root, run_id=args.run_id)
    except PathError as exc:
        print("PATH ERROR: " + _ascii(str(exc)))
        return 4
    try:
        conflicts = protection.process_conflicts()
    except Exception as exc:  # discovery failure is a refusal
        print("REFUSED: process discovery failed: " + _ascii(str(exc)))
        return 4
    if conflicts:
        print("REFUSED: other pytest/rebuild processes: " + _ascii(json.dumps(conflicts)))
        return 4
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    started = time.perf_counter()
    with protection.protected_session(paths, receipt="verification/" + stamp + "_census_"
                                      + args.scope + "_preservation.json"):
        summary = run(paths, scope=args.scope)
        summary["seconds"] = round(time.perf_counter() - started, 1)
        target = write_json(paths, "census/run_summary_" + args.scope + "_" + stamp + ".json", summary)
    print("summary: " + json.dumps(summary["counts"], sort_keys=True) + " | " + str(target))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
