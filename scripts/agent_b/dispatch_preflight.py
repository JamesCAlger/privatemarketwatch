"""Deterministic parent-side preflight for Agent B1 worker dispatch.

The B analog of ``scripts/agent_a/dispatch_preflight.py``. Keyed on ``review_id``
(not CIK). For one batch it: reads the batch worklist, validates each
``review-bundle.v1`` bundle, B0-short-circuits items with no raw source to an auto
``ambiguous``/escalate verdict (no worker), acquires a per-review_id lock for the
rest, writes one blinded adjudication prompt per dispatched item, and emits the
manifest the dispatcher consumes.

Non-LLM, cache-only, read-only on production holdings/ledger; writes only under the
batch dir (prompts/manifest) and the auto-verdict short-circuits under verdicts_dir.
ASCII-only messages.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import site
import sys
from datetime import datetime, timezone
from pathlib import Path

from pipeline import config
from scripts.agent_b import review_lock

_RID_RE = re.compile(r"^[A-Za-z0-9_]{3,64}$")

# evidence_completeness states with no raw source to adjudicate against -> short-circuit.
_SHORT_CIRCUIT = {"ledger_only", "artifact_missing"}

DEFAULT_BASE = config.OUTPUT_DIR / "agent_b"
DEFAULT_BUNDLES = config.OUTPUT_DIR / "review_queue" / "review_bundles"
DEFAULT_VERDICTS = config.OUTPUT_DIR / "review_queue" / "verdicts"
DEFAULT_CONTRACT = "docs/adjudication_architecture/B1_adjudication_contract.md"

# Worker tooling, resolved to ABSOLUTE paths in the prompt. The worker's cwd is its
# Codex runroot, not the repo, so relative paths (the old form) broke; and a bare
# `python` on the sandbox PATH lacks this project's deps (the evidence CLI imports
# pandas), so the prompt names the exact interpreter that ran preflight (sys.executable).
EVIDENCE_CLI = config.PROJECT_ROOT / "scripts" / "review_agent" / "evidence_cli.py"
VALIDATOR = config.PROJECT_ROOT / "scripts" / "review_agent" / "validate_leaf_verdicts.py"
WORKER_PYTHON = sys.executable


def _worker_read_dirs() -> list[str]:
    """Directories the worker's interpreter must READ to import the project deps, so the
    dispatcher can grant the sandbox read access to them. The evidence CLI imports pandas;
    pandas may live in the env site-packages (under sys.prefix) OR the user site
    (%APPDATA%\\Python, outside the repo AND outside the conda root). Emit every real
    import root so the grant covers wherever the operator installed the deps."""
    cands = [sys.prefix]
    try:
        cands += list(site.getsitepackages())
    except Exception:  # getsitepackages can be absent in some venvs
        pass
    try:
        if site.ENABLE_USER_SITE:
            cands.append(site.getusersitepackages())
    except Exception:
        pass
    out: list[str] = []
    seen: set[str] = set()
    for d in cands:
        if not d:
            continue
        try:
            rp = str(Path(d).resolve())
        except OSError:
            continue
        if rp not in seen and Path(rp).exists():
            seen.add(rp)
            out.append(rp)
    return out


class PreflightError(RuntimeError):
    pass


def _batch_dir(base_dir: Path, batch_id: str) -> Path:
    return base_dir / "batch" / batch_id


def _read_worklist(batch_dir: Path) -> list[dict]:
    path = batch_dir / "worklist.csv"
    if not path.exists():
        raise PreflightError(f"missing worklist: {path}")
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise PreflightError(f"empty worklist: {path}")
    return rows


def _resolve_bundle_path(row: dict, bundles_dir: Path) -> Path:
    rid = row["review_id"]
    expected = (bundles_dir / f"{rid}.json").resolve()
    raw = (row.get("bundle_path") or "").strip()
    if raw:
        path = Path(raw)
        if not path.is_absolute():
            path = config.PROJECT_ROOT / path
        if path.resolve() != expected:
            raise PreflightError(f"{rid}: bundle_path must be the exact bundle: {expected}")
    if not expected.exists():
        raise PreflightError(f"{rid}: bundle missing: {expected}")
    return expected


def _validate_bundle(rid: str, bundle_path: Path) -> dict:
    try:
        bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PreflightError(f"{rid}: invalid bundle JSON: {bundle_path}: {exc}") from exc
    if bundle.get("schema_version") != "review-bundle.v1":
        raise PreflightError(f"{rid}: unexpected bundle schema_version: {bundle.get('schema_version')!r}")
    if str(bundle.get("review_id") or "") != rid:
        raise PreflightError(f"{rid}: bundle review_id mismatch: {bundle.get('review_id')!r}")
    if not str(bundle.get("evidence_completeness") or "").strip():
        raise PreflightError(f"{rid}: bundle missing evidence_completeness")
    if not bundle.get("evidence_items"):
        raise PreflightError(f"{rid}: bundle has no evidence_items")
    # A source-to-output identity collision means the packet's claimed absence is
    # disproven by the baseline. Do not dispatch an internally contradictory packet.
    integrity_errors = bundle.get("integrity_errors") or []
    if integrity_errors:
        raise PreflightError(f"{rid}: bundle identity-integrity failure: {integrity_errors}")
    return bundle


def _auto_verdict(rid: str, completeness: str) -> dict:
    """B0 short-circuit verdict: no raw source -> not adjudicable -> ambiguous/escalate.
    ``artifact_missing`` is a COVERAGE state (resolve upstream by caching), tracked
    distinctly from adjudication outcomes; both carry ``auto`` so finalize never counts
    them in precision."""
    return {
        "review_id": rid,
        "verdict": "ambiguous",
        "ambiguity_basis": "source_unavailable",
        "mechanism": "",
        "localized": False,
        "anchor_used": "",
        "observed_value": None,
        "anchor_value": None,
        "confidence": 0.0,
        "escalate": True,
        "culprit_citations": [],
        "rationale": (
            f"B0 short-circuit: evidence_completeness={completeness}; no raw source to "
            "adjudicate against. Not an adjudication outcome -- coverage/escalation state."
        ),
        "auto": True,
        "evidence_completeness": completeness,
    }


def _worker_prompt(row: dict, bundle: dict, bundle_path: Path, verdict_path: Path,
                   contract_abs: str, evidence_cli: str, validator: str, py: str) -> str:
    rid = row["review_id"]
    cik = bundle.get("cik", "")
    report_date = bundle.get("report_date", "")
    rule_name = bundle.get("rule_name", "")
    lane = bundle.get("lane", "")
    engine = bundle.get("engine", "")
    class_hint = (row.get("class_hint") or "").strip() or "(unspecified -- infer from the flag)"
    return f"""Agent B1 adjudication worker (blinded).

