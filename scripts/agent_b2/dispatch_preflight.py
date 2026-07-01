"""Deterministic parent-side preflight for Agent B2 remediation worker dispatch.

The B2 analog of ``scripts/agent_b/dispatch_preflight.py``. Keyed on a ``(cik, fix_class)``
packet (from ``run_remediation discover``). For one batch it: reads the packet worklist,
validates each packet's source verdict(s) are real_error with grounding, resolves the
source bundles (the worker re-grounds the FIX against them), acquires a per-packet lock,
writes one blinded-to-nothing remediation prompt per packet, and emits the manifest the
dispatcher consumes.

Non-LLM, cache-only, read-only on production; writes only under the batch dir
(prompts/manifest). Reuses the B1 worker-env fixes (absolute interpreter + import dirs).
ASCII-only.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from pipeline import config
from pipeline.bdc_cik_review import normalize_cik
from scripts.agent_b import review_lock
from scripts.agent_b.dispatch_preflight import WORKER_PYTHON, EVIDENCE_CLI, _worker_read_dirs
from scripts.agent_b2.run_remediation import implemented_fix_classes

_CIK_RE = re.compile(r"^\d{1,10}$")

DEFAULT_BASE = config.OUTPUT_DIR / "agent_b2"
DEFAULT_VERDICTS = config.OUTPUT_DIR / "review_queue" / "verdicts"
DEFAULT_BUNDLES = config.OUTPUT_DIR / "review_queue" / "review_bundles"
DEFAULT_CORRECTIONS = DEFAULT_BASE / "corrections"
DEFAULT_CONTRACT = "docs/adjudication_architecture/B2_remediation_contract.md"
VALIDATOR = config.PROJECT_ROOT / "scripts" / "agent_b2" / "validate_corrections.py"


class PreflightError(RuntimeError):
    pass


def _batch_dir(base_dir: Path, batch_id: str) -> Path:
    return base_dir / "batch" / batch_id


def _read_worklist(batch_dir: Path) -> list[dict]:
    path = batch_dir / "worklist.csv"
    if not path.exists():
        raise PreflightError(f"missing worklist: {path} (run run_remediation discover first)")
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise PreflightError(f"empty worklist: {path}")
    return rows


def _load_verdict(rid: str, verdicts_dir: Path) -> dict:
    p = (verdicts_dir / f"{rid}.json").resolve()
    if not p.exists():
        raise PreflightError(f"{rid}: source verdict missing: {p}")
    try:
        v = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PreflightError(f"{rid}: invalid verdict JSON: {exc}") from exc
    if v.get("verdict") != "real_error":
        raise PreflightError(f"{rid}: source verdict is {v.get('verdict')!r}, not real_error")
    return v


def _load_bundle(rid: str, bundles_dir: Path) -> tuple[Path, dict]:
    p = (bundles_dir / f"{rid}.json").resolve()
    if not p.exists():
        raise PreflightError(f"{rid}: source bundle missing: {p}")
    try:
        bundle = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PreflightError(f"{rid}: invalid bundle JSON: {exc}") from exc
    bundle_rid = str(bundle.get("review_id") or "").strip()
    if bundle_rid and bundle_rid != rid:
        raise PreflightError(f"{rid}: bundle review_id mismatch: {bundle_rid!r}")
    return p, bundle


def _citations_block(verdicts: list[dict]) -> str:
    lines = []
    for v in verdicts:
        for c in (v.get("culprit_citations") or []):
            q = str(c.get("quoted_text") or "").strip()
            coord = f"t{c.get('table_index')}/r{c.get('row_index')}"
            if q:
                lines.append(f"  - [{coord}] {q[:160]}")
    return "\n".join(lines) if lines else "  (no quoted citations; re-ground from source)"


def _citations_json(verdicts: list[dict]) -> str:
    cites = []
    seen = set()
    for v in verdicts:
        for c in (v.get("culprit_citations") or []):
            cite = {
                "table_index": c.get("table_index"),
                "row_index": c.get("row_index"),
                "quoted_text": str(c.get("quoted_text") or "").strip()[:240],
            }
            key = (cite["table_index"], cite["row_index"], cite["quoted_text"])
            if cite["quoted_text"] and key not in seen:
                cites.append(cite)
                seen.add(key)
    return json.dumps(cites[:8], indent=2)


def _worker_prompt(row: dict, verdicts: list[dict], *, contract_abs: str, bundle_paths: list[str],
                   correction_path: Path, validator: str, py: str) -> str:
    cik = row["cik"]
    fix_class = row["fix_class"]
    mechanism = row.get("mechanism", "")
    quarters = str(row.get("quarters") or "").strip()
    correction_leaf = f"{fix_class}.json"
    srids = row.get("source_review_ids") or []
    if isinstance(srids, str):
        srids = [s for s in srids.split(";") if s.strip()]
    bundle_lines = "\n".join(f"    \"{py}\" \"{EVIDENCE_CLI.resolve().as_posix()}\" --bundle \"{b}\" totals"
                             for b in bundle_paths) or "    (no bundles resolved)"
    return f"""Agent B2 remediation worker.

