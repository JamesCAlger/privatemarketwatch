"""The owner's decision ledger: one row per REASON a finding is proposed to need no fix.

    python scripts/v05_evidence/owner_queue.py build
    python scripts/v05_evidence/owner_queue.py show [<reason key>]
    python scripts/v05_evidence/owner_queue.py rule <reason key> accept|reject|more --words "<the owner's words>"

Proposals are written per fund (data/overrides/finding_dispositions_proposed/*.json). The owner
decides per reason, so ``build`` groups them: proposals that carry the same ``reason_key`` are one
row; a proposal without one is a row of its own. The ledger is
docs/investigations/v05_owner_queue.csv (state, the owner's words and the date are kept across
rebuilds) with a readable view beside it (.md).

``rule ... accept`` is the only way a proposal becomes an accepted disposition: it copies the
row's proposals into data/overrides/finding_dispositions/owner_queue_accepted.json with the
owner's words. Nothing here adds a reason to the by-check list
(data/reference/accepted_disposition_reasons.json): that needs a check that has passed its
negative tests, and is a separate owner decision. ``reject`` and ``more`` only record the ruling;
the findings stay outstanding.
"""
from __future__ import annotations

import argparse
import csv
import datetime
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))
PROPOSED = REPO / "data/overrides/finding_dispositions_proposed"
ACCEPTED = REPO / "data/overrides/finding_dispositions/owner_queue_accepted.json"
LEDGER = REPO / "docs/investigations/v05_owner_queue.csv"
VIEW = REPO / "docs/investigations/v05_owner_queue.md"
REASONS = REPO / "data/reference/accepted_disposition_reasons.json"
COLUMNS = ["reason_key", "state", "engine", "rule_name", "class", "funds", "fund_quarters", "proposals", "quotes_verified",
           "check_available", "statement", "recommended", "owner_words", "ruled_on", "proposal_ids", "source_files"]
STATES = {"accept": "accepted", "reject": "rejected", "more": "more_evidence"}


def _proposals() -> list[tuple[str, dict]]:
    """Proposals that carry a reason key. One written before the fund-clearing loop has none: it
    predates the verbatim-quote rule and its fund has not been through the gate, so it is not put
    in front of the owner (its fund's next run rewrites or drops it)."""
    found = []
    for path in sorted(PROPOSED.glob("*.json")):
        for entry in json.loads(path.read_text(encoding="utf-8")).get("dispositions", []):
            if str(entry.get("reason_key") or "").strip():
                found.append((path.name, entry))
    return found


def _key(entry: dict) -> str:
    given = str(entry.get("reason_key") or "").strip()
    if given:
        return given
    digest = hashlib.sha256((str(entry.get("disposition_id")) + str(entry.get("statement"))).encode("utf-8")).hexdigest()[:8]
    return "single-%s-%s" % (entry.get("rule_name"), digest)


def _quotes_verified(entry: dict) -> tuple[int, int]:
    from fund_gate import normalise, page_text
    cited = [e for e in entry.get("evidence", []) if e.get("source") == "filing"]
    good = 0
    for item in cited:
        text = normalise(str(item.get("verbatim") or ""))
        for cik in entry.get("ciks", []):
            page = page_text(cik, str(item.get("accession") or "")) if item.get("accession") else None
            if page and len(text) >= 20 and text in page:
                good += 1
                break
    return good, len(cited)


