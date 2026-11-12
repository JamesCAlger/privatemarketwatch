"""One-off: fill the decision store from the places decisions were kept before it existed.

    python scripts/migrate_decision_store.py [--dry-run]

Reads, and never modifies:
  docs/investigations/v05_readings/reports/*.json and unreviewed_2026-10-21/0*.json
      investigations            -> verdict entries (the fund agent's conclusion per finding)
      orchestrator_requests,
      request_resolution_history -> check_repair_request (verification_bug) / owner_request (other)
  docs/investigations/v05_readings/reviews/*.json and unreviewed_2026-10-21/reviews/*.json
      finding_reviews           -> review_outcome on the matching verdict
  docs/investigations/v05_owner_queue.csv
      ruled reasons             -> owner_ruling entries
  data/output/review_queue/verdicts, data/output/bdc_cik_review/verdicts
      reviewer verdict files    -> copied byte-for-byte to data/decisions/verdict_files/<store>/

Writes data/decisions/. Refuses to run when data/decisions already holds .jsonl files: the store is
append-only and a second migration would duplicate history. Dates: an entry takes the modification
date of the file it came from when the source records none. ASCII-only output.
"""
from __future__ import annotations

import argparse
import csv
import datetime
import json
import re
import shutil
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from pipeline import decision_store as ds  # noqa: E402
from pipeline import finding_status  # noqa: E402

READ = REPO / "docs/investigations/v05_readings"
OWNER_QUEUE = REPO / "docs/investigations/v05_owner_queue.csv"
VERDICT_STORES = {"review_queue": REPO / "data/output/review_queue/verdicts",
                  "bdc_cik_review": REPO / "data/output/bdc_cik_review/verdicts"}
_ACCESSION = re.compile(r"\d{10}-\d{2}-\d{6}")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_DELEGATE = "delegate:2026-11-12"


def _load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def _file_date(path: Path) -> str:
    return datetime.date.fromtimestamp(path.stat().st_mtime).isoformat()


def _ascii(text) -> str:
    return " ".join(str(text or "").split())


def _evidence(items) -> list[dict]:
    out = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        quote = _ascii(item.get("text") or item.get("quote") or item.get("verbatim"))
        if not quote:
            continue
        accession = _ascii(item.get("accession"))
        if _ACCESSION.fullmatch(accession):
            out.append({"source": "filing", "accession": accession, "quote": quote})
        else:
            out.append({"source": "query", "quote": (accession + ": " if accession else "") + quote})
    return out


def _reviews(review_dirs) -> dict[tuple[str, str], dict]:
    """(review file stem, finding_id) -> finding review, and ('', finding_id) -> the last one by file name."""
    out: dict[tuple[str, str], dict] = {}
    for directory in review_dirs:
        for path in sorted(Path(directory).glob("*.json")):
            data = _load(path)
            if not isinstance(data, dict):
                continue
            for fr in data.get("finding_reviews") or []:
                if isinstance(fr, dict) and fr.get("finding_id"):
                    record = {"outcome": fr.get("outcome"), "reviewer": _ascii(data.get("reviewer_id")) or path.stem}
                    out[(path.stem, fr["finding_id"])] = record
                    out[("", fr["finding_id"])] = record
    return out


def verdict_entries(report_paths, review_dirs) -> list[dict]:
    reviews = _reviews(review_dirs)
    out = []
    for path in report_paths:
        data = _load(path)
        if not isinstance(data, dict):
            continue
        cik = str(data.get("cik") or path.stem)[:10].zfill(10)
        label = _ascii(data.get("label"))
        agent = "agent:" + (_ascii(data.get("investigator_id")) or "fund-agent-" + (label or path.stem)).replace(" ", "_")
        for inv in data.get("investigations") or []:
            if not isinstance(inv, dict) or not inv.get("finding_id"):
                continue
            conclusion = inv.get("conclusion")
            if conclusion not in finding_status.CONCLUSIONS:
                continue
            review = reviews.get((cik + "_" + label, inv["finding_id"])) or reviews.get(("", inv["finding_id"])) or {}
            outcome = review.get("outcome") if review.get("outcome") in ("supported", "rejected") else ""
            quarter = str(inv.get("report_date") or inv.get("quarter") or "")[:10]
            entry = {
                "type": "verdict", "cik": cik, "finding_ids": [inv["finding_id"]],
                "engine": _ascii(inv.get("engine")), "rule_name": _ascii(inv.get("rule_name") or inv.get("rule")),
                "quarters": [quarter] if _DATE.fullmatch(quarter) else [],
                "statement": _ascii(inv.get("next_action") or inv.get("summary")) or "Investigation recorded in the fund report.",
                "evidence": _evidence(inv.get("evidence")), "conclusion": conclusion,
                "review_outcome": outcome, "reviewed_by": review.get("reviewer", "") if outcome else "",
                "decided_by": agent, "decided_on": _file_date(path),
                "migrated_from": path.relative_to(REPO).as_posix() if path.is_relative_to(REPO) else path.name,
                "sandbox": label,
            }
            if inv.get("carried_from"):
                entry["carried_from"] = _ascii(inv["carried_from"])
            out.append(entry)
    return out


def _resolution(text: str) -> str:
    low = str(text or "").lower()
    if not low or "deferred" in low:
        return "open"
    if "reverted" in low or "rejected" in low or "declined" in low:
        return "declined"
    return "implemented"