You author ONE constrained correction for ONE (cik, fix_class) packet that Agent B1 already
adjudicated as a real data error. You do NOT re-decide the error -- you propose the bounded
TEMPLATE that fixes it. Do not launch nested Codex; no tests, rebuilds, network, SEC, repo
scans, git, package installs, or shell commands.

Windows sandbox note: do NOT use shell/command tools for this packet. The parent preflight has
embedded the packet fields and B1 citations below, and the parent dispatcher re-validates your
JSON after you exit. Use only the file edit tool to write the one correction file.

The packet:
- CIK: {cik}    fix_class: {fix_class}    mechanism: {mechanism}
- target quarter(s): {quarters}
- source verdict(s): {', '.join(srids)}

The CIK and fix_class are binding. The JSON you write MUST keep:
- "cik": "{cik}"
- "fix_class": "{fix_class}"
Do not emit a different fix_class, even if the filing suggests another mechanism. If the
requested fix_class is not supported by source evidence, write the narrowest valid correction
for the requested class with low confidence and explain the residual risk.

What B1 localized as the defect (re-ground these against source before trusting them):
{_citations_block(verdicts)}

All paths are ABSOLUTE; your working directory is NOT the repo root. Invoke Python via the
exact interpreter shown ("{py}").

Embedded contract excerpt for comparative_period_filter:
- Use only for prior-period comparative facts leaking into the current filing report_date.
- The bounded template is exactly {{"report_date": "<target report_date>"}}.
- Do not emit subtotal patterns, row indices, code, SQL, or file paths.
- The prompt's CIK and fix_class are binding; do not switch fix_class.

Allowed write (exactly one file):
- {correction_leaf}

Your current working directory is the correction directory for CIK {cik}. Write the relative
file name `{correction_leaf}` only. Do not write an absolute path. The parent dispatcher will
validate the resulting file at:
- {correction_path}

Required workflow:
1. Use the embedded packet fields and citations below. Do not call shell commands.
2. Choose template params that match the requested fix_class. For comparative_period_filter,
   set template.report_date to the packet target quarter.
3. Write the correction leaf JSON to the one allowed path: cik, mechanism, fix_class,
   template (the bounded params), source_review_ids, evidence_citations (the cited rows),
   confidence (0..1), rationale. NO code, SQL, paths, or row-index deletions.
4. Do not run validation inside the worker. The parent dispatcher validates with:
   "{py}" "{validator}" --correction "{correction_path}" --expected-cik "{cik}" --expected-fix-class "{fix_class}"
5. Finish with a concise report: cik, fix_class, template, confidence, residual risk,
   correction path.

Evidence citations to copy into evidence_citations:
{_citations_json(verdicts)}

