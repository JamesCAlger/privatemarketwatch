"""Cohort preflight guard: assert a dispatch worklist targets only the v1 cohort.

Expensive agentic validation (Codex fleets) is scoped to the ~70-BDC wrapper
cohort (AGENTS.md v1 scope). Data ingestion and the deterministic battery stay
universe-wide; DISPATCH is where the cohort boundary is enforced, because the
fleet is where the money goes. Historically the scoping lived inside each
sampler separately (ens1 shipped 51/56 out-of-cohort CIKs before the
sample_units fix, and 70% of its verdicts came back no_source); this guard
makes the boundary structural at the dispatch chokepoint instead.

Usage (dispatcher preflight, exit code is the contract):

    python -m pipeline.cohort_guard --worklist <batch>/worklist.csv
    python -m pipeline.cohort_guard --worklist ... --cik-column review_cik
    python -m pipeline.cohort_guard --worklist ... --all-vehicles   # logged bypass

Exit 0: all worklist CIKs in cohort (or bypass requested -- still prints the
out-of-cohort list so the bypass is an informed one). Exit 1: out-of-cohort
CIKs present. Exit 2: unreadable worklist/manifest. ASCII-only output.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from pipeline import config


def _pad(cik) -> str:
    digits = "".join(ch for ch in str(cik or "") if ch.isdigit())
    return digits.zfill(10) if digits else ""


def load_cohort_ciks(manifest_path: Path | None = None) -> set[str]:
    """10-digit-padded CIK set from the wrapper-cohort manifest ``entries``.

    held_back_ciks are deliberately NOT included: held-back means failed the
    FV-conservation admission gate, which is exactly the population the v1
    cohort excludes.
    """
    p = Path(manifest_path or config.WRAPPER_COHORT_MANIFEST_FILE)
    manifest = json.loads(p.read_text(encoding="utf-8-sig"))
    return {_pad(e.get("cik")) for e in manifest.get("entries", []) if _pad(e.get("cik"))}


def check_worklist(ciks, cohort: set[str] | None = None,
                   manifest_path: Path | None = None) -> dict:
    """Pure check: which of ``ciks`` fall outside the cohort.

    Returns {"ok", "cohort_id_size", "n_worklist", "n_in_cohort",
    "out_of_cohort": sorted padded ciks}. ``ok`` is True iff out_of_cohort is
    empty. Empty worklist is ok (nothing to dispatch is not a scope breach).
    """
    cohort = cohort if cohort is not None else load_cohort_ciks(manifest_path)
    padded = [_pad(c) for c in ciks if _pad(c)]
    out = sorted({c for c in padded if c not in cohort})
    return {
        "ok": not out,
        "cohort_size": len(cohort),
        "n_worklist": len(padded),
        "n_in_cohort": len(padded) - sum(1 for c in padded if c in set(out)),
        "out_of_cohort": out,
    }


def _read_worklist_ciks(path: Path, cik_column: str) -> list[str]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None or cik_column not in reader.fieldnames:
            raise KeyError(
                f"worklist has no '{cik_column}' column (columns: {reader.fieldnames})")
        return [row.get(cik_column, "") for row in reader]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Assert a dispatch worklist is cohort-scoped.")
    ap.add_argument("--worklist", required=True, help="batch worklist CSV")
    ap.add_argument("--cik-column", default="cik")
    ap.add_argument("--manifest", default=None,
                    help="override cohort manifest (default: config.WRAPPER_COHORT_MANIFEST_FILE)")
    ap.add_argument("--all-vehicles", action="store_true",
                    help="explicit bypass: report but do not fail on out-of-cohort CIKs")
    args = ap.parse_args(argv)

    try:
        ciks = _read_worklist_ciks(Path(args.worklist), args.cik_column)
        res = check_worklist(ciks, manifest_path=args.manifest)
    except (OSError, json.JSONDecodeError, KeyError) as exc:
        print(f"[cohort-guard] ERROR: {exc}")
        return 2

    if res["ok"]:
        print(f"[cohort-guard] OK: {res['n_worklist']} worklist CIKs all in the "
              f"{res['cohort_size']}-fund cohort")
        return 0
    listing = ", ".join(res["out_of_cohort"][:20])
    more = len(res["out_of_cohort"]) - 20
    tail = f" (+{more} more)" if more > 0 else ""
    if args.all_vehicles:
        print(f"[cohort-guard] BYPASS (--all-vehicles): {len(res['out_of_cohort'])} "
              f"out-of-cohort CIKs will be dispatched: {listing}{tail}")
        return 0
    print(f"[cohort-guard] REFUSED: {len(res['out_of_cohort'])} of {res['n_worklist']} "
          f"worklist CIKs are outside the v1 cohort: {listing}{tail}")
    print("[cohort-guard] pass --all-vehicles to bypass explicitly (logged), or "
          "re-draw the worklist cohort-scoped")
    return 1


if __name__ == "__main__":
    sys.exit(main())
