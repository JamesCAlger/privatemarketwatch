"""Finding status from the current batch: the one place to read what is outstanding.

    python scripts/status.py                 # latest batch of the production output dir
    python scripts/status.py --batch b1112a
    python scripts/status.py --owner-queue   # also print the findings waiting for the owner, by reason
    python scripts/status.py --no-write      # print only

Reads ``<output>/batches/latest.json`` (or ``--batch``), that batch's ledger and gate files, and the
decision store. Status is recomputed here from the ledger's detailed state and today's decisions,
so a fix or ruling recorded after the batch shows at once (a recorded fix as fix_awaiting_build).
Nothing is rebuilt. Writes docs/investigations/findings_status.md and .csv.

Quote counts only from this output, with its batch id. Zero outstanding is not data correct: no
rule detects a changed field meaning, a wrong rate on the right row, or offsetting errors.

Tie-out columns come from the batch's own gate files (acceptance_<quarter>.json and _funds.csv).
A quarter the gate did not read shows n/a, never a guess.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline import decision_store, finding_status  # noqa: E402

SINCE = "2022-01-01"
OUT_COLUMNS = ["cik", "report_date", "engine", "rule_name", "review_id", "state", "status", "reason"]
SHORT = {"needs_agent_review": "Agent review", "needs_data_fix": "Data fix", "needs_check_repair": "Check repair",
         "needs_owner_ruling": "Owner ruling", "fix_awaiting_build": "Fix awaiting build"}
OPEN_STATUSES = tuple(SHORT)


def _read_csv(path: Path) -> list[dict]:
    csv.field_size_limit(10 ** 9)
    with open(path, newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def load_batch(output_dir: Path, batch_id: str | None) -> tuple[dict, Path]:
    batches = Path(output_dir) / "batches"
    if batch_id is None:
        pointer = batches / "latest.json"
        if not pointer.exists():
            raise SystemExit("no batch yet: %s is missing (run scripts/run_batch.py)" % pointer)
        batch_id = json.loads(pointer.read_text(encoding="utf-8"))["batch_id"]
    batch_dir = batches / batch_id
    meta_path = batch_dir / "batch.json"
    if not (batch_dir / "findings_ledger.csv").exists() or not meta_path.exists():
        raise SystemExit("batch %s has no ledger: %s" % (batch_id, batch_dir))
    return json.loads(meta_path.read_text(encoding="utf-8")), batch_dir


def _reasons(entries: list[dict]) -> dict[tuple, list[str]]:
    """(cik, engine, rule, quarter) -> reason keys of store-class proposals awaiting the owner."""
    live = decision_store.standing(entries)
    rulings = decision_store._reason_rulings(live)
    out: dict[tuple, list[str]] = defaultdict(list)
    for e in live:
        if e.get("type") != "disposition_proposal":
            continue
        if decision_store._proposal_class(e, rulings) in finding_status.STORE_CLASSES:
            for cik in e.get("ciks", []):
                for quarter in e.get("quarters", []):
                    out[(cik, e.get("engine"), e.get("rule_name"), quarter)].append(e.get("reason_key") or e["decision_id"])
    return out


def findings(batch_dir: Path, meta: dict, entries: list[dict], *, ciks: set[str] | None, since: str) -> list[dict]:
    ledger = [r for r in _read_csv(batch_dir / "findings_ledger.csv")
              if str(r.get("report_date") or "")[:10] >= since
              and (ciks is None or str(r.get("cik") or "").zfill(10) in ciks)]
    facts = decision_store.facts_by_finding(entries, ledger, build_time=meta.get("build_time", ""))
    reasons = _reasons(entries)
    requests = {fid: e["request_id"] for e in decision_store.standing(entries)
                if e.get("type") in ("owner_request", "check_repair_request")
                and e.get("resolution") in decision_store.OPEN_RESOLUTIONS for fid in e.get("finding_ids", [])}
    rows = []
    for r in ledger:
        status = finding_status.status_of(r["state"], facts[r["review_id"]])
        if status == finding_status.CLOSED:
            continue
        cik = str(r.get("cik") or "").zfill(10)
        quarter = str(r.get("report_date") or "")[:10]
        reason = ""
        if status == finding_status.NEEDS_OWNER_RULING:
            keys = reasons.get((cik, r.get("engine"), r.get("rule_name"), quarter), [])
            reason = (keys[0] if keys else requests.get(r["review_id"])
                      or ("state " + r["state"] if r["state"] in finding_status.HUMAN_STATES
                          else "agent conclusion source_ambiguity"))
        elif status == finding_status.NEEDS_CHECK_REPAIR:
            reason = requests.get(r["review_id"], "")
        rows.append({"cik": cik, "report_date": quarter, "engine": r.get("engine", ""), "rule_name": r.get("rule_name", ""),
                     "review_id": r["review_id"], "state": r["state"], "status": status, "reason": reason})
    return rows


def tie_out(batch_dir: Path, quarters: list[str]) -> tuple[dict, dict]:
    """Per quarter gate summary, and per (cik, quarter) the fund's reconciliation line."""
    gate, funds = {}, {}
    for quarter in quarters:
        path = batch_dir / ("acceptance_%s.json" % quarter)
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            checks = {c.get("id"): c for c in data.get("checks", [])}
            gate[quarter] = {"verdict": data.get("verdict", "n/a"),
                             "reconcile_rate": checks.get("reconcile_rate", {}).get("actual", "n/a"),
                             "verified_fv_share": checks.get("verified_fv_share", {}).get("actual", "n/a"),
                             "outstanding_findings": checks.get("outstanding_findings", {}).get("actual", "n/a")}
        funds_path = batch_dir / ("acceptance_%s_funds.csv" % quarter)
        if funds_path.exists():
            for row in _read_csv(funds_path):
                funds[(str(row.get("cik") or "").zfill(10), quarter)] = row
    return gate, funds