Nothing you write is applied until it passes this screen AND the B3 held-out gate (a
full-ledger re-run on all the CIK's quarters that you cannot see or game). Author for B3.
"""


def preflight_batch(
    batch_id: str, *, base_dir: Path = DEFAULT_BASE, verdicts_dir: Path = DEFAULT_VERDICTS,
    bundles_dir: Path = DEFAULT_BUNDLES, corrections_dir: Path = DEFAULT_CORRECTIONS,
    contract_rel: str = DEFAULT_CONTRACT, fix_class: str | None = None, reserve: bool = False,
) -> dict:
    batch_dir = _batch_dir(base_dir, batch_id)
    rows = _read_worklist(batch_dir)
    # only actionable packets (a registered fix_class), optionally restricted to one.
    rows = [r for r in rows if (r.get("fix_class") or "").strip()
            and (fix_class is None or r.get("fix_class") == fix_class)]
    if not rows:
        raise PreflightError("no actionable packets selected (need a fix_class; e.g. --fix-class subtotal_filter)")

    corrections_dir.mkdir(parents=True, exist_ok=True)
    prompts_dir = batch_dir / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    contract_abs = (config.PROJECT_ROOT / contract_rel).resolve().as_posix()
    validator = VALIDATOR.resolve().as_posix()

    seen: set[tuple] = set()
    manifest_rows: list[dict] = []
    supported_fix_classes = implemented_fix_classes()
    for row in rows:
        cik = str(row.get("cik") or "").strip()
        fc = str(row.get("fix_class") or "").strip()
        if not _CIK_RE.match(cik):
            raise PreflightError(f"invalid cik in worklist: {cik!r}")
        if fc not in supported_fix_classes:
            raise PreflightError(
                f"{cik}/{fc}: fix_class has no implemented trial applier; "
                f"supported={sorted(supported_fix_classes)}"
            )
        quarters = [q for q in str(row.get("quarters") or "").split(";") if q.strip()]
        if fc == "comparative_period_filter" and len(quarters) != 1:
            raise PreflightError(
                f"{cik}/{fc}: expected exactly one target quarter for comparative filter, "
                f"got {quarters}"
            )
        key = (cik, fc)
        if key in seen:
            raise PreflightError(f"duplicate packet in batch: {cik}/{fc}")
        seen.add(key)

        rids = [s for s in (row.get("source_review_ids") or "").split(";") if s.strip()]
        if not rids:
            raise PreflightError(f"{cik}/{fc}: no source_review_ids")
        verdicts = [_load_verdict(rid, verdicts_dir) for rid in rids]
        bundles = [_load_bundle(rid, bundles_dir) for rid in rids]
        for rid, (_, bundle) in zip(rids, bundles):
            bundle_cik = normalize_cik(bundle.get("cik"))
            if not bundle_cik:
                raise PreflightError(f"{rid}: source bundle missing cik")
            if bundle_cik != normalize_cik(cik):
                raise PreflightError(
                    f"{cik}/{fc}: source bundle {rid} belongs to CIK {bundle_cik}"
                )
        bundle_paths = [str(path) for path, _ in bundles]

        correction_path = (corrections_dir / cik / f"{fc}.json").resolve()
        if correction_path.exists():
            raise PreflightError(f"{cik}/{fc}: correction already exists at {correction_path}; clear before re-dispatch")
        correction_path.parent.mkdir(parents=True, exist_ok=True)
        # Lock key doubles as a lock filename ({lock_key}.lock); Windows forbids ':'
        # in filenames (reserved for drive letters / NTFS ADS), so use a safe separator.
        lock_key = f"B2__{cik}__{fc}"
        if review_lock.is_locked(lock_key):
            raise PreflightError(f"{cik}/{fc}: live lock already exists")

        prompt_path = prompts_dir / f"{cik}__{fc}.md"
        row["source_review_ids"] = ";".join(rids)
        manifest_rows.append({
            "cik": cik, "fix_class": fc, "mechanism": row.get("mechanism", ""),
            "quarters": row.get("quarters", ""),
            "source_review_ids": rids, "verdict_paths": [str((verdicts_dir / f"{r}.json").resolve()) for r in rids],
            "bundle_paths": bundle_paths, "prompt_path": str(prompt_path),
            "correction_path": str(correction_path), "lock_key": lock_key})

    acquired: list[str] = []
    if reserve:
        for r in manifest_rows:
            if not review_lock.acquire(r["lock_key"], owner=f"b2dispatch:{batch_id}"):
                for held in acquired:
                    review_lock.release(held)
                raise PreflightError(f"{r['lock_key']}: failed to acquire lock; released prior claims")
            acquired.append(r["lock_key"])

    for r in manifest_rows:
        verdicts = [json.loads(Path(p).read_text(encoding="utf-8")) for p in r["verdict_paths"]]
        Path(r["prompt_path"]).write_text(
            _worker_prompt(r, verdicts, contract_abs=contract_abs, bundle_paths=r["bundle_paths"],
                           correction_path=Path(r["correction_path"]), validator=validator, py=WORKER_PYTHON),
            encoding="utf-8")

    manifest = {
        "batch_id": batch_id, "created_at": datetime.now(timezone.utc).isoformat(),
        "locks_reserved": reserve, "max_parallel_default": 2,
        "corrections_dir": str(corrections_dir), "worker_python": WORKER_PYTHON,
        "worker_read_dirs": _worker_read_dirs(), "n_dispatch": len(manifest_rows),
        "rows": manifest_rows}
    manifest_path = batch_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return {"manifest_path": str(manifest_path), "n_dispatch": len(manifest_rows), "batch_id": batch_id}


def release_manifest(manifest_path: str) -> None:
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    for row in manifest.get("rows", []):
        review_lock.release(row.get("lock_key", ""))


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Agent B2 dispatch preflight ((cik, fix_class) keyed).")
    p.add_argument("--batch-id")
    p.add_argument("--fix-class", default=None, help="Restrict to one fix_class (e.g. subtotal_filter).")
    p.add_argument("--reserve", action="store_true")
    p.add_argument("--release-manifest")
    args = p.parse_args(argv)
    try:
        if args.release_manifest:
            release_manifest(args.release_manifest)
            print(json.dumps({"released_manifest": args.release_manifest}))
            return 0
        if not args.batch_id:
            raise PreflightError("--batch-id is required")
        print(json.dumps(preflight_batch(args.batch_id, fix_class=args.fix_class, reserve=args.reserve)))
        return 0
    except PreflightError as exc:
        print(f"PRECHECK_FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
