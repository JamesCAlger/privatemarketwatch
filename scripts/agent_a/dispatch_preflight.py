"""Deterministic parent-side preflight for Agent A2 worker dispatch.

This module owns the checks that must happen once, before any Codex worker is
launched for a quarterly batch. It is intentionally non-LLM and cache-only.
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
from scripts.agent_a import cik_lock


_CIK_RE = re.compile(r"^[0-9]{1,10}$")


class PreflightError(RuntimeError):
    pass


def _quarter_dir(quarter: str) -> Path:
    return config.OUTPUT_DIR / "agent_a" / "quarter" / quarter


def _proposal_paths(cik: str) -> tuple[Path, Path]:
    proposals = config.OUTPUT_DIR / "agent_a" / "proposals"
    return proposals / f"{cik}.anchors.json", proposals / f"{cik}.grammar.json"


def _manifest_path(quarter: str, batch_id: str) -> Path:
    return _quarter_dir(quarter) / "dispatch" / batch_id / "manifest.json"


def _prompt_path(quarter: str, batch_id: str, cik: str) -> Path:
    return _quarter_dir(quarter) / "dispatch" / batch_id / "prompts" / f"{cik}.md"


def _read_worklist(quarter: str, remediation: bool = False) -> list[dict]:
    path = _quarter_dir(quarter) / ("remediation_worklist.csv" if remediation else "worklist.csv")
    if not path.exists():
        raise PreflightError(f"missing worklist: {path}")
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise PreflightError(f"empty worklist: {path}")
    return rows


def _resolve_bundle_path(row: dict, quarter: str, remediation: bool = False) -> Path:
    raw = row.get("bundle_path", "")
    if not raw:
        raise PreflightError(f"{row.get('cik', '<missing-cik>')}: missing bundle_path")
    path = Path(raw)
    if not path.is_absolute():
        path = config.PROJECT_ROOT / path
    actual = path.resolve()
    if remediation:
        bundles_dir = (_quarter_dir(quarter) / "bundles").resolve()
        if actual.parent != bundles_dir:
            raise PreflightError(f"{row['cik']}: remediation bundle must be under {bundles_dir}")
    else:
        expected = (_quarter_dir(quarter) / "bundles" / f"{row['cik']}_{quarter}.json").resolve()
        if actual != expected:
            raise PreflightError(f"{row['cik']}: bundle_path must be exact quarterly bundle: {expected}")
    if not actual.exists():
        raise PreflightError(f"{row['cik']}: bundle missing: {actual}")
    return actual


def _validate_bundle(row: dict, quarter: str, bundle_path: Path, remediation: bool = False) -> dict:
    try:
        bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PreflightError(f"{row['cik']}: invalid bundle JSON: {bundle_path}: {exc}") from exc

    bundle_quarter = row.get("remediate_quarter") if remediation else quarter
    checks = {
        "cik": row["cik"],
        "report_date": bundle_quarter,
        "engine": "agentA",
    }
    for key, expected in checks.items():
        if str(bundle.get(key, "")) != expected:
            raise PreflightError(
                f"{row['cik']}: bundle {key} mismatch: expected {expected}, got {bundle.get(key)!r}"
            )
    if int(bundle.get("n_rows") or 0) <= 0:
        raise PreflightError(f"{row['cik']}: bundle has no rows")
    if row.get("regime") and bundle.get("regime") != row.get("regime"):
        raise PreflightError(f"{row['cik']}: bundle/worklist regime mismatch")
    if not bundle.get("top_variants"):
        raise PreflightError(f"{row['cik']}: bundle has no top_variants")
    if not bundle.get("evidence_items"):
        raise PreflightError(f"{row['cik']}: bundle has no evidence_items")
    return bundle


def _worker_prompt(row: dict, quarter: str, bundle_path: Path) -> str:
    cik = row["cik"]
    anchors, grammar = _proposal_paths(cik)
    return f"""Agent A2 identifier/rate grammar induction worker.

