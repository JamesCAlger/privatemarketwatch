"""The observations log: errors a fund agent saw on the page that no ledger rule reported.

    python scripts/v05_evidence/observations.py add <report.json> [<report.json> ...]
    python scripts/v05_evidence/observations.py show [--open]

A fund agent lists them in its report under ``observations``; the gate has verified each one's
printed line before the orchestrator adds it here. The log is
docs/investigations/v05_observations.csv, one row per (fund, observation key). ``show`` groups by
key: an observation seen on several funds is a candidate for a new rule, and one whose cause is
shared code reaches funds nobody has looked at.

An entry in a report::

    {"observation_key": "unit-count-rescaled-by-issuer-normaliser",   (a slug for the PROBLEM, reused across funds)
     "what": "Warrant published with 6,314 units; the tag and the page say 4",
     "field": "shares_held", "quarters": ["2024-09-30"], "fair_value_m": 0.2,
     "cause": "row" | "fund" | "shared",    (this row; this fund's settings; shared code)
     "action": "fixed" | "parked" | "left",
     "suggested_check": "a unit count that changes by a factor of 1,000 or more between quarters",
     "quote": {"accession": "0000950170-24-124249", "text": "<line copied from page_line.py>"}}
"""
from __future__ import annotations

import csv
import datetime
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LOG = REPO / "docs/investigations/v05_observations.csv"
COLUMNS = ["observation_key", "cik", "cause", "action", "field", "quarters", "fair_value_m", "what", "suggested_check",
           "accession", "printed_line", "report", "added_on", "status"]
CAUSES = ("row", "fund", "shared")
ACTIONS = ("fixed", "parked", "left")


def problems(entry: dict) -> list[str]:
    """What is wrong with one observation entry; empty when it is well formed."""
    found = []
    for key in ("observation_key", "what", "field"):
        if not str(entry.get(key) or "").strip():
            found.append("missing " + key)
    if entry.get("cause") not in CAUSES:
        found.append("cause must be one of " + ", ".join(CAUSES))
    if entry.get("action") not in ACTIONS:
        found.append("action must be one of " + ", ".join(ACTIONS))
    if not isinstance(entry.get("quarters"), list) or not entry.get("quarters"):
        found.append("quarters must be a non-empty list")
    quote = entry.get("quote") or {}
    if not str(quote.get("accession") or "").strip() or not str(quote.get("text") or "").strip():
        found.append("needs a quote with accession and text")
    return found


def _read() -> list[dict]:
    if not LOG.exists():
        return []
    with open(LOG, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _write(rows: list[dict]) -> None:
    with open(LOG, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def add(paths: list[str]) -> int:
    rows = {(r["observation_key"], r["cik"]): r for r in _read()}
    added = 0
    for path in paths:
        report = json.loads(Path(path).read_text(encoding="utf-8"))
        cik = str(report.get("cik", "")).zfill(10)
        for entry in report.get("observations", []):
            bad = problems(entry)
            if bad:
                print("skipped (%s): %s" % ("; ".join(bad), str(entry.get("what"))[:80]))
                continue
            key = (entry["observation_key"], cik)
            previous = rows.get(key, {})
            rows[key] = {
                "observation_key": entry["observation_key"], "cik": cik, "cause": entry["cause"], "action": entry["action"],
                "field": entry["field"], "quarters": "; ".join(entry["quarters"]), "fair_value_m": entry.get("fair_value_m", ""),
                "what": " ".join(str(entry["what"]).split()), "suggested_check": " ".join(str(entry.get("suggested_check") or "").split()),
                "accession": entry["quote"]["accession"], "printed_line": " ".join(str(entry["quote"]["text"]).split())[:400],
                "report": Path(path).as_posix(), "added_on": previous.get("added_on") or datetime.date.today().isoformat(),
                # 'open' until a rule, a shared fix or an owner ruling closes it; kept across re-adds
                "status": previous.get("status") or ("closed_fixed_here" if entry["action"] == "fixed" and entry["cause"] == "row" else "open"),
            }
            added += 1
    _write([rows[k] for k in sorted(rows)])
    print("%d observations recorded; log holds %d" % (added, len(rows)))
    return 0


def show(only_open: bool) -> int:
    rows = [r for r in _read() if not only_open or r["status"] == "open"]
    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(row["observation_key"], []).append(row)
    order = {"shared": 0, "fund": 1, "row": 2}
    print("observation | funds | cause | open | what")
    for key, members in sorted(groups.items(), key=lambda kv: (min(order.get(m["cause"], 9) for m in kv[1]), -len(kv[1]))):
        causes = "/".join(sorted({m["cause"] for m in members}))
        print("   %-46s | %2d | %-6s | %d | %s" % (key[:46], len(members), causes, sum(m["status"] == "open" for m in members), members[0]["what"][:110]))
    return 0


def main(argv=None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if args and args[0] == "add" and len(args) > 1:
        return add(args[1:])
    if args and args[0] == "show":
        return show("--open" in args)
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
