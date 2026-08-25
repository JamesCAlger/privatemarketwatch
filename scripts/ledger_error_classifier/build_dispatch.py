"""Batch builder for the ledger-error-classifier worker lane.

Writes prompts + manifest for a batch of provenance-worklist review items.
NEVER dispatches workers (that is Task 4 / the admin-shell step).

Layout produced under ``batch_dir``:
  worklist.csv                   -- selected rows (PROVENANCE_WORKLIST_COLUMNS)
  prompts/{review_id}.md         -- one prompt per selected item
  manifest_w1.json               -- wave-stamped durable record
  manifest.json                  -- latest-wave pointer

Manifest fields mirror Agent B2's preflight conventions:
  batch_id, created_at, worker_python, worker_read_dirs,
  grant_profile, dispatch_requires, n_dispatch, rows[].

NO corrections_dir key -- this lane classifies ledger errors; it does not
author data corrections.

ASCII-only messages (Windows cp1252).
"""

from __future__ import annotations

import argparse
import csv
import json
import site
import sys
from datetime import datetime, timezone
from pathlib import Path

from pipeline import config
from pipeline.review_queue import PROVENANCE_WORKLIST_COLUMNS
from pipeline.ledger_error_verdict import ADJUDICATIONS

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Mirror B1's WORKER_PYTHON source (scripts/agent_b/dispatch_preflight.py)
WORKER_PYTHON: str = sys.executable

DEFAULT_BASE_DIR = config.OUTPUT_DIR / "ledger_error_classifier"
DEFAULT_WORKLIST = config.OUTPUT_DIR / "review_queue" / "provenance_worklist.csv"
DEFAULT_BUNDLES_DIR = config.OUTPUT_DIR / "review_queue" / "review_bundles"
DEFAULT_VERDICTS_DIR = config.OUTPUT_DIR / "ledger_error_classifier" / "verdicts"

# Read-only grant list (the four dirs the worker is allowed to read)
_GRANT_DIRS: list[str] = [
    str(config.OUTPUT_DIR / "review_queue" / "review_bundles"),
    str(config.OUTPUT_DIR / "provenance_ledger.csv"),
    str(config.OUTPUT_DIR / "private_markets_holdings.parquet"),
    str(config.RAW_DIR / "filings" / "bdc_xbrl"),
]


class BuildDispatchError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _worker_read_dirs() -> list[str]:
    """Python import roots + the lane-specific read grants.

    Mirrors scripts/agent_b/dispatch_preflight.py::_worker_read_dirs() for the
    interpreter import roots, then appends the four lane-specific grant paths.
    """
    cands: list[str] = [sys.prefix]
    try:
        cands += list(site.getsitepackages())
    except Exception:
        pass
    try:
        if site.ENABLE_USER_SITE:
            user = site.getusersitepackages()
            if user not in cands:
                cands.append(user)
    except Exception:
        pass
    seen: set[str] = set()
    result: list[str] = []
    for c in cands + _GRANT_DIRS:
        p = str(Path(c))
        if p not in seen:
            seen.add(p)
            result.append(p)
    return result


def _pad_cik(cik: str) -> str:
    digits = "".join(ch for ch in str(cik or "") if ch.isdigit())
    return digits.zfill(10) if digits else ""


def _next_wave_path(batch_dir: Path) -> tuple[Path, int]:
    """Return (manifest_wN.json path, wave number)."""
    waves: list[int] = []
    for p in batch_dir.glob("manifest_w*.json"):
        try:
            n = int(p.stem.split("_w")[1])
            waves.append(n)
        except (IndexError, ValueError):
            continue
    n = (max(waves) + 1) if waves else 1
    return batch_dir / f"manifest_w{n}.json", n


def _bundle_path(bundles_dir: Path, review_id: str) -> Path:
    return bundles_dir / f"{review_id}.json"


def _verdict_path(verdicts_dir: Path, review_id: str) -> Path:
    return verdicts_dir / f"{review_id}.json"


def _lock_key(review_id: str) -> str:
    # Colons forbidden in Windows filenames; use double-underscore as separator.
    return f"LEC__{review_id}"


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

_GATE_WARNING = (
    "GATE WARNING: every citation is re-derived from the provenance ledger by "
    "machinery you do not control; a citation that does not reproduce refuses "
    "the verdict."
)

_READ_ONLY_CONTRACT = (
    "READ-ONLY CONTRACT: you never modify data; your output is exactly one "
    "verdict JSON at the verdict_path shown below, or an escalation sibling "
    "({review_id}.escalation.json) when evidence is insufficient or unavailable."
)


