"""Task B2-2a cross-check: the Stage B fund-quarters inside an all-quarter census root.

For every authoritative Stage B census row (reference root, default
stageb-20260929t004819z) the new root must hold the same (cik, role) with the SAME
identity fingerprint, collector/census/detector versions and position count; that
triple is `match`. Because the fingerprint hashes every code file and absolute input
path, the check also reports, separately and without changing the verdict:
  - `content_equal`: the census result is identical once run-specific fields are removed
    (measurement, performance, cache_identity, collection.elapsed_seconds, dependency paths);
  - `dependency_differences`: which dependency file records changed bytes (`sha256`) and
    which moved without changing bytes (`path_only`), plus non-file dependency keys.
It also recomputes the cohort-mode inventory against the current data root and compares
its digest with the reference root's frozen primary_quarter_inventory (regression pin).
A mismatch is a finding, never repaired here. Read-only except one write-once result:

    python -m scripts.profile_pilot.census_crosscheck run --data-root D --run-id stageb2-census-... \
        [--reference-run-id stageb-20260929t004819z]

writes results/stageb_crosscheck.json under --run-id.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

REFERENCE_RUN_ID = "stageb-20260929t004819z"
COHORT_ROLES = ("q1", "q2", "verified_era")
RESULT_RELATIVE = "results/stageb_crosscheck.json"
RUN_SPECIFIC = ("measurement", "performance", "cache_identity")
VERSION_KEYS = ("collector_version", "census_version", "detector_version")


def _ascii(text) -> str:
    return str(text).encode("ascii", "backslashreplace").decode("ascii")


def _drop_paths(value):
    if isinstance(value, dict):
        return {k: _drop_paths(v) for k, v in value.items() if k != "path"}
    if isinstance(value, list):
        return [_drop_paths(v) for v in value]
    return value


def content_digest(result: dict) -> str:
    """Digest of a census result without run-specific fields (timings, identity, dependency paths)."""
    from scripts.profile_pilot.manifest import digest
    body = {k: v for k, v in result.items() if k not in RUN_SPECIFIC}
    body = copy.deepcopy(body)
    (body.get("collection") or {}).pop("elapsed_seconds", None)
    if "dependencies" in body:
        body["dependencies"] = _drop_paths(body["dependencies"])
    return digest(body)


def _records(value, found: dict) -> dict:
    """label -> file record, anywhere in an identity's dependencies."""
    if isinstance(value, dict):
        if "label" in value and "path" in value:
            found[value["label"]] = value
        for child in value.values():
            _records(child, found)
    elif isinstance(value, list):
        for child in value:
            _records(child, found)
    return found


def dependency_differences(ref_identity: dict, new_identity: dict) -> tuple[dict, list]:
    ref = _records(ref_identity.get("dependencies"), {})
    new = _records(new_identity.get("dependencies"), {})
    changed, moved = [], []
    for label in sorted(set(ref) | set(new)):
        a, b = ref.get(label), new.get(label)
        if a is None or b is None or a.get("sha256") != b.get("sha256"):
            changed.append(label)
        elif a.get("path") != b.get("path"):
            moved.append(label)
    other = []
    ref_deps, new_deps = ref_identity.get("dependencies") or {}, new_identity.get("dependencies") or {}
    for key in sorted(set(ref_deps) | set(new_deps)):
        a, b = ref_deps.get(key), new_deps.get(key)
        if _records(a, {}) or _records(b, {}):
            continue
        if a != b:
            other.append(key)
    return dict(sha256=changed, path_only=moved), other


def _positions(doc: dict) -> dict:
    summary = (doc.get("result") or {}).get("summary") or {}
    return dict(position_observations=summary.get("position_observations"),
                position_observations_current=summary.get("position_observations_current"))


def compare_pair(ref_row: dict, ref_doc: dict, new_row: dict | None, new_doc: dict | None) -> dict:
    """One Stage B fund-quarter: `match` = same fingerprint AND versions AND position count."""
    base = dict(cik=ref_row["cik"], role=ref_row["role"], report_date=ref_row["report_date"],
                reference_fingerprint=ref_row["fingerprint"], reference_positions=_positions(ref_doc))
    if new_row is None or new_doc is None:
        return dict(base, status="missing_in_new_root", match=False)
    fingerprint_equal = (ref_row["fingerprint"] == new_row["fingerprint"]
                         == new_doc["identity"]["fingerprint"])
    versions = {k: [ref_row.get(k), new_row.get(k)] for k in VERSION_KEYS}
    versions_equal = all(a == b for a, b in versions.values())
    positions_equal = _positions(ref_doc) == _positions(new_doc)
    content_equal = content_digest(ref_doc["result"]) == content_digest(new_doc["result"])
    differences, other = dependency_differences(ref_doc["identity"], new_doc["identity"])
    return dict(base, status="compared", new_fingerprint=new_row["fingerprint"],
                new_report_date=new_row["report_date"], new_positions=_positions(new_doc),
                fingerprint_equal=fingerprint_equal, versions=versions, versions_equal=versions_equal,
                positions_equal=positions_equal, content_equal=content_equal,
                dependency_differences=differences, other_dependency_differences=other,
                match=fingerprint_equal and versions_equal and positions_equal)