def request_entries(report_paths) -> list[dict]:
    out = []
    for path in report_paths:
        data = _load(path)
        if not isinstance(data, dict):
            continue
        cik = str(data.get("cik") or path.stem)[:10].zfill(10)
        label = _ascii(data.get("label"))
        agent = "agent:" + (_ascii(data.get("investigator_id")) or "fund-agent-" + (label or path.stem)).replace(" ", "_")
        items = [(r, True) for r in data.get("orchestrator_requests") or []] + \
                [(r, False) for r in data.get("request_resolution_history") or []]
        for number, (req, active) in enumerate(items, 1):
            if not isinstance(req, dict):
                continue
            original = req.get("original_request") if isinstance(req.get("original_request"), dict) else {}
            what = _ascii(req.get("what") or original.get("what"))
            target = _ascii(req.get("file") or original.get("file"))
            classification = _ascii(req.get("classification") or original.get("classification"))
            kind = "check_repair_request" if classification.startswith("verification_bug") else "owner_request"
            entry = {
                "type": kind, "cik": cik, "finding_ids": [], "quarters": [],
                "request_id": _ascii(req.get("request_id")) or "%s-%s-%d" % (cik, "active" if active else "hist", number),
                "statement": what or _ascii(req.get("response")) or "Request recorded in the fund report.",
                "evidence": _evidence(req.get("evidence") or original.get("evidence") or req.get("quotes")),
                "resolution": "open" if active else _resolution(req.get("resolution")),
                "classification": classification, "response": _ascii(req.get("response")),
                "authority": _ascii(req.get("authority")),
                "decided_by": agent, "decided_on": _file_date(path),
                "migrated_from": path.relative_to(REPO).as_posix() if path.is_relative_to(REPO) else path.name,
            }
            if kind == "check_repair_request":
                entry["check"] = target or "not named in the request"
            elif target:
                entry["target"] = target
            out.append(entry)
    return out


def ruling_entries(queue_path: Path) -> list[dict]:
    out = []
    if not Path(queue_path).exists():
        return out
    states = {"accepted": "accept", "rejected": "reject", "more_evidence": "more"}
    with open(queue_path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if row.get("state") not in states:
                continue
            words = _ascii(row.get("owner_words")) or "(no words recorded in the owner queue)"
            ruled_on = row.get("ruled_on") if _DATE.fullmatch(str(row.get("ruled_on") or "")) else _file_date(Path(queue_path))
            out.append({
                "type": "owner_ruling", "cik": "", "finding_ids": [], "quarters": [],
                "engine": _ascii(row.get("engine")), "rule_name": _ascii(row.get("rule_name")),
                "reason_key": row["reason_key"], "ruling": states[row["state"]], "words": words,
                "statement": "Owner queue ruling on reason %s (%s)." % (row["reason_key"], row["state"]),
                "evidence": [], "proposal_ids": _ascii(row.get("proposal_ids")),
                "decided_by": _DELEGATE if words.startswith("Delegated reviewer") else "owner",
                "decided_on": ruled_on, "migrated_from": "docs/investigations/v05_owner_queue.csv",
            })
    return out


def copy_verdict_files(stores: dict, target: Path, *, dry_run: bool) -> Counter:
    counts: Counter = Counter()
    for name, source in stores.items():
        if not Path(source).exists():
            continue
        for path in sorted(Path(source).glob("*.json")):
            counts[name] += 1
            if not dry_run:
                (target / name).mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target / name / path.name)
    return counts


def migrate(*, directory: Path, report_paths, review_dirs, queue_path: Path, verdict_stores: dict,
            dry_run: bool = False) -> dict:
    directory = Path(directory)
    if directory.exists() and any(directory.glob("*.jsonl")):
        raise SystemExit("refused: %s already holds decisions; the store is append-only" % directory)
    entries = verdict_entries(report_paths, review_dirs) + request_entries(report_paths) + ruling_entries(queue_path)
    counts: Counter = Counter()
    skipped: Counter = Counter()
    seen: set[str] = set()
    lines: dict[Path, list[str]] = {}
    stamp = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    for entry in entries:
        problems = ds.validate(entry)
        if problems:
            skipped[entry["type"] + ": " + problems[0]] += 1
            continue
        entry["decision_id"] = ds.decision_id(entry)
        if entry["decision_id"] in seen:
            skipped[entry["type"] + ": duplicate"] += 1
            continue
        seen.add(entry["decision_id"])
        # ordered by the source's own date, so a later report's conclusion outranks an earlier one
        entry["recorded_at"] = entry["decided_on"] + "T00:00:00"
        entry["migrated_at"] = stamp
        counts[entry["type"]] += 1
        target = directory / ((entry["cik"] + ".jsonl") if entry["cik"] else ds.SHARED_FILE)
        lines.setdefault(target, []).append(json.dumps(entry, sort_keys=True, ensure_ascii=True))
    if not dry_run:
        directory.mkdir(parents=True, exist_ok=True)
        for target, body in sorted(lines.items()):
            with open(target, "a", encoding="utf-8", newline="\n") as fh:
                fh.write("\n".join(body) + "\n")
    copied = copy_verdict_files(verdict_stores, directory / "verdict_files", dry_run=dry_run)
    return {"read": dict(Counter(e["type"] for e in entries)), "written": dict(counts),
            "skipped": dict(skipped), "verdict_files_copied": dict(copied), "files": len(lines)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--directory", type=Path, default=None)
    args = ap.parse_args(argv)
    reports = sorted((READ / "unreviewed_2026-10-21").glob("0*.json")) + sorted((READ / "reports").glob("*.json"))
    result = migrate(directory=args.directory or ds.default_dir(), report_paths=reports,
                     review_dirs=[READ / "unreviewed_2026-10-21/reviews", READ / "reviews"],
                     queue_path=OWNER_QUEUE, verdict_stores=VERDICT_STORES, dry_run=args.dry_run)
    print(json.dumps(result, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
