"""The real environment the driver acts on: worktrees, packets, the fund gate, the page sample,
recording through the decision store, and the observation store. Read-only on production except
``record``, which appends decisions through scripts/decide.py exactly as today's orchestrator does."""
from __future__ import annotations

import csv
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import checks
import worktree as wt
from config import (OBSERVATIONS_CSV, READER_BRIEF, REPO, SAMPLE_ROWS, SHARED_OVERRIDE_FILES, STATUS_CSV,
                    allowed_paths)
from state import FundState, Run

csv.field_size_limit(10 ** 9)
OUTSTANDING = ("needs_agent_review", "needs_data_fix")


def _dirty_main() -> list[str]:
    res = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all"], cwd=REPO, capture_output=True, text=True)
    return [line[3:].strip().strip('"') for line in res.stdout.splitlines() if line.strip()]


def build_packet(cik10: str, out: Path) -> int:
    batch = json.loads((REPO / "data/output/batches/latest.json").read_text(encoding="utf-8"))["batch_id"]
    with open(STATUS_CSV, newline="", encoding="utf-8-sig") as fh:
        rows = [r for r in csv.DictReader(fh) if r["cik"].zfill(10) == cik10 and r["status"] in OUTSTANDING]
    ids = {r["review_id"] for r in rows}
    ledger = {}
    with open(REPO / "data/output/batches" / batch / "findings_ledger.csv", newline="", encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            if r["review_id"] in ids:
                ledger[r["review_id"]] = r
    keep = ("state", "lane", "verdict_status", "verdict_detail", "fv_at_risk_m", "fund_quarter_fv_m", "population_origin")
    rows = [dict(r, **{k: ledger.get(r["review_id"], {}).get(k, "") for k in keep}) for r in rows]
    out.parent.mkdir(parents=True, exist_ok=True)
    if rows:
        with open(out, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
    return len(rows)


def packet_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    with open(path, newline="", encoding="utf-8") as fh:
        return {r["review_id"] for r in csv.DictReader(fh)}


def accepted_before(cik10: str) -> str | None:
    path = REPO / "docs/investigations/v05_readings/accepted_sandboxes.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    entry = data.get(cik10) if isinstance(data, dict) else None
    label = entry.get("label") if isinstance(entry, dict) else entry
    if label and (REPO / "scratch/fund_sandbox" / str(label) / "findings_ledger.csv").exists():
        return str(label)
    return None


class RealEnv:
    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run

    # --- per fund --------------------------------------------------------------
    def prepare(self, run: Run, fs: FundState) -> dict:
        allowed = allowed_paths(fs.cik)
        conflicts = [p for p in _dirty_main()
                     if p in SHARED_OVERRIDE_FILES or (re.search(r"^data/overrides/", p) and any(re.search(rx, p) for rx in allowed[:9]))]
        if conflicts:
            why = "uncommitted changes in the main checkout to files this fund may touch: %s" % ", ".join(conflicts[:5])
            if not (self.dry_run and run.meta.get("ignore_dirty")):
                return {"skip": why}
            print("  %s: WARNING (dry run continues): %s" % (fs.cik, why))
        n = build_packet(fs.cik, run.fund_dir(fs.cik) / "packet.csv")
        if n == 0:
            return {"skip": "nothing outstanding for this fund in the current status"}
        path, branch = wt.create(fs.cik, run.meta["run_id"], base=run.meta["base_commit"])
        return {"worktree": str(path), "branch": branch, "before": accepted_before(fs.cik), "findings": n}

    def new_round(self, run: Run, fs: FundState) -> None:
        rd = run.round_dir(fs.cik, fs.round)
        checks.gate_snapshot(Path(fs.worktree), rd / "gate_snapshot.json")
        (rd / "main_snapshot.json").write_text(json.dumps(checks.main_snapshot()), encoding="utf-8")

    def _label(self, run: Run, fs: FundState) -> str | None:
        prefix = run.meta.get("label_prefix", {}).get(fs.cik, "")
        base = REPO / "scratch/fund_sandbox"
        built = sorted((p for p in base.glob(prefix + "*") if prefix and (p / "findings_ledger.csv").exists()),
                       key=lambda p: p.stat().st_mtime)
        if built:
            return built[-1].name
        return fs.labels[-1] if fs.labels else fs.before

    def checks(self, run: Run, fs: FundState) -> dict:
        rd = run.round_dir(fs.cik, fs.round)
        path = Path(fs.worktree)
        problems = []
        label = self._label(run, fs)
        report = rd / "report.json"
        if not report.exists():
            return {"ok": False, "problems": ["no report.json written"], "label": label}
        try:
            report_data = json.loads(report.read_text(encoding="utf-8"))
        except ValueError as exc:
            return {"ok": False, "problems": ["report.json is not JSON: %s" % exc], "label": label}
        diff = checks.diff_check(path, run.meta["base_commit"], fs.cik)
        problems += diff["problems"]
        main = checks.compare_snapshot(json.loads((rd / "main_snapshot.json").read_text(encoding="utf-8")), checks.main_snapshot())
        problems += main["problems"]
        if not label:
            problems.append("no sandbox: the fund agent built nothing and there is no accepted sandbox")
        else:
            g = checks.gate(path, label, fs.cik, report, rd / "gate_snapshot.json", before=fs.before if fs.before != label else None)
            (rd / "gate_pre.json").write_text(json.dumps(g["result"], indent=1, default=str), encoding="utf-8")
            problems += g["problems"]
        actor = "agent:sdk-fundagent-%s-%s" % (fs.cik[-6:], run.meta.get("run_id", "x")[-6:])
        v = checks.verdict_check(rd / "verdicts.json", packet_ids(run.fund_dir(fs.cik) / "packet.csv"), actor, fs.cik)
        problems += v["problems"]
        sc = checks.shared_code_check(path, diff["changed"], report_data)
        problems += sc["problems"]
        return {"ok": not problems, "problems": problems, "label": label, "changed": diff["changed"]}

    def digest(self, run: Run, fs: FundState) -> str:
        return checks.report_digest(Path(fs.worktree), fs.labels[-1], fs.cik, run.round_dir(fs.cik, fs.round) / "report.json")

    def review_items(self, run: Run, fs: FundState) -> dict:
        path = run.round_dir(fs.cik, fs.round) / "review.json"
        if not path.exists():
            return {"review": "the reviewer wrote no review.json"}
        review = json.loads(path.read_text(encoding="utf-8"))
        out = {}
        for key, idf in (("finding_reviews", "finding_id"), ("observation_reviews", "observation_key"), ("request_reviews", "request_id")):
            for item in review.get(key, []) or []:
                if isinstance(item, dict) and item.get("outcome") != "supported":
                    out[str(item.get(idf))] = str(item.get("rationale", ""))[:1500]
        return out

    def dispute_rulings(self, run: Run, fs: FundState) -> dict:
        path = run.round_dir(fs.cik, fs.round) / "review_dispute.json"
        if not path.exists():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        return {str(d.get("item")): d.get("ruling") for d in data.get("disputes", []) if isinstance(d, dict)}

    def _sample_dir(self, run: Run, fs: FundState) -> Path:
        return run.round_dir(fs.cik, fs.round) / "sample"

    def draw_sample(self, run: Run, fs: FundState) -> dict:
        s = self._sample_dir(run, fs)
        path = Path(fs.worktree)
        script = path / "scripts/v05_evidence/field_sample.py"
        for args in (["draw", "--per-fund", str(SAMPLE_ROWS), "--label", fs.labels[-1], "--cik", fs.cik], ["cards", "--batch", str(SAMPLE_ROWS)]):
            res = subprocess.run([sys.executable, str(script), "--dir", str(s), *args], cwd=path, capture_output=True, text=True, timeout=1800)
            if res.returncode != 0:
                raise RuntimeError("field_sample %s failed: %s" % (args[0], (res.stdout + res.stderr)[-500:]))
        return {"cards": (s / "cards" / "batch_01.md").as_posix(), "labels": (s / "labels" / "batch_01.json").as_posix(),
                "brief_text": READER_BRIEF.read_text(encoding="utf-8") if READER_BRIEF.exists() else ""}

    def sample_items(self, run: Run, fs: FundState) -> dict:
        s = self._sample_dir(run, fs)
        labels = s / "labels" / "batch_01.json"
        if not labels.exists():
            return {"labels": "the reader wrote no labels"}
        path = Path(fs.worktree)
        script = path / "scripts/v05_evidence/field_sample.py"
        chk = subprocess.run([sys.executable, str(script), "--dir", str(s), "check", str(labels)], cwd=path, capture_output=True, text=True, timeout=600)
        if chk.returncode != 0:
            return {"labels": "labels failed field_sample check: " + (chk.stdout + chk.stderr)[-400:]}
        subprocess.run([sys.executable, str(script), "--dir", str(s), "score"], cwd=path, capture_output=True, text=True, timeout=600)
        return parse_published_errors(s / "results.md")

    def final_gate(self, run: Run, fs: FundState) -> dict:
        rd = run.round_dir(fs.cik, fs.round)
        g = checks.gate(Path(fs.worktree), fs.labels[-1], fs.cik, rd / "report.json", rd / "gate_snapshot.json",
                        before=fs.before if fs.before != fs.labels[-1] else None, review=rd / "review.json")
        (rd / "gate_final.json").write_text(json.dumps(g["result"], indent=1, default=str), encoding="utf-8")
        return g

    def record(self, run: Run, fs: FundState) -> dict:
        """Commit the worktree, then append verdicts, review outcomes and the fix_record through the
        decision store (scripts/decide.py), in the main checkout."""
        if self.dry_run:
            return {"dry_run": True}
        sys.path.insert(0, str(REPO))
        from scripts.decide import append_file
        rd = run.round_dir(fs.cik, fs.round)
        sha = wt.commit_all(Path(fs.worktree), "SDK fund loop %s: %s round %d\n\n- Fund agent work accepted by review, page sample and gate\n- Recorded in data/decisions by the driver\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
                            % (run.meta["run_id"], fs.cik, fs.round))
        actor = "agent:sdk-fundagent-%s-%s" % (fs.cik[-6:], run.meta["run_id"][-6:])
        reviewer = "agent:sdk-reviewer-%s-%s" % (fs.cik[-6:], run.meta["run_id"][-6:])
        out = {"commit": sha, "branch": fs.branch, "decisions": []}
        verdicts = rd / "verdicts.json"
        if verdicts.exists() and json.loads(verdicts.read_text(encoding="utf-8-sig")):
            written = append_file(verdicts, actor=actor)
            sup = []
            for e in written:
                s = {k: v for k, v in e.items() if k not in ("decision_id", "recorded_at", "origin")}
                s.update({"supersedes": e["decision_id"], "review_outcome": "supported", "reviewed_by": reviewer})
                sup.append(s)
            sup_path = rd / "verdicts_reviewed.json"
            sup_path.write_text(json.dumps(sup, indent=1), encoding="utf-8")
            out["decisions"] += [e["decision_id"] for e in written] + [e["decision_id"] for e in append_file(sup_path, actor=actor)]
        report = json.loads((rd / "report.json").read_text(encoding="utf-8"))
        fix = report.get("fix")
        if isinstance(fix, dict) and fix.get("expects"):
            entry = {"type": "fix_record", "cik": fs.cik, "statement": report.get("summary") or "SDK fund loop fix",
                     "finding_ids": fix["expects"].get("finding_ids", []), "expects": fix["expects"],
                     "files": fix.get("files", []), "commit": sha, "tested_in": fix.get("tested_in") or fs.labels[-1],
                     "decided_by": actor, "decided_on": run.meta.get("today", "")}
            fpath = rd / "fix_record.json"
            fpath.write_text(json.dumps(entry, indent=1), encoding="utf-8")
            out["decisions"] += [e["decision_id"] for e in append_file(fpath, actor=actor)]
        return out

    # --- observations -------------------------------------------------------------
    def open_observation_keys(self, run: Run) -> list[dict]:
        with open(OBSERVATIONS_CSV, newline="", encoding="utf-8-sig") as fh:
            rows = [r for r in csv.DictReader(fh) if r.get("status") == "open"]
        groups: dict[str, list[dict]] = {}
        for r in rows:
            groups.setdefault(r["observation_key"], []).append(r)

        def weight(items):
            fv = sum(float(r.get("fair_value_m") or 0) for r in items)
            return len({r["cik"] for r in items}) * max(fv, 1.0)
        out = []
        for key, items in sorted(groups.items(), key=lambda kv: -weight(kv[1])):
            d = run.folder / "observations" / re.sub(r"[^A-Za-z0-9_.-]", "_", key)[:60]
            d.mkdir(parents=True, exist_ok=True)
            p = d / "entries.json"
            p.write_text(json.dumps(items, indent=1), encoding="utf-8")
            out.append({"key": key, "entries_path": p.as_posix(), "cik": items[0]["cik"], "funds": len({r["cik"] for r in items})})
        return out

    def observation_outcome(self, run: Run, key: str) -> dict:
        d = run.folder / "observations" / re.sub(r"[^A-Za-z0-9_.-]", "_", key)[:60]
        inv = json.loads((d / "investigation.json").read_text(encoding="utf-8")) if (d / "investigation.json").exists() else {}
        rev = json.loads((d / "review.json").read_text(encoding="utf-8")) if (d / "review.json").exists() else {}
        if not inv or not rev or rev.get("outcome") != "supported":
            return {"route": "left_open", "why": "investigation missing or not supported by review"}
        route = rev.get("route")
        if route == "not_real":
            with open(run.folder / "observations" / "closures.csv", "a", newline="", encoding="utf-8") as fh:
                csv.writer(fh).writerow([key, rev.get("rationale", "")[:500]])
        elif route == "fund_specific":
            for a in inv.get("affected", []):
                tasks = run.fund_dir(str(a.get("cik", "")).zfill(10)) / "tasks.json"
                tasks.parent.mkdir(parents=True, exist_ok=True)
                old = json.loads(tasks.read_text(encoding="utf-8")) if tasks.exists() else []
                tasks.write_text(json.dumps(old + [{"observation_key": key, "statement": inv.get("statement", "")}], indent=1), encoding="utf-8")
        return {"route": route or "left_open", "funds": len(inv.get("affected", []))}

    def prepare_shared(self, run: Run, key: str) -> dict:
        tag = "sh" + hashlib.sha1(key.encode()).hexdigest()[:4]
        path, branch = wt.create("000000" + tag, run.meta["run_id"], base=run.meta["base_commit"])
        return {"worktree": str(path), "branch": branch}

    def shared_fix_checks(self, run: Run, key: str) -> dict:
        tag = "sh" + hashlib.sha1(key.encode()).hexdigest()[:4]
        path = wt.WORKTREE_ROOT / wt.name_for("000000" + tag, run.meta["run_id"])
        d = run.folder / "observations" / re.sub(r"[^A-Za-z0-9_.-]", "_", key)[:60]
        report = json.loads((d / "fix_report.json").read_text(encoding="utf-8")) if (d / "fix_report.json").exists() else {}
        changed = wt.changed_paths(path, run.meta["base_commit"])
        problems = ["not shared code: " + p for p in changed if not re.search(r"^(pipeline|scripts|tests|schemas)/", p)]
        problems += checks.shared_code_check(path, changed, report)["problems"]
        if report.get("needs_batch"):
            problems.append("needs the unified build: parked for the next batch")
        moved, predicted = set(report.get("moved_ciks", [])), set(report.get("predicted_ciks", []))
        if moved - predicted:
            problems.append("funds moved that the investigation did not predict: %s" % sorted(moved - predicted))
        return {"ok": not problems, "problems": problems, "changed": changed}


def parse_published_errors(results: Path) -> dict:
    if not results.exists():
        return {"score": "field_sample score wrote no results.md"}
    text = results.read_text(encoding="utf-8")
    m = re.search(r"Published errors: (\d+)", text)
    if not m or m.group(1) == "0":
        return {}
    out = {}
    for line in text[m.end():].splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 6 and cells[0] not in ("Card", "---") and not set(cells[0]) <= {"-"}:
            out["%s/%s" % (cells[0], cells[2])] = "%s %s %s: %s" % (cells[1], cells[3], cells[4], cells[5])
    return out