def build() -> list[dict]:
    kept = {}
    if LEDGER.exists():
        with open(LEDGER, newline="", encoding="utf-8") as fh:
            kept = {row["reason_key"]: row for row in csv.DictReader(fh)}
    by_check = {(r["engine"], r["rule_name"]) for r in json.loads(REASONS.read_text(encoding="utf-8"))["reasons"]}
    groups: dict[str, list[tuple[str, dict]]] = {}
    for source, entry in _proposals():
        groups.setdefault(_key(entry), []).append((source, entry))
    rows = []
    for key, members in sorted(groups.items()):
        first = members[0][1]
        good = cited = 0
        for _source, entry in members:
            g, c = _quotes_verified(entry)
            good, cited = good + g, cited + c
        previous = kept.get(key, {})
        rows.append({
            "reason_key": key, "state": previous.get("state") or "proposed",
            "engine": first.get("engine"), "rule_name": first.get("rule_name"),
            "class": "; ".join(sorted({str(e.get("class")) for _s, e in members})),
            "funds": "; ".join(sorted({c for _s, e in members for c in e.get("ciks", [])})),
            "fund_quarters": sum(len(e.get("ciks", [])) * len(e.get("quarters", [])) for _s, e in members),
            "proposals": len(members), "quotes_verified": "%d of %d" % (good, cited),
            "check_available": "yes" if (first.get("engine"), first.get("rule_name")) in by_check else "no",
            "statement": " ".join(str(first.get("statement") or "").split()),
            "recommended": " ".join(str(first.get("recommended") or "").split()),
            "owner_words": previous.get("owner_words", ""), "ruled_on": previous.get("ruled_on", ""),
            "proposal_ids": "; ".join(str(e.get("disposition_id")) for _s, e in members),
            "source_files": "; ".join(sorted({s for s, _e in members})),
        })
    # a row whose proposals are gone keeps its ruling on record
    rows += [dict(row, proposals=0) for key, row in sorted(kept.items()) if key not in groups and row.get("state") != "proposed"]
    with open(LEDGER, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    lines = ["# Owner decision ledger", "",
             "One row per reason. Generated by `scripts/v05_evidence/owner_queue.py build`; do not edit by hand.",
             "A ruling is recorded with `owner_queue.py rule <reason key> accept|reject|more --words \"...\"`.", "",
             "| Reason key | State | Rule | Funds | Fund-quarters | Quotes verified | Statement |", "|---|---|---|---|---|---|---|"]
    order = {"proposed": 0, "more_evidence": 1, "rejected": 2, "accepted": 3}
    for row in sorted(rows, key=lambda r: (order.get(r["state"], 9), -int(r["fund_quarters"] or 0))):
        lines.append("| `%s` | %s | %s | %d | %s | %s | %s |" % (
            row["reason_key"], row["state"], row["rule_name"], len(str(row["funds"]).split("; ")) if row["funds"] else 0,
            row["fund_quarters"], row["quotes_verified"], str(row["statement"])[:220].replace("|", "/")))
    VIEW.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return rows


def show(key: str | None) -> None:
    rows = build()
    if key is None:
        counts = {}
        for row in rows:
            counts[row["state"]] = counts.get(row["state"], 0) + 1
        print("reasons by state:", counts)
        for row in rows:
            if row["state"] in ("proposed", "more_evidence"):
                print("   %-52s %-22s funds %2d  fund-quarters %3s  quotes %s" % (
                    row["reason_key"][:52], row["rule_name"], len(str(row["funds"]).split("; ")), row["fund_quarters"], row["quotes_verified"]))
        return
    for source, entry in _proposals():
        if _key(entry) != key:
            continue
        print("%s  [%s]  %s %s  %s" % (entry.get("disposition_id"), source, entry.get("engine"), entry.get("rule_name"), entry.get("class")))
        print("   funds %s  quarters %s" % (", ".join(entry.get("ciks", [])), ", ".join(entry.get("quarters", []))))
        print("   " + " ".join(str(entry.get("statement")).split()))
        for item in entry.get("evidence", []):
            print("   - [%s] %s" % (item.get("source"), " ".join(str(item.get("verbatim") or item.get("quote")).split())[:400]))


def rule(key: str, ruling: str, words: str) -> int:
    rows = {row["reason_key"]: row for row in build()}
    if key not in rows:
        print("no such reason key:", key)
        return 2
    today = datetime.date.today().isoformat()
    members = [entry for _source, entry in _proposals() if _key(entry) == key]
    if ruling == "accept":
        from pipeline import finding_dispositions as fd
        store = json.loads(ACCEPTED.read_text(encoding="utf-8"))["dispositions"] if ACCEPTED.exists() else []
        held = {entry["disposition_id"]: entry for entry in store}
        for proposal in members:
            entry = {k: v for k, v in proposal.items() if k not in ("reason_key", "recommended")}
            entry["disposition_id"] = "DS-" + str(proposal["disposition_id"]).removeprefix("PD-")
            entry["decided_by"] = "owner, %s, reason %s: \"%s\"" % (today, key, words)
            entry["decided_on"] = today
            problems = fd.validate(entry)
            if problems:
                print("not accepted, entry invalid:", entry["disposition_id"], problems)
                return 2
            held[entry["disposition_id"]] = entry
        ACCEPTED.write_text(json.dumps({"dispositions": [held[k] for k in sorted(held)]}, indent=1) + "\n", encoding="utf-8")
        print("accepted %d proposals into %s" % (len(members), ACCEPTED.relative_to(REPO).as_posix()))
        print("re-run the ledger stage of the funds' sandboxes to see them clear")
    with open(LEDGER, newline="", encoding="utf-8") as fh:
        ledger = list(csv.DictReader(fh))
    for row in ledger:
        if row["reason_key"] == key:
            row.update(state=STATES[ruling], owner_words=words, ruled_on=today)
    with open(LEDGER, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(ledger)
    build()
    print("%s: %s" % (key, STATES[ruling]))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("build")
    showing = sub.add_parser("show")
    showing.add_argument("key", nargs="?")
    ruling = sub.add_parser("rule")
    ruling.add_argument("key")
    ruling.add_argument("ruling", choices=sorted(STATES))
    ruling.add_argument("--words", required=True)
    args = parser.parse_args(argv)
    if args.command == "build":
        rows = build()
        print("%d reasons; %d awaiting the owner" % (len(rows), sum(r["state"] in ("proposed", "more_evidence") for r in rows)))
        return 0
    if args.command == "show":
        show(args.key)
        return 0
    return rule(args.key, args.ruling, args.words)


if __name__ == "__main__":
    sys.exit(main())
