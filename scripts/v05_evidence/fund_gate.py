"""Mechanical gate for one fund's clearing run. Read-only on everything but its own verdict file.

    python scripts/v05_evidence/fund_gate.py snapshot --out <file>
    python scripts/v05_evidence/fund_gate.py check --label <sandbox> --cik <cik> --report <report.json>
                                                   [--before <sandbox>] [--snapshot <file>]
    python scripts/v05_evidence/fund_gate.py park --snapshot <file> --cik <cik>

``snapshot`` records the hash of every watched file before a fund agent starts. ``check`` then
decides, without judgment, whether the agent's run can be accepted:

  stages       every sandbox stage exited cleanly, no traceback, published data untouched
  corrections  no row correction of this fund was left unmatched by the build
  totals       published equals filed within 0.5M in every quarter since 2022, on one basis for the
               fund (with or without cash rows); every other quarter is a declared exception
  fields       against the sandbox before: every column that changed, and every row added or
               removed, is declared in the report with a count at least as large
  quotes       every quote the report or the fund's proposals cite is found in the cached filing
  files        nothing the agent may not touch changed since the snapshot
  verdicts     a proposal over a finding an earlier reviewer judged a real error answers that
               verdict, quarter by quarter ("addresses_verdict": {"<quarter>": "<what they found and
               why it does not stand, or was fixed>"}, 60 characters or more)
  observations the report lists what the agent saw that no rule reported (the list may be empty),
               each entry well formed and with a printed line
  names        no more than 1 pct of the fund's published rows has an issuer name that still holds
               an instrument, a row number or a holder label (pipeline/issuer_instrument_split.py
               shapes); more is declared in "name_shape_exceptions" with a count and a reason
  ledger       every outstanding finding of the fund is covered by a written proposal

Verdict: PASS, INCOMPLETE (clean, but findings without a proposal remain), FAIL, or
NEEDS_ORCHESTRATOR (clean, and the report asks for a change the agent may not make: a check, the
re-verifier, a rule). Written to scratch/fund_sandbox/<label>/gate_<cik>.json. Exit code 0, 1, 2, 3.

The report is the fund agent's own JSON (see .claude/skills/v05-fund-clearing/fund-agent-brief.md).
A quote is {"accession": "0001234567-25-000001", "text": "<as printed by page_line.py>"}.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import re
import subprocess
import sys
import unicodedata
from functools import lru_cache
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(1, str(Path(__file__).resolve().parents[2]))

REPO = Path(__file__).resolve().parents[2]
NAME_SHAPE_LIMIT = 0.01
SANDBOXES = REPO / "scratch" / "fund_sandbox"
TOLERANCE = 5e5
SINCE = "2022-01-01"
RESOLVED = {"adjudicated_false_alarm", "remediated_promoted", "resolved_upstream", "gone_unadjudicated",
            "dispositioned_informational", "dispositioned_as_filed", "dispositioned_not_applicable"}
# An earlier reviewer found a real error here (verdict on record; python scripts/v05_evidence/verdicts.py <label>).
PRIOR_REAL_ERROR = {"real_error_unremediated", "remediation_staged", "remediation_pulled"}
# Recomputed across whichever funds share a sandbox, so they differ between any two builds.
INFORMATIONAL_COLUMNS = {"entity_id", "canonical_name"}
WATCHED = ("pipeline", "scripts", "schemas", "tests", "data/overrides", "data/reference", "docs/investigations",
           ".claude/skills", "AGENTS.md", "CLAUDE.md", "requirements.txt")
# A fund agent clears findings by fixing data or proposing a disposition. It does not change what
# counts as a finding, what counts as accepted, or the gate that judges it.
FORBIDDEN = (r"^AGENTS\.md$", r"^CLAUDE\.md$", r"^\.claude/skills/", r"^data/reference/", r"^tests/conftest\.py$",
             # the accepted store, except the file make_batch_dispositions.py writes from the owner's reasons list
             r"^data/overrides/finding_dispositions/(?!fundloop_accepted_by_check\.json$)", r"^pipeline/quarter_acceptance", r"^pipeline/column_validation\.py$",
             r"^pipeline/oracle_checks\.py$", r"^pipeline/disposition_validity\.py$", r"^pipeline/finding_dispositions\.py$",
             r"^pipeline/provenance_reverify\.py$", r"^pipeline/validate_holdings\.py$", r"^scripts/findings_ledger\.py$",
             r"^scripts/shadow_", r"^scripts/fund_ledger_trial\.py$", r"^scripts/v05_evidence/fund_gate\.py$",
             r"^scripts/v05_evidence/make_batch_dispositions\.py$")
SHARED_CODE = (r"^pipeline/.*\.py$", r"^scripts/(?!v05_evidence/).*\.py$", r"^schemas/")


def normalise(text: str) -> str:
    """Page text as the gate compares it: entities resolved, dashes and spaces folded, ASCII only."""
    text = html.unescape(text).replace(" ", " ")
    text = re.sub(r"[‐-―−]", "-", text)
    for symbol, code in (("€", " EUR "), ("£", " GBP "), ("¥", " JPY ")):
        text = text.replace(symbol, code)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", text).strip()


@lru_cache(maxsize=8)
def page_text(cik: str, accession: str) -> str | None:
    """The cached filing with tags stripped, normalised; None when it is not on disk."""
    path = REPO / "data/raw/filings/bdc_html" / cik.lstrip("0") / (accession.replace("-", "") + ".html")
    if not path.exists():
        return None
    return normalise(re.sub(r"<[^>]+>", " ", path.read_text(encoding="utf-8", errors="replace")))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def take_snapshot() -> dict:
    files = {}
    for root in WATCHED:
        base = REPO / root
        paths = [base] if base.is_file() else [p for p in base.rglob("*") if p.is_file() and "__pycache__" not in p.parts]
        for path in paths:
            files[path.relative_to(REPO).as_posix()] = _sha(path)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True).stdout.strip()
    status = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all"], cwd=REPO, capture_output=True, text=True).stdout
    dirty = sorted(line[3:].strip().strip('"') for line in status.splitlines() if line.strip())
    return {"head": head, "files": files, "dirty": dirty}


def changed_since(snapshot: dict) -> list[str]:
    now = take_snapshot()["files"]
    before = snapshot["files"]
    return sorted(path for path in set(now) | set(before) if now.get(path) != before.get(path))


def _con():
    import duckdb
    con = duckdb.connect()
    con.execute("SET memory_limit='3GB'")
    return con


def check_stages(label: str, cik: str) -> dict:
    sandbox = SANDBOXES / label
    problems = []
    run = json.loads((sandbox / "run.json").read_text(encoding="utf-8")) if (sandbox / "run.json").exists() else {}
    if cik not in [str(c).zfill(10) for c in run.get("ciks", [])]:
        problems.append("fund not among the sandbox's funds")
    stages = {s["stage"]: s["exit"] for s in run.get("stages", [])}
    for needed in ("rebuild", "validate", "oracle", "provenance", "shadow", "queue", "ledger"):
        if needed not in stages:
            problems.append("stage %s did not run" % needed)
    problems += ["stage %s exit %s" % (name, code) for name, code in stages.items()
                 if code != 0 and not (name == "ledger" and code == 1)]
    for log in sorted((sandbox / "logs").glob("*.log")) if (sandbox / "logs").exists() else []:
        text = log.read_text(encoding="utf-8", errors="replace")
        if "Traceback (most recent call last)" in text:
            problems.append("traceback in %s" % log.name)
    # The runner compares the published folder before and after each call and says so in the build log.
    build_log = REPO / "scratch" / "fund_runs" / (label + ".log")
    text = build_log.read_text(encoding="utf-8", errors="replace") if build_log.exists() else ""
    if not text:
        problems.append("no build log at scratch/fund_runs/%s.log (build with build_fund.sh)" % label)
    else:
        if "CHAIN_DONE" not in text:
            problems.append("build log does not end in CHAIN_DONE")
        if "changed published files" in text or "published files touched: none" not in text:
            problems.append("published data not shown untouched in the build log")
    return {"ok": not problems, "problems": problems, "stages": stages}


def check_corrections(label: str, cik: str) -> dict:
    log = SANDBOXES / label / "logs" / "rebuild.log"
    lines = []
    if log.exists():
        short = cik.lstrip("0")
        for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
            if "Row correction unmatched" in line and re.search(r"\b0*%s\b" % short, line):
                lines.append(line[-240:])
    return {"ok": not lines, "unmatched": lines[:20], "count": len(lines)}


def check_totals(label: str, cik: str, exceptions: list[dict]) -> dict:
    output = (SANDBOXES / label / "output").as_posix()
    rows = _con().execute(f"""
        WITH p AS (SELECT strftime(CAST(report_date AS DATE), '%Y-%m-%d') AS q,
                          sum(fair_value) FILTER (WHERE coalesce(accounting_record_class,'') <> 'underlying_schedule'
                                                  AND index_classification <> 'CASH') AS ex_cash,
                          sum(fair_value) FILTER (WHERE coalesce(accounting_record_class,'') <> 'underlying_schedule') AS with_cash
                   FROM read_parquet('{output}/private_markets_holdings.parquet')
                   WHERE lpad(CAST(cik AS VARCHAR),10,'0') = ? GROUP BY 1),
             f AS (SELECT strftime(CAST(report_date AS DATE), '%Y-%m-%d') AS q, any_value(investments_at_fair_value) AS filed
                   FROM read_csv_auto('{output}/fund_financials.csv') WHERE lpad(CAST(cik AS VARCHAR),10,'0') = ? GROUP BY 1)
        SELECT p.q, p.ex_cash, p.with_cash, f.filed FROM p LEFT JOIN f USING (q) WHERE p.q >= '{SINCE}' ORDER BY 1""",
                          [cik, cik]).fetchall()
    ties = {"ex_cash": 0, "with_cash": 0}
    for _q, ex_cash, with_cash, filed in rows:
        if filed is not None:
            ties["ex_cash"] += abs((ex_cash or 0) - filed) <= TOLERANCE
            ties["with_cash"] += abs((with_cash or 0) - filed) <= TOLERANCE
    basis = "ex_cash" if ties["ex_cash"] >= ties["with_cash"] else "with_cash"
    declared = {str(e.get("quarter"))[:10] for e in exceptions}
    off, undeclared = [], []
    for q, ex_cash, with_cash, filed in rows:
        published = (ex_cash if basis == "ex_cash" else with_cash) or 0
        if filed is None:
            item = {"quarter": q, "problem": "no filed total"}
        elif abs(published - filed) > TOLERANCE:
            item = {"quarter": q, "problem": "published minus filed %.1fM" % ((published - filed) / 1e6)}
        else:
            continue
        off.append(item)
        if q not in declared:
            undeclared.append(item)
    return {"ok": bool(rows) and not undeclared, "basis": basis, "quarters": len(rows), "tie": len(rows) - len(off),
            "not_tying": off, "undeclared": undeclared}


def check_fields(label: str, before: str, cik: str, report: dict) -> dict:
    con = _con()
    path = lambda name: (SANDBOXES / name / "output/private_markets_holdings.parquet").as_posix()
    for name, source in (("a", label), ("b", before)):
        con.execute(f"CREATE TEMP TABLE {name} AS SELECT * FROM read_parquet('{path(source)}') WHERE lpad(CAST(cik AS VARCHAR),10,'0') = ?", [cik])
    if con.execute("SELECT count(*) FROM b").fetchone()[0] == 0:
        return {"ok": False, "problems": ["fund not in the sandbox before (%s)" % before]}
    cols_a = [r[0] for r in con.execute("DESCRIBE a").fetchall()]
    cols_b = {r[0] for r in con.execute("DESCRIBE b").fetchall()}
    added = con.execute("SELECT count(*) FROM a ANTI JOIN b USING (row_id)").fetchone()[0]
    removed = con.execute("SELECT count(*) FROM b ANTI JOIN a USING (row_id)").fetchone()[0]
    differing = {}
    for column in cols_a:
        if column == "row_id" or column not in cols_b:
            continue
        n = con.execute(f'SELECT count(*) FROM a JOIN b USING (row_id) WHERE CAST(a."{column}" AS VARCHAR) IS DISTINCT FROM CAST(b."{column}" AS VARCHAR)').fetchone()[0]
        if n:
            differing[column] = n
    lost = {}
    for column in ("gics_sub_industry", "lien_position", "maturity_date", "interest_rate", "cost", "principal_amount", "shares_held"):
        if column in cols_a and column in cols_b:
            n = con.execute(f'SELECT count(*) FROM a JOIN b USING (row_id) WHERE a."{column}" IS NULL AND b."{column}" IS NOT NULL').fetchone()[0]
            if n:
                lost[column] = n
    declared = {str(d.get("column")): int(d.get("rows", 0)) for d in report.get("declared_changes", [])}
    problems = []
    for column, n in differing.items():
        if column in INFORMATIONAL_COLUMNS:
            continue
        if column not in declared:
            problems.append("column %s changed on %d rows, not declared" % (column, n))
        elif n > declared[column]:
            problems.append("column %s changed on %d rows, declared %d" % (column, n, declared[column]))
    if added > int(report.get("rows_added", 0)):
        problems.append("%d rows added, declared %s" % (added, report.get("rows_added", 0)))
    if removed > int(report.get("rows_removed", 0)):
        problems.append("%d rows removed, declared %s" % (removed, report.get("rows_removed", 0)))
    new_columns = sorted(set(cols_a) - cols_b)
    return {"ok": not problems, "problems": problems, "rows_added": added, "rows_removed": removed, "columns_changed": differing,
            "values_lost": lost, "new_columns": new_columns}


def check_names(label: str, cik: str, report: dict) -> dict:
    """Issuer names that still carry an instrument, a row number or a holder label. No ledger rule
    looks at names; the 2026-10-14 page sample found them wrong on 75 pct of one fund's rows."""
    from pipeline.issuer_instrument_split import shapes
    output = (SANDBOXES / label / "output/private_markets_holdings.parquet").as_posix()
    names = _con().execute(f"""SELECT issuer_name, count(*) FROM read_parquet('{output}')
                               WHERE lpad(CAST(cik AS VARCHAR),10,'0') = ? AND source = 'bdc' GROUP BY 1""", [cik]).fetchall()
    total = sum(n for _name, n in names)
    counts: dict[str, int] = {}
    examples: dict[str, list[str]] = {}
    for name, n in names:
        for shape in shapes(name):
            counts[shape] = counts.get(shape, 0) + n
            examples.setdefault(shape, []).append(str(name)[:90])
    declared = {str(d.get("shape")): int(d.get("rows", 0)) for d in report.get("name_shape_exceptions", [])
                if len(str(d.get("why") or "").strip()) >= 30}
    problems = []
    for shape, n in sorted(counts.items()):
        if total and n / total > NAME_SHAPE_LIMIT and declared.get(shape, -1) < n:
            problems.append("%s on %d of %d rows (%.1f pct), e.g. %s" % (shape, n, total, 100 * n / total, "; ".join(examples[shape][:3])))
    return {"ok": not problems, "problems": problems, "rows": total, "shapes": counts}


