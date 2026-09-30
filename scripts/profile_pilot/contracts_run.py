"""Task 8 stage: learn contracts from Q1, freeze them, evaluate on Q2 and publish M2.

    python -m scripts.profile_pilot.contracts_run run --data-root D
        --census-run-id stageb-20260929t004819z --profile-run-id stageb-profile-20260929t015742z
        [--run-id stageb-contracts-<stamp>] [--main-root M] [--cik C ...]

Order (spec 6.3 / s8; R18/R26 pattern), all in a NEW write-once run root:
  1. freeze inventories/contract_tolerances.json from the spec table (before anything is read);
  2. pin the census root (authoritative listing, excluded listing, every Q1/Q2 census file:
     bytes hashed and checked against the listing, not parsed), the profile root (summary,
     manifest, every Q1 profile; refused unless profile_summary.census_run_id is this census
     root and every Q1 profile's census_sha256 is the authoritative row's, via
     lineage.check_profile_lineage), the authored grammars and anchors, the code (incl.
     pipeline/rate_convention.py and pipeline/identifier_rate.py), and materialise the
     pinned slices (bdc_holdings + private_markets_holdings via manifest.materialise_slices,
     bdc_fund_income here); write manifest.json;
  3. learn every CIK's contracts from its Q1 census + Q1 profile (+ Q1 S2 evidence) as a
     cached light stage (learning/{cik}.json);
  4. freeze inventories/contract_inventory.json (the fixed M2 denominator);
  5. only then parse each Q2 census and evaluate from the FROZEN files (results/contracts/{cik}.json);
  6. publish results/m2.json, re-verify every pinned input, write results/contracts_summary.json
     with the wall-clock order proof.
Reading census/profile JSON and 8-CIK slices is light; no XBRL instance is parsed.
Exit codes: 0 ok, 2 stage invalidated, 3 contract/adapter error, 4 refused.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

from scripts.profile_pilot import cohort, contracts, contracts_income, lineage, manifest, protection
from scripts.profile_pilot.manifest import StageInvalidated
from scripts.profile_pilot.paths import (PathError, PilotPaths, confined, discover_main_root, pilot_duckdb,
                                         resolve_paths, write_once_json)

CODE_ROOT = Path(__file__).resolve().parents[2]
EXIT_INVALIDATED, EXIT_CONTRACT, EXIT_REFUSED = 2, 3, 4
RUN_PREFIX = "stageb-contracts-"
ANCHOR_DIR = "data/overrides/identifier_anchors"
CODE_FILES = ("scripts/profile_pilot/contracts.py", "scripts/profile_pilot/contracts_income.py",
              "scripts/profile_pilot/contracts_totals.py",
              "scripts/profile_pilot/contracts_observe.py",
              "scripts/profile_pilot/contracts_run.py", "scripts/profile_pilot/lineage.py",
              "scripts/profile_pilot/envelope.py",
              "scripts/profile_pilot/census.py", "scripts/profile_pilot/census_detect.py",
              "scripts/profile_pilot/manifest.py", "pipeline/rate_convention.py", "pipeline/identifier_rate.py",
              "pipeline/identifier_signature.py")
INCOME_SLICE = "inputs/bdc_fund_income_pilot8.parquet"
FINANCIALS_SLICE = "inputs/fund_financials_pilot8.parquet"
FINANCIALS_COLUMNS = ("cik", "report_date", "investments_at_fair_value", "net_assets", "total_assets")
KEEP = ("label", "path", "status", "sha256", "bytes")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def default_run_id(now: datetime | None = None) -> str:
    return RUN_PREFIX + (now or datetime.now(timezone.utc)).strftime("%Y%m%dt%H%M%Sz")


def _record(path, label: str, *, required: bool = True, blob_of: str | None = None, code_root=None) -> dict:
    record = manifest.file_record(path, label)
    if required and record["status"] != "present":
        raise StageInvalidated("pinned input missing: " + label + " (" + str(path) + ")")
    if blob_of is not None and record["status"] == "present":
        record["git_blob"] = cohort.git_blob(code_root, blob_of)
    return record


def _other_root(paths: PilotPaths, run_id: str) -> PilotPaths:
    return resolve_paths(main_repo_root=paths.main_repo_root, data_root=paths.data_root,
                         code_root=paths.code_root, run_id=run_id)


# ---------------------------------------------------------------- pins (hash only; nothing parsed from Q2)

def pin_census(paths: PilotPaths, census_run_id: str, ciks) -> dict:
    census = lineage.load_authoritative_census(paths, census_run_id, roles=("q1", "q2"), ciks=ciks,
                                               label_prefix="census_root/", require_excluded=True)
    missing = json.loads(Path(census["excluded"]["path"]).read_text(encoding="ascii"))
    selected = census["rows"]
    unavailable = {(r["cik"], r["role"]): r for r in missing["fund_quarters"] if r["cik"] in ciks}
    for cik in ciks:
        if (cik, "q1") not in selected:
            raise StageInvalidated("no authoritative Q1 census for " + cik)
    return dict(run_id=census_run_id, run_root=census["run_root"], authoritative=census["authoritative"],
                excluded=census["excluded"], files=census["files"], selected=selected, unavailable=unavailable,
                paths=census["paths"])


def pin_profiles(paths: PilotPaths, profile_run_id: str, ciks, *, census: dict) -> dict:
    """The Q1 profiles, refused unless the profile root was derived from the pinned census root.

    Lineage (I1): profile_summary.census_run_id == the pinned census run id and every Q1
    profile's census_sha256 / census_relative == the authoritative Q1 row (lineage module)."""
    root = _other_root(paths, profile_run_id).run_root
    summary = _record(root / "results" / "profile_summary.json", "profile_root/results/profile_summary.json")
    built = _record(root / "manifest.json", "profile_root/manifest.json")
    body = json.loads(Path(summary["path"]).read_text(encoding="ascii"))
    checked = lineage.check_profile_lineage(body, census_run_id=census["run_id"], census_rows=census["selected"],
                                            ciks=ciks, eras=("q1",))
    listed = body["profiles"]
    profiles, census_sha = {}, {}
    for cik in ciks:
        entry = listed.get(cik + "/q1") or {}
        if entry.get("status") != "derived":
            raise StageInvalidated("Q1 profile not derived for " + cik)
        record = _record(root / "profiles" / cik / "q1.json", "profile_root/profiles/" + cik + "/q1.json")
        if record["sha256"] != entry.get("sha256"):
            raise StageInvalidated("profile file differs from profile_summary: " + cik)
        profiles[cik] = record
        census_sha[cik] = entry["census_sha256"]
    return dict(run_id=profile_run_id, run_root=str(root), summary=summary, manifest=built, profiles=profiles,
                census_sha256=census_sha, lineage=checked)


