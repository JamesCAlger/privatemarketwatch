"""Per-review_id serialization for Agent B1 -- review_id is the unit of exclusion.

Each B1 verdict is one ``verdicts/<review_id>.json``. Disjoint review_ids never
collide, so -- unlike Agent A's per-CIK lock -- the only thing to guard is two workers
adjudicating the SAME review_id concurrently (re-dispatch overlap). A simple, atomic,
self-timestamped file lock, reclaimable when stale so a crashed worker does not wedge a
review_id forever. Same contract as ``scripts.agent_a.cik_lock``, keyed differently and
in its own directory.

The key doubles as a lock *filename* (``{key}.lock``). Agent B2 reuses this module with
composite keys (e.g. ``B2__<cik>__<fix_class>``). To keep that safe on every platform --
Windows in particular forbids ``: \\ / | < > * ? "`` in filenames and reserves device
names like ``CON``/``NUL``/``COM1`` -- the key is mapped through ``_safe_name`` before it
touches the filesystem. The mapping is injective, so two distinct keys can never collide
on a single lock file, and keys already within ``[A-Za-z0-9._-]`` pass through unchanged
(so existing review_id / cik locks keep their current filenames).
"""

from __future__ import annotations

import os
import string

from pipeline import config

LOCK_DIR = config.OUTPUT_DIR / "agent_b" / "locks"
DEFAULT_TTL_S = 3600  # a run older than this is presumed dead -> lock reclaimable

# Characters safe in a path component on every platform we target.
_SAFE_CHARS = frozenset(string.ascii_letters + string.digits + "._-")
# Windows reserved device names (case-insensitive), invalid even with an extension.
_WIN_RESERVED = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{i}" for i in range(1, 10)}
    | {f"lpt{i}" for i in range(1, 10)}
)


def _escape_char(c: str) -> str:
    # Percent-style escape of a character's UTF-8 bytes: "~hh" per byte. "~" is itself
    # outside _SAFE_CHARS, so it is always escaped on input -- the mapping stays injective.
    return "".join(f"~{b:02x}" for b in c.encode("utf-8"))


def _safe_name(key: str) -> str:
    """Map an arbitrary lock key to one filesystem-safe path component.

    Injective: distinct keys never produce the same name, so they never share a lock
    file. Keys already in [A-Za-z0-9._-] and not naming a reserved device are returned
    verbatim. Anything else is escaped as ``~hh`` (UTF-8 bytes); reserved device names
    are forced off the reserved set by escaping their first character.
    """
    if not isinstance(key, str) or not key:
        raise ValueError(f"lock key must be a non-empty string, got {key!r}")
    out = "".join(c if c in _SAFE_CHARS else _escape_char(c) for c in key)
    # The device-name check looks at the stem before the first dot (Windows ignores
    # the extension when matching reserved names). Escaping the first char yields a
    # name starting with "~", which can never equal a reserved device name.
    if out.split(".", 1)[0].lower() in _WIN_RESERVED:
        out = _escape_char(out[0]) + out[1:]
    return out


def _lock_path(review_id: str):
    return LOCK_DIR / f"{_safe_name(review_id)}.lock"


def _stored_ts(p) -> float:
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


def is_locked(review_id: str, ttl_s: int = DEFAULT_TTL_S, now: float | None = None) -> bool:
    p = _lock_path(review_id)
    if not p.exists():
        return False
    return (_clock(now) - _stored_ts(p)) < ttl_s


def acquire(review_id: str, owner: str = "", ttl_s: int = DEFAULT_TTL_S, now: float | None = None) -> bool:
    LOCK_DIR.mkdir(parents=True, exist_ok=True)
    p = _lock_path(review_id)
    ts = _clock(now)
    if p.exists() and (ts - _stored_ts(p)) >= ttl_s:
        p.unlink()  # reclaim a stale lock
    try:
        fd = os.open(str(p), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(f"{owner or 'agentB'}\n{ts}")
    return True


def release(review_id: str) -> None:
    p = _lock_path(review_id)
    if p.exists():
        p.unlink()


def held_ids() -> list[str]:
    # Returns the on-disk lock stems. For the keys used in this repo (review_ids, ciks,
    # B2 composite keys) these equal the original keys, since those pass _safe_name
    # unchanged. Keys that required escaping appear in their escaped form.
    if not LOCK_DIR.exists():
        return []
    return sorted(p.stem for p in LOCK_DIR.glob("*.lock"))
