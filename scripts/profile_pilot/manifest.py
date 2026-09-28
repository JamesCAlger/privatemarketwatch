"""Frozen run dependencies: input hashes, write-once inventories, cache identity.

A stage result is reusable only when its full dependency identity matches and the
prior result is complete. Inputs are re-hashed before and after each stage; a
changed input invalidates the stage and nothing is written.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

from scripts.profile_pilot import cohort
from scripts.profile_pilot.paths import PathError, PilotPaths, confined, write_json, write_once_json

MANIFEST_VERSION = 1
INVENTORY_NAMES = ("primary_quarter_inventory", "wrapper_key_inventory",
                   "correction_inventory", "contract_inventory")
WRAPPER_DIR = "data/overrides/bdc_xbrl_wrappers"
GRAMMAR_DIR = "data/overrides/identifier_rate_grammars"
B2_DIR = "data/overrides/agent_b2_corrections"
INVESTIGATE_DIR = "data/overrides/agent_investigate_rules"
ANCHOR_DIR = "data/overrides/agent_anchor"
OUTPUT_INPUTS = ("bdc_holdings.csv", "private_markets_holdings.csv", "bdc_filings_index.csv",
                 "bdc_fund_income.csv")
CODE_INPUTS = ("scripts/run_context_census.py", "scripts/diff_outputs.py",
               "pipeline/programme/runner.py", "pipeline/programme/core.py",
               "pipeline/context_inventory.py", "pipeline/explicit_contexts.py",
               "pipeline/bdc_filings.py", "tests/conftest.py")
# Verified-era ledger rule: a blocker-lane finding at the verified quarter that is not
# in a closed state means the CIK was not reconciled there.
CLOSED_LEDGER_STATES = ("adjudicated_false_alarm", "resolved_upstream", "remediated_promoted",
                        "gone_unadjudicated")


class StageInvalidated(RuntimeError):
    """An input or cached result no longer matches its recorded identity."""


def sha256_file(path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode("ascii")).hexdigest()


def git(code_root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    done = subprocess.run(["git", *args], cwd=code_root, capture_output=True, timeout=120)
    if check and done.returncode != 0:
        raise RuntimeError("git " + " ".join(args) + " failed: "
                           + done.stderr.decode("ascii", "replace").strip())
    return done


def git_head(code_root: Path) -> str:
    return git(code_root, "rev-parse", "HEAD").stdout.decode("ascii").strip()


def dirty_source_digest(code_root: Path) -> dict:
    status = git(code_root, "status", "--porcelain=v1", "--untracked-files=all").stdout
    diff = git(code_root, "diff", "HEAD", "--binary").stdout
    return dict(sha256=hashlib.sha256(status + b"\0" + diff).hexdigest(),
                porcelain_lines=len(status.splitlines()), tracked_diff_bytes=len(diff))


def file_record(path, label: str) -> dict:
    path = Path(path)
    if not path.is_file():
        return dict(label=label, path=str(path), status="missing")
    before = path.stat()
    value = sha256_file(path)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise StageInvalidated("input changed while hashing: " + str(path))
    return dict(label=label, path=str(path), status="present", sha256=value, bytes=after.st_size)


def verify_inputs(manifest: dict) -> dict:
    """Re-hash every recorded input. Missing-then-present counts as a change too."""
    changed, missing, appeared = [], [], []
    records = manifest["inputs"]
    for record in records:
        path = Path(record["path"])
        if record["status"] == "missing":
            if path.exists():
                appeared.append(str(path))
            continue
        if not path.is_file():
            missing.append(str(path))
        elif sha256_file(path) != record["sha256"]:
            changed.append(str(path))
    return dict(ok=not (changed or missing or appeared), checked=len(records),
                changed=changed, missing=missing, appeared=appeared)


def assert_inputs_unchanged(records: list, when: str) -> None:
    report = verify_inputs({"inputs": records})
    if not report["ok"]:
        raise StageInvalidated("inputs changed " + when + ": "
                               + ", ".join(report["changed"] + report["missing"] + report["appeared"]))


# ---------------------------------------------------------------- inventories

def _inventory_relpath(name: str) -> str:
    if name not in INVENTORY_NAMES:
        raise ValueError("unknown inventory: " + repr(name))
    return "inventories/" + name + ".json"


def freeze_inventory(paths: PilotPaths, name: str, content: dict) -> dict:
    """Write-once; the embedded content digest is re-checked on every load."""
    relative = _inventory_relpath(name)
    body = dict(inventory=name, run_id=paths.run_id, content=content,
                content_sha256=digest(content))
    target = write_once_json(paths, relative, body)
    return dict(state="frozen", path=str(target), sha256=sha256_file(target),
                content_sha256=body["content_sha256"])


def load_inventory(paths: PilotPaths, name: str) -> dict:
    target = confined(paths, _inventory_relpath(name))
    body = json.loads(Path(target).read_text(encoding="ascii"))
    if body.get("inventory") != name or digest(body["content"]) != body.get("content_sha256"):
        raise StageInvalidated("frozen inventory does not match its digest: " + name)
    return body["content"]


def inventory_states(paths: PilotPaths) -> dict:
    states = {}
    for name in INVENTORY_NAMES:
        target = confined(paths, _inventory_relpath(name))
        if target.is_file():
            body = json.loads(target.read_text(encoding="ascii"))
            states[name] = dict(state="frozen", path=str(target), sha256=sha256_file(target),
                                content_sha256=body.get("content_sha256"))
        else:
            states[name] = {"state": "not_yet_frozen"}
    return states


def _key_paths(value, prefix: str = "") -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            path = prefix + "." + key if prefix else key
            keys.add(path)
            keys |= _key_paths(child, path)
    elif isinstance(value, list):
        for child in value:
            keys |= _key_paths(child, prefix + "[]")
    return keys


def wrapper_key_inventory(code_root: Path, *, wrapper_dir: Path | None = None,
                          ciks=cohort.PILOT_CIKS) -> dict:
    """Every top-level and nested key path of each pilot wrapper, listed once (M1 denominator)."""
    directory = Path(wrapper_dir) if wrapper_dir else Path(code_root) / WRAPPER_DIR
    entries = {}
    for cik in ciks:
        path = directory / (cik + ".json")
        if not path.is_file():
            entries[cik] = dict(status="missing", path=str(path))
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        entry = dict(status="present", path=str(path), sha256=sha256_file(path),
                     keys=sorted(_key_paths(data)))
        if wrapper_dir is None:
            entry["git_blob"] = cohort.git_blob(Path(code_root), WRAPPER_DIR + "/" + cik + ".json")
        entries[cik] = entry
    return dict(source_dir=str(directory), key_notation="dotted; [] marks list elements",
                ciks=entries)


# ---------------------------------------------------------------- verified era (ruling 8)

def historical_wrapper(code_root: Path, cik: str, commit: str) -> dict:
    relative = WRAPPER_DIR + "/" + cik + ".json"
    blob = git(code_root, "rev-parse", "--verify", "--quiet", commit + ":" + relative, check=False)
    if blob.returncode != 0:
        return dict(status="missing", commit=commit, path=relative,
                    reason="no wrapper at that commit")
    content = git(code_root, "show", commit + ":" + relative).stdout
    return dict(status="present", commit=commit, path=relative,
                git_blob=blob.stdout.decode("ascii").strip(),
                sha256=hashlib.sha256(content).hexdigest(), bytes=len(content))


def verified_era_ledger(ledger: Path, ciks) -> dict:
    ledger = Path(ledger)
    if not ledger.is_file():
        return dict(status="missing", path=str(ledger), ciks={
            cik: dict(label="verified_era_evidence_missing", rows=0) for cik in ciks})
    import duckdb
    con = duckdb.connect(config={"threads": 2})
    try:
        rows = con.execute("""
            SELECT lpad(cik, 10, '0') AS cik, lane, engine, state, count(*) AS n
            FROM read_csv(?, all_varchar=true, header=true)
            WHERE substr(report_date, 1, 10) = ? AND lpad(cik, 10, '0') IN (SELECT unnest(?))
            GROUP BY ALL ORDER BY ALL""",
            [str(ledger), cohort.VERIFIED_ERA_QUARTER, sorted(ciks)]).fetchall()
    finally:
        con.close()
    per_cik = {cik: dict(rows=0, blocking_rows=0, by_lane_engine_state=[]) for cik in ciks}
    for cik, lane, engine, state, n in rows:
        entry = per_cik[cik]
        entry["rows"] += n
        entry["by_lane_engine_state"].append([lane, engine, state, n])
        if lane == "blocker" and state not in CLOSED_LEDGER_STATES:
            entry["blocking_rows"] += n
    for entry in per_cik.values():
        entry["label"] = ("verified_era_unreconciled" if entry["blocking_rows"]
                          else "verified_era_reconciled")
    return dict(status="present", path=str(ledger), sha256=sha256_file(ledger),
                rule="blocker lane and state not in " + ",".join(CLOSED_LEDGER_STATES),
                ciks=per_cik)


def verified_era_evidence(paths: PilotPaths) -> dict:
    code = paths.code_root
    attestation_path = code / cohort.ATTESTATION
    attestation = file_record(attestation_path, "attestation")
    if attestation["status"] == "present":
        body = json.loads(attestation_path.read_text(encoding="utf-8"))
        attestation["signoff_commit"] = body.get("signoff_commit")
        attestation["target_quarter"] = body.get("acceptance", {}).get("target_quarter")
    pass_dir = paths.output_root / "quarter_pass" / cohort.VERIFIED_PASS_ID
    acceptance = file_record(pass_dir / "acceptance_post.json", "acceptance_post")
    if acceptance["status"] == "present":
        body = json.loads((pass_dir / "acceptance_post.json").read_text(encoding="utf-8"))
        acceptance["verdict"] = body.get("verdict")
        acceptance["target_quarter"] = body.get("target_quarter")
    wrappers = {}
    for cik in cohort.PILOT_CIKS:
        then = historical_wrapper(code, cik, cohort.SIGNOFF_COMMIT)
        now = historical_wrapper(code, cik, "HEAD")
        wrappers[cik] = dict(verified_era=then, head=now,
                             identical=(then["status"] == now["status"] == "present"
                                        and then["git_blob"] == now["git_blob"]))
    return dict(quarter=cohort.VERIFIED_ERA_QUARTER, signoff_commit=cohort.SIGNOFF_COMMIT,
                pass_id=cohort.VERIFIED_PASS_ID, attestation=attestation,
                acceptance_post=acceptance, wrappers=wrappers,
                ledger=verified_era_ledger(pass_dir / "findings_ledger_post.csv", cohort.PILOT_CIKS),
                note="git add dates are metadata only")


def materialise_verified_era_wrappers(paths: PilotPaths, evidence: dict) -> list[dict]:
    """Copy the eed082b wrapper bytes into the run root so later stages read pinned content."""
    written = []
    for cik, entry in evidence["wrappers"].items():
        then = entry["verified_era"]
        if then["status"] != "present":
            continue
        content = git(paths.code_root, "show", then["commit"] + ":" + then["path"]).stdout
        if hashlib.sha256(content).hexdigest() != then["sha256"]:
            raise StageInvalidated("historical wrapper bytes changed: " + cik)
        target = confined(paths, "inputs/verified_era_wrappers/" + cik + ".json")
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "xb") as stream:
            stream.write(content)
        written.append(file_record(target, "run/inputs/verified_era_wrappers/" + cik + ".json"))
    return written


# ---------------------------------------------------------------- manifest

def _directory_records(root: Path, label_prefix: str) -> list[dict]:
    if not root.is_dir():
        return [dict(label=label_prefix, path=str(root), status="missing")]
    files = sorted(p for p in root.rglob("*") if p.is_file())
    if not files:
        return [dict(label=label_prefix, path=str(root), status="empty")]
    return [file_record(p, label_prefix + "/" + p.relative_to(root).as_posix()) for p in files]


def collect_inputs(paths: PilotPaths, primary_inventory: dict) -> list[dict]:
    records = [file_record(paths.output_root / name, "output/" + name) for name in OUTPUT_INPUTS]
    seen = set()
    for entry in primary_inventory["fund_quarters"]:
        for candidate in entry["candidates"]:
            if candidate["path"] in seen:
                continue
            seen.add(candidate["path"])
            records.append(file_record(candidate["path"], "xml/" + entry["cik"] + "/"
                                       + candidate["accession_number"]))
    code = paths.code_root
    for cik in cohort.PILOT_CIKS:
        stripped = str(int(cik))
        records.append(file_record(code / WRAPPER_DIR / (cik + ".json"), "wrapper/" + cik))
        records.append(file_record(code / GRAMMAR_DIR / (cik + ".json"), "grammar/" + cik))
        records.extend(_directory_records(code / B2_DIR / cik, "b2/" + cik))
        records.extend(_directory_records(code / INVESTIGATE_DIR / stripped, "investigate/" + cik))
        records.extend(_directory_records(code / ANCHOR_DIR / stripped, "anchor/" + cik))
    pilot_code = sorted((code / "scripts" / "profile_pilot").rglob("*.py"))
    for path in [code / p for p in CODE_INPUTS] + pilot_code:
        record = file_record(path, "code/" + path.relative_to(code).as_posix())
        if record["status"] == "present":
            record["git_blob"] = cohort.git_blob(code, path.relative_to(code).as_posix())
        records.append(record)
    records.append(file_record(paths.main_repo_root / "scripts" / "diff_outputs.py",
                               "main/scripts/diff_outputs.py"))
    records.append(file_record(paths.main_repo_root / "pipeline" / "programme" / "runner.py",
                               "main/pipeline/programme/runner.py"))
    return records


def build_manifest(paths: PilotPaths, *, primary_inventory: dict) -> dict:
    evidence = verified_era_evidence(paths)
    inputs = collect_inputs(paths, primary_inventory)
    for key in ("attestation", "acceptance_post"):
        record = evidence[key]
        inputs.append({k: record[k] for k in ("label", "path", "status", "sha256", "bytes")
                       if k in record})
    ledger = evidence["ledger"]
    inputs.append(dict(label="findings_ledger_post", path=ledger["path"], status=ledger["status"],
                       **({"sha256": ledger["sha256"]} if ledger["status"] == "present" else {})))
    return dict(manifest_version=MANIFEST_VERSION, run_id=paths.run_id,
                roots=dict(main_repo_root=str(paths.main_repo_root), code_root=str(paths.code_root),
                           data_root=str(paths.data_root), run_root=str(paths.run_root)),
                protected_roots=[str(r) for r in paths.protected_roots],
                git=dict(head=git_head(paths.code_root),
                         dirty_source_digest=dirty_source_digest(paths.code_root)["sha256"]),
                inputs=inputs, inventories=inventory_states(paths), verified_era=evidence)


# ---------------------------------------------------------------- stage cache

def cache_identity(stage: str, dependencies: dict, *, collector_version: str) -> dict:
    body = dict(stage=stage, collector_version=collector_version, dependencies=dependencies)
    return dict(body, fingerprint=digest(body))


def _identity_records(identity: dict) -> list[dict]:
    records = []
    for value in identity["dependencies"].values():
        if isinstance(value, list):
            records.extend(r for r in value if isinstance(r, dict) and "path" in r and "status" in r)
    return records


def run_cached_stage(paths: PilotPaths, relative: str, identity: dict, compute, *, heavy: bool,
                     lease=None) -> dict:
    """Reuse a complete result with the same identity, else compute (under the lease if heavy)."""
    records = _identity_records(identity)
    assert_inputs_unchanged(records, "before stage " + identity["stage"])
    target = confined(paths, relative)
    if target.is_file():
        prior = json.loads(target.read_text(encoding="ascii"))
        if prior.get("identity", {}).get("fingerprint") != identity["fingerprint"]:
            raise StageInvalidated("result exists with a different dependency identity: " + relative)
        if prior.get("complete") is not True:
            raise StageInvalidated("prior result is incomplete; refusing to reuse: " + relative)
        return dict(cache="hit", result=prior["result"], path=str(target))
    if heavy and lease is None:
        raise ValueError("a heavy stage needs the shared lease")
    if heavy:
        with lease():
            result = compute()
            assert_inputs_unchanged(records, "during stage " + identity["stage"])
    else:
        result = compute()
        assert_inputs_unchanged(records, "during stage " + identity["stage"])
    try:
        write_once_json(paths, relative, dict(identity=identity, complete=True, result=result))
    except PathError as exc:
        raise StageInvalidated(str(exc)) from exc
    return dict(cache="miss", result=result, path=str(target))