def pin_grammar(paths: PilotPaths, cik: str) -> tuple[dict | None, list]:
    """Authored grammar (inherited) + the per-CIK keyword anchors its scope uses."""
    from pipeline.identifier_rate import load_grammar
    from pipeline.identifier_signature import load_anchors
    code = paths.code_root
    relative = manifest.GRAMMAR_DIR + "/" + cik + ".json"
    grammar = _record(code / relative, "grammar/" + cik, required=False, blob_of=relative, code_root=code)
    anchor_rel = ANCHOR_DIR + "/" + cik + ".json"
    anchors = _record(code / anchor_rel, "anchors/" + cik, required=False, blob_of=anchor_rel, code_root=code)
    if grammar["status"] != "present":
        return None, [grammar, anchors]
    body = json.loads((code / relative).read_text(encoding="utf-8"))
    if load_grammar(cik) != body:
        raise StageInvalidated("pipeline.identifier_rate.load_grammar reads a different file than " + relative)
    compiled = load_anchors(cik, anchor_dir=code / ANCHOR_DIR)
    info = contracts.grammar_info(body, path=relative, sha256=grammar["sha256"], anchors=compiled)
    info["anchors_source"] = anchor_rel if anchors["status"] == "present" else "identifier_signature.STARTER_ANCHORS"
    return info, [grammar, anchors]


