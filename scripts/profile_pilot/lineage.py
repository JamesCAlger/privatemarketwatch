"""Producer lineage shared by the Stage B consumers (profile, translate, contracts).

ONE reader of a census root's authoritative listing (`load_authoritative_census`) and ONE
check that a profile root was derived from that same census root
(`check_profile_lineage`). Both fail closed:

  - every listing row in scope must carry `validation_verdict` and it must equal "pass"
    (a missing field is refused, never defaulted);
  - the profile summary's `census_run_id` must equal the census root the consumer pins,
    and every derived profile's `census_sha256` / `census_relative` must equal the
    authoritative row for its (cik, role).

Any mismatch raises StageInvalidated (stage runners exit 2). Reading the listing and
the summary is light; census files are hashed only when the caller reads them.
"""
from __future__ import annotations

import json
from pathlib import Path

from scripts.profile_pilot import manifest
from scripts.profile_pilot.manifest import StageInvalidated
from scripts.profile_pilot.paths import PilotPaths, resolve_paths

AUTHORITATIVE_RELATIVE = "results/authoritative.json"
EXCLUDED_RELATIVE = "results/excluded.json"
PROFILE_SUMMARY_RELATIVE = "results/profile_summary.json"
# Task 6 era -> census role (kept equal to profile.ERA_ROLES; tested).
ERA_ROLES = {"q1": "q1", "same_era": "verified_era"}


def sibling_root(paths: PilotPaths, run_id: str) -> PilotPaths:
    """Another run root under the same data root (validated like any run id)."""
    return resolve_paths(main_repo_root=paths.main_repo_root, data_root=paths.data_root,
                         code_root=paths.code_root, run_id=run_id)


def load_authoritative_census(paths: PilotPaths, run_id: str, *, roles, ciks, label_prefix: str = "",
                              require_excluded: bool = False, hash_files: bool = True) -> dict:
    """The authoritative listing of census root `run_id`, restricted to `roles` x `ciks`.

    Returns dict(run_id, run_root, paths, authoritative, excluded, listing, rows, files) where
    rows maps (cik, role) -> the listing row plus `record` (the census file re-hashed and
    checked against the listing when hash_files, else None). Raises StageInvalidated when
    the listing is missing, a row in scope lacks `validation_verdict` or is not "pass", a
    (cik, role) is listed twice, or a census file differs from its listed sha256.
    """
    census_paths = sibling_root(paths, run_id)
    root = census_paths.run_root
    authoritative = manifest.file_record(root / AUTHORITATIVE_RELATIVE, "census_root/" + AUTHORITATIVE_RELATIVE)
    if authoritative["status"] != "present":
        raise StageInvalidated("census root has no " + AUTHORITATIVE_RELATIVE + ": " + str(root))
    excluded = manifest.file_record(root / EXCLUDED_RELATIVE, "census_root/" + EXCLUDED_RELATIVE)
    if require_excluded and excluded["status"] != "present":
        raise StageInvalidated("pinned input missing: census_root/" + EXCLUDED_RELATIVE + " (" + str(root) + ")")
    listing = json.loads(Path(authoritative["path"]).read_text(encoding="ascii"))
    roles, ciks = tuple(roles), set(ciks)
    rows, files = {}, []
    for row in listing["fund_quarters"]:
        if row["cik"] not in ciks or row["role"] not in roles:
            continue
        relative = row["census_relative"]
        if "validation_verdict" not in row:
            raise StageInvalidated("authoritative listing row has no validation_verdict: " + relative)
        if row["validation_verdict"] != "pass":
            raise StageInvalidated("authoritative listing holds a non-pass census ("
                                   + str(row["validation_verdict"]) + "): " + relative)
        key = (row["cik"], row["role"])
        if key in rows:
            raise StageInvalidated("authoritative listing holds two censuses for " + repr(key))
        record = None
        if hash_files:
            record = manifest.file_record(root / relative, label_prefix + relative)
            if record["status"] != "present" or record["sha256"] != row["census_sha256"]:
                raise StageInvalidated("census file differs from the authoritative listing: " + relative)
            files.append(record)
        rows[key] = dict(row, record=record)
    return dict(run_id=run_id, run_root=str(root), paths=census_paths, authoritative=authoritative,
                excluded=excluded, listing=listing, rows=rows, files=files)


def check_profile_lineage(summary: dict, *, census_run_id: str, census_rows: dict, ciks, eras) -> dict:
    """Refuse a profile root that was not derived from census root `census_run_id`.

    `summary` is the profile root's results/profile_summary.json body; `census_rows` the
    `rows` of load_authoritative_census for that census root. Every DERIVED profile of
    (ciks x eras) must name the authoritative census row of its (cik, role) by sha256 and
    relative path. Returns the record of what was checked.
    """
    claimed = summary.get("census_run_id")
    if claimed != census_run_id:
        raise StageInvalidated("profile root was derived from census root " + repr(claimed)
                               + ", not the pinned census root " + repr(census_run_id))
    checked = []
    for cik in ciks:
        for era in eras:
            entry = (summary.get("profiles") or {}).get(cik + "/" + era) or {}
            if entry.get("status") != "derived":
                continue
            role = ERA_ROLES[era]
            row = census_rows.get((cik, role))
            if row is None:
                raise StageInvalidated("profile " + cik + "/" + era + " has no authoritative census row for role "
                                       + role + " in " + census_run_id)
            if entry.get("census_sha256") != row["census_sha256"] \
                    or entry.get("census_relative") != row["census_relative"]:
                raise StageInvalidated("profile " + cik + "/" + era + " was derived from census "
                                       + str(entry.get("census_relative")) + " sha256 "
                                       + str(entry.get("census_sha256")) + "; the authoritative listing of "
                                       + census_run_id + " holds " + row["census_relative"] + " sha256 "
                                       + row["census_sha256"])
            checked.append(dict(profile=cik + "/" + era, role=role, census_relative=row["census_relative"],
                                census_sha256=row["census_sha256"]))
    return dict(census_run_id=census_run_id, checked=checked, ok=True)


def check_profile_document_source(document: dict, *, census_sha256: str, label: str) -> None:
    """The derived profile document's own `source` must name the same census bytes."""
    source = (document or {}).get("source") or {}
    if source.get("census_sha256") != census_sha256:
        raise StageInvalidated("profile document source differs from its lineage (" + label + "): "
                               + str(source.get("census_sha256")) + " vs " + census_sha256)
