"""Task 6 stage: derive Q1 and same-era profiles from the authoritative census, then score M1.

    python -m scripts.profile_pilot.profile_run run --data-root D --run-id stageb-profile-<stamp>
        --census-run-id stageb-20260929t004819z [--main-root M] [--cik C ...]

Order (ruling R26), all in a NEW write-once run root:
  1. pin the census root: results/authoritative.json and every census file it lists that
     this stage reads (sha256 re-checked against the listing);
  2. freeze wrapper_key_inventory (Task 1 mechanism); its content hash must equal the
     census root's frozen inventory, else StageInvalidated (exit 2);
  3. freeze inventories/m1_comparison_semantics.json;
  4. write manifest.json (Task 1 build_manifest + the census-source pins + the eed082b
     wrapper bytes re-materialised in THIS run root);
  5. derive every profile (profile.derive_profile: no wrapper access) as a cached stage
     at profiles/{cik}/{q1|same_era}.json;
  6. only then load wrappers (m1.load_wrapper) and score each era into its own
     results/m1_q1.json / results/m1_same_era.json (explicit per-era paths, no glob);
  7. re-verify every pinned input; a change invalidates the stage.

Reading census JSON is light (no XBRL instance is parsed); each cached stage still
declares a complete typed workload. Exit codes: 0 ok, 2 stage invalidated, 4 refused.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time

from scripts.profile_pilot import cohort, lineage, m1, manifest, profile, protection
from scripts.profile_pilot.manifest import StageInvalidated
from scripts.profile_pilot.paths import (PathError, PilotPaths, discover_main_root, resolve_paths,
                                         write_once_json)

CODE_ROOT = Path(__file__).resolve().parents[2]
EXIT_INVALIDATED = 2
EXIT_REFUSED = 4
RUN_PREFIX = "stageb-profile-"
CODE_FILES = ("scripts/profile_pilot/profile.py", "scripts/profile_pilot/envelope.py",
              "scripts/profile_pilot/census.py", "scripts/profile_pilot/census_detect.py",
              "scripts/profile_pilot/schemas/filer_profile_v0.schema.json",
              "scripts/profile_pilot/schemas/filer_profile_document_v0.schema.json")
GROUPS = {"verified_era_reconciled": "reconciled", "verified_era_unreconciled": "verified_era_unreconciled"}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def default_run_id(now: datetime | None = None) -> str:
    return RUN_PREFIX + (now or datetime.now(timezone.utc)).strftime("%Y%m%dt%H%M%Sz")


def _peak_bytes() -> int | None:
    try:
        import psutil
        info = psutil.Process(os.getpid()).memory_info()
        return int(getattr(info, "peak_wset", 0) or info.rss)
    except Exception:  # measurement only; never a gate
        return None


# ---------------------------------------------------------------- census root pins

def census_root(paths: PilotPaths, census_run_id: str) -> PilotPaths:
    return resolve_paths(main_repo_root=paths.main_repo_root, data_root=paths.data_root,
                         code_root=paths.code_root, run_id=census_run_id)


def pin_census(census_paths: PilotPaths, ciks) -> dict:
    """The authoritative listing and every census file this stage will read, re-hashed.

    Through the shared lineage reader: a row without `validation_verdict` or with any
    verdict other than "pass" is refused (ruling I8; no fail-open default)."""
    era_of = {role: era for era, role in profile.ERA_ROLES.items()}
    census = lineage.load_authoritative_census(census_paths, census_paths.run_id, roles=tuple(era_of), ciks=ciks)
    selected, files = {}, []
    for (cik, role), row in census["rows"].items():
        record = row["record"]
        record.update(cik=cik, era=era_of[role], role=role, report_date=row["report_date"],
                      fingerprint=row["fingerprint"])
        selected[(cik, era_of[role])] = row
        files.append(record)
    return dict(run_id=census_paths.run_id, run_root=census["run_root"], authoritative=census["authoritative"],
                excluded=census["excluded"], census_files=files, selected=selected,
                authoritative_git_head=census["listing"].get("git_head"))


def freeze_and_check_inventory(paths: PilotPaths, census_paths: PilotPaths) -> dict:
    state = manifest.freeze_inventory(paths, "wrapper_key_inventory", manifest.wrapper_key_inventory(paths.code_root))
    theirs = census_paths.run_root / "inventories" / "wrapper_key_inventory.json"
    manifest.load_inventory(census_paths, "wrapper_key_inventory")  # digest check of the census root's copy
    body = json.loads(theirs.read_text(encoding="ascii"))
    if body["content_sha256"] != state["content_sha256"]:
        raise StageInvalidated("wrapper_key_inventory content differs from the census root's ("
                               + state["content_sha256"] + " vs " + body["content_sha256"] + "): stage invalid")
    return dict(this_run=state, census_root=manifest.file_record(theirs, "census_root/inventories/"
                                                                         "wrapper_key_inventory.json"),
                census_root_content_sha256=body["content_sha256"], equal=True)


# ---------------------------------------------------------------- profiles (derivation: no wrapper)

def anchors_for(paths: PilotPaths, cik: str, report_date: str) -> tuple[dict, list]:
    folder = paths.code_root / manifest.ANCHOR_DIR / str(int(cik))
    available = sorted(p.stem for p in folder.glob("*.json")) if folder.is_dir() else []
    target = folder / (report_date + ".json")
    relative = manifest.ANCHOR_DIR + "/" + str(int(cik)) + "/" + report_date + ".json"
    record = manifest.file_record(target, "anchor/" + relative)
    if record["status"] != "present":
        return dict(status="stub", available=available), [record]
    content = json.loads(target.read_text(encoding="utf-8"))
    return dict(status="copied", provenance="inherited", inherited_from=relative,
                files=[dict(path=relative, sha256=record["sha256"], report_date=report_date, content=content)],
                available=available), [record]


def write_profile(paths: PilotPaths, cik: str, era: str, row: dict, *, census_paths: PilotPaths,
                  recorded_at: str) -> dict:
    census_file = census_paths.run_root / row["census_relative"]
    census_record = manifest.file_record(census_file, row["census_relative"])
    if census_record.get("sha256") != row["census_sha256"]:
        raise StageInvalidated("census file changed before derivation: " + row["census_relative"])
    anchors, anchor_records = anchors_for(paths, cik, row["report_date"])
    code = [manifest.file_record(paths.code_root / rel, "code/" + rel) for rel in CODE_FILES]
    identity = manifest.cache_identity("profile", dict(
        cik=cik, era=era, report_date=row["report_date"], recorded_at=recorded_at,
        census=census_record, census_fingerprint=row["fingerprint"], anchors=anchor_records, code=code),
        collector_version=profile.PROFILE_VERSION)
    size = census_record["bytes"]
    workload = dict(ciks=[cik], instance_count=0, full_cache_scan=False, pipeline_cik_count=0,
                    est_seconds=round(2 + size / 5e6, 1), est_bytes=int(300e6 + 20 * size))

    def compute() -> dict:
        outer = json.loads(census_file.read_text(encoding="ascii"))
        if outer.get("identity", {}).get("fingerprint") != row["fingerprint"] or outer.get("complete") is not True:
            raise StageInvalidated("census result identity differs from the authoritative listing: "
                                   + row["census_relative"])
        doc = outer["result"]
        source = dict(cik=cik, report_date=row["report_date"], role=row["role"],
                      census_relative=row["census_relative"], census_sha256=row["census_sha256"],
                      fingerprint=row["fingerprint"], accession_number=doc["document"].get("accession_number"),
                      form_type=doc["document"].get("form_type"))
        derived = profile.derive_profile(doc, source=source, era=era, recorded_at=recorded_at, anchors=anchors)
        profile.validate_document(derived)
        return derived

    started = time.perf_counter()
    out = manifest.run_cached_stage(paths, "profiles/" + cik + "/" + era + ".json", identity, compute,
                                    workload=workload)
    target = Path(out["path"])
    return dict(status="derived", relative="profiles/" + cik + "/" + era + ".json", path=str(target),
                sha256=manifest.sha256_file(target), cache=out["cache"], seconds=round(time.perf_counter() - started, 2),
                workload=workload, document=out["result"])


# ---------------------------------------------------------------- M1 (wrappers loaded only here)

def _wrapper_pin(paths: PilotPaths, cik: str, era: str, inventory: dict, verified: dict) -> dict:
    if era == "q1":
        entry = inventory["ciks"][cik]
        return dict(commit="HEAD", path=entry["path"], git_blob=entry.get("git_blob"), sha256=entry["sha256"],
                    rule="HEAD wrapper, pinned by the frozen wrapper_key_inventory")
    then = verified["wrappers"][cik]["verified_era"]
    return dict(commit=then["commit"], path=str(paths.run_root / "inputs" / "verified_era_wrappers" / (cik + ".json")),
                git_blob=then["git_blob"], sha256=then["sha256"],
                rule="wrapper bytes at sign-off commit, re-materialised in this run root")


def _unavailable(keys, reason: str, semantics: dict) -> dict:
    records = [dict(key=k, section=m1.section_of(k), container=False, family=None, reason="insufficient_evidence",
                    note=reason, **{"class": "unresolved"}) for k in keys]
    return dict(keys=records, **m1.summarise(records, semantics["classes"], semantics["reasons"]))


def score_era(paths: PilotPaths, era: str, profiles: dict, inventory: dict, semantics: dict,
              verified: dict, ciks, sem_state: dict) -> dict:
    per_cik, all_records, groups = {}, [], {"reconciled": [], "verified_era_unreconciled": []}
    for cik in ciks:
        keys = inventory["ciks"][cik]["keys"]
        pin = _wrapper_pin(paths, cik, era, inventory, verified)
        entry = profiles[(cik, era)]
        if entry["status"] != "derived":
            result = _unavailable(keys, "census unavailable for this era: " + entry.get("reason", ""),
                                  semantics)
        else:
            wrapper = m1.load_wrapper(pin["path"], expected_sha256=pin["sha256"])
            result = m1.compare_to_wrapper(entry["document"], wrapper, cik=cik, inventory_keys=keys,
                                           semantics=semantics)
        body = dict(wrapper=pin, profile={k: entry.get(k) for k in ("status", "relative", "sha256", "reason")},
                    census={k: entry.get(k) for k in ("census_relative", "census_sha256", "report_date",
                                                      "form_type")}, **result)
        if era == "same_era":
            label = verified["ledger"]["ciks"].get(cik, {}).get("label", "verified_era_evidence_missing")
            body["verified_era_label"] = label
            groups.setdefault(GROUPS.get(label, label), []).append(cik)
        per_cik[cik] = body
        all_records += result["keys"]
    totals = m1.summarise(all_records, semantics["classes"], semantics["reasons"])
    out = dict(era=era, run_id=paths.run_id, semantics=sem_state,
               inventory=dict(content_sha256=manifest.digest(inventory)), ciks=per_cik,
               totals={k: totals[k] for k in ("denominator", "counts", "unresolved_by_reason", "by_section",
                                              "leaf_only")},
               disclaimer=m1.DISCLAIMER)
    if era == "same_era":
        out["groups"] = {}
        for name, members in groups.items():
            records = [r for c in members for r in per_cik[c]["keys"]]
            summary = m1.summarise(records, semantics["classes"], semantics["reasons"])
            out["groups"][name] = dict(ciks=members, denominator=summary["denominator"], counts=summary["counts"],
                                       unresolved_by_reason=summary["unresolved_by_reason"])
        out["group_rule"] = ("reporting split only: every CIK stays in the fixed denominator; label from the "
                             "q1p3_20260831 findings ledger via the Task 1 manifest")
    return out


# ---------------------------------------------------------------- the stage

def run_stage(paths: PilotPaths, *, census_run_id: str, ciks=None, recorded_at: str | None = None) -> dict:
    ciks = list(ciks or cohort.PILOT_CIKS)
    recorded_at = recorded_at or _now()
    started = time.perf_counter()
    census_paths = census_root(paths, census_run_id)
    pins = pin_census(census_paths, ciks)
    inventory_check = freeze_and_check_inventory(paths, census_paths)
    inventory = manifest.load_inventory(paths, "wrapper_key_inventory")
    sem_state = m1.freeze_semantics(paths, inventory)
    primary = manifest.load_inventory(census_paths, "primary_quarter_inventory")
    built = manifest.build_manifest(paths, primary_inventory=primary)
    built["materialised"] = manifest.materialise_verified_era_wrappers(paths, built["verified_era"])
    built["census_source"] = dict({k: v for k, v in pins.items() if k != "selected"},
                                  wrapper_key_inventory=inventory_check)
    semantics_record = manifest.file_record(sem_state["path"], "run/" + m1.SEMANTICS_RELATIVE)
    built["inputs"] += ([pins["authoritative"], pins["excluded"], inventory_check["census_root"], semantics_record]
                        + [{k: r[k] for k in ("label", "path", "status", "sha256", "bytes")}
                           for r in pins["census_files"]] + built["materialised"])
    built["inventories"] = manifest.inventory_states(paths)
    built["m1_comparison_semantics"] = sem_state
    built["stage"] = dict(ciks=ciks, eras=list(profile.ERAS), recorded_at=recorded_at,
                          census_run_id=census_run_id)
    built["input_verification"] = manifest.verify_inputs(built)
    if not built["input_verification"]["ok"]:
        raise StageInvalidated("pinned inputs changed while building the manifest")
    built["frozen_utc"] = _now()
    write_once_json(paths, "manifest.json", built)

    profiles = {}
    for cik in ciks:
        for era in profile.ERAS:
            row = pins["selected"].get((cik, era))
            if row is None:
                profiles[(cik, era)] = dict(status="unavailable", reason="no authoritative census for role "
                                            + profile.ERA_ROLES[era])
                continue
            profiles[(cik, era)] = dict(write_profile(paths, cik, era, row, census_paths=census_paths,
                                                      recorded_at=recorded_at),
                                        census_relative=row["census_relative"], census_sha256=row["census_sha256"],
                                        report_date=row["report_date"])
            profiles[(cik, era)]["form_type"] = profiles[(cik, era)]["document"]["form_type"]
    derived_utc = _now()

    semantics = m1.load_semantics(paths)
    results = {}
    for era in profile.ERAS:
        scored = score_era(paths, era, profiles, inventory, semantics, built["verified_era"], ciks, sem_state)
        target = write_once_json(paths, "results/m1_" + era + ".json", scored)
        results[era] = str(target)
    after = manifest.verify_inputs(built)
    if not after["ok"]:
        raise StageInvalidated("pinned inputs changed during the stage: " + json.dumps(after)[:400])
    summary = dict(
        run_id=paths.run_id, git_head=built["git"]["head"], dirty_source_digest=built["git"]["dirty_source_digest"],
        census_run_id=census_run_id, recorded_at=recorded_at, derived_utc=derived_utc, finished_utc=_now(),
        seconds=round(time.perf_counter() - started, 1), peak_working_set_bytes=_peak_bytes(),
        results=results, input_verification_after=after, disclaimer=m1.DISCLAIMER,
        profiles={cik + "/" + era: dict({k: v for k, v in p.items() if k != "document"},
                                        counts=(p.get("document") or {}).get("counts"),
                                        sections={n: dict(status=s["status"], entries=len(s["entry_ids"]),
                                                          stubs=len(s["stub_ids"]))
                                                  for n, s in ((p.get("document") or {}).get("sections") or {}).items()})
                  for (cik, era), p in profiles.items()})
    write_once_json(paths, "results/profile_summary.json", summary)
    return summary


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="ascii", errors="backslashreplace")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    cmd = sub.add_parser("run")
    cmd.add_argument("--main-root", type=Path, default=None)
    cmd.add_argument("--data-root", type=Path, required=True)
    cmd.add_argument("--code-root", type=Path, default=None)
    cmd.add_argument("--run-id", default=None)
    cmd.add_argument("--census-run-id", required=True)
    cmd.add_argument("--cik", action="append", default=None)
    args = parser.parse_args(argv)
    try:
        main_root = args.main_root or discover_main_root(CODE_ROOT)
        paths = resolve_paths(main_repo_root=main_root, data_root=args.data_root,
                              code_root=args.code_root or CODE_ROOT, run_id=args.run_id or default_run_id())
        receipt = "verification/" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_profile_preservation.json"
        with protection.protected_session(paths, receipt=receipt):
            summary = run_stage(paths, census_run_id=args.census_run_id, ciks=args.cik)
    except StageInvalidated as exc:
        print("STAGE INVALIDATED: " + str(exc).encode("ascii", "backslashreplace").decode("ascii"))
        return EXIT_INVALIDATED
    except PathError as exc:
        print("REFUSED: " + str(exc).encode("ascii", "backslashreplace").decode("ascii"))
        return EXIT_REFUSED
    print("run: " + summary["run_id"] + " | git_head " + summary["git_head"] + " | " + str(summary["seconds"]) + " s")
    for era, path in summary["results"].items():
        body = json.loads(Path(path).read_text(encoding="ascii"))
        print("M1 " + era + ": " + json.dumps(body["totals"]["counts"], sort_keys=True) + " unresolved "
              + json.dumps(body["totals"]["unresolved_by_reason"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
