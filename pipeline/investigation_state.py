"""Investigation state: rules fingerprint + stale-investigation audit.

Q1 2026 (2026-09-07 forensics): HPS's gate verdict was written at 09:00 on a half-finished rule
set; the worker's final rules landed at 11:12/11:18; nothing re-gated; the rules were never
promoted. The gate reads the corrected frame written by the LAST apply, so any rule written
after that apply is invisible to it. This module makes that state explicit: apply and gate
record the fingerprint of the rules they saw, and a CIK whose rules directory no longer
matches is STALE -- refused by promote and counted by the acceptance contract.

ASCII-only. Pure filesystem reads; no pipeline imports.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

_CIK_DIR_RE = re.compile(r"^\d{1,10}$")


def rules_fingerprint(rules_dir: Path) -> str:
    """sha256 over (sorted filename, bytes) of every *.json in rules_dir; '' if none."""
    rules_dir = Path(rules_dir)
    files = sorted(rules_dir.glob("*.json")) if rules_dir.exists() else []
    if not files:
        return ""
    h = hashlib.sha256()
    for p in files:
        h.update(p.name.encode("utf-8"))
        h.update(b"\0")
        h.update(p.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


def newest_rule_file(rules_dir: Path) -> str:
    rules_dir = Path(rules_dir)
    files = sorted(rules_dir.glob("*.json"), key=lambda p: p.stat().st_mtime) if rules_dir.exists() else []
    return files[-1].name if files else ""


def _read_json(path: Path) -> dict:
    try:
        obj = json.loads(path.read_text(encoding="utf-8-sig"))
        return obj if isinstance(obj, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def stale_investigations(base_dir: Path, target_quarter: str,
                         ciks: set[str] | None = None) -> list[dict]:
    """CIKs under base_dir whose staged rules do not match the fingerprint recorded by their
    last apply (apply_audit.json) or their last gate for target_quarter (gate.<q>.json).
    ciks: optional 10-digit filter. CIK dirs are the numeric ones (batch/, routing/ skipped)."""
    base_dir = Path(base_dir)
    out: list[dict] = []
    if not base_dir.exists():
        return out
    for child in sorted(base_dir.iterdir()):
        if not child.is_dir() or not _CIK_DIR_RE.match(child.name):
            continue
        cik10 = child.name.zfill(10)
        if ciks is not None and cik10 not in ciks:
            continue
        fp = rules_fingerprint(child / "rules")
        if not fp:
            continue                                   # no staged rules -> nothing to be stale
        apply_fp = str(_read_json(child / "apply_audit.json").get("rules_fingerprint") or "")
        gate_rec = _read_json(child / f"gate.{target_quarter}.json")
        gate_fp = str(gate_rec.get("rules_fingerprint") or "")
        reasons = []
        if apply_fp != fp:
            reasons.append("rules changed after last apply" if apply_fp else "never applied")
        if gate_fp != fp:
            reasons.append("rules changed after last gate" if gate_fp else "never gated for quarter")
        if reasons:
            out.append({"cik": cik10, "target_quarter": str(target_quarter),
                        "reason": "; ".join(reasons), "rules_fingerprint": fp,
                        "apply_fingerprint": apply_fp, "gate_fingerprint": gate_fp,
                        "gate_verdict": str(gate_rec.get("verdict") or "")})
    return out