You are one bounded worker for the SEC XBRL private markets data platform. You adjudicate
ONE flagged item: is this flag a real data error, a false alarm, or genuinely ambiguous?
Do not launch nested Codex. Do not run tests, rebuilds, network calls, package installs,
SEC downloads, repo-wide scans, git status, or git diff.

The item under review:
- review_id: {rid}
- CIK: {cik}    report_date: {report_date}
- rule: {rule_name}    lane: {lane}    engine: {engine}
- localization class (B0.5 routing hint): {class_hint}
- bundle: {bundle_path}

You are BLINDED to the pipeline's own guess: the bundle does not tell you the answer.
Decide from raw source only.

All paths below are ABSOLUTE; your working directory is NOT the repo root, so use them
exactly as written. Invoke Python via the exact interpreter shown ("{py}") -- a bare
`python` on PATH may lack this project's dependencies (pandas etc.) and the evidence CLI
will fail to import.

Allowed reads:
- {contract_abs}  (the adjudication contract -- read it first)
- {bundle_path}
- The shared evidence CLI, pointed ONLY at the exact bundle above:
    "{py}" "{evidence_cli}" --bundle "{bundle_path}" overview
    "{py}" "{evidence_cli}" --bundle "{bundle_path}" tables
    "{py}" "{evidence_cli}" --bundle "{bundle_path}" totals
    "{py}" "{evidence_cli}" --bundle "{bundle_path}" roam --query "<issuer,terms>"
    "{py}" "{evidence_cli}" --bundle "{bundle_path}" grid --table <N> [--start 0 --count 100]

Allowed write (exactly one file):
- {verdict_path}

Required workflow:
1. Read the contract and the exact bundle. If the contract has a rule-specific
   adjudication standard for "{rule_name}", that standard is authoritative -- apply it.
2. Route by class (contract section "B0.5"): Class 1 confirm the one cell against its
   column; Class 2 decide WHICH field is wrong from the full row; Class 3 triangulate
   anchors FIRST (filing total vs companyfacts vs position sum), then localize via the
   row-disposition structure -- never scan a haystack.
