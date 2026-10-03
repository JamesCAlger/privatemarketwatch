"""SP3 proper CLI: build the inception profile documents for the pilot filers, regenerate the override shapes,
check consistency and write the sub-project 3 exit test.

    python -m scripts.profile_pilot.profile_document_run build --data-root D --run-id sp3p-profile-<stamp>
        --census-run-id stageb2-sp1census-20260930t2235z --replay-run-id <sp1 replay run id>
        [--main-root M] [--cik C ...]

Reads, pinned by sha256 and re-verified at the end (a change invalidates the stage, exit 2): every file of
<main>/data/overrides that mentions a pilot filer (the MAIN checkout's production overrides, not the worktree copy)
plus the shared override files, the census root's authoritative/excluded listings and the Q4-2025 / Q1-2026 census
files it names for each filer, <data_root>/pilot/filer_profile/<replay>/results/replay_q4_q1.json and
scripts/profile_pilot/census_published.py. Sign-off attestation is a read-only `git show <tag>:<path>` in the main
checkout. Writes ONLY under <data_root>/pilot/filer_profile/<run_id>/ (write-once): manifest.json,
profiles/<cik>.json and roundtrip/overrides/<path> (order-preserving), results/{roundtrip,consistency,exit_test}.json.
No production reader is switched and nothing under data/overrides or data/output is written.

Census role selection (controller ruling A1): the Q4-2025 row for a filer is whichever role the census root gave it
(q1 / q2 / an "all:2025-12-31" generic quarter) -- selected by REPORT DATE, not by a fixed role string, since the
inherited q1/q2 primary-quarter roles are filer-specific dates that rarely coincide with the fixed inception date.
The Q1-2026 row is always role "verified_era" (the cohort's fixed verified-era quarter equals the fixed Q1 date for
every filer by construction); more than one row for either selection is StageInvalidated, never silently resolved.

Guards beyond the standard protected_session (which already covers the MAIN checkout's data/output and
frontend/public/data via PilotPaths.protected_roots, and the WORKTREE's data/overrides via read_only_roots): this
module separately inventories the MAIN checkout's data/overrides before and after the stage body and raises
protection.PreservationError on any create/change/delete, because that tree is a second read-only root specific to
this CLI's real run (controller ruling A7) that the shared paths.read_only_roots property does not cover (it is
fixed to the CODE checkout's copy for every other pilot stage).

Workload (ruling A8): declared once for the whole build from the pinned file sizes actually read (census result
documents run 35-55 MB each; they are read one filer at a time, never all at once, so the byte estimate uses the
single largest pinned census file, matching profile_run.write_profile's established per-file formula, while the
time estimate sums the pinned bytes since wall-clock is cumulative across the sequential loop). No lease mechanism
is wired into this CLI; a workload that classifies heavy is refused (exit 4), never silently run unleased.

Exit codes: 0 exit test PASS, 1 FAIL (documents still written), 2 stage invalidated / document-contract violation,
4 refused.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

from scripts.profile_pilot import (census_published, cohort, contracts_run, lineage, manifest, protection,
                                   profile_consistency, translate)
from scripts.profile_pilot import profile_document as pd
from scripts.profile_pilot import profile_families as pf
from scripts.profile_pilot import profile_inception as pi
from scripts.profile_pilot import profile_roundtrip as rt
from scripts.profile_pilot.manifest import StageInvalidated
from scripts.profile_pilot.paths import PathError, discover_main_root, resolve_paths, write_once_json
from scripts.profile_pilot.protection import LeaseRefused, PreservationError

CODE_ROOT = Path(__file__).resolve().parents[2]
RUN_PREFIX = "sp3p-profile-"
EXIT_FAIL, EXIT_INVALIDATED, EXIT_REFUSED = 1, 2, 4
Q4, Q1 = pd.INCEPTION_REPORT_DATE, "2026-03-31"
# A1: Q4 is selected by report date among whatever role the census root gave it (q1 / q2 / an "all:"
# generic quarter); Q1 is always role "verified_era" by construction of the cohort's fixed verified-era
# quarter. Both role strings are included so load_authoritative_census's role filter admits either row.
CENSUS_ROLES = ("q1", "q2", "verified_era", "all:" + Q4)

# loader_parity family -> (per_cik | pooled) mapping used by _loader_parity_problems (I5/I6 tally, A7-adjacent
# defensive check): a filesystem-expected file whose loader_parity status is "absent" means the materialised
# and original roots were miswired, not that nothing needed converting.
PER_CIK_LOADER_FAMILIES = {"bdc_xbrl_wrappers": "bdc_xbrl_wrappers", "agent_investigate_rules": "agent_investigate_rules",
                           "rate_convention": "rate_convention", "identifier_anchors": "identifier_anchors",
                           "identifier_rate_grammars": "identifier_rate_grammars"}
POOLED_LOADER_FAMILIES = {"agent_b2_corrections": "agent_b2_corrections",
                          "bdc_xbrl_oracle_exceptions.json": "bdc_xbrl_oracle_exceptions"}
# bdc_aggregate_row_overrides.json has no directory- or path-parameterised production loader
# (profile_roundtrip.loader_parity's own not_loader_checked list); there is nothing to tally it against.
LOADER_NOT_CHECKED = {"bdc_aggregate_row_overrides.json"}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ascii(text: str) -> str:
    return text.encode("ascii", "backslashreplace").decode("ascii")


def default_run_id(now: datetime | None = None) -> str:
    return RUN_PREFIX + (now or datetime.now(timezone.utc)).strftime("%Y%m%dt%H%M%Sz")


def _check_prefix(run_id: str) -> None:
    if not run_id.startswith(RUN_PREFIX):
        raise PathError("run id must start with " + RUN_PREFIX + ": " + run_id)


def attested_under(main_root: Path, rel: str, content) -> list:
    """Tags in pi.SIGNOFF_TAGS whose main-checkout blob at that tag parses order-identical to `content`.

    A tolerant (check=False) `git show`: a main_root that is not a git checkout (every pilot test's fake
    main root) or a tag that does not carry the path simply yields no attestation, never a crash.
    """
    tags = []
    for tag in pi.SIGNOFF_TAGS:
        done = manifest.git(Path(main_root), "show", tag + ":" + pf.REPO_PREFIX + rel, check=False)
        if done.returncode != 0:
            continue
        try:
            tagged = json.loads(done.stdout.decode("utf-8-sig"))
        except ValueError:
            continue
        if translate.value_sha256(tagged) == translate.value_sha256(content):
            tags.append(tag)
    return tags


def _main_overrides_git_head(main_root: Path) -> str | None:
    """The MAIN checkout's HEAD, for inputs["overrides_git_head"] (the checkout whose data/overrides was
    read, distinct from code.git_head which is the WORKTREE's own converter-code HEAD). Tolerant like
    attested_under: a non-git main root (every pilot test's fake main root) yields None, never a crash."""
    done = manifest.git(Path(main_root), "rev-parse", "HEAD", check=False)
    if done.returncode != 0:
        return None
    return done.stdout.decode("ascii").strip()


def _census(row) -> dict | None:
    """Reuse contracts_run.load_census (the existing census reader) rather than re-opening the census
    file by hand; build the `source` record build_document/profile.derive_profile expect from the
    authoritative listing row plus the census document's own DEI facts."""
    if row is None:
        return None
    doc = contracts_run.load_census(row)
    source = dict(cik=row["cik"], report_date=row["report_date"], role=row["role"],
                 census_relative=row["census_relative"], census_sha256=row["census_sha256"],
                 fingerprint=row["fingerprint"], accession_number=doc["document"].get("accession_number"),
                 form_type=doc["document"].get("form_type"))
    return dict(doc=doc, source=source)


def _select_census_row(census: dict, cik: str, *, report_date: str | None = None, role: str | None = None) -> dict | None:
    """One authoritative row for `cik` matching `report_date` and/or `role`; more than one is refused
    (A1: never silently resolved by taking the first)."""
    matches = [row for (c, r), row in census["rows"].items()
              if c == cik and (role is None or r == role) and (report_date is None or row["report_date"] == report_date)]
    if len(matches) > 1:
        raise StageInvalidated("more than one authoritative census row for " + cik + " at "
                               + repr(dict(report_date=report_date, role=role)) + ": "
                               + repr(sorted(m["census_relative"] for m in matches)))
    return matches[0] if matches else None


def _unavailable(excluded: dict, cik: str, census_run_id: str) -> dict:
    for row in excluded.get("fund_quarters", []):
        if row.get("cik") == cik and row.get("report_date") == Q4:
            return dict(census_run_id=census_run_id, reason=str(row.get("reason")), detail=row.get("detail"))
    return dict(census_run_id=census_run_id, reason="not_listed", detail="no authoritative or excluded row")


def _assert_dispositions_hashed(cik: str, disposition: list) -> None:
    """A converted disposition (entry/wrapper_block/correction) with no ordered_sha256 cannot be
    round-tripped or verified; refuse before ever writing the document, rather than let the round trip
    fail on it later with a less specific error."""
    for d in disposition:
        if d["action"] in rt.CONVERTED_ACTIONS and d.get("ordered_sha256") is None:
            raise pi.InceptionError(cik + ": converted disposition " + d["path"] + " (action " + d["action"]
                                    + ") has no ordered_sha256; refusing to build an unhashed conversion")


def _loader_parity_problems(parity: dict, expected: list) -> list:
    """I5/I6 tally: every filesystem-expected file (filesystem_expected_paths, independent of the
    documents) must show up as something other than "absent" in loader_parity's matching family -- an
    expected-on-disk file that loader_parity calls absent means the original/materialised roots were
    miswired, which parity.ok alone (true on all-absent) would not catch."""
    problems, seen_pooled = [], set()
    for rel in expected:
        if rel in LOADER_NOT_CHECKED:
            continue
        family = pf.family_of(rel)
        if family in PER_CIK_LOADER_FAMILIES:
            key = PER_CIK_LOADER_FAMILIES[family]
            cik = pf.owner_cik(rel)
            status = (parity.get(key) or {}).get(cik)
            if status == rt.ABSENT:
                problems.append(rel + ": loader_parity[" + key + "][" + str(cik) + "] is absent but the "
                                "file exists on disk")
        elif family in POOLED_LOADER_FAMILIES:
            if family in seen_pooled:
                continue
            seen_pooled.add(family)
            key = POOLED_LOADER_FAMILIES[family]
            status = (parity.get(key) or {}).get("status")
            if status == rt.ABSENT:
                problems.append(rel + ": loader_parity[" + key + "].status is absent but the file exists "
                                "on disk")
        else:
            problems.append(rel + ": no loader-parity family mapping for " + repr(family))
    return problems


def _workload(pins: list, census_files: list, ciks) -> dict:
    """A4/A8: one typed workload for the whole build. Bytes use the single largest pinned census file
    (census documents run 35-55 MB; they are read one filer at a time in the loop below, so peak memory
    is bounded by one file, not their sum) with profile_run.write_profile's own per-file constants (300e6
    base + 20x). Seconds sum every pinned byte read (wall-clock is cumulative, not peak) at an assumed
    50 MB/s JSON read+parse+build throughput; this is a measurement-free estimate pending Task 10's actual
    timing, deliberately conservative toward refusing rather than running heavy work unleased."""
    present = [p for p in pins if isinstance(p, dict) and p.get("status") == "present"]
    total_bytes = sum(p.get("bytes", 0) for p in present)
    census_bytes = [r.get("bytes", 0) for r in census_files if r.get("status") == "present"]
    max_census_bytes = max(census_bytes) if census_bytes else 0
    return dict(ciks=tuple(sorted(ciks)), instance_count=0, full_cache_scan=False, pipeline_cik_count=0,
               est_seconds=round(2.0 + total_bytes / 50e6, 1), est_bytes=int(300e6 + 20 * max_census_bytes))


def run_stage(paths, *, census_run_id: str, replay_run_id: str, ciks=None, recorded_at=None) -> dict:
    _check_prefix(paths.run_id)
    root = paths.main_repo_root / "data" / "overrides"
    guard_specs = [protection.RootSpec(path=root.resolve(strict=False), mode="full")]
    before_guard = protection.inventory(guard_specs)
    try:
        started = time.perf_counter()
        ciks = sorted(pf.cik10(c) for c in (ciks or cohort.PILOT_CIKS))
        recorded_at = recorded_at or _now()
        hits = pf.scan_overrides(root, ciks)
        census = lineage.load_authoritative_census(paths, census_run_id, roles=CENSUS_ROLES, ciks=ciks,
                                                    require_excluded=True)
        excluded = json.loads(Path(census["excluded"]["path"]).read_text(encoding="ascii"))
        replay_path = paths.data_root / "pilot" / "filer_profile" / replay_run_id / "results" / "replay_q4_q1.json"
        replay_record = manifest.file_record(replay_path, "replay/" + replay_run_id + "/results/replay_q4_q1.json")
        if replay_record["status"] != "present":
            raise StageInvalidated("replay result missing: " + str(replay_path))
        floors = json.loads(replay_path.read_text(encoding="ascii"))["floors"]
        detection = {k: dict(verdict=v["verdict"], replay_run_id=replay_run_id) for k, v in floors.items()}
        predicate_record = manifest.file_record(paths.code_root / pi.PREDICATE_CODE_PATH,
                                                 "code/" + pi.PREDICATE_CODE_PATH)
        predicate = dict(version=census_published.CENSUS_PUBLISHED_VERSION, code_sha256=predicate_record["sha256"])
        shared_names = [n for n in pf.SHARED_FILES if (root / n).is_file()]
        hit_paths = {h["path"] for h in hits}
        pins = ([manifest.file_record(root / h["path"], "overrides/" + h["path"]) for h in hits]
                + [manifest.file_record(root / n, "overrides/" + n) for n in shared_names if n not in hit_paths]
                + [census["authoritative"], census["excluded"]] + census["files"] + [replay_record, predicate_record])
        workload = _workload(pins, census["files"], ciks)
        if manifest.classify_workload(workload):
            raise LeaseRefused("profile_document_run has no lease mechanism; this build classified heavy "
                               "(workload=" + json.dumps(workload, sort_keys=True) + "); refusing rather than "
                               "running heavy work unleased")
        git = dict(head=manifest.git_head(paths.code_root),
                  dirty_source_digest=manifest.dirty_source_digest(paths.code_root))
        overrides_git_head = _main_overrides_git_head(paths.main_repo_root)
        write_once_json(paths, "manifest.json", dict(
            stage="sp3_profile_document", run_id=paths.run_id, git=git, inputs=pins, census_run_id=census_run_id,
            replay_run_id=replay_run_id, overrides_root=str(root), overrides_git_head=overrides_git_head,
            recorded_at=recorded_at, converter_version=pd.CONVERTER_VERSION, ciks=ciks, hits=hits,
            workload=workload))
        documents = {}
        for cik in ciks:
            inputs = pf.collect_override_inputs(root, cik, hits)
            inputs["attested_under"] = {x["path"]: attested_under(paths.main_repo_root, x["path"], x["content"])
                                        for x in inputs["files"].get("bdc_xbrl_wrappers", [])}
            q4_row = _select_census_row(census, cik, report_date=Q4)
            q1_row = _select_census_row(census, cik, role="verified_era")
            if q1_row is not None and q1_row["report_date"] != Q1:
                raise StageInvalidated("verified_era census row for " + cik + " is not at " + Q1 + ": "
                                       + repr(q1_row["report_date"]))
            q4 = _census(q4_row)
            inputs.update(census_q4=q4, census_q1=_census(q1_row),
                          census_q4_unavailable=None if q4 else _unavailable(excluded, cik, census_run_id),
                          detection=detection, predicate=predicate,
                          code_mirror=list(census_published.REPORTING_ENTITIES.get(cik, ())),
                          overrides_root="main checkout data/overrides", overrides_git_head=overrides_git_head,
                          replay_run_id=replay_run_id)
            doc = pi.build_document(cik, inputs=inputs, recorded_at=recorded_at, run_id=paths.run_id,
                                    git_head=git["head"])
            _assert_dispositions_hashed(cik, doc["disposition"])
            target_relative = "profiles/" + cik + ".json"
            translate._write_once_ordered(paths, target_relative, doc)
            # I1: the document used from here on is the one actually written and reread through the
            # production reader, never the in-memory build_document() return value.
            documents[cik] = pd.load_document(paths.run_root / target_relative)
        shared = {n: pf.read_json(root / n) for n in shared_names}
        expected = rt.filesystem_expected_paths(root, ciks)   # I3: filesystem-derived, never document-derived
        doc_paths = [paths.run_root / "profiles" / (cik + ".json") for cik in ciks]
        materialised = rt.load_and_materialise(doc_paths, shared_originals=shared)
        originals = {rel: pf.read_json(root / rel) for rel in expected if rel not in pf.SHARED_FILES}
        originals.update({name: value for name, value in shared.items() if name in expected})
        for rel, value in materialised.items():
            translate._write_once_ordered(paths, "roundtrip/overrides/" + rel, value)
        roundtrip = rt.roundtrip_check(materialised, originals)
        roundtrip["loader_parity"] = rt.loader_parity(root, paths.run_root / "roundtrip" / "overrides", ciks)
        parity_problems = _loader_parity_problems(roundtrip["loader_parity"], expected)
        if parity_problems:
            raise rt.RoundTripError("loader_parity reports absent for files that exist on disk: "
                                    + "; ".join(parity_problems[:5]))
        roundtrip["ok"] = roundtrip["ok"] and roundtrip["loader_parity"]["ok"]
        consistency = {cik: profile_consistency.consistency_contract(
            doc, report_date=Q4, code_mirror=census_published.REPORTING_ENTITIES.get(cik, ()))
            for cik, doc in documents.items()}
        exit_body = profile_consistency.exit_test(documents, consistency, roundtrip, report_date=Q4,
                                                   expected_ciks=cohort.PILOT_CIKS)
        write_once_json(paths, "results/roundtrip.json", roundtrip)
        write_once_json(paths, "results/consistency.json", consistency)
        write_once_json(paths, "results/exit_test.json", exit_body)
        after = manifest.verify_inputs(dict(inputs=pins))
        if not after["ok"]:
            raise StageInvalidated("pinned inputs changed during the stage: " + json.dumps(after)[:400])
        return dict(run_id=paths.run_id, git_head=git["head"], verdict=exit_body["verdict"],
                   seconds=round(time.perf_counter() - started, 1), roundtrip_counts=roundtrip["counts"],
                   loader_parity_ok=roundtrip["loader_parity"]["ok"], missing_filers=exit_body["missing_filers"],
                   per_cik={c: dict(criterion_1=p["criterion_1"], resolver=p["resolver"],
                                    consistency=p["consistency"], resolved=p["resolved"], stubs=p["stubs"],
                                    counts=p["consistency_counts"])
                           for c, p in exit_body["per_cik"].items()})
    finally:
        # Matches protection.protected_session's own documented convention: a preservation failure
        # outranks (and chains onto, via Python's implicit exception context) the body's own exception.
        after_guard = protection.inventory(guard_specs)
        comparison = protection.compare(before_guard, after_guard)
        if not comparison["ok"]:
            raise PreservationError(
                "MAIN checkout data/overrides changed during the run (read-only root for this CLI, "
                "ruling A7): created=" + str(len(comparison["created"])) + " changed="
                + str(len(comparison["changed"])) + " deleted=" + str(len(comparison["deleted"])))


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="ascii", errors="backslashreplace")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    cmd = sub.add_parser("build")
    cmd.add_argument("--main-root", type=Path, default=None)
    cmd.add_argument("--data-root", type=Path, required=True)
    cmd.add_argument("--code-root", type=Path, default=None)
    cmd.add_argument("--run-id", default=None)
    cmd.add_argument("--census-run-id", required=True)
    cmd.add_argument("--replay-run-id", required=True)
    cmd.add_argument("--cik", action="append", default=None)
    args = parser.parse_args(argv)
    try:
        run_id = args.run_id or default_run_id()
        _check_prefix(run_id)
        main_root = args.main_root or discover_main_root(CODE_ROOT)
        paths = resolve_paths(main_repo_root=main_root, data_root=args.data_root,
                              code_root=args.code_root or CODE_ROOT, run_id=run_id)
        receipt = ("verification/" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                   + "_profile_document_preservation.json")
        with protection.protected_session(paths, receipt=receipt):
            summary = run_stage(paths, census_run_id=args.census_run_id, replay_run_id=args.replay_run_id,
                                ciks=args.cik)
    except StageInvalidated as exc:
        print("STAGE INVALIDATED: " + _ascii(str(exc)))
        return EXIT_INVALIDATED
    except (pi.InceptionError, rt.RoundTripError, pd.ProfileDocumentError) as exc:
        print("DOCUMENT INVALID: " + _ascii(str(exc)))
        return EXIT_INVALIDATED
    except (PathError, pf.FamilyError, LeaseRefused) as exc:
        print("REFUSED: " + _ascii(str(exc)))
        return EXIT_REFUSED
    print(json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=True))
    return 0 if summary["verdict"] == "PASS" else EXIT_FAIL


if __name__ == "__main__":
    raise SystemExit(main())
