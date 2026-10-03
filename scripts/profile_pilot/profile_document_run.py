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
profiles/<cik>.json and roundtrip/overrides/<path> (order-preserving), results/{roundtrip,consistency,exit_test}.json,
verification/main_overrides_guard.json. No production reader is switched and nothing under data/overrides or
data/output is written.

Census role selection (controller ruling A1): the Q1-2026 row is always role "verified_era" (the cohort's fixed
verified-era quarter, by construction, equals the fixed Q1 date for every filer). The Q4-2025 row is selected by
REPORT DATE among whatever role the census root actually gave it; in practice that is always a generic
"all:2025-12-31" quarter, since no PILOT_COHORT member's own primary q1/q2 date (earliest 2022-09-30) ever lands on
2025-12-31 -- "q1"/"q2" are therefore not in CENSUS_ROLES (fix round 1, F10): admitting them only pinned and hashed
unrelated census files at other report dates for no benefit. More than one authoritative row for either selection is
StageInvalidated, never silently resolved.

Guards beyond the standard protected_session (which already covers the MAIN checkout's data/output and
frontend/public/data via PilotPaths.protected_roots, and the WORKTREE's data/overrides via read_only_roots -- a
fixed property other pilot stages rely on staying unchanged, tests/test_profile_pilot_protection.py:120): this
module additionally (a) installs its own open-guard over the MAIN checkout's data/overrides via
protection.install_open_guard's explicit roots list (no change to protection.py needed), blocking any write-mode
`open()`/`io.open()` to it for the whole stage body, and (b) inventories that same root before and after the body,
writing the comparison to verification/main_overrides_guard.json and raising protection.PreservationError on any
create/change/delete that the open-guard did not itself block (e.g. a deletion via os.unlink, which does not go
through open()). Fix round 1 (F8): protection.py's own protected_session receipt is NOT parameterised for extra
roots, so this guard's receipt is a separate file, not folded into that one.

Workload (ruling A8, honesty fix round 1 F1): declared once for the whole build. Q4 and Q1 censuses are BOTH loaded
together for a given filer (not one at a time), so est_bytes uses the LARGEST per-filer Q4+Q1 byte sum across the
requested filers (profile_run.write_profile's own per-file formula, 300e6 base + 20x, applied to that sum rather
than a single file), read against protection.HEAVY_ESTIMATE_BYTES -- never a hard-coded threshold here. At the
owner-raised threshold (4 GiB, protection.py, 2026-10-03; was 2 GiB) real census sizes (BCRED ~50.8 MB + ~54.5 MB)
stay light; at the prior 2 GiB threshold the same filer would have classified heavy. est_seconds sums every pinned
byte (wall-clock is cumulative across the sequential per-filer loop, unlike peak memory) at an assumed 50 MB/s JSON
read+parse+build throughput -- a measurement-free estimate pending Task 10's actual timing. When heavy, the SAME
per-filer build loop runs unchanged, just inside the shared programme lease (profile_run's/census_run's own
lease_factory pattern) rather than refusing outright; with no lease_factory supplied a heavy classification is
refused (LeaseRefused, exit 4) -- that refuse-if-heavy-without-a-lease path is kept regardless of where the
threshold sits.

Exit codes: 0 exit test PASS, 1 FAIL (documents still written), 2 stage invalidated / document-contract violation /
preservation failure, 3 any other unexpected exception, 4 refused.
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
from scripts.profile_pilot.protection import LeaseRefused, PreservationError, assert_lease_held

CODE_ROOT = Path(__file__).resolve().parents[2]
RUN_PREFIX = "sp3p-profile-"
EXIT_FAIL, EXIT_INVALIDATED, EXIT_UNEXPECTED, EXIT_REFUSED = 1, 2, 3, 4
Q4, Q1 = pd.INCEPTION_REPORT_DATE, "2026-03-31"
# F10: "q1"/"q2" dropped. No PILOT_COHORT member's own primary quarter (cohort.py; earliest 2022-09-30) ever
# lands on the fixed Q4 inception date, so admitting those roles only pinned and hashed unrelated census
# files at other report dates. Q1 is always role "verified_era" by construction of the cohort's fixed
# verified-era quarter; Q4 is selected by report date, in practice always the generic "all:2025-12-31" role.
CENSUS_ROLES = ("verified_era", "all:" + Q4)
GUARD_RECEIPT_RELATIVE = "verification/main_overrides_guard.json"