def _fund_line(row: dict | None) -> str:
    if not row:
        return "n/a"
    return "%s %s%% / %s blockers" % (row.get("conservation_status") or "n/a",
                                      row.get("conservation_residual_pct") or "n/a", row.get("n_blockers") or "0")


def render(meta: dict, rows: list[dict], gate: dict, funds: dict, *, pending_fixes: int, since: str) -> list[str]:
    quarters = meta.get("quarters") or []
    total = Counter(r["status"] for r in rows)
    head = "| " + " | ".join(SHORT[s] for s in OPEN_STATUSES) + " |"
    lines = ["# Finding status", "",
             "Batch `%s`, built %s, git %s, decisions %s. Generated by `python scripts/status.py`; do not edit by hand."
             % (meta.get("batch_id"), meta.get("build_time") or "n/a", meta.get("git") or "n/a",
                meta.get("decisions_hash") or "n/a"), "",
             "- Findings from %s on; status = who acts next (pipeline/finding_status.py)." % since,
             "- Status is this batch's ledger read with today's decisions. Only a new batch shows whether a fix worked.",
             "- %d fix record(s) are newer than this batch; their findings show as Fix awaiting build." % pending_fixes,
             "- Tie-out columns are from this batch's gate files; n/a = the gate did not read that quarter.",
             "- Zero outstanding is not data correct.", "",
             "**Outstanding: %d**" % len(rows), "",
             "| Status | Findings |", "|---|---|"]
    lines += ["| %s | %d |" % (SHORT[s], total[s]) for s in OPEN_STATUSES]
    lines += ["", "## Gate", "", "| Quarter | Verdict | Reconcile rate | Verified FV share | Outstanding (v0.5 funds) |",
              "|---|---|---|---|---|"]
    for q in quarters:
        g = gate.get(q)
        lines.append("| %s | %s | %s | %s | %s |" % ((q, g["verdict"], g["reconcile_rate"], g["verified_fv_share"],
                                                     g["outstanding_findings"]) if g else (q, "n/a", "n/a", "n/a", "n/a")))
    by_q: dict = defaultdict(Counter)
    by_f: dict = defaultdict(Counter)
    for r in rows:
        by_q[r["report_date"]][r["status"]] += 1
        by_f[r["cik"]][r["status"]] += 1
    lines += ["", "## By quarter", "", "| Quarter | Outstanding " + head, "|---|---" + "|---" * len(OPEN_STATUSES) + "|"]
    for q in sorted(by_q):
        lines.append("| %s | %d | %s |" % (q, sum(by_q[q].values()), " | ".join(str(by_q[q][s]) for s in OPEN_STATUSES)))
    lines += ["", "## By fund", "",
              "| CIK | Outstanding " + head + "".join(" Tie-out %s |" % q for q in quarters),
              "|---|---" + "|---" * (len(OPEN_STATUSES) + len(quarters)) + "|"]
    fund_ids = sorted(set(by_f) | {c for c, _q in funds}, key=lambda c: (-sum(by_f[c].values()), c))
    for cik in fund_ids:
        lines.append("| %s | %d | %s |%s" % (
            cik, sum(by_f[cik].values()), " | ".join(str(by_f[cik][s]) for s in OPEN_STATUSES),
            "".join(" %s |" % _fund_line(funds.get((cik, q))) for q in quarters)))
    return lines