You are operating as one bounded worker for the SEC XBRL private markets data platform.
Do not launch nested Codex. Do not run tests, rebuilds, network calls, package installs,
SEC downloads, repo-wide scans, git status, or git diff.

Parent preflight has acquired the per-CIK claim for:
- Quarter: {quarter}
- CIK: {cik}
- Fund: {row.get('entity_name', '')}
- Bundle: {bundle_path}

Allowed reads:
- docs/adjudication_architecture/A2_sandbox_task_contract.md
- {bundle_path}
- Existing production override files for CIK {cik}, read-only:
  data/overrides/identifier_anchors/{cik}.json
  data/overrides/identifier_rate_grammars/{cik}.json
- Shared evidence CLI commands only when pointed at the exact bundle above.

Allowed writes:
- {anchors}
- {grammar}

Required workflow:
1. Read the contract and exact bundle.
2. Inventory the datapoints actually present in the bundle's investment_identifier strings.
   Do not treat SOI/source-table columns as if they were embedded in the identifier.
3. If rate/date datapoints are present in identifiers, propose extractors for only those
   supported datapoints. If identifiers carry issuer/type/tranche only, write
   status NOT_APPLICABLE_RATE_GRAMMAR with available_identifier_datapoints,
   unsupported_identifier_datapoints, and not_applicable_reason instead of forcing a rate
   grammar.
   Extractor schema (agentA-rate-grammar.v1) -- the deterministic screen REJECTS anything
   else, so use EXACTLY these or you will waste iterations:
   - extractor keys: ONLY "field", "regex", "group" (an INTEGER capture-group index; a
     "(?:...)" non-capturing group does not count -- the value must be a real "(...)" group),
     "type", "map". Do NOT use "scale"/"format"/"required"/"source"/"unit" -- the engine
     ignores unknown keys, so the extractor would silently no-op.
   - "type" must be one of: "pct", "bps", "date_mdy", "ref_code", "text". NOT
     "percent"/"date"/"string". Use "bps" for spreads in basis points (e.g. 400 -> 4.00%),
     "pct" for percent values, "date_mdy" for M/D/Y dates.
   - required_fields must include >=1 substantive rate field (basis_spread, interest_rate,
     interest_rate_all_in, interest_rate_total, reference_rate_type, or maturity_date) and
     must NOT include optional fields (pik_rate, interest_rate_floor, interest_rate_cash_leg).
   - The grammar MUST include applies_to (with regime AND signature) and, if it extracts any
     rate/date field, at least one invariant. Each invariant needs "name", "kind", and the
     keys its kind requires (or the screen rejects it): pct_agree/date_agree -> "parsed" +
     "twin"; implication -> "if_present" + "then_present"; sum_identity -> "total" + "parts".
   - Samples span multiple report_date eras; one grammar must parse the OLD and NEW formats.
4. Write proposal JSON only to the two allowed staged proposal paths.
5. Run:
   python -m scripts.agent_a.validate_proposal --cik {cik} --bundle {bundle_path}
6. If validation fails, fix the proposal and rerun it within the worker budget.
7. Finish with a concise report: actions run, files read/written, available datapoints,
   validation result,
   confidence, residual risk, and changed proposal paths.

