"""Task 7 stage: translate the Task 6 profiles into wrapper v3 files and test production admission.

    python -m scripts.profile_pilot.translate_run run --data-root D --profile-run-id P
        [--run-id stageb-translate-<stamp>] [--main-root M] [--cik C ...]

Order, all in a NEW write-once run root (R18/R26 pattern):
  1. pin the profile root: manifest.json, results/profile_summary.json,
     inventories/m1_comparison_semantics.json and every profile file read (sha256 checked
     against profile_summary); lineage (I1): the census root the profile root names must
     list, per derived profile, the census sha256 that profile was derived from
     (lineage.check_profile_lineage; its authoritative.json is pinned too);
  2. pin the base wrappers: HEAD (tracked file == `git show HEAD:` bytes, blob recorded) and
     the eed082b bytes the profile root re-materialised (sha from its manifest, blob and
     sha re-derived from git);
  3. pin the production wrapper schema, the loader and the adapter code (sha256 + blob);
  4. write manifest.json;
  5. per CIK and era, a cached stage (typed light workload) translates the profile and
     writes translate/wrappers_<era>/<cik10>.json + translate/<cik>/<era>.sidecar.json;
  6. per era, production loader admission over the generated directory (and the base
     directory for spec parity) inside restored_wrapper_context;
  7. re-verify every pinned input, then write results/translate_summary.json.
Nothing is written under data/overrides/; generated wrappers are never promoted.
Exit codes: 0 ok, 2 stage invalidated, 4 refused.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

from scripts.profile_pilot import cohort, lineage, m1, manifest, profile, protection, translate
from scripts.profile_pilot.manifest import StageInvalidated
from scripts.profile_pilot.paths import (PathError, PilotPaths, discover_main_root, resolve_paths,
                                         write_once_json)

CODE_ROOT = Path(__file__).resolve().parents[2]
EXIT_INVALIDATED = 2
EXIT_REFUSED = 4
RUN_PREFIX = "stageb-translate-"
CODE_FILES = (translate.WRAPPER_SCHEMA_RELATIVE, translate.LOADER_RELATIVE,
              "scripts/profile_pilot/translate.py", "scripts/profile_pilot/translate_run.py",
              "scripts/profile_pilot/lineage.py", "pipeline/staging_bdc.py",
              "pipeline/wrapper_content_signatures.py",
              "scripts/profile_pilot/envelope.py", "scripts/profile_pilot/m1.py",
              "scripts/profile_pilot/profile.py", "pipeline/extract_companyfacts.py",
              "scripts/profile_pilot/schemas/filer_profile_v0.schema.json",
              "scripts/profile_pilot/schemas/filer_profile_document_v0.schema.json")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def default_run_id(now: datetime | None = None) -> str:
    return RUN_PREFIX + (now or datetime.now(timezone.utc)).strftime("%Y%m%dt%H%M%Sz")


def _record(path, label: str, *, blob_of: str | None = None, code_root: Path | None = None) -> dict:
    record = manifest.file_record(path, label)
    if record["status"] != "present":
        raise StageInvalidated("pinned input missing: " + label + " (" + str(path) + ")")
    if blob_of is not None:
        record["git_blob"] = cohort.git_blob(code_root, blob_of)
    return record


def pin_profile_root(paths: PilotPaths, profile_run_id: str, ciks) -> dict:
    other = resolve_paths(main_repo_root=paths.main_repo_root, data_root=paths.data_root,
                          code_root=paths.code_root, run_id=profile_run_id)
    root = other.run_root
    records = dict(manifest=_record(root / "manifest.json", "profile_root/manifest.json"),
                   summary=_record(root / "results" / "profile_summary.json", "profile_root/results/profile_summary.json"),
                   semantics=_record(root / m1.SEMANTICS_RELATIVE, "profile_root/" + m1.SEMANTICS_RELATIVE))
    summary = json.loads(Path(records["summary"]["path"]).read_text(encoding="ascii"))
    body = json.loads(Path(records["manifest"]["path"]).read_text(encoding="ascii"))
    # Lineage (I1), transitively: the profile root names its census root; that root's
    # authoritative listing must hold, per derived profile, the census bytes it was derived from.
    census_run_id = summary.get("census_run_id")
    if not census_run_id or (body.get("census_source") or {}).get("run_id") != census_run_id:
        raise StageInvalidated("profile root summary and manifest disagree on the census root: "
                               + repr(census_run_id) + " vs " + repr((body.get("census_source") or {}).get("run_id")))
    census = lineage.load_authoritative_census(paths, census_run_id, roles=tuple(lineage.ERA_ROLES.values()),
                                               ciks=ciks, label_prefix="census_root/", hash_files=False)
    checked = lineage.check_profile_lineage(summary, census_run_id=census_run_id, census_rows=census["rows"],
                                            ciks=ciks, eras=profile.ERAS)
    profiles = {}
    for cik in ciks:
        for era in profile.ERAS:
            relative = "profiles/" + cik + "/" + era + ".json"
            listed = summary["profiles"].get(cik + "/" + era) or {}
            if listed.get("status") != "derived":
                profiles[(cik, era)] = dict(status="unavailable", reason="profile not derived: "
                                            + str(listed.get("reason")))
                continue
            record = _record(root / relative, "profile_root/" + relative)
            if record["sha256"] != listed.get("sha256"):
                raise StageInvalidated("profile file differs from profile_summary: " + relative)
            profiles[(cik, era)] = dict(status="present", relative=relative, record=record,
                                        census_sha256=listed["census_sha256"])
    return dict(run_id=profile_run_id, run_root=str(root), git_head=summary.get("git_head"),
                records=records, profiles=profiles, verified_era=body["verified_era"],
                census_root=dict(run_id=census_run_id, run_root=census["run_root"],
                                 authoritative=census["authoritative"], lineage=checked))


def pin_base_wrappers(paths: PilotPaths, pins: dict, ciks) -> dict:
    code = paths.code_root
    out = {}
    for cik in ciks:
        relative = manifest.WRAPPER_DIR + "/" + cik + ".json"
        head = manifest.historical_wrapper(code, cik, "HEAD")
        record = _record(code / relative, "base_wrapper/q1/" + cik, blob_of=relative, code_root=code)
        # Blob equality (git hash-object applies the checkout filters, e.g. CRLF), not raw bytes.
        if head["status"] != "present" or record["git_blob"] != head["git_blob"]:
            raise StageInvalidated("tracked wrapper differs from HEAD: " + relative)
        record.update(commit="HEAD", commit_sha=manifest.git_head(code), head_git_blob=head["git_blob"])
        then_pin = pins["verified_era"]["wrappers"][cik]["verified_era"]
        then = manifest.historical_wrapper(code, cik, then_pin["commit"])
        same = _record(Path(pins["run_root"]) / "inputs" / "verified_era_wrappers" / (cik + ".json"),
                       "base_wrapper/same_era/" + cik)
        if not (then["status"] == "present" and same["sha256"] == then_pin["sha256"] == then["sha256"]
                and then["git_blob"] == then_pin["git_blob"]):
            raise StageInvalidated("verified-era wrapper bytes differ from their pins: " + cik)
        same.update(commit=then_pin["commit"], git_blob=then["git_blob"])
        out[cik] = dict(q1=record, same_era=same)
    return out


def build_manifest(paths: PilotPaths, pins: dict, bases: dict, *, ciks, as_of: str) -> dict:
    code = [_record(paths.code_root / rel, "code/" + rel, blob_of=rel, code_root=paths.code_root)
            for rel in CODE_FILES]
    profile_records = [p["record"] for p in pins["profiles"].values() if p["status"] == "present"]
    base_records = [r for b in bases.values() for r in (b["q1"], b["same_era"])]
    keep = ("label", "path", "status", "sha256", "bytes")
    inputs = ([{k: r[k] for k in keep} for r in list(pins["records"].values()) + profile_records + base_records]
              + [{k: r[k] for k in keep} for r in code]
              + [{k: pins["census_root"]["authoritative"][k] for k in keep}])
    built = dict(manifest_version=manifest.MANIFEST_VERSION, stage="translate", run_id=paths.run_id,
                 roots=dict(main_repo_root=str(paths.main_repo_root), code_root=str(paths.code_root),
                            data_root=str(paths.data_root), run_root=str(paths.run_root)),
                 protected_roots=[str(r) for r in paths.protected_roots],
                 git=dict(head=manifest.git_head(paths.code_root),
                          dirty_source_digest=manifest.dirty_source_digest(paths.code_root)["sha256"]),
                 profile_root=dict(run_id=pins["run_id"], run_root=pins["run_root"], git_head=pins["git_head"],
                                   files={k: v for k, v in pins["records"].items()},
                                   profiles={c + "/" + e: p for (c, e), p in pins["profiles"].items()}),
                 census_root=pins["census_root"],
                 base_wrappers=bases, code=code, inputs=inputs,
                 stage_config=dict(ciks=list(ciks), eras=list(profile.ERAS), as_of=as_of,
                                   translate_version=translate.TRANSLATE_VERSION,
                                   translations=[dict(t, wrapper_path=list(t["wrapper_path"]))
                                                 for t in translate.TRANSLATIONS]))
    built["input_verification"] = manifest.verify_inputs(built)
    if not built["input_verification"]["ok"]:
        raise StageInvalidated("pinned inputs changed while building the manifest")
    return built


def translate_one(paths: PilotPaths, cik: str, era: str, pin: dict, base: dict, *, as_of: str, code: list) -> dict:
    identity = manifest.cache_identity("translate", dict(cik=cik, era=era, as_of=as_of, profile=pin["record"],
                                                          base_wrapper=base, code=code),
                                       collector_version=translate.TRANSLATE_VERSION)
    workload = dict(ciks=[cik], instance_count=0, full_cache_scan=False, pipeline_cik_count=0,
                    est_seconds=2.0, est_bytes=int(200e6))

    def compute() -> dict:
        doc = json.loads(Path(pin["record"]["path"]).read_text(encoding="ascii"))
        if doc.get("complete") is not True:
            raise StageInvalidated("profile result is incomplete: " + pin["relative"])
        prof = doc["result"]
        profile.validate_document(prof)
        lineage.check_profile_document_source(prof, census_sha256=pin["census_sha256"], label=pin["relative"])
        base_wrapper = m1.load_wrapper(base["path"], expected_sha256=base["sha256"])
        result = translate.to_wrapper_v3(prof, base_wrapper, prof["report_date"], prof["form_type"], as_of=as_of)
        wrapper = translate.write_wrapper(paths, cik, era, result["wrapper"])
        # The sidecar is written after loader admission (it carries consumer_parity).
        return dict(wrapper=wrapper, sidecar=result["sidecar"], extra=dict(
            profile_file=dict(relative=pin["relative"], sha256=pin["record"]["sha256"]),
            base_wrapper={k: base.get(k) for k in ("label", "commit", "git_blob", "sha256", "path")}))

    out = manifest.run_cached_stage(paths, "translate/" + cik + "/" + era + ".stage.json", identity, compute,
                                    workload=workload)
    return out["result"]


def finish_sidecar(paths: PilotPaths, cik: str, era: str, result: dict, admission: dict) -> dict:
    parity = translate.consumer_parity(admission.get("spec_parity"), result["sidecar"]["created_objects"])
    extra = dict(result["extra"], loader_admission={k: v for k, v in admission.items() if k != "spec"},
                 consumer_parity=parity)
    written = translate.write_sidecar(paths, cik, era, result["sidecar"], result["wrapper"], extra=extra)
    return dict(written, consumer_parity=parity)


def _row(result: dict, admission: dict, sidecar: dict) -> dict:
    side = result["sidecar"]
    return dict(wrapper=result["wrapper"], sidecar={k: sidecar[k] for k in ("path", "relative", "sha256")},
                fields_added=side["fields_added"], created_objects=side["created_objects"],
                consumer_parity=sidecar["consumer_parity"],
                sections_translated=side["sections_translated"], entries_used=side["entries_used"],
                translated=[dict(profile_key=t["profile_key"], wrapper_pointer=t["wrapper_pointer"], via=t["via"],
                                 coverage_class=t["coverage_class"], equal_to_base=t["equal_to_base"])
                            for t in side["translated"]],
                not_expressible=[dict(profile_key=n["profile_key"], reasons=n["reasons"], entry_ids=n["entry_ids"],
                                      wrapper_pointer=n["wrapper_pointer"], detail=n["detail"],
                                      would_create=n.get("would_create", []))
                                 for n in side["not_expressible"]],
                no_wrapper_field_keys=len(side["no_wrapper_field"]),
                inherited_overlay=dict(field_count=side["inherited_overlay"]["field_count"],
                                       sidecar=sidecar["relative"]),
                coverage=side["coverage"], parity=side["parity"], schema_validation=side["schema_validation"],
                loader_admission=admission)


def run_stage(paths: PilotPaths, *, profile_run_id: str, ciks=None, as_of: str | None = None) -> dict:
    ciks = list(ciks or cohort.PILOT_CIKS)
    as_of = as_of or _now()
    started = time.perf_counter()
    pins = pin_profile_root(paths, profile_run_id, ciks)
    bases = pin_base_wrappers(paths, pins, ciks)
    built = build_manifest(paths, pins, bases, ciks=ciks, as_of=as_of)
    built["frozen_utc"] = _now()
    write_once_json(paths, "manifest.json", built)
    code = built["code"]
    results = {}
    for cik in ciks:
        for era in profile.ERAS:
            pin = pins["profiles"][(cik, era)]
            if pin["status"] != "present":
                results[(cik, era)] = dict(status="unavailable", reason=pin["reason"])
                continue
            results[(cik, era)] = translate_one(paths, cik, era, pin, bases[cik][era], as_of=as_of, code=code)
    admissions = {}
    base_dirs = dict(q1=paths.code_root / manifest.WRAPPER_DIR,
                     same_era=Path(pins["run_root"]) / "inputs" / "verified_era_wrappers")
    for era in profile.ERAS:
        folder = paths.run_root / "translate" / ("wrappers_" + era)
        admissions[era] = translate.admit_directory(folder, ciks, base_dir=base_dirs[era])
    after = manifest.verify_inputs(built)
    if not after["ok"]:
        raise StageInvalidated("pinned inputs changed during the stage: " + json.dumps(after)[:400])
    per_cik, totals = {}, {}
    for cik in ciks:
        per_cik[cik] = {}
        for era in profile.ERAS:
            result = results[(cik, era)]
            if result.get("status") == "unavailable":
                per_cik[cik][era] = result
                continue
            admission = admissions[era]["ciks"][cik]
            sidecar = finish_sidecar(paths, cik, era, result, admission)
            per_cik[cik][era] = _row(result, admission, sidecar)
    for era in profile.ERAS:
        rows = [per_cik[c][era] for c in ciks if "coverage" in per_cik[c][era]]
        by_reason: dict = {}
        for r in rows:
            for n in r["not_expressible"]:
                for reason in n["reasons"]:
                    by_reason[reason] = by_reason.get(reason, 0) + 1
        totals[era] = dict(
            ciks=len(rows), admitted=sum(1 for r in rows if r["loader_admission"]["admitted"]),
            schema_pass=sum(1 for r in rows if r["schema_validation"]["verdict"] == "pass"),
            not_expressible=sum(len(r["not_expressible"]) for r in rows),
            not_expressible_by_reason=dict(sorted(by_reason.items())),
            fields_added=sum(len(r["fields_added"]) for r in rows),
            created_objects=sum(len(r["created_objects"]) for r in rows),
            consumer_parity_true=sum(1 for r in rows if r["consumer_parity"]["verdict"]),
            spec_parity_true=sum(1 for r in rows if r["consumer_parity"]["spec_parity"]),
            entries_used=sum(r["entries_used"] for r in rows),
            mean_coverage=round(sum(r["coverage"]["ratio"] for r in rows) / len(rows), 6) if rows else None,
            profile_driven_fields=sum(r["coverage"]["profile_driven"] for r in rows),
            profile_driven_header=sum(r["coverage"]["profile_driven_header"] for r in rows),
            profile_driven_structural=sum(r["coverage"]["profile_driven_structural"] for r in rows),
            profile_driven_via_inherited=sum(r["coverage"]["profile_driven_via_inherited"] for r in rows),
            mean_structural_coverage=(round(sum(r["coverage"]["structural_ratio"] for r in rows) / len(rows), 6)
                                      if rows else None),
            fields_total=sum(r["coverage"]["fields_total"] for r in rows),
            directory_error=admissions[era]["directory_error"], base_error=admissions[era]["base_error"],
            loader_state_mutations=admissions[era]["state_mutations"],
            wrapper_consumers=admissions[era]["wrapper_consumers"])
    summary = dict(run_id=paths.run_id, git_head=built["git"]["head"],
                   dirty_source_digest=built["git"]["dirty_source_digest"], profile_run_id=profile_run_id,
                   as_of=as_of, finished_utc=_now(), seconds=round(time.perf_counter() - started, 1),
                   input_verification_after=after, totals=totals, ciks=per_cik,
                   admission={era: {k: v for k, v in a.items() if k != "ciks"} for era, a in admissions.items()},
                   disclaimer=translate.DISCLAIMER)
    write_once_json(paths, "results/translate_summary.json", summary)
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
    cmd.add_argument("--profile-run-id", required=True)
    cmd.add_argument("--cik", action="append", default=None)
    args = parser.parse_args(argv)
    try:
        main_root = args.main_root or discover_main_root(CODE_ROOT)
        paths = resolve_paths(main_repo_root=main_root, data_root=args.data_root,
                              code_root=args.code_root or CODE_ROOT, run_id=args.run_id or default_run_id())
        receipt = ("verification/" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                   + "_translate_preservation.json")
        with protection.protected_session(paths, receipt=receipt):
            summary = run_stage(paths, profile_run_id=args.profile_run_id, ciks=args.cik)
    except StageInvalidated as exc:
        print("STAGE INVALIDATED: " + str(exc).encode("ascii", "backslashreplace").decode("ascii"))
        return EXIT_INVALIDATED
    except PathError as exc:
        print("REFUSED: " + str(exc).encode("ascii", "backslashreplace").decode("ascii"))
        return EXIT_REFUSED
    print("run: " + summary["run_id"] + " | git_head " + summary["git_head"] + " | " + str(summary["seconds"]) + " s")
    for era, row in summary["totals"].items():
        print(era + ": " + json.dumps({k: row[k] for k in (
            "ciks", "admitted", "schema_pass", "not_expressible", "not_expressible_by_reason", "entries_used",
            "mean_coverage", "profile_driven_fields", "profile_driven_header", "profile_driven_structural",
            "profile_driven_via_inherited", "fields_total", "fields_added", "created_objects",
            "consumer_parity_true", "spec_parity_true", "loader_state_mutations")},
            sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