def cohort_inventory_regression(paths, reference_paths) -> dict:
    """Cohort-mode inventory recomputed now vs the reference root's frozen content."""
    from scripts.profile_pilot import cohort, manifest
    frozen = manifest.load_inventory(reference_paths, "primary_quarter_inventory")
    now = cohort.primary_quarter_inventory(paths)
    differing = sorted(k for k in set(frozen) | set(now) if frozen.get(k) != now.get(k))
    new_frozen = manifest.load_inventory(paths, "primary_quarter_inventory")
    by_role = {(r["cik"], r["role"]): r for r in new_frozen["fund_quarters"]}
    row_mismatch = [r["cik"] + "/" + r["role"] for r in frozen["fund_quarters"]
                    if by_role.get((r["cik"], r["role"])) != r]
    return dict(reference_content_sha256=manifest.digest(frozen), recomputed_content_sha256=manifest.digest(now),
                identical=manifest.digest(frozen) == manifest.digest(now), differing_top_level_keys=differing,
                new_root_cohort_rows_equal_reference=not row_mismatch, new_root_row_mismatches=row_mismatch)


def run(paths, *, reference_run_id: str = REFERENCE_RUN_ID) -> dict:
    from scripts.profile_pilot import cohort, lineage
    ref = lineage.load_authoritative_census(paths, reference_run_id, roles=COHORT_ROLES,
                                            ciks=cohort.PILOT_CIKS, require_excluded=True)
    new = lineage.load_authoritative_census(paths, paths.run_id, roles=COHORT_ROLES,
                                            ciks=cohort.PILOT_CIKS, require_excluded=True)
    pairs = []
    for key in sorted(ref["rows"]):
        ref_row, new_row = ref["rows"][key], new["rows"].get(key)
        ref_doc = json.loads((Path(ref["run_root"]) / ref_row["census_relative"]).read_text(encoding="ascii"))
        new_doc = None
        if new_row is not None:
            new_doc = json.loads((Path(new["run_root"]) / new_row["census_relative"]).read_text(encoding="ascii"))
        pairs.append(compare_pair(ref_row, ref_doc, new_row, new_doc))
        del ref_doc, new_doc
    extra = sorted(c + "/" + r for (c, r) in new["rows"] if (c, r) not in ref["rows"])
    def exclusions(loaded) -> list:
        rows = json.loads(Path(loaded["excluded"]["path"]).read_text(encoding="ascii"))["fund_quarters"]
        return sorted((r["cik"], r["role"], r["reason"], r.get("detail") or "") for r in rows
                      if r["role"] in COHORT_ROLES)

    ref_excluded, new_excluded = exclusions(ref), exclusions(new)
    regression = cohort_inventory_regression(paths, ref["paths"])
    tally = {name: sum(1 for p in pairs if p.get(name)) for name in
             ("match", "fingerprint_equal", "versions_equal", "positions_equal", "content_equal")}
    return dict(reference_run_id=reference_run_id, run_id=paths.run_id, compared=len(pairs), tally=tally,
                rule="match = identical identity.fingerprint AND collector/census/detector versions AND "
                     "position counts; content_equal is reported separately",
                reference_listing_sha256=ref["authoritative"]["sha256"],
                new_listing_sha256=new["authoritative"]["sha256"],
                cohort_rows_only_in_new_root=extra,
                cohort_exclusions=dict(reference=[list(x) for x in ref_excluded],
                                       new=[list(x) for x in new_excluded],
                                       equal=ref_excluded == new_excluded),
                cohort_inventory_regression=regression, pairs=pairs)


def main(argv=None) -> int:
    import argparse
    from scripts.profile_pilot import protection
    from scripts.profile_pilot.manifest import StageInvalidated
    from scripts.profile_pilot.paths import PathError, discover_main_root, resolve_paths, write_once_json
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="ascii", errors="backslashreplace")
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    cmd = sub.add_parser("run")
    cmd.add_argument("--main-root", type=Path, default=None)
    cmd.add_argument("--data-root", type=Path, required=True)
    cmd.add_argument("--run-id", required=True)
    cmd.add_argument("--reference-run-id", default=REFERENCE_RUN_ID)
    args = parser.parse_args(argv)
    code_root = Path(__file__).resolve().parents[2]
    try:
        paths = resolve_paths(main_repo_root=args.main_root or discover_main_root(code_root),
                              data_root=args.data_root, code_root=code_root, run_id=args.run_id)
    except PathError as exc:
        print("PATH ERROR: " + _ascii(exc))
        return 4
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    started = time.perf_counter()
    try:
        with protection.protected_session(paths, receipt="verification/" + stamp + "_crosscheck_preservation.json"):
            body = run(paths, reference_run_id=args.reference_run_id)
            body["seconds"] = round(time.perf_counter() - started, 1)
            target = write_once_json(paths, RESULT_RELATIVE, body)
    except (StageInvalidated, PathError) as exc:
        print("REFUSED: " + _ascii(exc))
        return 4
    print("crosscheck: compared " + str(body["compared"]) + " | " + json.dumps(body["tally"], sort_keys=True))
    print("cohort inventory regression identical: " + str(body["cohort_inventory_regression"]["identical"])
          + " | cohort rows equal: "
          + str(body["cohort_inventory_regression"]["new_root_cohort_rows_equal_reference"])
          + " | exclusions equal: " + str(body["cohort_exclusions"]["equal"]))
    print("written: " + str(target))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
