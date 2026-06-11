"""Concurrent claim helper for BDC XBRL wrapper work.

The queue is derived from the unlisted BDC wrapper reference.  Claims are a
small coordination artifact, protected by an atomic file lock so multiple
agents can safely claim different CIKs in parallel.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import socket
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REFERENCE_FILE = (
    PROJECT_ROOT
    / "data"
    / "overrides"
    / "bdc_xbrl_wrappers"
    / "unlisted_bdc_xbrl_reference.json"
)
DEFAULT_WRAPPER_DIR = PROJECT_ROOT / "data" / "overrides" / "bdc_xbrl_wrappers"
DEFAULT_CLAIMS_FILE = PROJECT_ROOT / "data" / "output" / "bdc_wrapper_claims.json"
DEFAULT_SOURCE_RESIDUAL_FILE = PROJECT_ROOT / "data" / "output" / "source_reconciliation_residual_classification.csv"

CLAIMS_SCHEMA_VERSION = "bdc-wrapper-claims.v1"
ACTIVE_STATUSES = {"claimed"}
TERMINAL_STATUSES = {"done", "skipped"}


@dataclass(frozen=True)
class QueueEntry:
    cik: str
    entity_name: str
    wrapper_status: str
    has_holdings_data: bool
    holdings_rows: int
    holdings_quarters: int
    holdings_latest: str
    wrapper_staging_strategy: str
    blocking_issue_count: int
    blocking_fair_value: float


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _parse_iso(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _norm_cik(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return text.zfill(10)


def _to_int(value: Any) -> int:
    try:
        return int(float(str(value or "0").replace(",", "")))
    except ValueError:
        return 0


def _to_float(value: Any) -> float:
    try:
        return float(str(value or "0").replace(",", ""))
    except ValueError:
        return 0.0


class ClaimsLock:
    """File-based lock for atomic read-modify-write of claims JSON."""

    def __init__(self, claims_file: Path, stale_seconds: int = 60, timeout_seconds: int = 10) -> None:
        self.lock_file = claims_file.with_suffix(claims_file.suffix + ".lock")
        self.stale_seconds = stale_seconds
        self.timeout_seconds = timeout_seconds

    def __enter__(self) -> "ClaimsLock":
        deadline = time.time() + self.timeout_seconds
        while time.time() < deadline:
            try:
                self.lock_file.parent.mkdir(parents=True, exist_ok=True)
                fd = os.open(str(self.lock_file), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, f"{os.getpid()} {socket.gethostname()} {_now_iso()}\n".encode("ascii"))
                os.close(fd)
                return self
            except FileExistsError:
                try:
                    age = time.time() - self.lock_file.stat().st_mtime
                    if age > self.stale_seconds:
                        self.lock_file.unlink()
                        continue
                except OSError:
                    pass
                time.sleep(0.1)
        raise RuntimeError(f"Could not acquire claims lock: {self.lock_file}")

    def __exit__(self, *_exc: object) -> None:
        try:
            self.lock_file.unlink()
        except OSError:
            pass


def load_claims(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "schema_version": CLAIMS_SCHEMA_VERSION,
            "updated_at": "",
            "claims": {},
        }
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    if data.get("schema_version") == CLAIMS_SCHEMA_VERSION:
        data.setdefault("claims", {})
        return data

    # Accept the older flat style used by template learning helpers.
    claims = {}
    for cik, status in data.items():
        claims[_norm_cik(cik)] = {"status": str(status)}
    return {
        "schema_version": CLAIMS_SCHEMA_VERSION,
        "updated_at": "",
        "claims": claims,
    }


def save_claims(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data["schema_version"] = CLAIMS_SCHEMA_VERSION
    data["updated_at"] = _now_iso()
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)
        fh.write("\n")
    tmp.replace(path)


def load_reference_entries(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    entries = data.get("entries", [])
    if not isinstance(entries, list):
        raise ValueError(f"Reference file has no entries array: {path}")
    return entries


def load_blocking_summary(path: Path) -> dict[str, tuple[int, float]]:
    if not path.exists():
        return {}

    summary: dict[str, tuple[int, float]] = {}
    with path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            mechanism = str(row.get("mechanism", ""))
            blocking_issue = str(row.get("blocking_issue", "")).strip().lower()
            is_blocking = mechanism.startswith("blocking_") or blocking_issue in {"true", "1", "yes"}
            if not is_blocking:
                continue
            cik = _norm_cik(row.get("cik"))
            if not cik:
                continue
            issue_count = _to_int(row.get("issue_count") or row.get("blocking_issue_count"))
            fair_value = _to_float(row.get("affected_source_fair_value") or row.get("source_only_blocker_fv"))
            prev_count, prev_fv = summary.get(cik, (0, 0.0))
            summary[cik] = (prev_count + max(issue_count, 1), prev_fv + fair_value)
    return summary


def build_queue(
    reference_file: Path = DEFAULT_REFERENCE_FILE,
    wrapper_dir: Path = DEFAULT_WRAPPER_DIR,
    source_residual_file: Path = DEFAULT_SOURCE_RESIDUAL_FILE,
    include_no_holdings: bool = False,
    include_existing_wrappers: bool = False,
) -> list[QueueEntry]:
    blocking = load_blocking_summary(source_residual_file)
    wrapper_files = {
        path.stem.zfill(10)
        for path in wrapper_dir.glob("*.json")
        if path.name != "unlisted_bdc_xbrl_reference.json" and path.stem.isdigit()
    }
    queue: list[QueueEntry] = []
    seen: set[str] = set()

    for entry in load_reference_entries(reference_file):
        cik = _norm_cik(entry.get("cik"))
        if not cik or cik in seen:
            continue
        seen.add(cik)
        has_holdings = bool(entry.get("has_holdings_data"))
        wrapper_status = str(entry.get("wrapper_status", "")).strip().lower()
        has_wrapper_file = cik in wrapper_files
        if not include_no_holdings and not has_holdings:
            continue
        if not include_existing_wrappers and (wrapper_status == "exists" or has_wrapper_file):
            continue

        issue_count, fair_value = blocking.get(cik, (0, 0.0))
        queue.append(
            QueueEntry(
                cik=cik,
                entity_name=str(entry.get("entity_name", "")).strip(),
                wrapper_status=wrapper_status or "none",
                has_holdings_data=has_holdings,
                holdings_rows=_to_int(entry.get("holdings_rows")),
                holdings_quarters=_to_int(entry.get("holdings_quarters")),
                holdings_latest=str(entry.get("holdings_latest", "")).strip(),
                wrapper_staging_strategy=str(entry.get("wrapper_staging_strategy", "")).strip(),
                blocking_issue_count=issue_count,
                blocking_fair_value=fair_value,
            )
        )

    queue.sort(
        key=lambda item: (
            -item.blocking_issue_count,
            -item.blocking_fair_value,
            -item.holdings_rows,
            item.entity_name.lower(),
            item.cik,
        )
    )
    return queue


def _claim_status(claims: dict[str, Any], cik: str) -> str:
    claim = claims.get("claims", {}).get(cik, {})
    if isinstance(claim, str):
        return claim
    return str(claim.get("status", "")).strip().lower()


def _is_stale_claim(claim: dict[str, Any], stale_hours: float, now: datetime | None = None) -> bool:
    if stale_hours <= 0:
        return False
    claimed_at = _parse_iso(str(claim.get("claimed_at", "")))
    if claimed_at is None:
        return False
    now = now or datetime.now(timezone.utc)
    return (now - claimed_at).total_seconds() > stale_hours * 3600


def claim_next(
    *,
    claims_file: Path = DEFAULT_CLAIMS_FILE,
    reference_file: Path = DEFAULT_REFERENCE_FILE,
    wrapper_dir: Path = DEFAULT_WRAPPER_DIR,
    source_residual_file: Path = DEFAULT_SOURCE_RESIDUAL_FILE,
    agent: str = "",
    stale_hours: float = 24.0,
) -> QueueEntry | None:
    queue = build_queue(
        reference_file=reference_file,
        wrapper_dir=wrapper_dir,
        source_residual_file=source_residual_file,
    )
    with ClaimsLock(claims_file):
        claims = load_claims(claims_file)
        claim_map = claims.setdefault("claims", {})
        selected: QueueEntry | None = None
        previous_claim: dict[str, Any] | None = None
        for entry in queue:
            existing = claim_map.get(entry.cik)
            if isinstance(existing, str):
                existing = {"status": existing}
            status = str((existing or {}).get("status", "")).strip().lower()
            if status in TERMINAL_STATUSES:
                continue
            if status in ACTIVE_STATUSES and not _is_stale_claim(existing or {}, stale_hours):
                continue
            selected = entry
            previous_claim = existing if status in ACTIVE_STATUSES else None
            break

        if selected is None:
            return None

        claim_id = f"{selected.cik}-{int(time.time())}-{os.getpid()}"
        claim_map[selected.cik] = {
            "status": "claimed",
            "claim_id": claim_id,
            "claimed_at": _now_iso(),
            "claimed_by": agent or os.environ.get("USERNAME") or os.environ.get("USER") or socket.gethostname(),
            "entity_name": selected.entity_name,
            "holdings_rows": selected.holdings_rows,
            "holdings_quarters": selected.holdings_quarters,
            "holdings_latest": selected.holdings_latest,
            "blocking_issue_count": selected.blocking_issue_count,
            "blocking_fair_value": round(selected.blocking_fair_value, 2),
            "reclaimed_previous_claim": previous_claim,
        }
        save_claims(claims_file, claims)
        return selected


def update_claim(
    cik: str,
    status: str,
    *,
    claims_file: Path = DEFAULT_CLAIMS_FILE,
    agent: str = "",
    note: str = "",
) -> None:
    cik = _norm_cik(cik)
    if status not in {"done", "released", "skipped"}:
        raise ValueError(f"Unsupported claim status: {status}")
    with ClaimsLock(claims_file):
        claims = load_claims(claims_file)
        claim_map = claims.setdefault("claims", {})
        existing = claim_map.get(cik)
        if isinstance(existing, str):
            existing = {"status": existing}
        existing = dict(existing or {})
        if status == "released":
            existing["status"] = "released"
            existing["released_at"] = _now_iso()
            existing["released_by"] = agent
        else:
            existing["status"] = status
            existing[f"{status}_at"] = _now_iso()
            existing[f"{status}_by"] = agent
        if note:
            existing["note"] = note
        claim_map[cik] = existing
        save_claims(claims_file, claims)


def get_stats(
    *,
    claims_file: Path = DEFAULT_CLAIMS_FILE,
    reference_file: Path = DEFAULT_REFERENCE_FILE,
    wrapper_dir: Path = DEFAULT_WRAPPER_DIR,
    source_residual_file: Path = DEFAULT_SOURCE_RESIDUAL_FILE,
    stale_hours: float = 24.0,
) -> dict[str, int]:
    queue = build_queue(
        reference_file=reference_file,
        wrapper_dir=wrapper_dir,
        source_residual_file=source_residual_file,
    )
    claims = load_claims(claims_file)
    claim_map = claims.get("claims", {})
    active = 0
    stale = 0
    done = 0
    released = 0
    skipped = 0
    unclaimed = 0
    queued_ciks = {entry.cik for entry in queue}
    for entry in queue:
        claim = claim_map.get(entry.cik)
        if isinstance(claim, str):
            claim = {"status": claim}
        status = str((claim or {}).get("status", "")).strip().lower()
        if status == "claimed":
            if _is_stale_claim(claim or {}, stale_hours):
                stale += 1
            else:
                active += 1
        elif status == "done":
            done += 1
        elif status == "released":
            released += 1
            unclaimed += 1
        elif status == "skipped":
            skipped += 1
        else:
            unclaimed += 1

    orphan_claims = len([cik for cik in claim_map if cik not in queued_ciks])
    return {
        "queue": len(queue),
        "unclaimed": unclaimed,
        "claimed": active,
        "stale": stale,
        "done": done,
        "released": released,
        "skipped": skipped,
        "orphan_claims": orphan_claims,
    }


def _print_claim(entry: QueueEntry | None) -> int:
    if entry is None:
        print("All eligible wrapper CIKs are claimed, done, or skipped.")
        return 1
    print(f"CLAIMED CIK: {entry.cik}")
    print(f"  Name: {entry.entity_name}")
    print(f"  Holdings rows: {entry.holdings_rows}")
    print(f"  Holdings quarters: {entry.holdings_quarters}")
    print(f"  Latest holdings: {entry.holdings_latest}")
    print(f"  Blocking issue count: {entry.blocking_issue_count}")
    print(f"  Blocking fair value: {entry.blocking_fair_value:.2f}")
    print(f"  Staging strategy: {entry.wrapper_staging_strategy}")
    print("")
    print("Workflow:")
    print(f"  1. Profile: /wrapper {entry.cik} profile")
    print(f"  2. Create/update: /wrapper {entry.cik} create")
    print(f"  3. Validate: /wrapper {entry.cik} validate")
    print(f"  4. Mark done: python scripts/bdc_wrapper_worklist.py --done {entry.cik}")
    return 0


def _print_stats(stats: dict[str, int]) -> None:
    print("BDC wrapper worklist")
    for key in ["queue", "unclaimed", "claimed", "stale", "done", "released", "skipped", "orphan_claims"]:
        print(f"  {key}: {stats[key]}")


def _print_list(queue: list[QueueEntry], claims: dict[str, Any], limit: int) -> None:
    count = 0
    for entry in queue:
        status = _claim_status(claims, entry.cik) or "unclaimed"
        if status in TERMINAL_STATUSES:
            continue
        print(
            f"{entry.cik} | {status} | issues={entry.blocking_issue_count} | "
            f"fv={entry.blocking_fair_value:.2f} | rows={entry.holdings_rows} | {entry.entity_name}"
        )
        count += 1
        if limit and count >= limit:
            break


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Claim BDC wrapper CIKs for parallel agent work")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--next", action="store_true", help="Claim the next unclaimed CIK")
    action.add_argument("--stats", action="store_true", help="Show queue and claim counts")
    action.add_argument("--list", action="store_true", help="List queued CIKs and claim status")
    action.add_argument("--done", metavar="CIK", help="Mark a CIK as done")
    action.add_argument("--release", metavar="CIK", help="Release a claimed CIK back to the queue")
    action.add_argument("--skip", metavar="CIK", help="Mark a CIK as skipped")
    parser.add_argument("--agent", default="", help="Agent/operator name to record in claims")
    parser.add_argument("--note", default="", help="Optional note for done/release/skip")
    parser.add_argument("--stale-hours", type=float, default=24.0, help="Hours before a claimed CIK can be reclaimed")
    parser.add_argument("--limit", type=int, default=20, help="Rows to show with --list")
    parser.add_argument("--claims-file", type=Path, default=DEFAULT_CLAIMS_FILE)
    parser.add_argument("--reference-file", type=Path, default=DEFAULT_REFERENCE_FILE)
    parser.add_argument("--wrapper-dir", type=Path, default=DEFAULT_WRAPPER_DIR)
    parser.add_argument("--source-residual-file", type=Path, default=DEFAULT_SOURCE_RESIDUAL_FILE)
    args = parser.parse_args(argv)

    if args.next:
        entry = claim_next(
            claims_file=args.claims_file,
            reference_file=args.reference_file,
            wrapper_dir=args.wrapper_dir,
            source_residual_file=args.source_residual_file,
            agent=args.agent,
            stale_hours=args.stale_hours,
        )
        return _print_claim(entry)
    if args.stats:
        _print_stats(
            get_stats(
                claims_file=args.claims_file,
                reference_file=args.reference_file,
                wrapper_dir=args.wrapper_dir,
                source_residual_file=args.source_residual_file,
                stale_hours=args.stale_hours,
            )
        )
        return 0
    if args.list:
        queue = build_queue(
            reference_file=args.reference_file,
            wrapper_dir=args.wrapper_dir,
            source_residual_file=args.source_residual_file,
        )
        claims = load_claims(args.claims_file)
        _print_list(queue, claims, args.limit)
        return 0
    if args.done:
        update_claim(args.done, "done", claims_file=args.claims_file, agent=args.agent, note=args.note)
        print(f"Marked done: {_norm_cik(args.done)}")
        return 0
    if args.release:
        update_claim(args.release, "released", claims_file=args.claims_file, agent=args.agent, note=args.note)
        print(f"Released: {_norm_cik(args.release)}")
        return 0
    if args.skip:
        update_claim(args.skip, "skipped", claims_file=args.claims_file, agent=args.agent, note=args.note)
        print(f"Skipped: {_norm_cik(args.skip)}")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
