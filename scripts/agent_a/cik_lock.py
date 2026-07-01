"""Per-CIK serialization for Agent A2 -- CIK is the unit of mutual exclusion.

The A2 output is keyed by CIK (one identifier_anchors/<CIK>.json + one rate_grammars/<CIK>.json),
so two agents working the SAME CIK concurrently would write the same files -- last-writer-wins,
or each extends the grammar BLIND to the other's new rules (corruption). Rule:

  - ACROSS CIKs: fully parallel (disjoint config files, no shared state).
  - WITHIN a CIK: strictly serial -- at most one in-flight agent. Remediation is a FOLLOW-UP
    pass that reads the promoted config and extends it, never concurrent with induction.

This module provides a simple file-lock the dispatcher/parent must acquire before launching an
agent for a CIK and release after promote/gate. Stale locks (older than ttl) are reclaimable so
a crashed run does not wedge a CIK forever.
"""

from __future__ import annotations

import os

from pipeline import config

LOCK_DIR = config.OUTPUT_DIR / "agent_a" / "locks"
DEFAULT_TTL_S = 3600  # a run older than this is presumed dead -> lock reclaimable


def _lock_path(cik: str):
    return LOCK_DIR / f"{cik}.lock"


def _stored_ts(p) -> float:
    """The acquire-time stored IN the lock file (so staleness is self-consistent and testable,
    independent of filesystem mtime). Returns 0.0 if unreadable (-> treated as ancient/stale)."""
    try:
        parts = p.read_text(encoding="utf-8").splitlines()
        return float(parts[1]) if len(parts) > 1 else 0.0
    except (OSError, ValueError):
        return 0.0


def _clock(now):
    if now is not None:
        return now
    import time
    return time.time()


def is_locked(cik: str, ttl_s: int = DEFAULT_TTL_S, now: float | None = None) -> bool:
    p = _lock_path(cik)
    if not p.exists():
        return False
    return (_clock(now) - _stored_ts(p)) < ttl_s   # a stale lock is not "locked"


def acquire(cik: str, owner: str = "", ttl_s: int = DEFAULT_TTL_S, now: float | None = None) -> bool:
    """Acquire the per-CIK lock. Returns False if another LIVE holder exists. O_EXCL makes the
    create atomic so two concurrent acquirers cannot both win. A stale lock (older than ttl by
    the timestamp stored IN the file) is reclaimed."""
    LOCK_DIR.mkdir(parents=True, exist_ok=True)
    p = _lock_path(cik)
    ts = _clock(now)
    if p.exists() and (ts - _stored_ts(p)) >= ttl_s:
        p.unlink()  # reclaim a stale lock
    try:
        fd = os.open(str(p), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(f"{owner or 'agentA'}\n{ts}")
    return True


def release(cik: str) -> None:
    p = _lock_path(cik)
    if p.exists():
        p.unlink()


def held_ciks() -> list[str]:
    if not LOCK_DIR.exists():
        return []
    return sorted(p.stem for p in LOCK_DIR.glob("*.lock"))