Production override paths are read-only. The parent will run staged finalize/gate and
promote only PASS proposals after deterministic validation.
"""


def preflight_quarter(
    quarter: str,
    batch_id: str | None = None,
    selected_ciks: set[str] | None = None,
    reserve: bool = False,
    remediation: bool = False,
) -> dict:
    batch_id = batch_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    rows = _read_worklist(quarter, remediation=remediation)
    if selected_ciks:
        rows = [r for r in rows if r.get("cik") in selected_ciks]
        missing = selected_ciks - {r.get("cik") for r in rows}
        if missing:
            raise PreflightError(f"selected CIK(s) absent from worklist: {', '.join(sorted(missing))}")
    if not rows:
        raise PreflightError("no rows selected for dispatch")

    seen: set[str] = set()
    manifest_rows: list[dict] = []
    for row in rows:
        cik = str(row.get("cik", "")).strip()
        if not _CIK_RE.match(cik):
            raise PreflightError(f"invalid CIK in worklist: {cik!r}")
        row["cik"] = cik
        if cik in seen:
            raise PreflightError(f"duplicate CIK in selected batch: {cik}")
        seen.add(cik)
        if not remediation and row.get("quarter") != quarter:
            raise PreflightError(f"{cik}: worklist quarter mismatch")
        if cik_lock.is_locked(cik):
            raise PreflightError(f"{cik}: live CIK lock already exists")
        anchors, grammar = _proposal_paths(cik)
        stale = [str(p) for p in (anchors, grammar) if p.exists()]
        if stale:
            raise PreflightError(f"{cik}: stale proposal file(s) exist: {', '.join(stale)}")
        bundle_path = _resolve_bundle_path(row, quarter, remediation=remediation)
        bundle = _validate_bundle(row, quarter, bundle_path, remediation=remediation)
        row["regime"] = row.get("regime") or str(bundle.get("regime", ""))
        manifest_rows.append({
            "cik": cik,
            "entity_name": row.get("entity_name", ""),
            "quarter": quarter,
            "bundle_report_date": str(bundle.get("report_date", "")),
            "reason": row.get("reason", ""),
            "regime": row.get("regime", ""),
            "n_rows": int(bundle.get("n_rows") or 0),
            "bundle_path": str(bundle_path),
            "prompt_path": str(_prompt_path(quarter, batch_id, cik)),
            "proposal_anchors_path": str(anchors),
            "proposal_grammar_path": str(grammar),
        })

    acquired: list[str] = []
    if reserve:
        for row in manifest_rows:
            cik = row["cik"]
            if not cik_lock.acquire(cik, owner=f"dispatch:{batch_id}"):
                for held in acquired:
                    cik_lock.release(held)
                raise PreflightError(f"{cik}: failed to acquire CIK lock; released prior claims")
            acquired.append(cik)

    out_path = _manifest_path(quarter, batch_id)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    (out_path.parent / "prompts").mkdir(parents=True, exist_ok=True)
    manifest = {
        "quarter": quarter,
        "batch_id": batch_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "locks_reserved": reserve,
        "max_parallel_default": 2,
        "proposals_dir": str(config.OUTPUT_DIR / "agent_a" / "proposals"),
        "rows": manifest_rows,
    }
    for row in manifest_rows:
        prompt_path = Path(row["prompt_path"])
        prompt_path.write_text(_worker_prompt(row, quarter, Path(row["bundle_path"])), encoding="utf-8")
    out_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return {"manifest_path": str(out_path), "n_rows": len(manifest_rows), "batch_id": batch_id}


def release_manifest(manifest_path: str) -> None:
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    for row in manifest.get("rows", []):
        cik_lock.release(row["cik"])


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quarter")
    parser.add_argument("--batch-id")
    parser.add_argument("--cik", action="append", default=[])
    parser.add_argument("--reserve", action="store_true")
    parser.add_argument("--remediation", action="store_true")
    parser.add_argument("--release-manifest")
    args = parser.parse_args(argv)

    try:
        if args.release_manifest:
            release_manifest(args.release_manifest)
            print(json.dumps({"released_manifest": args.release_manifest}))
            return 0
        if not args.quarter:
            raise PreflightError("--quarter is required")
        result = preflight_quarter(
            args.quarter,
            batch_id=args.batch_id,
            selected_ciks=set(args.cik) if args.cik else None,
            reserve=args.reserve,
            remediation=args.remediation,
        )
        print(json.dumps(result))
        return 0
    except PreflightError as exc:
        print(f"PRECHECK_FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