def materialise_income_slice(paths: PilotPaths) -> dict:
    source = paths.output_root / "bdc_fund_income.csv"
    before = manifest.file_record(source, "output/bdc_fund_income.csv")
    target = confined(paths, INCOME_SLICE)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise PathError("refusing to overwrite frozen slice: " + str(target))
    con = pilot_duckdb(paths)
    try:
        con.execute("COPY (SELECT * FROM read_csv(?, all_varchar=true, header=true) "
                    "WHERE lpad(cik, 10, '0') IN (SELECT unnest(?))) TO '"
                    + target.as_posix().replace("'", "''") + "' (FORMAT parquet)",
                    [str(source), list(cohort.PILOT_CIKS)])
        rows = con.execute("SELECT lpad(cik, 10, '0'), count(*) FROM read_parquet(?) GROUP BY 1 ORDER BY 1",
                           [str(target)]).fetchall()
    finally:
        con.close()
    manifest.assert_inputs_unchanged([before], "while slicing bdc_fund_income")
    record = manifest.file_record(target, "run/" + INCOME_SLICE)
    record.update(source=before, rows_by_cik={c: n for c, n in rows})
    return record


def materialise_financials_slice(paths: PilotPaths) -> dict:
    """Pin the 8 CIKs' fund_financials rows (the independent_totals anchor), write-once, like the income slice."""
    source = paths.output_root / "fund_financials.csv"
    before = manifest.file_record(source, "output/fund_financials.csv")
    target = confined(paths, FINANCIALS_SLICE)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise PathError("refusing to overwrite frozen slice: " + str(target))
    con = pilot_duckdb(paths)
    try:
        con.execute("COPY (SELECT lpad(cik, 10, '0') AS cik, substr(report_date, 1, 10) AS report_date, "
                    "TRY_CAST(investments_at_fair_value AS DOUBLE) AS investments_at_fair_value, "
                    "TRY_CAST(net_assets AS DOUBLE) AS net_assets, TRY_CAST(total_assets AS DOUBLE) AS total_assets "
                    "FROM read_csv(?, all_varchar=true, header=true) "
                    "WHERE lpad(cik, 10, '0') IN (SELECT unnest(?)) ORDER BY 1, 2) TO '"
                    + target.as_posix().replace("'", "''") + "' (FORMAT parquet)",
                    [str(source), list(cohort.PILOT_CIKS)])
        rows = con.execute("SELECT cik, count(*) FROM read_parquet(?) GROUP BY 1 ORDER BY 1",
                           [str(target)]).fetchall()
    finally:
        con.close()
    manifest.assert_inputs_unchanged([before], "while slicing fund_financials")
    record = manifest.file_record(target, "run/" + FINANCIALS_SLICE)
    record.update(source=before, rows_by_cik={c: n for c, n in rows})
    return record


def load_financials(paths: PilotPaths, cik: str, report_date: str) -> dict | None:
    """The pinned fund_financials row of one (cik, quarter), or None; two rows are a ContractError."""
    con = pilot_duckdb(paths)
    try:
        rows = con.execute("SELECT " + ", ".join(FINANCIALS_COLUMNS) + " FROM read_parquet(?) "
                           "WHERE cik = ? AND report_date = ?",
                           [str(confined(paths, FINANCIALS_SLICE)), str(cik).zfill(10), str(report_date)[:10]]
                           ).fetchall()
    finally:
        con.close()
    if len(rows) > 1:
        raise contracts.ContractError("fund_financials has %d rows for %s %s" % (len(rows), cik, report_date))
    return dict(zip(FINANCIALS_COLUMNS, rows[0])) if rows else None


# ---------------------------------------------------------------- loading pinned JSON

def load_census(row: dict) -> dict:
    path = Path(row["record"]["path"])
    if manifest.sha256_file(path) != row["census_sha256"]:
        raise StageInvalidated("census file changed before use: " + row["census_relative"])
    outer = json.loads(path.read_text(encoding="ascii"))
    if outer.get("identity", {}).get("fingerprint") != row["fingerprint"] or outer.get("complete") is not True:
        raise StageInvalidated("census identity differs from the authoritative listing: " + row["census_relative"])
    return outer["result"]


def load_profile(record: dict, *, census_sha256: str | None = None) -> dict:
    path = Path(record["path"])
    if manifest.sha256_file(path) != record["sha256"]:
        raise StageInvalidated("profile file changed before use: " + str(path))
    outer = json.loads(path.read_text(encoding="ascii"))
    if outer.get("complete") is not True:
        raise StageInvalidated("profile result incomplete: " + str(path))
    if census_sha256 is not None:
        lineage.check_profile_document_source(outer["result"], census_sha256=census_sha256, label=str(path))
    return outer["result"]


