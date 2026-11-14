"""Deterministic checks between agents (spec section 5). Plain code; no agent can satisfy them by
editing its own output. Each returns {"ok": bool, "problems": [str], ...}."""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

from config import PROTECTED, REPO, SHARED_CODE_RES, allowed_paths
import worktree as wt


# --- 1. worktree diff ----------------------------------------------------------
def diff_check(path: Path, base: str, cik10: str) -> dict:
    changed = wt.changed_paths(path, base)
    allowed = allowed_paths(cik10)
    problems = ["not allowed for this fund: " + p for p in changed if not any(re.search(rx, p) for rx in allowed)]
    problems += ["decision store changed in the worktree: " + p for p in changed if p.startswith("data/decisions/")]
    short = cik10.lstrip("0")
    for rel in [p for p in changed if re.search(r"^data/overrides/row_corrections(_by_context)?\.csv$", p)]:
        foreign = [l for l in wt.diff_lines(path, base, rel) if cik10 not in l and not re.search(r"(^|[,\s\"])%s([,\s\"]|$)" % short, l)]
        if foreign:
            problems.append("%s: %d changed lines do not belong to %s (first: %s)" % (rel, len(foreign), cik10, foreign[0][:120]))
    shared = [p for p in changed if any(re.search(rx, p) for rx in SHARED_CODE_RES)]
    return {"ok": not problems, "problems": problems, "changed": changed, "shared_code": shared}


# --- 2. main checkout untouched ------------------------------------------------
def main_snapshot(repo: Path = REPO) -> dict:
    files = {}
    for rel in PROTECTED:
        base = repo / rel
        if not base.exists():
            continue
        for p in base.rglob("*"):
            try:
                if p.is_file():
                    st = p.stat()
                    files[p.relative_to(repo).as_posix()] = [st.st_size, int(st.st_mtime)]
            except OSError:
                continue
    status = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=repo,
                            capture_output=True, text=True).stdout
    return {"files": files, "status": sorted(status.splitlines())}


def compare_snapshot(before: dict, after: dict, allow_prefixes: tuple[str, ...] = ()) -> dict:
    """allow_prefixes: paths the DRIVER itself may change in the main checkout (decide.py appends)."""
    b, a = before["files"], after["files"]
    changed = sorted(p for p in set(a) | set(b) if a.get(p) != b.get(p) and not p.startswith(allow_prefixes))
    status = sorted(set(after["status"]) ^ set(before["status"]))
    status = [s for s in status if not s[3:].strip('"').startswith(allow_prefixes)]
    problems = ["main checkout changed: " + p for p in changed[:30]] + ["git status changed: " + s for s in status[:10]]
    return {"ok": not problems, "problems": problems, "changed": changed}


# --- 3. fund gate ----------------------------------------------------------------
def _py(path: Path, script: str, *args, timeout: int = 1800) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(path / script), *args], cwd=path, capture_output=True, text=True,
                          timeout=timeout, env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"})


def gate_snapshot(path: Path, out: Path) -> None:
    res = _py(path, "scripts/v05_evidence/fund_gate.py", "snapshot", "--out", str(out))
    if res.returncode != 0:
        raise RuntimeError("fund_gate snapshot failed: " + (res.stdout + res.stderr)[-400:])


def gate(path: Path, label: str, cik10: str, report: Path, snapshot: Path, before: str | None = None,
         review: Path | None = None) -> dict:
    args = ["check", "--label", label, "--cik", cik10, "--report", str(report), "--snapshot", str(snapshot)]
    if before:
        args += ["--before", before]
    if review:
        args += ["--review", str(review)]
    res = _py(path, "scripts/v05_evidence/fund_gate.py", *args)
    out_file = path / "scratch" / "fund_sandbox" / label / ("gate_%s.json" % cik10)
    result = json.loads(out_file.read_text(encoding="utf-8")) if out_file.exists() else {}
    failed = result.get("failed", ["gate_did_not_run"])
    investigation = result.get("investigation", {})
    problems = []
    for name in failed:
        problems += ["gate %s: %s" % (name, p) for p in (result.get("checks", {}).get(name, {}).get("problems") or [name])][:8]
    if review is not None and not investigation.get("ok"):
        problems += ["investigation: " + p for p in investigation.get("problems", [])[:12]]
    return {"ok": not problems, "problems": problems, "verdict": result.get("verdict", "NONE"),
            "exit": res.returncode, "requests": result.get("orchestrator_requests", []),
            "stdout": res.stdout[-3000:], "result": result}


def report_digest(path: Path, label: str, cik10: str, report: Path) -> str:
    res = subprocess.run([sys.executable, str(Path(__file__).resolve().parent / "digest.py"), str(path), label, cik10, str(report)],
                         capture_output=True, text=True, timeout=600)
    if res.returncode != 0:
        raise RuntimeError("digest failed: " + (res.stdout + res.stderr)[-400:])
    return res.stdout.strip().splitlines()[-1]


# --- 4. verdict entries ------------------------------------------------------------
def verdict_check(entries_path: Path, packet_ids: set[str], actor: str, cik10: str) -> dict:
    sys.path.insert(0, str(REPO))
    from pipeline import decision_store
    from scripts.decide import page_quote_ok
    if not entries_path.exists():
        return {"ok": False, "problems": ["no verdicts.json"], "covered": set()}
    data = json.loads(entries_path.read_text(encoding="utf-8-sig"))
    entries = data if isinstance(data, list) else [data]
    problems, covered = [], set()
    for n, e in enumerate(entries, 1):
        errs = decision_store.validate(e) if isinstance(e, dict) else ["not an object"]
        if isinstance(e, dict):
            if e.get("decided_by") != actor:
                errs.append("decided_by must be %s" % actor)
            if str(e.get("cik") or "") != cik10:
                errs.append("cik must be %s" % cik10)
            for item in e.get("evidence", []) if isinstance(e.get("evidence"), list) else []:
                if isinstance(item, dict) and item.get("source") == "filing" and not page_quote_ok(cik10, str(item.get("accession", "")), str(item.get("quote", ""))):
                    errs.append("quote not on the page: %s %r" % (item.get("accession"), str(item.get("quote"))[:60]))
            ids = set(e.get("finding_ids", []) or [])
            if ids - packet_ids:
                errs.append("finding ids not in the packet: %s" % sorted(ids - packet_ids)[:3])
            covered |= ids & packet_ids
        if errs:
            problems.append("entry %d: %s" % (n, "; ".join(errs)))
    return {"ok": not problems, "problems": problems, "covered": covered, "entries": len(entries)}


# --- 5. shared code ----------------------------------------------------------------
def shared_code_check(path: Path, changed: list[str], report: dict, timeout: int = 1800) -> dict:
    shared = [p for p in changed if any(re.search(rx, p) for rx in SHARED_CODE_RES)]
    if not shared:
        return {"ok": True, "problems": [], "ran": []}
    problems = []
    if not report.get("shared_code"):
        problems.append("shared code changed but the report does not set shared_code")
    tests = [p for p in changed if re.search(r"^tests/test_[^/]+\.py$", p)]
    if not tests:
        problems.append("shared code changed with no test file changed or added")
    if not report.get("cohort_diff"):
        problems.append("shared code changed with no cohort_diff in the report")
    ran = []
    if tests:
        res = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *tests], cwd=path,
                             capture_output=True, text=True, timeout=timeout)
        ran = tests
        if res.returncode != 0:
            problems.append("tests failed: " + res.stdout[-600:])
    return {"ok": not problems, "problems": problems, "ran": ran}