def owner_queue(rows: list[dict]) -> list[str]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if r["status"] == finding_status.NEEDS_OWNER_RULING:
            groups[r["reason"]].append(r)
    lines = ["", "## Waiting for the owner (%d findings, %d reasons)" % (sum(map(len, groups.values())), len(groups)), "",
             "| Reason | Findings | Funds | Rules |", "|---|---|---|---|"]
    for reason, items in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        lines.append("| `%s` | %d | %s | %s |" % (reason, len(items), ", ".join(sorted({i["cik"] for i in items}))[:120],
                                                 ", ".join(sorted({i["rule_name"] for i in items}))[:80]))
    return lines


def build(*, output_dir: Path, batch_id: str | None = None, decisions_dir: Path | None = None,
          ciks: set[str] | None = None, since: str = SINCE, entries: list[dict] | None = None):
    meta, batch_dir = load_batch(output_dir, batch_id)
    entries = decision_store.load_all(decisions_dir) if entries is None else entries
    rows = findings(batch_dir, meta, entries, ciks=ciks, since=since)
    gate, funds = tie_out(batch_dir, meta.get("quarters") or [])
    build_time = meta.get("build_time", "")
    pending = sum(1 for e in decision_store.standing(entries) if e.get("type") == "fix_record"
                  and build_time and e.get("recorded_at", "") > build_time)
    lines = render(meta, rows, gate, funds, pending_fixes=pending, since=since) + owner_queue(rows)
    return meta, rows, lines


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--batch")
    ap.add_argument("--output-dir", type=Path, default=None)
    ap.add_argument("--out-dir", type=Path, default=ROOT / "docs" / "investigations")
    ap.add_argument("--all-funds", action="store_true", help="do not restrict to the manifest cohort")
    ap.add_argument("--owner-queue", action="store_true")
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args(argv)
    if args.output_dir is None:
        from pipeline import config
        args.output_dir = config.OUTPUT_DIR
    ciks = None
    if not args.all_funds:
        from pipeline.cohort_guard import load_cohort_ciks
        ciks = {str(c).zfill(10) for c in load_cohort_ciks()}
    meta, rows, lines = build(output_dir=args.output_dir, batch_id=args.batch, ciks=ciks)
    if not args.no_write:
        args.out_dir.mkdir(parents=True, exist_ok=True)
        (args.out_dir / "findings_status.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        with open(args.out_dir / "findings_status.csv", "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=OUT_COLUMNS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
    counts = Counter(r["status"] for r in rows)
    print("batch %s: %d outstanding (%s)" % (meta.get("batch_id"), len(rows),
                                            ", ".join("%s %d" % (SHORT[s], counts[s]) for s in OPEN_STATUSES)))
    if args.owner_queue:
        print("\n".join(owner_queue(rows)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