def _proposals(cik: str) -> list[dict]:
    path = REPO / "data/overrides/finding_dispositions_proposed" / ("fund_%s.json" % cik)
    return json.loads(path.read_text(encoding="utf-8")).get("dispositions", []) if path.exists() else []


def check_quotes(cik: str, report: dict) -> dict:
    quotes = []
    for fix in report.get("fixes", []):
        if not fix.get("quotes"):
            quotes.append(({"accession": "", "text": ""}, "fix without a quote: %s" % str(fix.get("what"))[:80]))
        quotes += [(q, "fix: %s" % str(fix.get("what"))[:60]) for q in fix.get("quotes", [])]
    for item in report.get("total_exceptions", []):
        quotes.append((item.get("quote") or {"accession": "", "text": ""}, "total exception %s" % item.get("quarter")))
    for item in report.get("observations", []):
        quotes.append((item.get("quote") or {"accession": "", "text": ""}, "observation: %s" % str(item.get("what"))[:60]))
    for entry in _proposals(cik):
        cited = [e for e in entry.get("evidence", []) if e.get("source") == "filing"]
        if not any(e.get("verbatim") for e in cited):
            quotes.append(({"accession": "", "text": ""}, "proposal %s has no verbatim filing quote" % entry.get("disposition_id")))
        quotes += [({"accession": e.get("accession", ""), "text": e.get("verbatim", "")}, "proposal %s" % entry.get("disposition_id"))
                   for e in cited if e.get("verbatim")]
    missing = []
    for quote, where in quotes:
        accession, text = str(quote.get("accession") or ""), normalise(str(quote.get("text") or ""))
        page = page_text(cik, accession) if re.fullmatch(r"\d{10}-\d{2}-\d{6}", accession) else None
        if len(text) < 20:
            missing.append({"where": where, "problem": "no quote, or shorter than 20 characters"})
        elif page is None:
            missing.append({"where": where, "problem": "filing %s not in the cache" % accession})
        elif text not in page:
            missing.append({"where": where, "problem": "not found in %s: %s" % (accession, text[:90])})
    return {"ok": not missing, "checked": len(quotes), "missing": missing}


