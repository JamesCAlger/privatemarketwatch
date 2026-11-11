"""Outstanding ledger findings for the v1 cohort: what is reviewed, what is not, per quarter and fund.

The single place to read "what remains" before processing outstanding ledger items.

    python scripts/v05_evidence/outstanding_status.py [--refresh] [--skip LABEL ...] [--prod-pass PASS_ID]

--refresh   re-run the ledger stage (fund_ledger_trial.py --from ledger, about 10 s per sandbox) on each
            fund's sandbox first, so the ledger reads today's disposition, verdict and retirement stores.
            Holdings are NOT rebuilt: new rules and extraction fixes need a fund build. Each ledger is
            backed up once per day to findings_ledger.pre_<YYYYMMDD>.csv.
--skip      sandbox labels not to refresh (a fund agent is building in them).

Writes docs/investigations/v05_readings/outstanding_status.md and outstanding_status.csv.

Sandbox per fund: among sandboxes whose holdings contain the fund, the one whose holdings were BUILT
last (holdings parquet mtime; a ledger refresh does not move it). The accepted sandbox
(accepted_sandboxes.json) is shown alongside.

Outstanding = ledger state not in pipeline.quarter_acceptance.RESOLVED_FINDING_STATES (the gate's
definition; verdict_retired is closed, real_error_check_silent is open). Reviewed, first match wins:
  proposal          a proposal in finding_dispositions_proposed covers (cik, engine, rule, quarter)
  verdict           the ledger state carries an earlier reviewer's verdict
  review_supported  finding_id has outcome 'supported' in an independent review file
  investigated      finding_id has an investigation entry but no supported review
  narrative         listed in unreviewed_2026-10-21/prior_review_exclusions.json
  unreviewed        none of the above: the agent review scope (owner ruling 2026-11-10)
"""
from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from pipeline.cohort_guard import load_cohort_ciks  # noqa: E402
from pipeline.quarter_acceptance import RESOLVED_FINDING_STATES  # noqa: E402

SANDBOXES = REPO / "scratch/fund_sandbox"
READ = REPO / "docs/investigations/v05_readings"
PASSES = REPO / "data/output/quarter_pass"
SINCE = "2022-01-01"
VERDICT = {"real_error_unremediated", "real_error_check_silent", "remediation_staged", "remediation_pulled",
           "needs_human", "evidence_backlog"}
CATS = ["proposal", "verdict", "review_supported", "investigated", "narrative", "unreviewed"]
csv.field_size_limit(10 ** 9)


def load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def review_sets():
    supported, investigated, narrative = set(), set(), set()
    for p in list((READ / "reviews").glob("*.json")) + list((READ / "unreviewed_2026-10-21/reviews").glob("*.json")):
        d = load(p)
        for fr in d.get("finding_reviews", []) if isinstance(d, dict) else []:
            if isinstance(fr, dict) and fr.get("outcome") == "supported":
                supported.add(fr.get("finding_id"))
    for p in list((READ / "reports").glob("*.json")) + list((READ / "unreviewed_2026-10-21").glob("0*.json")):
        d = load(p)
        for inv in d.get("investigations", []) if isinstance(d, dict) else []:
            if isinstance(inv, dict):
                investigated.add(inv.get("finding_id"))
    for e in load(READ / "unreviewed_2026-10-21/prior_review_exclusions.json") or []:
        for f in e.get("removed_findings", []):
            narrative.add(f.get("review_id"))
    proposed = set()
    for f in (REPO / "data/overrides/finding_dispositions_proposed").glob("fund_*.json"):
        for d in (load(f) or {}).get("dispositions", []):
            for c in d.get("ciks", []):
                for q in d.get("quarters", []):
                    proposed.add((c.zfill(10), d.get("engine"), d.get("rule_name"), q[:10]))
    return supported, investigated, narrative, proposed


def pick_sandboxes(ciks: list[str]) -> dict[str, Path]:
    con = duckdb.connect()
    boxes = sorted((p for p in SANDBOXES.iterdir() if (p / "findings_ledger.csv").exists()
                    and (p / "output/private_markets_holdings.parquet").exists()),
                   key=lambda p: (p / "output/private_markets_holdings.parquet").stat().st_mtime, reverse=True)
    found: dict[str, Path] = {}
    for box in boxes:
        if len(found) == len(ciks):
            break
        held = {r[0] for r in con.execute(
            "SELECT DISTINCT lpad(CAST(cik AS VARCHAR),10,'0') FROM read_parquet(?)",
            [(box / "output/private_markets_holdings.parquet").as_posix()]).fetchall()}
        for cik in ciks:
            if cik in held and cik not in found:
                found[cik] = box
    return found


