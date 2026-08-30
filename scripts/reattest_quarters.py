"""Quarter re-attestation: freeze the ATTESTATION, not the code (owner decision 2026-08-30).

A signed-off quarter's acceptance verdict is a function of (code, data) at
sign-off time. The codebase deliberately evolves -- correctness fixes reach
history -- so a semantics change can retroactively flip a signed-off quarter
(observed 2026-08-30: retain-and-flag regressed 1633336's Q4-2025 reconciles
until the is_subsidiary false-positive fix restored it; caught only by an
ad-hoc diff). This tool makes such flips DETECTED, ATTRIBUTED, and LEDGERED:

  attest --quarter 2025-12-31 --source data/output/quarter_pass/q4final/acceptance_post.json
      Record the signed acceptance artifact (plus the current git commit) into
      data/reference/acceptance_attestations/<quarter>.json. Pair with a git
      tag: `git tag signoff-<quarter> <commit>`.

  check [--quarter 2025-12-31]
      Re-run pipeline.quarter_acceptance for each attested quarter against
      CURRENT code+data, diff verdict + per-check outcomes vs the stored
      attestation, print the flips, and APPEND one row per quarter to
      data/output/acceptance_reattestation_ledger.csv (append-only).
      Exit 1 if any quarter REGRESSED (pass->fail on verdict or any check).

Run `check` after any validation-semantics change and in the quarter-pass
preflight window. Cache-only, no network. ASCII-only output.
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline import config

ATTEST_DIR = PROJECT_ROOT / "data" / "reference" / "acceptance_attestations"
LEDGER = config.OUTPUT_DIR / "acceptance_reattestation_ledger.csv"
LEDGER_COLUMNS = ["checked_utc", "quarter", "stored_verdict", "current_verdict",
                  "regressed", "check_flips", "stored_commit", "current_commit", "note"]


def compare_attestation(stored: dict, current: dict) -> dict:
    """Diff a stored acceptance artifact against a current re-run.

    Returns verdict_flip (None or (stored, current)), check_flips (per-check
    (actual, pass) pairs for every check whose PASS/FAIL outcome changed), and
    regressed (True when the stored verdict/check passed and now fails --
    improvements are flips but not regressions)."""
    sv, cv = str(stored.get("verdict")), str(current.get("verdict"))
    verdict_flip = None if sv == cv else (sv, cv)
    s_checks = {c.get("id"): c for c in (stored.get("checks") or [])}
    c_checks = {c.get("id"): c for c in (current.get("checks") or [])}
    flips = []
    regressed = sv == "PASS" and cv != "PASS"
    for cid in sorted(set(s_checks) | set(c_checks)):
        s, c = s_checks.get(cid), c_checks.get(cid)
        sp = bool(s.get("pass")) if s else None
        cp = bool(c.get("pass")) if c else None
        if sp != cp:
            flips.append({"id": cid,
                          "stored": (s.get("actual"), sp) if s else None,
                          "current": (c.get("actual"), cp) if c else None})
            if sp is True and cp is not True:
                regressed = True
    return {"verdict_flip": verdict_flip, "check_flips": flips, "regressed": regressed}


def ledger_row(quarter: str, diff: dict, *, stored_commit: str = "",
               current_commit: str = "", note: str = "") -> dict:
    vf = diff.get("verdict_flip")
    stored_v = vf[0] if vf else "="
    current_v = vf[1] if vf else "="
    # When no flip, record the shared verdict if the caller passed it via note-free
    # convention; the check() driver fills real verdicts before writing.
    return {
        "checked_utc": datetime.now(timezone.utc).isoformat(),
        "quarter": quarter,
        "stored_verdict": stored_v,
        "current_verdict": current_v,
        "regressed": 1 if diff.get("regressed") else 0,
        "check_flips": ";".join(
            f"{f['id']}:{(f.get('stored') or ('?', '?'))[1]}->{(f.get('current') or ('?', '?'))[1]}"
            for f in diff.get("check_flips") or []) or "",
        "stored_commit": stored_commit,
        "current_commit": current_commit,
        "note": note,
    }


def _git_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True,
                              cwd=PROJECT_ROOT).stdout.strip()
    except OSError:
        return ""


def _append_ledger(row: dict) -> None:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    exists = LEDGER.exists()
    with open(LEDGER, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=LEDGER_COLUMNS)
        if not exists:
            w.writeheader()
        w.writerow(row)


def attest(quarter: str, source: Path) -> None:
    obj = json.loads(Path(source).read_text(encoding="utf-8-sig"))
    if str(obj.get("target_quarter")) != quarter:
        raise SystemExit(f"source artifact is for {obj.get('target_quarter')!r}, not {quarter}")
    ATTEST_DIR.mkdir(parents=True, exist_ok=True)
    out = ATTEST_DIR / f"{quarter}.json"
    record = {"attested_utc": datetime.now(timezone.utc).isoformat(),
              "signoff_commit": _git_commit(),
              "source_artifact": str(source),
              "acceptance": obj}
    out.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(f"attested {quarter} (verdict {obj.get('verdict')}) -> {out}")
    print(f"pair with: git tag signoff-{quarter} {record['signoff_commit']}")


def check(quarter: str | None = None) -> int:
    quarters = ([quarter] if quarter else
                sorted(p.stem for p in ATTEST_DIR.glob("*.json")))
    if not quarters:
        print("no attested quarters; run `attest` first")
        return 0
    any_regressed = False
    cur_commit = _git_commit()
    for q in quarters:
        stored_rec = json.loads((ATTEST_DIR / f"{q}.json").read_text(encoding="utf-8-sig"))
        stored = stored_rec["acceptance"]
        # Re-run acceptance for the quarter against current code+data. The module
        # writes its normal artifact; we read the JSON it prints/writes.
        proc = subprocess.run(
            [sys.executable, "-m", "pipeline.quarter_acceptance", "--quarter", q],
            capture_output=True, text=True, cwd=PROJECT_ROOT)
        current = json.loads((config.OUTPUT_DIR / "quarter_acceptance.json")
                             .read_text(encoding="utf-8-sig"))
        if str(current.get("target_quarter")) != q:
            print(f"[{q}] SKIP: current artifact is for {current.get('target_quarter')!r}")
            continue
        diff = compare_attestation(stored, current)
        row = ledger_row(q, diff, stored_commit=str(stored_rec.get("signoff_commit") or ""),
                         current_commit=cur_commit,
                         note="" if proc.returncode in (0, 1, 2) else f"acceptance rc={proc.returncode}")
        row["stored_verdict"] = str(stored.get("verdict"))
        row["current_verdict"] = str(current.get("verdict"))
        _append_ledger(row)
        flips = row["check_flips"] or "none"
        tag = "REGRESSED" if diff["regressed"] else ("flip" if diff["verdict_flip"] or diff["check_flips"] else "ok")
        print(f"[{q}] {row['stored_verdict']} -> {row['current_verdict']} | {tag} | check flips: {flips}")
        any_regressed = any_regressed or diff["regressed"]
    return 1 if any_regressed else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Quarter acceptance re-attestation.")
    sub = ap.add_subparsers(dest="mode", required=True)
    a = sub.add_parser("attest")
    a.add_argument("--quarter", required=True)
    a.add_argument("--source", type=Path, required=True,
                   help="the signed acceptance_post.json (e.g. the pass dir's)")
    c = sub.add_parser("check")
    c.add_argument("--quarter", default=None)
    args = ap.parse_args(argv)
    if args.mode == "attest":
        attest(args.quarter, args.source)
        return 0
    return check(args.quarter)


if __name__ == "__main__":
    sys.exit(main())