# loader_parity family -> (per_cik | pooled) mapping used by _loader_parity_tally (F4): per-family compared
# vs filesystem-expected counts, not just loader_parity["ok"] (true on all-absent).
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

    A tolerant (check=False) `git show`: a tag that does not carry the path simply yields no attestation.
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


def _main_overrides_git_head(main_root: Path) -> str:
    """The MAIN checkout's HEAD, for inputs["overrides_git_head"] (the checkout whose data/overrides was
    read, distinct from code.git_head which is the WORKTREE's own converter-code HEAD). Fix round 1 (F7):
    a git failure here is a refusal (StageInvalidated, exit 2), not a silently recorded None -- the MAIN
    checkout is expected to be a real git repository for every real run."""
    done = manifest.git(Path(main_root), "rev-parse", "HEAD", check=False)
    if done.returncode != 0:
        raise StageInvalidated("could not determine the MAIN checkout's git HEAD for data/overrides (ruling "
                               "A7's read-only root): " + done.stderr.decode("ascii", "backslashreplace").strip())
    return done.stdout.decode("ascii").strip()


def _main_overrides_dirty(main_root: Path) -> bool:
    """F7: whether the MAIN checkout's data/overrides has uncommitted changes relative to its HEAD."""
    done = manifest.git(Path(main_root), "status", "--porcelain", "--", "data/overrides", check=False)
    if done.returncode != 0:
        raise StageInvalidated("could not check the MAIN checkout's data/overrides for uncommitted changes: "
                               + done.stderr.decode("ascii", "backslashreplace").strip())
    return bool(done.stdout.strip())


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
    (A1/F9: never silently resolved by taking the first)."""
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


def _owned_shared_files(root: Path, shared_names, ciks) -> set:
    """M2 (fix round 1): a shared file merely MENTIONING a pilot cik (profile_families.scan_overrides'
    broader text-match condition, which filesystem_expected_paths uses) is not necessarily converted for
    that cik -- only an OWNED record (its own `cik` field) produces a correction
    (profile_families.collect_override_inputs / profile_roundtrip._materialise's "owned" check). Narrow
    back down to that same condition so a --cik subset run's expected and materialised sets agree."""
    wanted = {pf.cik10(c) for c in ciks}
    owned = set()
    for name in shared_names:
        content = pf.read_json(root / name)
        records = content["overrides"] if isinstance(content, dict) else content
        if any(isinstance(r, dict) and pf.cik10(r.get("cik")) in wanted for r in records):
            owned.add(name)
    return owned


def _loader_parity_tally(parity: dict, expected: list) -> tuple[dict, list]:
    """F4: per family, the count of files loader_parity actually compared against the count
    filesystem_expected_paths says should be there. A family with files on disk and FEWER compared (or
    all absent) is a problem, even when loader_parity["ok"] is true (true on all-absent alone)."""
    by_cik_family: dict[str, set] = {}
    by_pooled_family: dict[str, int] = {}
    unmapped: list[str] = []
    for rel in expected:
        if rel in LOADER_NOT_CHECKED:
            continue
        family = pf.family_of(rel)
        if family in PER_CIK_LOADER_FAMILIES:
            by_cik_family.setdefault(family, set()).add(pf.owner_cik(rel))
        elif family in POOLED_LOADER_FAMILIES:
            by_pooled_family[family] = by_pooled_family.get(family, 0) + 1
        else:
            unmapped.append(rel)
    tally: dict[str, dict] = {}
    problems = [rel + ": no loader-parity family mapping for " + repr(pf.family_of(rel)) for rel in unmapped]
    for family, expected_ciks in by_cik_family.items():
        key = PER_CIK_LOADER_FAMILIES[family]
        statuses = parity.get(key) or {}
        compared = sum(1 for c in expected_ciks if statuses.get(c) not in (None, rt.ABSENT))
        expected_n = len(expected_ciks)
        tally[key] = dict(expected=expected_n, compared=compared)
        if compared < expected_n:
            problems.append(key + ": expected " + str(expected_n) + " filer(s) with a file on disk, "
                            "loader_parity compared " + str(compared) + " (" + repr(sorted(expected_ciks)) + ")")
    for family, expected_n in by_pooled_family.items():
        key = POOLED_LOADER_FAMILIES[family]
        entry = parity.get(key) or {}
        compared = entry.get("compared")
        if compared is None:   # a single-status pooled family (oracle exceptions): present counts as compared
            compared = 0 if entry.get("status") == rt.ABSENT else 1
            expected_n = min(expected_n, 1)
        tally[key] = dict(expected=expected_n, compared=compared)
        if compared < expected_n:
            problems.append(key + ": expected " + str(expected_n) + " file(s)/record(s) on disk, "
                            "loader_parity compared " + str(compared))
    return tally, problems


def _row_bytes(row) -> int:
    if row is None:
        return 0
    record = row.get("record") or {}
    return record.get("bytes", 0) if record.get("status") == "present" else 0


def _workload(pins: list, max_cik_census_bytes: int, ciks) -> dict:
    """F1: one typed workload for the whole build. Bytes use the LARGEST per-filer Q4+Q1 census byte sum
    (both are loaded together for a given filer, never one at a time) with profile_run.write_profile's own
    per-file constants (300e6 base + 20x). Seconds sum every pinned byte read (wall-clock is cumulative
    across the sequential per-filer loop, unlike peak memory) at an assumed 50 MB/s throughput -- a
    measurement-free estimate pending Task 10's actual timing."""
    present = [p for p in pins if isinstance(p, dict) and p.get("status") == "present"]
    total_bytes = sum(p.get("bytes", 0) for p in present)
    return dict(ciks=tuple(sorted(ciks)), instance_count=0, full_cache_scan=False, pipeline_cik_count=0,
               est_seconds=round(2.0 + total_bytes / 50e6, 1), est_bytes=int(300e6 + 20 * max_cik_census_bytes))


def run_stage(paths, *, census_run_id: str, replay_run_id: str, ciks=None, recorded_at=None,
             lease_factory=None) -> dict:
    _check_prefix(paths.run_id)
    root = paths.main_repo_root / "data" / "overrides"
    guard_specs = [protection.RootSpec(path=root.resolve(strict=False), mode="full")]
    before_guard = protection.inventory(guard_specs)
    # F8: an explicit open-guard over the MAIN checkout's data/overrides, beyond the standard
    # protected_session (which only guards the CODE checkout's copy via the fixed read_only_roots
    # property). install_open_guard takes an explicit roots list, so no change to protection.py is needed.
    uninstall_open_guard = protection.install_open_guard([root])
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

        # F1/F9: resolve every filer's Q4/Q1 rows up front -- needed for an honest per-filer-combined
        # workload estimate and for publishing q1_census present/absent later.
        rows_by_cik = {}
        for cik in ciks:
            q4_row = _select_census_row(census, cik, report_date=Q4)
            q1_row = _select_census_row(census, cik, role="verified_era")
            if q1_row is not None and q1_row["report_date"] != Q1:
                raise StageInvalidated("verified_era census row for " + cik + " is not at " + Q1 + ": "
                                       + repr(q1_row["report_date"]))
            rows_by_cik[cik] = (q4_row, q1_row)

        pins = ([manifest.file_record(root / h["path"], "overrides/" + h["path"]) for h in hits]
                + [manifest.file_record(root / n, "overrides/" + n) for n in shared_names if n not in hit_paths]
                + [census["authoritative"], census["excluded"]] + census["files"] + [replay_record, predicate_record])

        max_cik_census_bytes = max((_row_bytes(q4) + _row_bytes(q1) for q4, q1 in rows_by_cik.values()), default=0)
        workload = _workload(pins, max_cik_census_bytes, ciks)
        heavy = manifest.classify_workload(workload)
        if heavy and lease_factory is None:
            raise LeaseRefused("profile_document_run classified this build heavy and was given no lease "
                               "factory (workload=" + json.dumps(workload, sort_keys=True) + "); refusing "
                               "rather than running heavy work unleased")

        git = dict(head=manifest.git_head(paths.code_root),
                  dirty_source_digest=manifest.dirty_source_digest(paths.code_root))
        overrides_git_head = _main_overrides_git_head(paths.main_repo_root)
        overrides_dirty = _main_overrides_dirty(paths.main_repo_root)
        write_once_json(paths, "manifest.json", dict(
            stage="sp3_profile_document", run_id=paths.run_id, git=git, inputs=pins, census_run_id=census_run_id,
            replay_run_id=replay_run_id, overrides_root=str(root), overrides_git_head=overrides_git_head,
            overrides_dirty=overrides_dirty, recorded_at=recorded_at, converter_version=pd.CONVERTER_VERSION,
            ciks=ciks, hits=hits, workload=workload, heavy=heavy))

        documents: dict = {}

        def _build_documents() -> None:
            for cik in ciks:
                inputs = pf.collect_override_inputs(root, cik, hits)
                inputs["attested_under"] = {x["path"]: attested_under(paths.main_repo_root, x["path"], x["content"])
                                            for x in inputs["files"].get("bdc_xbrl_wrappers", [])}
                q4_row, q1_row = rows_by_cik[cik]
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

        # F1: the heavy work -- both census documents loaded together per filer -- runs under the shared
        # lease when the workload classifies heavy, following profile_run's/census_run's own
        # lease_factory pattern (acquired once for the whole loop); light builds run the identical code
        # unleased. The loop itself is not restructured either way.
        if heavy:
            with lease_factory() as lease:
                assert_lease_held(lease)
                _build_documents()
        else:
            _build_documents()

        owned_shared = _owned_shared_files(root, shared_names, ciks)
        shared = {n: pf.read_json(root / n) for n in shared_names}
        # I3/M2: filesystem-derived, never document-derived, and narrowed to shared files this cik set
        # actually OWNS a record in -- a shared file a filer merely mentions inside another record's text
        # is not expected to round-trip for it (materialise_overrides's own "owned" condition).
        expected = [rel for rel in rt.filesystem_expected_paths(root, ciks)
                   if rel not in pf.SHARED_FILES or rel in owned_shared]
        doc_paths = [paths.run_root / "profiles" / (cik + ".json") for cik in ciks]
        materialised = rt.load_and_materialise(doc_paths, shared_originals=shared)
        originals = {rel: pf.read_json(root / rel) for rel in expected if rel not in pf.SHARED_FILES}
        originals.update({name: value for name, value in shared.items() if name in expected})
        for rel, value in materialised.items():
            translate._write_once_ordered(paths, "roundtrip/overrides/" + rel, value)
        roundtrip = rt.roundtrip_check(materialised, originals)
        roundtrip["loader_parity"] = rt.loader_parity(root, paths.run_root / "roundtrip" / "overrides", ciks)
        parity_tally, parity_problems = _loader_parity_tally(roundtrip["loader_parity"], expected)
        roundtrip["loader_parity_tally"] = parity_tally
        if parity_problems:
            raise rt.RoundTripError("loader_parity family tally disagrees with the filesystem: "
                                    + "; ".join(parity_problems[:5]))
        roundtrip["ok"] = roundtrip["ok"] and roundtrip["loader_parity"]["ok"]

        consistency = {cik: profile_consistency.consistency_contract(
            doc, report_date=Q4, code_mirror=census_published.REPORTING_ENTITIES.get(cik, ()))
            for cik, doc in documents.items()}
        exit_body = profile_consistency.exit_test(documents, consistency, roundtrip, report_date=Q4,
                                                   expected_ciks=cohort.PILOT_CIKS)

        # F5/F9: the verdict word, insufficient_evidence count and q1_census presence published on a
        # WRITTEN COPY -- profile_consistency.exit_test's own return value is left exactly as that module
        # defines it; this module adds fields derivable from data it already has.
        def _enrich(c: str, row: dict) -> dict:
            return dict(row, consistency_verdict=consistency[c]["verdict"],
                       insufficient_evidence=consistency[c]["counts"]["insufficient_evidence"],
                       q1_census="present" if rows_by_cik[c][1] is not None else "absent")

        exit_file_body = dict(exit_body, per_cik={c: _enrich(c, row) for c, row in exit_body["per_cik"].items()})

        # F2: verify the pins before any verdict file is written, so a mid-stage change invalidates the
        # stage with NO results written, rather than leaving a (possibly PASS) exit_test.json on disk
        # under an exit-2 run.
        after = manifest.verify_inputs(dict(inputs=pins))
        if not after["ok"]:
            raise StageInvalidated("pinned inputs changed during the stage: " + json.dumps(after)[:400])

        write_once_json(paths, "results/roundtrip.json", roundtrip)
        write_once_json(paths, "results/consistency.json", consistency)
        write_once_json(paths, "results/exit_test.json", exit_file_body)
        return dict(run_id=paths.run_id, git_head=git["head"], verdict=exit_body["verdict"],
                   seconds=round(time.perf_counter() - started, 1), roundtrip_counts=roundtrip["counts"],
                   loader_parity_ok=roundtrip["loader_parity"]["ok"], missing_filers=exit_body["missing_filers"],
                   per_cik={c: _enrich(c, dict(criterion_1=p["criterion_1"], resolver=p["resolver"],
                                               consistency=p["consistency"], resolved=p["resolved"],
                                               stubs=p["stubs"], counts=p["consistency_counts"]))
                           for c, p in exit_body["per_cik"].items()})
    finally:
        # F8: a preservation failure outranks (and chains onto, via Python's implicit exception context)
        # the body's own exception, matching protection.protected_session's own documented convention.
        uninstall_open_guard()
        after_guard = protection.inventory(guard_specs)
        comparison = protection.compare(before_guard, after_guard)
        receipt_body = protection.summarize(before_guard, after_guard, comparison)
        try:
            write_once_json(paths, GUARD_RECEIPT_RELATIVE, receipt_body)
        except PathError:
            pass   # already written by an earlier attempt in this run root
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
        head = manifest.git_head(paths.code_root)

        def lease_factory():
            return protection.shared_heavy_lease(paths, head=head)

        with protection.protected_session(paths, receipt=receipt):
            summary = run_stage(paths, census_run_id=args.census_run_id, replay_run_id=args.replay_run_id,
                                ciks=args.cik, lease_factory=lease_factory)
    except StageInvalidated as exc:
        print("STAGE INVALIDATED: " + _ascii(str(exc)))
        return EXIT_INVALIDATED
    except PreservationError as exc:
        print("PRESERVATION FAILED: " + _ascii(str(exc)))
        return EXIT_INVALIDATED
    except (pi.InceptionError, rt.RoundTripError, pd.ProfileDocumentError) as exc:
        print("DOCUMENT INVALID: " + _ascii(str(exc)))
        return EXIT_INVALIDATED
    except (PathError, pf.FamilyError, LeaseRefused) as exc:
        print("REFUSED: " + _ascii(str(exc)))
        return EXIT_REFUSED
    except Exception as exc:
        print("UNEXPECTED ERROR: " + _ascii(type(exc).__name__ + ": " + str(exc)))
        return EXIT_UNEXPECTED
    print(json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=True))
    return 0 if summary["verdict"] == "PASS" else EXIT_FAIL


if __name__ == "__main__":
    raise SystemExit(main())