3. Adjudicate against RAW SOURCE via the evidence CLI. Skeptic by default: missing or
   unclear source -> ambiguous, never a guess.
4. Write the verdict leaf JSON to the one allowed path. Required keys: review_id, verdict
   (real_error|false_alarm|ambiguous), mechanism, localized, anchor_used, observed_value,
   anchor_value, confidence (0..1), escalate, culprit_citations[], rationale.
   INVARIANT (the screen enforces it): a real_error MUST carry >=1 culprit_citation
   (table_index+row_index or a quoted_text) OR an anchor-disagreement proof (anchor_used
   set AND observed_value != anchor_value). No grounding -> you must say ambiguous.
   If the row carries MORE THAN ONE defect (e.g. a bad value AND a duplicate), record each
   in the optional "findings" list (mechanism + one-sentence detail + fix_class + citation)
   so the remediator does not re-derive it. findings are an ADVISORY diagnosis, not a fix;
   a finding's citation also satisfies the grounding invariant. See the contract's
   "findings" section for the fix_class vocabulary.
   AMBIGUOUS REQUIRES a basis -- set "ambiguity_basis" to one of:
     "source_checked"    -- you READ the raw source via the evidence CLI and it genuinely
                            does not decide the question (a real adjudication outcome).
     "source_unavailable" -- you could NOT read the raw source (evidence CLI failed,
                            cache miss, or env/sandbox error). Also set escalate=true.
                            This is a coverage/infra signal, NOT a judgment that the data
                            is unclear. Do NOT use it just because the answer is hard.
   Use "source_unavailable" ONLY when the evidence CLI did not return usable source.
5. Validate your own verdict and fix-and-rerun within budget if it fails:
   "{py}" "{validator}" --verdict "{verdict_path}"
6. Finish with a concise report: class, anchors used, verdict (and ambiguity_basis if
   ambiguous), mechanism, confidence, residual risk, and the verdict path written.