def _adjudication_vocab_block() -> str:
    """Full adjudication vocabulary with per-verdict requirements.

    Requirements EXACTLY match pipeline.ledger_error_verdict.validate_ledger_verdict.
    Constants imported from that module (ADJUDICATIONS) so prompt and validator
    cannot drift silently.
    """
    lines = [
        "ADJUDICATION VOCABULARY",
        "=======================",
        f"Allowed verdict values: {', '.join(ADJUDICATIONS)}",
        "",
        "Per-verdict requirements (all verdicts require review_id + confidence in [0,1]):",
        "",
        "  extraction_wrong",
        "    - mechanism: non-empty string describing the extraction defect",
        "    - culprit_citations: >= 1 entry, each with:",
        "        row_id (str, non-empty), field (str, non-empty)",
        "        optional: declared_raw, instance_raw, published (numbers or null)",
        "",
        "  parser_drift",
        "    - mechanism: non-empty string (same as extraction_wrong)",
        "    - culprit_citations: >= 1 entry (same shape as extraction_wrong)",
        "    - drift_fingerprint: object with:",
        "        field (str, non-empty) -- the unified-holdings field that drifted",
        "        transform_code (str, non-empty) -- transform identifier (e.g. 'PCT_DIV_100')",
        "        affected_row_ids (list, non-empty) -- row_ids where the drift fires",
        "",
        "  filer_error",
        "    - filer_error_basis: non-empty string explaining why it is a filer error",
        "    - culprit_citations: >= 1 entry (same shape as extraction_wrong)",
        "    - escalate: true (recommended; this is an escalation-shaped outcome)",
        "",
        "  amended",
        "    - superseding_accession: non-empty accession number of the amending filing",
        "    - (no citations required)",
        "",
        "  false_flag",
        "    - no additional required keys",
        "",
        "  ambiguous",
        "    - ambiguity_basis: one of ('evidence_insufficient', 'source_unavailable')",
        "    - escalate: true (required when ambiguity_basis='source_unavailable')",
        "",
        "ESCALATION SIBLING CONVENTION",
        "=============================",
        "When you cannot reach a confident verdict (evidence insufficient or source",
        "unavailable), write {review_id}.escalation.json in the same directory as the",
        "verdict_path instead of a verdict JSON.  Escalation siblings count as coverage",
        "in the batch intake validator.  Shape: {review_id, ambiguity_basis,",
        "'escalation_reason': str, 'confidence': float}.",
    ]
    return "\n".join(lines)


def _build_prompt(row: dict, bundle_path: Path, verdict_path: Path) -> str:
    review_id = row["review_id"]
    cik = row["cik"]
    report_date = row["report_date"]
    reason_code = row["reason_code"]
    n_units = row.get("n_units", "?")
    fv_at_risk = row.get("fv_at_risk_m", "?")
    confidence = row.get("confidence", "?")

    return f"""Ledger-error-classifier adjudication worker.

{_READ_ONLY_CONTRACT}

{_GATE_WARNING}

FLAG SUMMARY
============
  review_id : {review_id}
  cik       : {cik}
  quarter   : {report_date}
  reason_code : {reason_code}
  n_units   : {n_units}
  fv_at_risk_m : {fv_at_risk}
  confidence (queue) : {confidence}

INPUT BUNDLE
============
  {bundle_path}

Read the bundle JSON at the path above.  It contains the provenance ledger
rows that triggered this flag, plus a holdings slice for the CIK/quarter.
The bundle is your primary evidence source.  Do NOT re-run the pipeline,
download SEC filings, or access any path outside the granted read dirs.

{_adjudication_vocab_block()}

OUTPUT
======
Write EXACTLY ONE of:
  (a) Verdict JSON at:
        {verdict_path}
      Required top-level keys: review_id, verdict, confidence
      (plus the per-verdict keys documented above)

  (b) Escalation sibling at:
        {verdict_path.with_name(review_id + ".escalation.json")}
      When evidence is insufficient or the source is unavailable; never
      write both files.

Do NOT create any other files.  Do NOT modify any existing file.

WORKFLOW
========
1. Read the bundle at the path above.
2. Identify which culprit rows triggered the {reason_code} flag.
3. Determine the verdict category from the vocabulary above.
4. If verdict is extraction_wrong or parser_drift: fill mechanism +
   culprit_citations (row_id + field per cited row) + drift_fingerprint
   if parser_drift.
5. If verdict is filer_error: fill filer_error_basis + culprit_citations.
6. If verdict is amended: fill superseding_accession.
7. If verdict is ambiguous: fill ambiguity_basis.
8. Write the verdict JSON to the verdict_path shown above.

Keep investigation bounded -- you should not need more than a few reads of
the bundle.  The gate re-derives every citation from the provenance ledger;
a cited (row_id, field) pair that is not in the ledger refuses the verdict.
"""


# ---------------------------------------------------------------------------
# Core: build_batch
# ---------------------------------------------------------------------------