def check_files(snapshot_path: str | None, report: dict) -> dict:
    if not snapshot_path:
        return {"ok": False, "problems": ["no snapshot given: file changes not checked"], "changed": []}
    changed = changed_since(json.loads(Path(snapshot_path).read_text(encoding="utf-8")))
    forbidden = [p for p in changed if any(re.search(rule, p) for rule in FORBIDDEN)]
    shared = [p for p in changed if any(re.search(rule, p) for rule in SHARED_CODE)]
    problems = ["forbidden file changed: " + p for p in forbidden]
    if shared and not report.get("shared_code"):
        problems.append("shared code changed and not declared: " + ", ".join(shared[:6]))
    return {"ok": not problems, "problems": problems, "changed": changed, "shared_code": shared}


def check_ledger(label: str, cik: str) -> dict:
    csv.field_size_limit(10 ** 9)
    findings, outstanding, judged = 0, [], []
    with open(SANDBOXES / label / "findings_ledger.csv", newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            if row["cik"].zfill(10) != cik or row["report_date"][:10] < SINCE or row["state"] in RESOLVED - {
                    "dispositioned_informational", "dispositioned_as_filed", "dispositioned_not_applicable"}:
                continue
            findings += 1
            if row["state"] not in RESOLVED:
                outstanding.append((row["engine"], row["rule_name"], row["report_date"][:10]))
                if row["state"] in PRIOR_REAL_ERROR:
                    judged.append((row["engine"], row["rule_name"], row["report_date"][:10]))
    covered, answered = set(), set()
    for entry in _proposals(cik):
        if cik in entry.get("ciks", []):
            keys = {(entry.get("engine"), entry.get("rule_name"), q) for q in entry.get("quarters", [])}
            covered |= keys
            # quarter -> what the earlier reviewer found and why it does not stand, in the agent's words
            replies = entry.get("addresses_verdict") or {}
            answered |= {(entry.get("engine"), entry.get("rule_name"), q) for q, text in replies.items() if len(str(text).strip()) >= 60}
    uncovered = sorted(set(outstanding) - covered)
    unanswered = sorted(set(judged) & covered - answered)
    return {"ok": not uncovered, "findings": findings, "outstanding": len(outstanding), "with_proposal": len(outstanding) - len(uncovered),
            "uncovered": [" ".join(u) for u in uncovered], "prior_real_error": len(judged),
            "unanswered_verdicts": [" ".join(u) for u in unanswered]}


def park(snapshot_path: str, cik: str) -> int:
    """Take a rejected fund's changes out of the working tree, keeping a copy. Returns an exit code.

    Every file changed since the snapshot is copied to scratch/fund_runs/parked/<cik>/. A file that
    was clean at the snapshot is restored from git; a file that did not exist is removed (its copy
    is kept). A file that was already modified or untracked at the snapshot (another session's work)
    is never restored: the run stops there.
    """
    import shutil
    snapshot = json.loads(Path(snapshot_path).read_text(encoding="utf-8"))
    changed = changed_since(snapshot)
    if not changed:
        print("nothing changed since the snapshot")
        return 0
    dirty_before = set(snapshot.get("dirty", []))
    def tracked(path: str) -> bool:
        return subprocess.run(["git", "cat-file", "-e", "%s:%s" % (snapshot["head"], path)], cwd=REPO, capture_output=True).returncode == 0
    plan, blocked = [], []
    for path in changed:
        if path in dirty_before:
            blocked.append(path)
        elif path not in snapshot["files"]:
            plan.append((path, "remove"))
        elif tracked(path):
            plan.append((path, "restore"))
        else:
            blocked.append(path)
    if blocked:
        print("STOP: changed files that were already modified before the run (not restored): " + ", ".join(blocked))
        return 2
    keep = REPO / "scratch/fund_runs/parked" / cik
    for path, action in plan:
        source = REPO / path
        if source.exists():
            (keep / path).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, keep / path)
        if action == "remove":
            source.unlink(missing_ok=True)
        else:
            subprocess.run(["git", "checkout", snapshot["head"], "--", path], cwd=REPO, check=True)
    print("parked %d files under %s" % (len(plan), keep.relative_to(REPO).as_posix()))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    parking = sub.add_parser("park")
    parking.add_argument("--snapshot", required=True)
    parking.add_argument("--cik", required=True)
    snap = sub.add_parser("snapshot")
    snap.add_argument("--out", required=True)
    check = sub.add_parser("check")
    check.add_argument("--label", required=True)
    check.add_argument("--cik", required=True)
    check.add_argument("--report", required=True)
    check.add_argument("--before")
    check.add_argument("--snapshot")
    args = parser.parse_args(argv)
    if args.command == "park":
        return park(args.snapshot, args.cik.zfill(10))
    if args.command == "snapshot":
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        snapshot = take_snapshot()
        Path(args.out).write_text(json.dumps(snapshot), encoding="utf-8")
        print("snapshot of %d files at %s" % (len(snapshot["files"]), snapshot["head"][:7]))
        return 0
    cik = args.cik.zfill(10)
    report_path = Path(args.report)
    if not report_path.exists():
        print("FAIL: no report at", report_path)
        return 2
    report = json.loads(report_path.read_text(encoding="utf-8"))
    # What the agent saw that no rule reported: the list must be there (it may be empty) and well formed.
    from observations import problems as observation_problems
    listed = report.get("observations")
    malformed = (["report has no 'observations' list"] if not isinstance(listed, list) else
                 ["observation %d: %s" % (i + 1, "; ".join(bad)) for i, bad in enumerate(map(observation_problems, listed)) if bad])
    checks = {"observations": {"ok": not malformed, "problems": malformed, "count": len(listed) if isinstance(listed, list) else 0},
              "stages": check_stages(args.label, cik), "corrections": check_corrections(args.label, cik),
              "totals": check_totals(args.label, cik, report.get("total_exceptions", [])),
              "quotes": check_quotes(cik, report), "files": check_files(args.snapshot, report),
              "names": check_names(args.label, cik, report)}
    if args.before:
        checks["fields"] = check_fields(args.label, args.before, cik, report)
    ledger = check_ledger(args.label, cik)
    # A proposal over a finding an earlier reviewer called a real error must answer that verdict.
    checks["verdicts"] = {"ok": not ledger["unanswered_verdicts"], "problems": [
        "proposal does not answer the earlier real-error verdict: " + item for item in ledger["unanswered_verdicts"]]}
    failed = [name for name, result in checks.items() if not result["ok"]]
    # A change the agent may not make itself (a check, the re-verifier, a rule) is asked for in the report.
    requests = report.get("orchestrator_requests") or []
    verdict = "FAIL" if failed else ("NEEDS_ORCHESTRATOR" if requests else ("PASS" if ledger["ok"] else "INCOMPLETE"))
    result = {"verdict": verdict, "cik": cik, "label": args.label, "before": args.before, "failed": failed,
              "checks": checks, "ledger": ledger, "fields_checked": bool(args.before), "orchestrator_requests": requests}
    (SANDBOXES / args.label / ("gate_%s.json" % cik)).write_text(json.dumps(result, indent=1), encoding="utf-8")
    print("%s  %s in %s%s" % (verdict, cik, args.label, "" if args.before else "  (no sandbox before: fields not compared)"))
    for name, outcome in checks.items():
        detail = outcome.get("problems") or outcome.get("undeclared") or outcome.get("missing") or outcome.get("unmatched") or ""
        print("   %-12s %s  %s" % (name, "ok" if outcome["ok"] else "FAILED", json.dumps(detail)[:600] if detail else ""))
    print("   totals: %d of %d quarters tie (%s)" % (checks["totals"]["tie"], checks["totals"]["quarters"], checks["totals"]["basis"]))
    print("   ledger: %d findings, %d outstanding, %d with a proposal%s" % (
        ledger["findings"], ledger["outstanding"], ledger["with_proposal"],
        "" if ledger["ok"] else "; without: " + "; ".join(ledger["uncovered"][:12])))
    for request in requests:
        print("   asks the orchestrator: %s" % json.dumps(request)[:400])
    return {"PASS": 0, "INCOMPLETE": 1, "FAIL": 2, "NEEDS_ORCHESTRATOR": 3}[verdict]


if __name__ == "__main__":
    sys.exit(main())