Production artifacts are read-only. The parent collects and re-validates every verdict;
nothing you write is trusted until it passes the deterministic screen.
"""


def preflight_batch(
    batch_id: str,
    *,
    base_dir: Path = DEFAULT_BASE,
    bundles_dir: Path = DEFAULT_BUNDLES,
    verdicts_dir: Path = DEFAULT_VERDICTS,
    contract_rel: str = DEFAULT_CONTRACT,
    selected_ids: set[str] | None = None,
    reserve: bool = False,
) -> dict:
    batch_dir = _batch_dir(base_dir, batch_id)
    rows = _read_worklist(batch_dir)
    if selected_ids:
        rows = [r for r in rows if r.get("review_id") in selected_ids]
        missing = selected_ids - {r.get("review_id") for r in rows}
        if missing:
            raise PreflightError(f"selected review_id(s) absent from worklist: {', '.join(sorted(missing))}")
    if not rows:
        raise PreflightError("no rows selected for dispatch")

    verdicts_dir.mkdir(parents=True, exist_ok=True)
    prompts_dir = batch_dir / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)

    seen: set[str] = set()
    manifest_rows: list[dict] = []
    auto_rows: list[dict] = []

    for row in rows:
        rid = str(row.get("review_id", "")).strip()
        if not _RID_RE.match(rid):
            raise PreflightError(f"invalid review_id in worklist: {rid!r}")
        if rid in seen:
            raise PreflightError(f"duplicate review_id in selected batch: {rid}")
        seen.add(rid)
        row["review_id"] = rid

        bundle_path = _resolve_bundle_path(row, bundles_dir)
        bundle = _validate_bundle(rid, bundle_path)
        completeness = str(bundle.get("evidence_completeness")).strip()
        verdict_path = (verdicts_dir / f"{rid}.json").resolve()

        if completeness in _SHORT_CIRCUIT:
            # Auto-resolve, no worker. Idempotent: don't clobber a non-auto verdict.
            if verdict_path.exists():
                existing = json.loads(verdict_path.read_text(encoding="utf-8"))
                if not existing.get("auto"):
                    raise PreflightError(f"{rid}: non-auto verdict already exists at {verdict_path}")
            else:
                verdict_path.write_text(
                    json.dumps(_auto_verdict(rid, completeness), indent=2) + "\n", encoding="utf-8"
                )
            auto_rows.append({"review_id": rid, "evidence_completeness": completeness,
                              "verdict_path": str(verdict_path)})
            continue

        if verdict_path.exists():
            raise PreflightError(f"{rid}: verdict already exists at {verdict_path}; clear before re-dispatch")
        if review_lock.is_locked(rid):
            raise PreflightError(f"{rid}: live review lock already exists")

        prompt_path = prompts_dir / f"{rid}.md"
        manifest_rows.append({
            "review_id": rid,
            "cik": bundle.get("cik", ""),
            "report_date": bundle.get("report_date", ""),
            "rule_name": bundle.get("rule_name", ""),
            "lane": bundle.get("lane", ""),
            "engine": bundle.get("engine", ""),
            "evidence_completeness": completeness,
            "bundle_path": str(bundle_path),
            "prompt_path": str(prompt_path),
            "verdict_path": str(verdict_path),
        })

    if not manifest_rows and not auto_rows:
        raise PreflightError("nothing to dispatch and nothing auto-resolved")

    acquired: list[str] = []
    if reserve:
        for row in manifest_rows:
            rid = row["review_id"]
            if not review_lock.acquire(rid, owner=f"dispatch:{batch_id}"):
                for held in acquired:
                    review_lock.release(held)
                raise PreflightError(f"{rid}: failed to acquire review lock; released prior claims")
            acquired.append(rid)

    # Resolve worker tooling to absolute paths (the worker's cwd is its Codex runroot).
    contract_abs = (config.PROJECT_ROOT / contract_rel).resolve().as_posix()
    evidence_cli = EVIDENCE_CLI.resolve().as_posix()
    validator = VALIDATOR.resolve().as_posix()

    # Write the per-worker prompts (after validation, so a bad row aborts before any write).
    for row in manifest_rows:
        bundle_path = Path(row["bundle_path"])
        bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
        Path(row["prompt_path"]).write_text(
            _worker_prompt(row, bundle, bundle_path, Path(row["verdict_path"]),
                           contract_abs, evidence_cli, validator, WORKER_PYTHON),
            encoding="utf-8",
        )

    manifest = {
        "batch_id": batch_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "locks_reserved": reserve,
        "max_parallel_default": 2,
        "verdicts_dir": str(verdicts_dir),
        # The interpreter the prompt tells the worker to use, plus the import roots the
        # dispatcher must grant the sandbox READ on so that interpreter can execute AND
        # import the project deps (pandas et al., which may be in the user site outside
        # the repo/conda root). user_site_enabled tells the dispatcher whether to keep
        # PYTHONNOUSERSITE off (the deps here are in the user site).
        "worker_python": WORKER_PYTHON,
        "worker_read_dirs": _worker_read_dirs(),
        "user_site_enabled": bool(getattr(site, "ENABLE_USER_SITE", False)),
        "n_dispatch": len(manifest_rows),
        "n_auto_resolved": len(auto_rows),
        "auto_resolved": auto_rows,
        "rows": manifest_rows,
    }
    manifest_path = batch_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return {
        "manifest_path": str(manifest_path),
        "n_dispatch": len(manifest_rows),
        "n_auto_resolved": len(auto_rows),
        "batch_id": batch_id,
    }


def release_manifest(manifest_path: str) -> None:
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    for row in manifest.get("rows", []):
        review_lock.release(row["review_id"])


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Agent B1 dispatch preflight (review_id keyed).")
    parser.add_argument("--batch-id")
    parser.add_argument("--review-id", action="append", default=[])
    parser.add_argument("--reserve", action="store_true")
    parser.add_argument("--release-manifest")
    parser.add_argument("--verdicts-dir", type=Path, default=None,
                        help="Override the verdict output dir (e.g. a scratch dir for a "
                             "stability re-run that must not touch the production store).")
    args = parser.parse_args(argv)

    try:
        if args.release_manifest:
            release_manifest(args.release_manifest)
            print(json.dumps({"released_manifest": args.release_manifest}))
            return 0
        if not args.batch_id:
            raise PreflightError("--batch-id is required")
        kwargs = {}
        if args.verdicts_dir is not None:
            kwargs["verdicts_dir"] = args.verdicts_dir
        result = preflight_batch(
            args.batch_id,
            selected_ids=set(args.review_id) if args.review_id else None,
            reserve=args.reserve,
            **kwargs,
        )
        print(json.dumps(result))
        return 0
    except PreflightError as exc:
        print(f"PRECHECK_FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
