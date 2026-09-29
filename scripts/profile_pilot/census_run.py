"""Census stage runner (Tasks 4-5): census each frozen fund-quarter through manifest.run_cached_stage.

Heavy work (Ares/BCRED instances, estimates above 60 s / 2 GiB) runs only inside
protection.shared_heavy_lease; a refused lease stops the heavy work and is reported
as `lease_refused`.

Cache (ruling R15): the ONE cache is Task 1's `manifest.cache_identity` /
`run_cached_stage`. The identity holds the source file record, every code file record
plus their digest, the runtime library versions, the configuration dependencies (wrapper,
grammar, bounds) and the collector version. Layout (ruling R23): the authoritative result
is `census/{cik}/{report_date}.json`, write-once, exactly one census per fund-quarter per
run root; the cache fingerprint is recorded INSIDE that JSON and in the run summary. A
re-run inside the same run id whose identity differs (other bounds or dependencies) is
refused (StageInvalidated: use a new run id), so regeneration is proven across run ids,
never by a second result in one root and never by a silent reuse.
Only complete, validated, within-limit results are cached. Incomplete collections, failed
validations and limit breaches write a separate write-once receipt under census_failures/.

Performance (Task 5): each instance is measured (wall time; peak memory from the OS peak
working set, exact when this instance raised it, else an upper bound) and assessed against
LIMITS (60 s, 2 GiB). A breach or a bounded/incomplete collection is a failure to assess.

    python -m scripts.profile_pilot.census_run run --data-root D --run-id stageb-... [--scope light|heavy|all] [--only CIK:DATE]
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

from scripts.profile_pilot.census import (CENSUS_VERSION, Bounds, CensusIncomplete, _ascii,
                                          build_census, dumps_census, validate_census)
from scripts.profile_pilot.census_detect import DETECTOR_VERSION

LARGE = ("0001287750", "0001803498")
COLLECTOR_VERSION = CENSUS_VERSION + "+" + DETECTOR_VERSION
CODE_DEPENDENCIES = ("scripts/profile_pilot/census.py", "scripts/profile_pilot/census_collect.py",
                     "scripts/profile_pilot/census_detect.py", "scripts/profile_pilot/census_run.py",
                     "scripts/profile_pilot/envelope.py",
                     "scripts/profile_pilot/schemas/census_v0.schema.json",
                     "pipeline/bdc_filings.py", "pipeline/context_inventory.py",
                     "pipeline/explicit_contexts.py", "pipeline/monetary_units.py",
                     "pipeline/identifier_rate.py")
FINGERPRINT_CHARS = 16


@dataclass(frozen=True)
class PerformanceLimits:
    """Spec s10: census over a 1,000-position instance must finish in < 60 s and < 2 GiB."""
    max_wall_seconds: float = 60.0
    max_peak_bytes: int = 2 * 2 ** 30
    target_positions: int = 1000


LIMITS = PerformanceLimits()

# Calibration of the heavy/light estimate (Task 4 carry-forward: the old 5 s + bytes/1.5 MB,
# 400 MB + 20x model was an unfitted guess). Points are FULL-STAGE measurements (build +
# schema/semantic validation + serialisation) from the Task 5 calibration run: the Task 4
# numbers were build-only and missed validation, which is 75-85% of the stage (about 0.7 ms
# per fact). Seconds scale with facts, not bytes, so a byte model must carry the worst
# per-MB cost: the fit is 2 s + 2.0 s/MB, about 1.6x the largest observed 1.24 s/MB (Ares
# 2026-03-31); it is 5-7x conservative for byte-heavy, fact-light files (Stepstone
# 2026-03-31, 66 MB, is estimated heavy and so runs under the lease). Memory uses only
# `exact` points (the OS peak rose during that instance): 350 MB + 15 x bytes. The run
# summary records estimate vs measured per instance. The estimate only decides heaviness
# for CIKs outside the R3 list: Ares/BCRED are heavy by CIK whatever the estimate.
CALIBRATION = dict(
    source_run="stageb-20260928t235741z",
    model="seconds = seconds_base + seconds_per_source_mb * MB; bytes = bytes_base + bytes_per_source_byte * bytes",
    seconds_base=2.0, seconds_per_source_mb=2.0, bytes_base=350_000_000, bytes_per_source_byte=15,
    points=[dict(cik=c, report_date=d, source_bytes=b, wall_seconds=w, peak_bytes_upper=p, peak_exact=x)
            for c, d, b, w, p, x in (
        ("0001287750", "2022-09-30", 26804027, 12.82, 327196672, True),
        ("0001287750", "2026-03-31", 14005717, 17.305, 619499520, False),
        ("0001588272", "2023-09-30", 3344206, 1.221, 619499520, False),
        ("0001588272", "2023-12-31", 4032193, 1.286, 619499520, False),
        ("0001588272", "2026-03-31", 2647573, 0.815, 619499520, False),
        ("0001715933", "2023-03-31", 3783731, 1.375, 281202688, False),
        ("0001715933", "2023-06-30", 4199455, 1.423, 281202688, False),
        ("0001715933", "2026-03-31", 3971940, 1.712, 281202688, False),
        ("0001803498", "2022-09-30", 45476291, 11.237, 619499520, False),
        ("0001803498", "2022-12-31", 22165169, 12.267, 619499520, False),
        ("0001803498", "2026-03-31", 43793401, 25.432, 619499520, False),
        ("0001860424", "2023-06-30", 4133212, 1.301, 295026688, False),
        ("0001860424", "2023-09-30", 3848739, 1.368, 295026688, False),
        ("0001860424", "2026-03-31", 5000727, 1.731, 295026688, False),
        ("0001901037", "2022-09-30", 1530993, 1.522, 218877952, True),
        ("0001901037", "2022-12-31", 2273729, 0.839, 223784960, True),
        ("0001901037", "2026-03-31", 7907216, 5.917, 276492288, True),
        ("0001920453", "2023-03-31", 1238108, 0.312, 281202688, False),
        ("0001920453", "2023-06-30", 2290334, 0.56, 281202688, False),
        ("0001920453", "2026-03-31", 14060799, 5.086, 295026688, True),
        ("0001950803", "2023-09-30", 2928267, 1.171, 295026688, False),
        ("0001950803", "2023-12-31", 5024112, 2.091, 295026688, False),
        ("0001950803", "2026-03-31", 66454503, 19.786, 619499520, True))])

FAILURE_STATUSES = ("incomplete", "limit_exceeded", "validation_failed", "stage_invalidated",
                    "lease_refused")


class CensusInvalid(RuntimeError):
    """A complete collection whose document fails schema or semantic validation."""


class LimitExceeded(RuntimeError):
    """A complete census that breached the wall-time or peak-memory limit: not assessable."""

    def __init__(self, doc: dict, assessment: dict):
        super().__init__("performance limit exceeded: " + "; ".join(assessment["reasons"]))
        self.doc, self.assessment = doc, assessment


def estimate(source_bytes: int) -> tuple[float, int]:
    """Calibrated upper-envelope wall/peak estimate for one instance (see CALIBRATION)."""
    cal = CALIBRATION
    return (round(cal["seconds_base"] + cal["seconds_per_source_mb"] * source_bytes / 1_000_000, 2),
            int(cal["bytes_base"] + cal["bytes_per_source_byte"] * source_bytes))


def assess(measured: dict, limits: PerformanceLimits = None) -> dict:
    """Compare a measurement with the limits; the peak uses the upper bound (conservative)."""
    limits = limits or LIMITS
    reasons = []
    if measured["wall_seconds"] > limits.max_wall_seconds:
        reasons.append("wall %.2f s > %.0f s" % (measured["wall_seconds"], limits.max_wall_seconds))
    if measured["peak_bytes_upper"] > limits.max_peak_bytes:
        reasons.append("peak %d bytes > %d bytes" % (measured["peak_bytes_upper"], limits.max_peak_bytes))
    return dict(status="fail" if reasons else "pass", reasons=reasons, limits=asdict(limits),
                peak_basis="exact" if measured.get("peak_exact") else "upper_bound")


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


def _grammar(paths, cik: str) -> dict | None:
    """The authored identifier_rate_grammars file for this CIK (inherited), or None."""
    from scripts.profile_pilot.manifest import file_record
    path = paths.code_root / "data" / "overrides" / "identifier_rate_grammars" / (cik + ".json")
    record = file_record(path, "grammar/" + cik)
    if record["status"] != "present":
        return None
    return dict(path="data/overrides/identifier_rate_grammars/" + cik + ".json", sha256=record["sha256"],
                body=json.loads(path.read_text(encoding="utf-8")), record=record)


def runtime_versions() -> dict:
    from importlib import metadata
    from lxml import etree
    return dict(python=sys.version.split()[0], lxml=".".join(map(str, etree.LXML_VERSION)),
                libxml2=".".join(map(str, etree.LIBXML_VERSION)),
                jsonschema=metadata.version("jsonschema"))


class _PeakMemory:
    """Peak memory of this process while a block runs (lxml memory is not in tracemalloc).

    Primary: the OS peak working set (psutil `peak_wset`, Windows). When the block raises the
    process lifetime peak, that peak IS the block's peak (`peak_exact`); otherwise the block's
    peak lies between the sampled RSS and the lifetime peak, and the lifetime peak is used as
    the (conservative) upper bound. A 20 ms RSS sampler runs as a cross-check and fallback.
    """

    def __init__(self, interval: float = 0.02):
        import threading
        import psutil
        self.process = psutil.Process()
        self.interval = interval
        info = self.process.memory_info()
        self.start_rss = info.rss
        self.os_peak_before = getattr(info, "peak_wset", None)
        self.os_peak_after = None
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
        info = self.process.memory_info()
        self.peak = max(self.peak, info.rss)
        self.os_peak_after = getattr(info, "peak_wset", None)
        return False

    def result(self) -> dict:
        if self.os_peak_after is None:
            upper, exact, method = self.peak, False, "sampled_rss_only"
        else:
            exact = self.os_peak_after > self.os_peak_before
            upper, method = max(self.os_peak_after, self.peak), "os_peak_working_set"
        return dict(sampled_peak_rss_bytes=self.peak, start_rss_bytes=self.start_rss,
                    os_peak_wset_before=self.os_peak_before, os_peak_wset_after=self.os_peak_after,
                    peak_bytes_upper=upper, peak_exact=exact, peak_method=method)


def plan(paths, entry: dict, bounds: Bounds = Bounds()) -> dict:
    """The cache identity, storage path and workload of one fund-quarter (no computation)."""
    from scripts.profile_pilot import manifest
    source = Path(entry["source_path"])
    source_record = manifest.file_record(source, "xml/" + entry["cik"] + "/" + entry["accession_number"])
    if source_record["status"] != "present":
        return dict(status="source_not_cached", source=source)
    markers = _wrapper_markers(paths, entry["cik"], entry.get("role") or "")
    grammar = _grammar(paths, entry["cik"])
    code = [manifest.file_record(paths.code_root / rel, "code/" + rel) for rel in CODE_DEPENDENCIES]
    deps = dict(source=source_record, code=code,
                code_digest=manifest.digest([[r["label"], r.get("sha256")] for r in code]),
                runtime=runtime_versions(),
                wrapper=markers["record"] if markers else dict(status="absent_no_wrapper"),
                grammar=grammar["record"] if grammar else dict(status="absent_no_grammar"),
                bounds=asdict(bounds))
    identity = manifest.cache_identity("census", deps, collector_version=COLLECTOR_VERSION)
    est_seconds, est_bytes = estimate(source_record["bytes"])
    workload = dict(ciks=[entry["cik"]], instance_count=1, full_cache_scan=False, pipeline_cik_count=0,
                    est_seconds=est_seconds, est_bytes=est_bytes)
    fingerprint = identity["fingerprint"]
    relative = "census/" + entry["cik"] + "/" + entry["quarter"] + ".json"  # ruling R23: one per run root
    return dict(status="planned", source=source, source_record=source_record, markers=markers,
                grammar=grammar, identity=identity, fingerprint=fingerprint, relative=relative,
                workload=workload, estimate=dict(seconds=est_seconds, bytes=est_bytes))


def refuse_other_identity(paths, relative: str, fingerprint: str) -> None:
    """Ruling R23: a run root holds ONE result per fund-quarter at the constraint path.

    A different dependency identity inside the same run id is refused (never a second
    result beside it); regeneration happens in a new run id.
    """
    from scripts.profile_pilot import manifest
    from scripts.profile_pilot.paths import confined
    target = confined(paths, relative)
    if not target.is_file():
        return
    prior = json.loads(target.read_text(encoding="ascii")).get("identity", {}).get("fingerprint")
    if prior != fingerprint:
        raise manifest.StageInvalidated(
            relative + " already holds a result with dependency identity " + str(prior)[:16]
            + " (requested " + fingerprint[:16] + "); run roots are write-once: use a new run id")


def write_receipt(paths, kind: str, entry: dict, fingerprint: str | None, body: dict) -> str:
    """Write-once failure receipt, separate from cached results; never overwrites."""
    from scripts.profile_pilot.paths import PathError, write_once_json
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    base = (kind + "/" + entry["cik"] + "/" + entry["quarter"] + "/" + stamp + "-"
            + (fingerprint or "nofingerprint")[:FINGERPRINT_CHARS])
    for attempt in range(100):
        relative = base + ("" if attempt == 0 else "-" + str(attempt)) + ".json"
        try:
            write_once_json(paths, relative, dict(body, fingerprint=fingerprint, run_id=paths.run_id,
                                                  written_utc=stamp))
            return relative
        except PathError:
            continue
    raise RuntimeError("could not allocate a failure receipt name under " + base)


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
    planned = plan(paths, entry, bounds)
    if planned["status"] != "planned":
        return dict(base, status="unavailable", reason=planned["status"])
    identity, workload, fingerprint = planned["identity"], planned["workload"], planned["fingerprint"]
    markers, grammar, source = planned["markers"], planned["grammar"], planned["source"]
    est = planned["estimate"]
    measured: dict = {}
    marker_input = None if markers is None else {k: markers[k] for k in ("markers", "path", "sha256")}

    def compute():
        started = time.perf_counter()
        memory = _PeakMemory()
        try:
            with memory:
                doc = build_census(source, dict(cik=entry["cik"], report_date=entry["quarter"],
                                                accession_number=entry["accession_number"],
                                                form_type=entry.get("form_type"), role=entry.get("role")),
                                   bounds=bounds, aggregate_markers=marker_input,
                                   grammar=None if grammar is None else
                                   {k: grammar[k] for k in ("path", "sha256", "body")})
                measured["build_seconds"] = round(time.perf_counter() - started, 3)
                if doc["collection"]["state"] != "complete":
                    raise CensusIncomplete(doc)
                t_validate = time.perf_counter()
                report = validate_census(doc)
                measured["validate_seconds"] = round(time.perf_counter() - t_validate, 3)
                if not report["ok"]:
                    raise CensusInvalid("census failed validation: " + "; ".join(report["errors"][:5]))
                t_dump = time.perf_counter()
                measured["serialised_bytes"] = len(dumps_census(doc))
                measured["compact_bytes"] = len(json.dumps(doc, sort_keys=True, ensure_ascii=True,
                                                           separators=(",", ":"), allow_nan=False))
                measured["serialise_seconds"] = round(time.perf_counter() - t_dump, 3)
        finally:
            measured.update(wall_seconds=round(time.perf_counter() - started, 3), **memory.result(),
                            estimate_seconds=est["seconds"], estimate_bytes=est["bytes"])
        assessment = assess(measured)
        if assessment["status"] != "pass":
            raise LimitExceeded(doc, assessment)
        doc["measurement"] = dict(measured)
        doc["performance"] = assessment
        doc["cache_identity"] = dict(fingerprint=fingerprint, collector_version=COLLECTOR_VERSION,
                                     census_version=CENSUS_VERSION, detector_version=DETECTOR_VERSION)
        return doc

    lease_state: dict = {}

    def lease():
        if lease_factory is None:
            raise LeaseRefused("no lease factory supplied")
        return _RecordingLease(lease_factory(), lease_state)

    heavy = manifest.classify_workload(workload)
    if heavy and refuse_heavy:
        return dict(base, status="lease_refused", reason="not attempted: " + refuse_heavy, heavy=True,
                    lease=None, fingerprint=fingerprint)
    common = dict(base, heavy=heavy, fingerprint=fingerprint)
    refuse_other_identity(paths, planned["relative"], fingerprint)
    stage_started = time.perf_counter()
    try:
        result = manifest.run_cached_stage(paths, planned["relative"], identity, compute, workload=workload,
                                           lease=lease if (heavy and lease_factory is not None) else None)
    except LeaseRefused as exc:
        return dict(common, status="lease_refused", reason=_ascii(str(exc)), lease=lease_state or None)
    except CensusIncomplete as exc:
        failed = exc.doc
        receipt = write_receipt(paths, "census_failures", entry, fingerprint, dict(
            status="incomplete", reason=_ascii(str(exc))[:1000], collection=failed["collection"],
            channels=failed["channels"], document=failed["document"], measured=measured))
        return dict(common, status="incomplete", reason=_ascii(str(exc)), receipt=receipt,
                    measurement=dict(measured), lease=lease_state or None)
    except LimitExceeded as exc:
        receipt = write_receipt(paths, "census_failures", entry, fingerprint, dict(
            status="limit_exceeded", reason=_ascii(str(exc)), assessment=exc.assessment,
            collection=exc.doc["collection"], document=exc.doc["document"], summary=exc.doc["summary"],
            measured=measured))
        return dict(common, status="limit_exceeded", reason=_ascii(str(exc)), receipt=receipt,
                    measurement=dict(measured), performance=exc.assessment, lease=lease_state or None)
    except CensusInvalid as exc:
        receipt = write_receipt(paths, "census_failures", entry, fingerprint, dict(
            status="validation_failed", reason=_ascii(str(exc))[:2000], measured=measured))
        return dict(common, status="validation_failed", reason=_ascii(str(exc))[:1000], receipt=receipt,
                    lease=lease_state or None)
    except (PathError, manifest.StageInvalidated) as exc:
        return dict(common, status="stage_invalidated", reason=_ascii(str(exc)))
    doc = result["result"]
    measurement = dict(doc.get("measurement") or {}, stage_seconds=round(time.perf_counter() - stage_started, 3),
                       file_bytes=Path(result["path"]).stat().st_size)
    return dict(common, status="collected", cache=result["cache"], path=result["path"],
                lease=lease_state or None, measurement=measurement, performance=doc.get("performance"),
                channels={k: v["state"] for k, v in doc["channels"].items()}, summary=doc["summary"])


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


def performance_summary(results: list, limits: PerformanceLimits = None) -> dict:
    """Per-instance limits table plus the 1,000-position target verdict.

    A result that could not be assessed (incomplete, limit breach, validation failure,
    refused lease, invalidated stage) makes the overall status `fail`: it is never
    counted as a pass with fewer positions.
    """
    limits = limits or LIMITS
    instances, not_assessed = [], []
    for item in results:
        if item["status"] == "collected":
            m = item.get("measurement") or {}
            instances.append(dict(cik=item["cik"], report_date=item["report_date"],
                                  positions_current=(item.get("summary") or {}).get("position_observations_current"),
                                  wall_seconds=m.get("wall_seconds"), stage_seconds=m.get("stage_seconds"),
                                  peak_bytes_upper=m.get("peak_bytes_upper"), peak_exact=m.get("peak_exact"),
                                  status=(item.get("performance") or {}).get("status", "not_measured"),
                                  cache=item.get("cache")))
        elif item["status"] in FAILURE_STATUSES:
            not_assessed.append(dict(cik=item["cik"], report_date=item["report_date"], status=item["status"]))
    target = [i for i in instances if (i["positions_current"] or 0) >= limits.target_positions]
    if not target:
        target_status = "not_assessed"
    else:
        target_status = "pass" if all(i["status"] == "pass" for i in target) else "fail"
    ok = all(i["status"] == "pass" for i in instances) and not not_assessed
    return dict(limits=asdict(limits), status="pass" if ok else "fail", instances=instances,
                not_assessed=not_assessed,
                target=dict(positions_at_least=limits.target_positions, status=target_status,
                            instances=target))


def calibration_check(results: list) -> list:
    """Calibrated estimate vs measured, per computed instance (cache misses only)."""
    rows = []
    for item in results:
        m = item.get("measurement") or {}
        if item["status"] != "collected" or item.get("cache") != "miss" or "estimate_seconds" not in m:
            continue
        rows.append(dict(cik=item["cik"], report_date=item["report_date"],
                         estimate_seconds=m["estimate_seconds"], measured_wall_seconds=m["wall_seconds"],
                         measured_stage_seconds=m.get("stage_seconds"),
                         estimate_bytes=m["estimate_bytes"], measured_peak_bytes_upper=m["peak_bytes_upper"],
                         peak_exact=m.get("peak_exact"),
                         seconds_ratio=round(m["estimate_seconds"] / max(m["wall_seconds"], 1e-3), 2),
                         bytes_ratio=round(m["estimate_bytes"] / max(m["peak_bytes_upper"], 1), 2),
                         seconds_envelope_holds=m["estimate_seconds"] >= m["wall_seconds"],
                         # a non-exact peak is the process lifetime peak, not this instance's
                         bytes_envelope_holds=(m["estimate_bytes"] >= m["peak_bytes_upper"]
                                               if m.get("peak_exact") else "not_exact")))
    return rows


def _selected(entries: list, scope: str, only) -> list:
    light = [e for e in entries if e["cik"] in LIGHT_SCOPE_CIKS]
    heavy = [e for e in entries if e["cik"] in LARGE]
    unknown = [e["cik"] for e in entries if e["cik"] not in LIGHT_SCOPE_CIKS + LARGE]
    if unknown:
        raise ValueError("inventory CIKs in neither scope list: " + ", ".join(sorted(set(unknown))))
    ordered = (light if scope in ("light", "all") else []) + (heavy if scope in ("heavy", "all") else [])
    if only:
        wanted = set(only)
        ordered = [e for e in ordered if e["cik"] + ":" + e["quarter"] in wanted]
    return ordered


def run(paths, *, scope: str, bounds: Bounds = Bounds(), only=None) -> dict:
    """Census every frozen fund-quarter in scope; light first, then heavy under the lease."""
    from scripts.profile_pilot import manifest, protection
    inventory = manifest.load_inventory(paths, "primary_quarter_inventory")
    ordered = _selected(inventory["fund_quarters"], scope, only)
    head = manifest.git_head(paths.code_root)
    results, stopped = [], None
    for entry in ordered:
        got = census_fund_quarter(paths, entry, bounds=bounds, refuse_heavy=stopped,
                                  lease_factory=lambda: protection.shared_heavy_lease(paths, head=head))
        results.append(got)
        m = got.get("measurement") or {}
        print(_ascii("census " + got["cik"] + " " + got["report_date"] + " " + str(got.get("role"))
                     + ": " + got["status"] + (" (" + str(got.get("reason"))[:160] + ")"
                                                if got["status"] != "collected" else
                                                " cache=" + got["cache"] + " wall=" + str(m.get("wall_seconds"))
                                                + " stage=" + str(m.get("stage_seconds")) + " peak="
                                                + str(m.get("peak_bytes_upper")) + " exact="
                                                + str(m.get("peak_exact")))), flush=True)
        if got["status"] == "lease_refused" and not stopped:
            stopped = "lease refused earlier in this run: " + str(got.get("reason"))[:200]
    counts: dict[str, int] = {}
    for item in results:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    files = [Path(r["path"]).stat().st_size for r in results if r["status"] == "collected"]
    compact = [(r.get("measurement") or {}).get("compact_bytes") or 0 for r in results
               if r["status"] == "collected"]
    return dict(run_id=paths.run_id, scope=scope, only=list(only or []), git_head=head,
                census_version=CENSUS_VERSION, collector_version=COLLECTOR_VERSION, bounds=asdict(bounds),
                counts=counts, results=results, performance=performance_summary(results),
                calibration=dict(model={k: v for k, v in CALIBRATION.items() if k != "points"},
                                 instances=calibration_check(results)),
                output_bytes=dict(result_files=sum(files), compact_equivalent=sum(compact)))


def main(argv=None) -> int:
    import argparse
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
    cmd.add_argument("--only", action="append", default=None, help="CIK:YYYY-MM-DD (repeatable)")
    cmd.add_argument("--timeout-seconds", type=float, default=None,
                     help="collection time bound (a bounds change is a new cache identity)")
    args = parser.parse_args(argv)
    if not args.run_id.startswith(("stageb-", "stageb2-")):
        print("run id must start with stageb- or stageb2- (ruling R18; stageb2- per Task B2-2a)")
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
    from scripts.profile_pilot.manifest import StageInvalidated
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    started = time.perf_counter()
    refused = None
    with protection.protected_session(paths, receipt="verification/" + stamp + "_census_"
                                      + args.scope + "_preservation.json"):
        bounds = Bounds() if args.timeout_seconds is None else Bounds(timeout_seconds=args.timeout_seconds)
        try:
            summary = run(paths, scope=args.scope, only=args.only, bounds=bounds)
        except StageInvalidated as exc:  # ruling R23: another identity in this run root
            refused = _ascii(str(exc))
        else:
            summary["seconds"] = round(time.perf_counter() - started, 1)
            relative = "census/run_summary_" + args.scope + "_" + stamp + ".json"
            summary["summary_path"] = relative
            target = write_json(paths, relative, summary)
    if refused is not None:
        print("REFUSED: " + refused)
        return 4
    print("summary: " + json.dumps(summary["counts"], sort_keys=True) + " | performance "
          + summary["performance"]["status"] + " | target " + summary["performance"]["target"]["status"]
          + " | " + str(target))
    failed = [s for s in summary["counts"] if s in FAILURE_STATUSES]
    if failed or summary["performance"]["status"] != "pass":
        print("FAILED: " + ",".join(failed or ["performance " + summary["performance"]["status"]]))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