def _workload(cik: str, size: int) -> dict:
    return dict(ciks=[cik], instance_count=0, full_cache_scan=False, pipeline_cik_count=1,
                est_seconds=round(3 + size / 5e6, 1), est_bytes=int(350e6 + 20 * size))


def _tolerances_for_version(tolerances_version: int) -> dict:
    """The frozen tolerance content for a --tolerances-version CLI choice (3 default, 4 opt-in).

    v3 is today's freeze (contracts.tolerance_content()); v4 extends that same v3 content with
    the pre-registered independent_totals bands (contracts.tolerance_content_v4)."""
    content = contracts.tolerance_content()
    return content if tolerances_version == 3 else contracts.tolerance_content_v4(content)


def _kinds_for_version(tolerances_version: int) -> list:
    """The kinds that can be learned under the frozen tolerances: v3 has no independent_totals band."""
    if tolerances_version == 4:
        return list(contracts.ALL_KINDS)
    return [k for k in contracts.ALL_KINDS if k != contracts.TOTALS_KIND]


def _q2_listing(census: dict, cik: str) -> dict:
    row = census["selected"].get((cik, "q2"))
    if row:
        return dict(status="available", report_date=row["report_date"], census_relative=row["census_relative"],
                    census_sha256=row["census_sha256"])
    gone = census["unavailable"].get((cik, "q2")) or {}
    return dict(status="unavailable", report_date=gone.get("report_date"), reason=gone.get("reason"),
                detail=gone.get("detail") or "no authoritative Q2 census")


def order_proof(clock: dict, *, cached_q2_stamps: list):
    """True/False from the wall clock; "unknown" (never True) when no Q2 parse time is known.

    On cache hits the parse time is the cached record's own evaluated_utc (earliest)."""
    first = clock.get("first_q2_parse_utc") or (min(cached_q2_stamps) if cached_q2_stamps else None)
    if first is None:
        return "unknown"
    return (clock["tolerances_frozen_utc"] <= clock["manifest_written_utc"] <= clock["learning_done_utc"]
            <= clock["inventory_frozen_utc"] <= first)


def _yield_brief(ev: dict | None) -> dict | None:
    if not ev:
        return None
    s2 = ev.get("s2") or {}
    return dict(report_date=ev.get("report_date"), status=ev.get("status"), vote=ev.get("vote"),
                cause=ev.get("cause"), interpreted=ev.get("interpreted"), src=s2.get("src"), r=s2.get("r"),
                coverage_ratio=s2.get("coverage_ratio"), interest_income=s2.get("interest_income"),
                total_investment_income=s2.get("total_investment_income"),
                base=(s2.get("mirror") or {}).get("base"), pik_add=(s2.get("mirror") or {}).get("pik_add"),
                pik_share=(s2.get("mirror") or {}).get("pik_share"),
                preconditions={k: v.get("ok") for k, v in (ev.get("preconditions") or {}).items()},
                durations_months=((ev.get("preconditions") or {}).get("duration") or {}).get("durations_months"))


# ---------------------------------------------------------------- Task B2-3: the v2 subset under v3

