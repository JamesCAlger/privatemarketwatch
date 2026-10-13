"""End-of-run regression check: have funds already accepted moved? Read-only.

    python scripts/v05_evidence/regression_check.py <new sandbox label> [<cik> ...]

For each fund in the new sandbox (or the funds named) that has an accepted sandbox on record
(docs/investigations/v05_readings/accepted_sandboxes.json, written by the orchestrator when a fund
passes its gate), compares the two builds:

  ledger   findings outstanding now that were not outstanding before, by rule and quarter
  fields   every published column that differs, rows added and removed (entity_id and
           canonical_name are recomputed per sandbox and are not counted)
  totals   quarters that tied to the filed total before and do not now

A fund with none of these is UNCHANGED. Exit code 1 if any fund moved. A fund that moved is not
necessarily worse: every difference has to be explained by a change made on purpose.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import fund_gate  # noqa: E402

RECORD = REPO / "docs/investigations/v05_readings/accepted_sandboxes.json"


def _outstanding(label: str, cik: str) -> set[tuple[str, str, str]]:
    csv.field_size_limit(10 ** 9)
    found = set()
    with open(fund_gate.SANDBOXES / label / "findings_ledger.csv", newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            if row["cik"].zfill(10) == cik and row["report_date"][:10] >= fund_gate.SINCE and row["state"] not in fund_gate.RESOLVED:
                found.add((row["engine"], row["rule_name"], row["report_date"][:10]))
    return found


def _funds(label: str) -> list[str]:
    run = json.loads((fund_gate.SANDBOXES / label / "run.json").read_text(encoding="utf-8"))
    return [str(c).zfill(10) for c in run.get("ciks", [])]


def main(argv=None) -> int:
    args = (argv if argv is not None else sys.argv[1:])
    if not args:
        print(__doc__)
        return 2
    label, named = args[0], [a.zfill(10) for a in args[1:]]
    accepted = json.loads(RECORD.read_text(encoding="utf-8")) if RECORD.exists() else {}
    moved = 0
    print("fund | accepted sandbox | new findings outstanding | columns changed | rows added / removed | quarters no longer tying")
    for cik in named or _funds(label):
        before = accepted.get(cik, {}).get("label")
        if not before:
            print("   %s | none on record: not compared" % cik)
            continue
        if before == label:
            print("   %s | %s is its accepted sandbox" % (cik, label))
            continue
        new_findings = sorted(_outstanding(label, cik) - _outstanding(before, cik))
        fields = fund_gate.check_fields(label, before, cik, {})
        changed = {c: n for c, n in fields.get("columns_changed", {}).items() if c not in fund_gate.INFORMATIONAL_COLUMNS}
        tied_before = {q["quarter"] for q in fund_gate.check_totals(before, cik, [])["not_tying"]}
        untied = sorted(q["quarter"] for q in fund_gate.check_totals(label, cik, [])["not_tying"] if q["quarter"] not in tied_before)
        added, removed = fields.get("rows_added", 0), fields.get("rows_removed", 0)
        same = not (new_findings or changed or added or removed or untied)
        moved += not same
        print("   %s | %s | %d | %d | %d / %d | %d   %s" % (cik, before, len(new_findings), len(changed), added, removed, len(untied),
                                                           "UNCHANGED" if same else "MOVED"))
        for engine, rule, quarter in new_findings[:12]:
            print("        new: %s %s %s" % (engine, rule, quarter))
        for column, n in sorted(changed.items(), key=lambda kv: -kv[1])[:12]:
            print("        column %s: %d rows%s" % (column, n, "  (values lost: %d)" % fields["values_lost"][column] if column in fields.get("values_lost", {}) else ""))
        if untied:
            print("        no longer tying: " + ", ".join(untied))
    print("funds that moved: %d" % moved)
    return 1 if moved else 0


if __name__ == "__main__":
    sys.exit(main())