def build_batch(
    worklist_rows: list[dict],
    batch_dir: Path,
    *,
    bundles_dir: Path = DEFAULT_BUNDLES_DIR,
    verdicts_dir: Path | None = None,
    batch_id: str | None = None,
) -> dict:
    """Build batch artifacts (worklist.csv, prompts, manifest) for a set of
    provenance-worklist rows.

    Parameters
    ----------
    worklist_rows:
        Selected rows from the provenance worklist.
    batch_dir:
        Target directory for this batch.
    bundles_dir:
        Where review bundle JSONs live (or will be built by build_review_bundles).
    verdicts_dir:
        Where workers write their verdict JSONs.
        Defaults to ``batch_dir / "verdicts"``.
    batch_id:
        Identifier string.  Defaults to batch_dir.name.

    Returns
    -------
    dict
        Manifest dict (also written to disk).

    Side effects
    ------------
    Calls ``sys.exit(1)`` if any row is outside the cohort (cohort guard).
    Calls ``pipeline.review_bundles.build_review_bundles(review_ids=...)`` for
    any review_ids whose bundle file is missing.
    """
    from pipeline import cohort_guard
    from pipeline import review_bundles as rb_module

    batch_dir = Path(batch_dir)
    bundles_dir = Path(bundles_dir)
    if verdicts_dir is None:
        verdicts_dir = batch_dir / "verdicts"
    verdicts_dir = Path(verdicts_dir)
    batch_id = batch_id or batch_dir.name

    # ---- cohort guard ----
    ciks = [r.get("cik", "") for r in worklist_rows]
    guard_result = cohort_guard.check_worklist(ciks)
    if not guard_result["ok"]:
        out = guard_result["out_of_cohort"]
        msg = (
            f"COHORT_GUARD_REFUSED: {len(out)} of {guard_result['n_worklist']} "
            f"worklist CIKs are outside the v1 cohort: {', '.join(out[:10])}"
        )
        print(msg, file=sys.stderr)
        sys.exit(1)

    # ---- ensure bundles exist ----
    missing_ids: set[str] = set()
    for row in worklist_rows:
        rid = row.get("review_id", "")
        if rid and not _bundle_path(bundles_dir, rid).exists():
            missing_ids.add(rid)
    if missing_ids:
        rb_module.build_review_bundles(review_ids=missing_ids)

    # ---- write worklist.csv ----
    batch_dir.mkdir(parents=True, exist_ok=True)
    worklist_path = batch_dir / "worklist.csv"
    with open(worklist_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=PROVENANCE_WORKLIST_COLUMNS,
                                extrasaction="ignore")
        writer.writeheader()
        writer.writerows(worklist_rows)

    # ---- write prompts ----
    prompts_dir = batch_dir / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    verdicts_dir.mkdir(parents=True, exist_ok=True)

    manifest_rows: list[dict] = []
    for row in worklist_rows:
        rid = row["review_id"]
        bpath = _bundle_path(bundles_dir, rid)
        vpath = _verdict_path(verdicts_dir, rid)
        prompt_path = prompts_dir / f"{rid}.md"

        prompt_text = _build_prompt(row, bpath, vpath)
        prompt_path.write_text(prompt_text, encoding="utf-8")

        manifest_rows.append({
            "review_id": rid,
            "cik": row.get("cik", ""),
            "report_date": row.get("report_date", ""),
            "reason_code": row.get("reason_code", ""),
            "prompt_path": str(prompt_path),
            "bundle_path": str(bpath),
            "verdict_path": str(vpath),
            "lock_key": _lock_key(rid),
        })

    # ---- write manifests ----
    wave_path, wave = _next_wave_path(batch_dir)
    manifest = {
        "batch_id": batch_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "wave": wave,
        "worker_python": WORKER_PYTHON,
        "worker_read_dirs": _worker_read_dirs(),
        "grant_profile": "read_only_classifier",
        "dispatch_requires": "admin_shell",
        "n_dispatch": len(manifest_rows),
        "rows": manifest_rows,
    }
    payload = json.dumps(manifest, indent=2)
    wave_path.write_text(payload, encoding="utf-8")
    (batch_dir / "manifest.json").write_text(payload, encoding="utf-8")

    return manifest


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="Build ledger-error-classifier batch (prompts + manifest, no dispatch)."
    )
    p.add_argument("--batch-id", required=True, help="Batch identifier string.")
    p.add_argument("--worklist", type=Path, default=DEFAULT_WORKLIST,
                   help="Provenance worklist CSV (Task 1 output).")
    p.add_argument("--top-n", type=int, default=None,
                   help="Take top-N rows by priority_rank.")
    p.add_argument("--base-dir", type=Path, default=DEFAULT_BASE_DIR,
                   help="Base dir; batch written to <base-dir>/batch/<batch-id>/.")
    args = p.parse_args(argv)

    if not args.worklist.exists():
        print(f"BUILD_DISPATCH_FAIL: worklist not found: {args.worklist}",
              file=sys.stderr)
        return 1

    with open(args.worklist, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    if args.top_n is not None:
        # Sort by priority_rank (ascending integer); rows without it go last.
        def _rank(r):
            try:
                return int(r.get("priority_rank") or 999999)
            except (ValueError, TypeError):
                return 999999

        rows = sorted(rows, key=_rank)[: args.top_n]

    batch_dir = args.base_dir / "batch" / args.batch_id

    try:
        manifest = build_batch(
            worklist_rows=rows,
            batch_dir=batch_dir,
            batch_id=args.batch_id,
        )
    except BuildDispatchError as exc:
        print(f"BUILD_DISPATCH_FAIL: {exc}", file=sys.stderr)
        return 1

    print(json.dumps({
        "batch_id": manifest["batch_id"],
        "n_dispatch": manifest["n_dispatch"],
        "manifest": str(batch_dir / "manifest.json"),
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