def refresh(boxes: set[Path], skip: set[str]) -> list[str]:
    stamp = time.strftime("%Y%m%d")
    log = []
    for box in sorted(boxes):
        if box.name in skip:
            log.append("%s skipped" % box.name)
            continue
        backup = box / ("findings_ledger.pre_%s.csv" % stamp)
        if not backup.exists():
            shutil.copy2(box / "findings_ledger.csv", backup)
        start = time.time()
        r = subprocess.run([sys.executable, "scripts/fund_ledger_trial.py", "--label", box.name, "--from", "ledger"],
                           cwd=REPO, capture_output=True, text=True, timeout=600)
        log.append("%s exit %d %.0fs" % (box.name, r.returncode, time.time() - start))
        print(log[-1], flush=True)
    return log


def latest_prod_pass(name: str | None) -> Path | None:
    if name:
        return PASSES / name
    cands = [p for p in PASSES.iterdir() if p.is_dir() and ((p / "findings_ledger_post.csv").exists()
                                                           or (p / "findings_ledger_pre.csv").exists())]
    return max(cands, key=lambda p: max((p / f).stat().st_mtime for f in ("findings_ledger_post.csv", "findings_ledger_pre.csv")
                                        if (p / f).exists())) if cands else None


def prod_counts(pass_dir: Path | None, ciks: set[str]) -> tuple[str, Counter]:
    if pass_dir is None:
        return "none", Counter()
    f = pass_dir / "findings_ledger_post.csv"
    f = f if f.exists() else pass_dir / "findings_ledger_pre.csv"
    out = Counter()
    with open(f, newline="", encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            c = r["cik"].zfill(10)
            if c in ciks and r["report_date"][:10] >= SINCE and r["state"] not in RESOLVED_FINDING_STATES:
                out[(c, r["report_date"][:10])] += 1
    return "%s (%s)" % (f.relative_to(REPO).as_posix(), time.strftime("%Y-%m-%d %H:%M", time.localtime(f.stat().st_mtime))), out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--skip", nargs="*", default=[])
    ap.add_argument("--prod-pass")
    args = ap.parse_args()

    ciks = sorted(c.zfill(10) for c in load_cohort_ciks())
    chosen = pick_sandboxes(ciks)
    refresh_log = refresh(set(chosen.values()), set(args.skip)) if args.refresh else []
    supported, investigated, narrative, proposed = review_sets()
    accepted = load(READ / "accepted_sandboxes.json") or {}
    prod_src, prod = prod_counts(latest_prod_pass(args.prod_pass), set(ciks))

    rows = []
    for cik in ciks:
        box = chosen.get(cik)
        if box is None:
            continue
        with open(box / "findings_ledger.csv", newline="", encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                q = r["report_date"][:10]
                if r["cik"].zfill(10) != cik or q < SINCE or r["state"] in RESOLVED_FINDING_STATES:
                    continue
                rid = r["review_id"]
                if (cik, r["engine"], r["rule_name"], q) in proposed:
                    cat = "proposal"
                elif r["state"] in VERDICT:
                    cat = "verdict"
                elif rid in supported:
                    cat = "review_supported"
                elif rid in investigated:
                    cat = "investigated"
                elif rid in narrative:
                    cat = "narrative"
                else:
                    cat = "unreviewed"
                rows.append({"cik": cik, "sandbox": box.name, "review_id": rid, "engine": r["engine"],
                             "rule_name": r["rule_name"], "report_date": q, "state": r["state"], "category": cat})

    out_csv = READ / "outstanding_status.csv"
    with open(out_csv, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["cik", "sandbox", "review_id", "engine", "rule_name", "report_date", "state", "category"])
        w.writeheader()
        w.writerows(rows)

    by_q = defaultdict(Counter)
    by_f = defaultdict(Counter)
    for r in rows:
        by_q[r["report_date"]][r["category"]] += 1
        by_f[r["cik"]][r["category"]] += 1
        by_f[r["cik"]]["q:" + r["report_date"]] += 1
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO, capture_output=True, text=True).stdout.strip()
    L = ["# Outstanding ledger findings, v1 cohort", "",
         "Generated %s at git %s by `python scripts/v05_evidence/outstanding_status.py%s`. Do not edit by hand; re-run it."
         % (time.strftime("%Y-%m-%d %H:%M"), head, " --refresh" if args.refresh else ""), "",
         "- Ledgers: each fund's most recently BUILT sandbox. %s" % (
             "Ledger stage re-run now against today's stores." if args.refresh else
             "NOT refreshed: ledgers are as of each sandbox's last ledger run (column `ledger at`)."),
         "- A refresh does not rebuild holdings: rules added and extraction fixes since a sandbox's build are not in it.",
         "- Outstanding = state not in `RESOLVED_FINDING_STATES` (quarter_acceptance). `real_error_check_silent` is outstanding (owner 2026-11-10).",
         "- Review scope (owner 2026-11-10): agents investigate only `unreviewed` findings plus finding ids a rebuild newly produces; "
         "reviewed findings carry their earlier investigation forward (`carried_from`); fixing confirmed errors stays in scope.",
         "- Production column: %s." % prod_src,
         "- Zero outstanding is not data correct.", ""]
    total = Counter()
    L += ["## By quarter", "", "| Quarter | Outstanding | " + " | ".join(CATS) + " | Production |", "|---" * (len(CATS) + 3) + "|"]
    for q in sorted(by_q):
        total.update(by_q[q])
        L.append("| %s | %d | %s | %d |" % (q, sum(by_q[q][c] for c in CATS), " | ".join(str(by_q[q][c]) for c in CATS),
                                          sum(n for (c, qq), n in prod.items() if qq == q)))
    L.append("| **Total** | **%d** | %s | %d |" % (sum(total[c] for c in CATS), " | ".join("**%d**" % total[c] for c in CATS),
                                                   sum(prod.values())))
    quarters = sorted({q for c in by_f for q in [k[2:] for k in by_f[c] if k.startswith("q:")]})
    recent = [q for q in ("2025-12-31", "2026-03-31", "2026-06-30") if q in quarters]
    L += ["", "## By fund", "",
          "| CIK | Sandbox used | Accepted sandbox | Holdings built | Ledger at | Outstanding | Unreviewed | %s | Production %s |"
          % (" | ".join(recent), " / ".join(recent)), "|---" * (7 + len(recent) + 1) + "|"]
    for cik in sorted(by_f, key=lambda c: -sum(by_f[c][k] for k in CATS)):
        box = chosen[cik]
        built = time.strftime("%Y-%m-%d", time.localtime((box / "output/private_markets_holdings.parquet").stat().st_mtime))
        led = time.strftime("%Y-%m-%d %H:%M", time.localtime((box / "findings_ledger.csv").stat().st_mtime))
        acc = (accepted.get(cik) or {}).get("label", "none")
        L.append("| %s | %s | %s | %s | %s | %d | %d | %s | %s |" % (
            cik, box.name, acc if acc != box.name else "same", built, led, sum(by_f[cik][k] for k in CATS),
            by_f[cik]["unreviewed"], " | ".join(str(by_f[cik]["q:" + q]) for q in recent),
            " / ".join(str(prod[(cik, q)]) for q in recent)))
    missing = [c for c in ciks if c not in chosen]
    if missing:
        L += ["", "No sandbox holds: " + ", ".join(missing)]
    un = [r for r in rows if r["category"] in ("unreviewed", "investigated")]
    L += ["", "## Review scope: unreviewed and investigated-without-review (%d)" % len(un), "",
          "| CIK | Quarter | Engine | Rule | State | Category | review_id |", "|---|---|---|---|---|---|---|"]
    L += ["| %s | %s | %s | %s | %s | %s | %s |" % (r["cik"], r["report_date"], r["engine"], r["rule_name"], r["state"],
                                                   r["category"], r["review_id"]) for r in sorted(un, key=lambda r: (r["cik"], r["report_date"]))]
    if refresh_log:
        L += ["", "## Refresh log", ""] + ["- " + s for s in refresh_log]
    (READ / "outstanding_status.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("wrote %s and %s: %d outstanding, %d unreviewed" % (
        (READ / "outstanding_status.md").relative_to(REPO).as_posix(), out_csv.relative_to(REPO).as_posix(),
        len(rows), total["unreviewed"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