def v2_subset_check(blocks: dict, results: dict, *, v2_blocks: dict, v2_results: dict) -> dict:
    """v2 contract ids, expectations and results must be byte-for-byte the v2 run's under v3: the v3
    block's v2 contracts equal the v2 inventory's, and the v3 results of those contracts (without the
    newly_abstained flag, which v2 results do not carry) equal the v2 results after a JSON round trip."""
    by_cik, diffs, ev_diffs = {}, {}, {}
    rt = lambda x: json.loads(json.dumps(x))
    for cik in sorted(blocks):
        v2c = rt([c for c in blocks[cik]["contracts"] if c["kind"] in contracts.KINDS])
        old = rt(v2_blocks[cik]["contracts"])
        mine = rt([{k: v for k, v in r.items() if k != "newly_abstained"}
                   for r in results[cik] if r["kind"] in contracts.KINDS])
        theirs = rt([{k: v for k, v in r.items() if k != "newly_abstained"} for r in v2_results[cik]])
        strip = lambda cs: [{k: v for k, v in c.items() if k != "evidence"} for c in cs]
        same_c = strip(v2c) == strip(old)
        same_r = mine == theirs
        noise = []
        for a, b in zip(v2c, old):
            _paths(a.get("evidence"), b.get("evidence"), a["contract_id"] + ".evidence", noise)
        by_cik[cik] = dict(contracts=same_c, results=same_r, evidence_identical=not noise and len(v2c) == len(old),
                           v2_contracts=len(v2c), semantic_contracts=len(blocks[cik]["contracts"]) - len(v2c))
        bad = [a.get("contract_id") for a, b in zip(mine, theirs) if a != b]
        if len(mine) != len(theirs):
            bad.append("result count %d != %d" % (len(mine), len(theirs)))
        if len(v2c) != len(old):
            bad.append("v2 contract count %d != %d" % (len(v2c), len(old)))
        bad += [a["contract_id"] + " (contract)" for a, b in zip(strip(v2c), strip(old)) if a != b]
        if bad:
            diffs[cik] = bad[:20]
        if noise:
            ev_diffs[cik] = noise[:20]
    return dict(identical=not diffs, by_cik=by_cik, differences=diffs, evidence_differences=ev_diffs,
                rule="identity verdict = v2 contract ids, bands, learn status/cause and expectations, and the v2 "
                     "results (without newly_abstained), byte-for-byte after a JSON round trip; learning EVIDENCE "
                     "differences are reported apart (evidence_differences) and do not decide the verdict: the "
                     "pinned parquet slices are written by an unordered parallel DuckDB COPY, so S2 float sums in "
                     "the yield evidence can differ in the last ulp between runs")


def _paths(a, b, path: str, out: list) -> None:
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            _paths(a.get(k), b.get(k), path + "." + str(k), out)
    elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for i, (x, y) in enumerate(zip(a, b)):
            _paths(x, y, path + "[" + str(i) + "]", out)
    elif a != b:
        out.append(path)


def load_v2_run(paths: PilotPaths, run_id: str, ciks) -> dict:
    """The v2 contracts root's frozen inventory and per-CIK results (read only, hashed)."""
    other = _other_root(paths, run_id)
    inv = manifest.load_inventory(other, "contract_inventory")
    records, results = [_record(other.run_root / "inventories" / "contract_inventory.json",
                                "v2_root/inventories/contract_inventory.json")], {}
    for cik in ciks:
        rec = _record(other.run_root / "results" / "contracts" / (cik + ".json"),
                      "v2_root/results/contracts/" + cik + ".json")
        outer = json.loads(Path(rec["path"]).read_text(encoding="ascii"))
        if outer.get("complete") is not True:
            raise StageInvalidated("v2 result file incomplete: " + cik)
        results[cik] = outer["result"]["results"]
        records.append(rec)
    return dict(run_id=run_id, blocks={c: inv["ciks"][c] for c in ciks}, results=results, records=records,
                tolerances_sha256=inv["tolerances"]["content_sha256"])


# ---------------------------------------------------------------- the stage

def run_stage(paths: PilotPaths, *, census_run_id: str, profile_run_id: str, ciks=None, v2_run_id: str | None = None,
              recorded_at: str | None = None, tolerances_version: int = 3) -> dict:
    ciks = list(ciks or cohort.PILOT_CIKS)
    recorded_at = recorded_at or _now()
    started = time.perf_counter()
    clock = dict(started_utc=_now())
    tolerances_content = _tolerances_for_version(tolerances_version)
    tolerances_state = manifest.freeze_inventory(paths, "contract_tolerances", tolerances_content)
    clock["tolerances_frozen_utc"] = _now()

    census = pin_census(paths, census_run_id, ciks)
    profiles = pin_profiles(paths, profile_run_id, ciks, census=census)
    grammars, grammar_records = {}, []
    for cik in ciks:
        grammars[cik], records = pin_grammar(paths, cik)
        grammar_records += records
    v2 = load_v2_run(paths, v2_run_id, ciks) if v2_run_id else None
    code = [_record(paths.code_root / rel, "code/" + rel, blob_of=rel, code_root=paths.code_root)
            for rel in CODE_FILES]
    slices = manifest.materialise_slices(paths)
    income_slice = materialise_income_slice(paths)
    financials_slice = materialise_financials_slice(paths)
    holdings_path = next(s["path"] for s in slices if s["label"].endswith("private_markets_holdings_pilot8.parquet"))

    primary = manifest.load_inventory(census["paths"], "primary_quarter_inventory")
    built = manifest.build_manifest(paths, primary_inventory=primary)
    tol_record = manifest.file_record(tolerances_state["path"], "run/inventories/contract_tolerances.json")
    pinned = ([census["authoritative"], census["excluded"], profiles["summary"], profiles["manifest"], tol_record]
              + census["files"] + list(profiles["profiles"].values()) + grammar_records + code + slices
              + [income_slice, financials_slice] + (v2["records"] if v2 else []))
    built["inputs"] += [{k: r[k] for k in KEEP if k in r} for r in pinned]
    built["inputs"] += [s["source"] for s in slices + [income_slice, financials_slice]]
    built.update(stage="contracts", census_source=dict(run_id=census_run_id, run_root=census["run_root"]),
                 profile_source=dict(run_id=profile_run_id, run_root=profiles["run_root"],
                                     lineage=profiles["lineage"]),
                 grammars={c: (None if g is None else dict(path=g["path"], sha256=g["sha256"], dialect=g["dialect"],
                                                           signatures=g["signatures"],
                                                           anchors_source=g["anchors_source"], provenance="inherited"))
                           for c, g in grammars.items()},
                 slices=slices + [income_slice, financials_slice], code=code, s2_constants=contracts_income.s2_constants(),
                 stage_config=dict(ciks=ciks, recorded_at=recorded_at, contracts_version=contracts.CONTRACTS_VERSION,
                                   tolerances_version=tolerances_content["version"],
                                   kinds=_kinds_for_version(tolerances_version),
                                   yield_holdings="private_markets_holdings slice (S2's production input); "
                                                  "bdc_holdings is pinned but is not S2-shaped"))
    built["inventories"] = manifest.inventory_states(paths)
    built["input_verification"] = manifest.verify_inputs(built)
    if not built["input_verification"]["ok"]:
        raise StageInvalidated("pinned inputs changed while building the manifest")
    built["frozen_utc"] = _now()
    write_once_json(paths, "manifest.json", built)
    clock["manifest_written_utc"] = _now()

    # The parquet slices are what the stages read; their CSV sources are pinned in the manifest
    # (re-hashing 1.3 GB of CSV around every cached stage would add nothing).
    slice_deps = [{k: s[k] for k in KEEP} for s in slices + [income_slice, financials_slice]]
    blocks, deps_common = {}, dict(tolerances=tol_record, code=code, slices=slice_deps)
    for cik in ciks:
        row = census["selected"][(cik, "q1")]
        profile_record = profiles["profiles"][cik]
        identity = manifest.cache_identity("contracts_learn", dict(
            deps_common, cik=cik, census=row["record"], census_fingerprint=row["fingerprint"], profile=profile_record,
            grammar=[r for r in grammar_records if r["label"].endswith("/" + cik)], recorded_at=recorded_at),
            collector_version=contracts.CONTRACTS_VERSION)
        tolerances = manifest.load_inventory(paths, "contract_tolerances")

        def learn(cik=cik, row=row, profile_record=profile_record, tolerances=tolerances):
            q1_doc = load_census(row)
            yield_q1 = contracts_income.load_income_evidence(
                paths, cik=cik, report_date=row["report_date"], holdings_path=holdings_path,
                income_path=income_slice["path"], census_doc=q1_doc,
                min_quarters=contracts.frozen_min_quarters(tolerances))
            q1_profile = load_profile(profile_record, census_sha256=profiles["census_sha256"][cik])
            return contracts.learn_contracts(cik=cik, q1_doc=q1_doc, q1_profile=q1_profile,
                                             grammar=grammars[cik], yield_q1=yield_q1, tolerances=tolerances,
                                             q2_listing=_q2_listing(census, cik), recorded_at=recorded_at,
                                             financials_q1=load_financials(paths, cik, row["report_date"]))

        out = manifest.run_cached_stage(paths, "learning/" + cik + ".json", identity, learn,
                                        workload=_workload(cik, row["record"]["bytes"]))
        blocks[cik] = out["result"]
    clock["learning_done_utc"] = _now()
    inventory_state = contracts.freeze_contracts(paths, blocks, tolerances_state=tolerances_state)
    clock["inventory_frozen_utc"] = _now()

    tolerances = manifest.load_inventory(paths, "contract_tolerances")
    inventory = manifest.load_inventory(paths, "contract_inventory")
    inv_record = manifest.file_record(inventory_state["path"], "run/inventories/contract_inventory.json")
    results, yields, cached_stamps = [], {}, []
    for cik in ciks:
        row = census["selected"].get((cik, "q2"))
        block = inventory["ciks"][cik]
        identity = manifest.cache_identity("contracts_evaluate", dict(
            deps_common, cik=cik, inventory=inv_record, census=row["record"] if row else None,
            census_fingerprint=row["fingerprint"] if row else None,
            grammar=[r for r in grammar_records if r["label"].endswith("/" + cik)]),
            collector_version=contracts.CONTRACTS_VERSION)

        def evaluate(cik=cik, row=row, block=block):
            stamp = _now()
            clock.setdefault("first_q2_parse_utc", stamp)
            q2_doc = load_census(row) if row else None
            yield_q2 = None if row is None else contracts_income.load_income_evidence(
                paths, cik=cik, report_date=row["report_date"], holdings_path=holdings_path,
                income_path=income_slice["path"], census_doc=q2_doc,
                min_quarters=contracts.frozen_min_quarters(tolerances))
            listing = block["q2_listing"]
            financials_q2 = None if row is None else load_financials(paths, cik, row["report_date"])
            return dict(evaluated_utc=stamp, yield_q2=yield_q2, results=contracts.evaluate_contracts(
                block, tolerances, q2_doc=q2_doc, q2_listing=listing, grammar=grammars[cik], yield_q2=yield_q2,
                financials_q2=financials_q2))

        size = row["record"]["bytes"] if row else 0
        out = manifest.run_cached_stage(paths, "results/contracts/" + cik + ".json", identity, evaluate,
                                        workload=_workload(cik, size))
        if out["cache"] == "hit" and out["result"].get("evaluated_utc"):
            cached_stamps.append(out["result"]["evaluated_utc"])
        results += out["result"]["results"]
        q1_yield = next(c for c in block["contracts"] if c["kind"] == "fund_income_yield")["evidence"]["q1_yield"]
        verdict = next(r for r in out["result"]["results"] if r["kind"] == "fund_income_yield")
        yields[cik] = dict(q1=_yield_brief(q1_yield), q2=_yield_brief(out["result"]["yield_q2"]),
                           verdict=verdict["status"], cause=verdict["cause"])
    clock["evaluation_done_utc"] = _now()
    m2 = contracts.summarise_m2(results, denominator=inventory["denominator"]["total"])
    m2.update(run_id=paths.run_id, inventory=dict(content_sha256=inventory_state["content_sha256"],
                                                  denominator=inventory["denominator"]),
              tolerances=dict(content_sha256=tolerances_state["content_sha256"]), yield_evidence=yields,
              partition_statement={c: inventory["ciks"][c]["partition_statement"] for c in ciks},
              partitions_evidenced={c: inventory["ciks"][c]["partitions_evidenced"] for c in ciks},
              tiers={c: inventory["ciks"][c]["tier"] for c in ciks})
    write_once_json(paths, "results/m2.json", m2)
    subset = None
    if v2:
        per_cik = {}
        for r in results:
            per_cik.setdefault(r["cik"], []).append(r)
        subset = v2_subset_check({c: inventory["ciks"][c] for c in ciks}, per_cik, v2_blocks=v2["blocks"],
                                 v2_results=v2["results"])
        subset.update(v2_run_id=v2["run_id"], v2_tolerances_sha256=v2["tolerances_sha256"])
        write_once_json(paths, "results/v2_subset_check.json", subset)
    after = manifest.verify_inputs(built)
    if not after["ok"]:
        raise StageInvalidated("pinned inputs changed during the stage: " + json.dumps(after)[:400])
    if subset is not None and not subset["identical"]:
        raise contracts.ContractError("the v2 subset under v3 differs from " + v2["run_id"] + ": "
                                      + json.dumps(subset["differences"])[:400])
    order_ok = order_proof(clock, cached_q2_stamps=cached_stamps)
    strict = m2["strict_6_3"]
    summary = dict(run_id=paths.run_id, git_head=built["git"]["head"],
                   dirty_source_digest=built["git"]["dirty_source_digest"], census_run_id=census_run_id,
                   profile_run_id=profile_run_id, recorded_at=recorded_at, clock=clock, order_ok=order_ok,
                   cached_q2_stamps=cached_stamps, tolerances_version=tolerances["version"],
                   seconds=round(time.perf_counter() - started, 1), counts=m2["counts"],
                   by_q2_form_type=m2["by_q2_form_type"], denominator=m2["denominator"],
                   holds_share=m2["holds_share"],
                   strict_6_3=dict(counts=strict["counts"], by_q2_form_type=strict["by_q2_form_type"],
                                   holds_share=strict["holds_share"], interpretation=strict["interpretation"]),
                   input_verification_after=after, results="results/m2.json", claim=contracts.CLAIM,
                   stage_b_note=contracts.STAGE_B_NOTE, newly_abstained=m2["newly_abstained"],
                   by_kind=m2["by_kind"], v2_subset=None if subset is None else dict(
                       identical=subset["identical"], v2_run_id=subset["v2_run_id"], by_cik=subset["by_cik"]))
    write_once_json(paths, "results/contracts_summary.json", summary)
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
    cmd.add_argument("--profile-run-id", required=True)
    cmd.add_argument("--cik", action="append", default=None)
    cmd.add_argument("--v2-run-id", default=None, help="Task B2-3: assert the v2 subset equals this v2 run")
    cmd.add_argument("--tolerances-version", type=int, choices=[3, 4], default=3,
                     help="sp1 Task 6a: 3 (default, today's frozen content) or 4 (adds the independent_totals bands)")
    args = parser.parse_args(argv)
    try:
        main_root = args.main_root or discover_main_root(CODE_ROOT)
        paths = resolve_paths(main_repo_root=main_root, data_root=args.data_root,
                              code_root=args.code_root or CODE_ROOT, run_id=args.run_id or default_run_id())
        receipt = ("verification/" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                   + "_contracts_preservation.json")
        with protection.protected_session(paths, receipt=receipt):
            summary = run_stage(paths, census_run_id=args.census_run_id, profile_run_id=args.profile_run_id,
                                ciks=args.cik, v2_run_id=args.v2_run_id, tolerances_version=args.tolerances_version)
    except StageInvalidated as exc:
        print("STAGE INVALIDATED: " + str(exc).encode("ascii", "backslashreplace").decode("ascii"))
        return EXIT_INVALIDATED
    except (contracts.ContractError, contracts_income.IncomeEvidenceError) as exc:
        print("CONTRACT ERROR: " + str(exc).encode("ascii", "backslashreplace").decode("ascii"))
        return EXIT_CONTRACT
    except PathError as exc:
        print("REFUSED: " + str(exc).encode("ascii", "backslashreplace").decode("ascii"))
        return EXIT_REFUSED
    print("run: " + summary["run_id"] + " | git_head " + summary["git_head"] + " | " + str(summary["seconds"])
          + " s | order_ok " + str(summary["order_ok"]))
    print("M2 (denominator " + str(summary["denominator"]) + "): " + json.dumps(summary["counts"], sort_keys=True))
    for form, counts in summary["by_q2_form_type"].items():
        print("  Q2 " + form + ": " + json.dumps(counts, sort_keys=True))
    strict = summary["strict_6_3"]
    print("M2 strict 6.3: " + json.dumps(strict["counts"], sort_keys=True))
    print("newly_abstained (a flag, not a status): " + json.dumps({k: v for k, v in summary["newly_abstained"].items()
                                                                  if k != "rule"}, sort_keys=True))
    if summary["v2_subset"] is not None:
        print("v2 subset identical to " + summary["v2_subset"]["v2_run_id"] + ": " + str(summary["v2_subset"]["identical"]))
    for form, counts in strict["by_q2_form_type"].items():
        print("  Q2 " + form + ": " + json.dumps(counts, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
