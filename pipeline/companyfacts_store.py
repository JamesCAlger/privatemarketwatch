"""Immutable companyfacts snapshots and the pins that say which one a build reads.

Why: ``data/raw/companyfacts_cache/<cik10>.json`` was one mutable file per fund,
overwritten in place, and companyfacts restates history. Copying Q2 files over
the cache silently changed production fund financials and no build recorded the
version it read. This module replaces that with:

* a content-addressed snapshot store
  ``data/raw/companyfacts_snapshots/<cik10>/<YYYYMMDDTHHMMSSZ>_<sha12>.json``
  (never overwritten; identical bytes for a CIK are stored once) and a
  ``manifest.jsonl`` with one row per snapshot;
* pins: ``data/reference/companyfacts_pins/published.json`` (tracked in git)
  maps each CIK to one snapshot. ``PM_COMPANYFACTS_PIN`` points a candidate or
  sandbox build at another pin file;
* ``companyfacts_path(cik)``: the one resolver every reader uses.

Resolution rules (``companyfacts_path``):

1. A caller that passes an explicit directory other than the canonical legacy
   cache (tests, fixtures) reads ``<dir>/<cik10>.json`` as before.
2. Otherwise, when the active pin file exists, the CIK resolves to its pinned
   snapshot, or to None when the pin has no entry for it (same meaning as a
   missing cache file today). A pinned snapshot missing on disk raises.
3. Only when no pin file exists at all does it fall back to the legacy
   directory, with one ASCII warning per process. An explicitly configured
   ``PM_COMPANYFACTS_PIN`` that does not exist raises instead.

No network calls. ASCII-only log messages.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pipeline import config

logger = logging.getLogger(__name__)

PIN_ENV = "PM_COMPANYFACTS_PIN"
SOURCES = ("live_cache_import", "quarter_backup_import", "quarter_download_import", "api_download")
_STAMP_FORMAT = "%Y%m%dT%H%M%SZ"

# The canonical legacy cache as configured when this module was imported. A
# directory that differs from it is a caller override (rule 1 above).
_LEGACY_DEFAULT = Path(config.COMPANYFACTS_CACHE_DIR).resolve()
_warned_legacy = False
_pin_cache: dict[tuple, dict] = {}


class CompanyfactsStoreError(RuntimeError):
    """Pin or snapshot store is inconsistent; never resolved silently."""


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def cik10(cik: Any) -> str:
    digits = "".join(ch for ch in str(cik) if ch.isdigit())
    if not digits:
        raise ValueError("Invalid CIK: %r" % (cik,))
    return digits.zfill(10)


def snapshot_root() -> Path:
    return Path(config.COMPANYFACTS_SNAPSHOT_DIR)


def manifest_path() -> Path:
    return snapshot_root() / "manifest.jsonl"


def published_pin_file() -> Path:
    return Path(config.COMPANYFACTS_PUBLISHED_PIN_FILE)


def active_pin_file() -> Path:
    """The pin file this process reads: ``PM_COMPANYFACTS_PIN`` if set, else the configured one."""
    override = os.environ.get(PIN_ENV)
    if override:
        return Path(override).resolve()
    return Path(config.COMPANYFACTS_PIN_FILE)


def _same(a: Path, b: Path) -> bool:
    try:
        return Path(a).resolve() == Path(b).resolve()
    except OSError:
        return str(a) == str(b)


def _legacy_override(cache_dir) -> Path | None:
    """The caller-overridden legacy directory, if any (rule 1)."""
    if cache_dir is not None and not _same(Path(cache_dir), _LEGACY_DEFAULT):
        return Path(cache_dir)
    configured = Path(config.COMPANYFACTS_CACHE_DIR)
    if not _same(configured, _LEGACY_DEFAULT):
        return configured
    return None


# ---------------------------------------------------------------------------
# Pins
# ---------------------------------------------------------------------------

def load_pin(path: Path | None = None) -> dict | None:
    """Parsed pin document, or None when the file does not exist."""
    path = Path(path) if path is not None else active_pin_file()
    try:
        st = path.stat()
    except FileNotFoundError:
        return None
    key = (str(path.resolve()), st.st_mtime_ns, st.st_size)
    cached = _pin_cache.get(key)
    if cached is None:
        doc = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(doc, dict) or not isinstance(doc.get("pins"), dict):
            raise CompanyfactsStoreError("Pin file has no 'pins' object: %s" % path)
        _pin_cache.clear()
        _pin_cache[key] = doc
        cached = doc
    return cached


def pin_digest(path: Path | None = None) -> str | None:
    """sha256 of the active pin file (None when no pin file exists), for build stamps."""
    path = Path(path) if path is not None else active_pin_file()
    return sha256_file(path) if path.is_file() else None


def pin_stamp() -> dict:
    """Small provenance record for build/release stamps."""
    path = active_pin_file()
    doc = load_pin(path)
    return dict(pin_file=str(path), pin_sha256=pin_digest(path),
                pins=len(doc["pins"]) if doc else None,
                mode="pinned" if doc is not None else "legacy_directory")


def _snapshot_file(relative: str) -> Path:
    rel = Path(str(relative).replace("\\", "/"))
    if rel.is_absolute() or ".." in rel.parts:
        raise CompanyfactsStoreError("Pinned path escapes the snapshot store: %s" % relative)
    return snapshot_root() / rel


def companyfacts_path(cik, cache_dir=None) -> Path | None:
    """Path of the companyfacts JSON a reader must use for ``cik``, or None if there is none."""
    global _warned_legacy
    key = cik10(cik)
    override = _legacy_override(cache_dir)
    if override is not None:
        path = override / (key + ".json")
        return path if path.is_file() else None
    pin_file = active_pin_file()
    doc = load_pin(pin_file)
    if doc is None:
        if os.environ.get(PIN_ENV):
            raise CompanyfactsStoreError("%s points at a missing pin file: %s" % (PIN_ENV, pin_file))
        if not _warned_legacy:
            _warned_legacy = True
            logger.warning("Companyfacts pin file %s not found; reading the legacy directory %s",
                           pin_file, config.COMPANYFACTS_CACHE_DIR)
        path = Path(config.COMPANYFACTS_CACHE_DIR) / (key + ".json")
        return path if path.is_file() else None
    relative = doc["pins"].get(key)
    if not relative:
        return None
    path = _snapshot_file(relative)
    if not path.is_file():
        raise CompanyfactsStoreError("Pinned companyfacts snapshot missing for %s: %s" % (key, path))
    return path


def nominal_companyfacts_path(cik, cache_dir=None) -> Path:
    """Like ``companyfacts_path`` but never None: an unresolved CIK gets a path that does not exist.

    For readers that record the path they looked at (evidence, audit status)."""
    path = companyfacts_path(cik, cache_dir)
    if path is not None:
        return path
    override = _legacy_override(cache_dir)
    if override is not None or load_pin() is None:
        return (override or Path(config.COMPANYFACTS_CACHE_DIR)) / (cik10(cik) + ".json")
    return snapshot_root() / cik10(cik) / "_unpinned.json"


def load_companyfacts(cik, cache_dir=None) -> dict:
    """Parsed companyfacts for ``cik``; {} when unresolved or unreadable (legacy reader semantics)."""
    path = companyfacts_path(cik, cache_dir)
    if path is None:
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return {}


def write_pin(path: Path, pins: dict, *, promoted_by: str, note: str = "",
              allow_published: bool = False) -> Path:
    """Write a pin document atomically. Refuses the published pin unless ``allow_published``."""
    path = Path(path)
    if _same(path, published_pin_file()) and not allow_published:
        raise CompanyfactsStoreError("Refusing to write the published pin without --published --yes: %s" % path)
    clean = {}
    for cik, relative in pins.items():
        key = cik10(cik)
        rel = str(relative).replace("\\", "/")
        if not rel.startswith(key + "/"):
            raise CompanyfactsStoreError("Pin for %s points outside its CIK folder: %s" % (key, rel))
        if not _snapshot_file(rel).is_file():
            raise CompanyfactsStoreError("Pin for %s points at a missing snapshot: %s" % (key, rel))
        clean[key] = rel
    doc = dict(pins=dict(sorted(clean.items())), promoted_at=_utc_now(),
               promoted_by=promoted_by, note=note)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    _pin_cache.clear()
    return path


def write_candidate_pin(path: Path, updates: dict, *, promoted_by: str, note: str = "",
                        allow_published: bool = False) -> Path:
    """Re-pin ``updates`` ({cik: snapshot relative path}) in ``path``.

    Starts from ``path`` if it exists, else from the published pin, so every CIK
    not named keeps its published version."""
    path = Path(path)
    base = load_pin(path) if path.is_file() else load_pin(published_pin_file())
    pins = dict((base or {}).get("pins") or {})
    pins.update({cik10(k): v for k, v in updates.items()})
    return write_pin(path, pins, promoted_by=promoted_by, note=note, allow_published=allow_published)


# ---------------------------------------------------------------------------
# Snapshot store
# ---------------------------------------------------------------------------

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_time(value) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def fact_summary(data: dict) -> tuple[int, str | None]:
    """(fact count, max fact end date) over every taxonomy/concept/unit."""
    count, latest = 0, None
    for taxonomy in (data.get("facts") or {}).values():
        if not isinstance(taxonomy, dict):
            continue
        for concept in taxonomy.values():
            for rows in ((concept or {}).get("units") or {}).values():
                for row in rows:
                    count += 1
                    end = row.get("end")
                    if end and (latest is None or end > latest):
                        latest = end
    return count, latest


def read_manifest() -> list[dict]:
    path = manifest_path()
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def snapshots_for(cik) -> list[dict]:
    """Manifest rows for ``cik``, oldest first."""
    key = cik10(cik)
    return sorted((r for r in read_manifest() if r["cik"] == key),
                  key=lambda r: (r["retrieved_at"], r["path"]))


def latest_snapshot(cik) -> dict | None:
    rows = snapshots_for(cik)
    return rows[-1] if rows else None


def add_snapshot(cik, content: bytes, *, source: str, retrieved_at=None,
                 manifest_rows: list[dict] | None = None) -> tuple[dict, bool]:
    """Store ``content`` as a snapshot of ``cik``. Returns (manifest row, created).

    Content-addressed: if the same bytes are already stored for this CIK, the
    existing row is returned and nothing is written. Never touches any pin."""
    if source not in SOURCES:
        raise ValueError("Unknown snapshot source: %s" % source)
    key = cik10(cik)
    digest = hashlib.sha256(content).hexdigest()
    rows = read_manifest() if manifest_rows is None else manifest_rows
    for row in rows:
        if row["cik"] == key and row["sha256"] == digest:
            return row, False
    data = json.loads(content.decode("utf-8"))
    declared = data.get("cik") if isinstance(data, dict) else None
    if declared not in (None, "") and cik10(declared) != key:
        raise CompanyfactsStoreError("Companyfacts content declares CIK %s, not %s" % (declared, key))
    when = _parse_time(retrieved_at)
    relative = "%s/%s_%s.json" % (key, when.strftime(_STAMP_FORMAT), digest[:12])
    target = _snapshot_file(relative)
    if target.exists():
        if sha256_file(target) != digest:
            raise CompanyfactsStoreError("Snapshot path exists with other content: %s" % target)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_bytes(content)
        os.replace(tmp, target)
        os.chmod(target, stat.S_IREAD | stat.S_IRGRP | stat.S_IROTH)
    facts, max_end = fact_summary(data)
    row = dict(cik=key, path=relative, sha256=digest, bytes=len(content),
               retrieved_at=when.strftime("%Y-%m-%dT%H:%M:%SZ"), source=source,
               max_fact_end=max_end, fact_count=facts)
    manifest_path().parent.mkdir(parents=True, exist_ok=True)
    with open(manifest_path(), "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(row, sort_keys=True) + "\n")
    if manifest_rows is not None:
        manifest_rows.append(row)
    return row, True


def verify(pin_file: Path | None = None, *, all_snapshots: bool = False) -> list[str]:
    """Problems found: pinned path missing, not in the manifest, or bytes differ from the manifest sha."""
    pin_file = Path(pin_file) if pin_file is not None else active_pin_file()
    doc = load_pin(pin_file)
    if doc is None:
        return ["pin file not found: %s" % pin_file]
    by_path = {r["path"]: r for r in read_manifest()}
    problems = []
    targets = [(cik, rel) for cik, rel in sorted(doc["pins"].items())]
    if all_snapshots:
        pinned = {rel for _, rel in targets}
        targets += [(r["cik"], p) for p, r in sorted(by_path.items()) if p not in pinned]
    for cik, rel in targets:
        path = _snapshot_file(rel)
        row = by_path.get(rel)
        if row is None:
            problems.append("%s: %s not in manifest" % (cik, rel))
        elif row["cik"] != cik:
            problems.append("%s: %s belongs to CIK %s in the manifest" % (cik, rel, row["cik"]))
        if not path.is_file():
            problems.append("%s: %s missing on disk" % (cik, rel))
        elif row is not None and sha256_file(path) != row["sha256"]:
            problems.append("%s: %s sha256 differs from manifest" % (cik, rel))
    return problems


# ---------------------------------------------------------------------------
# Diff
# ---------------------------------------------------------------------------

_KEY_FIELDS = ("end", "start", "form", "fy", "fp")


def _fact_index(data: dict) -> dict[tuple, set]:
    index: dict[tuple, set] = {}
    for taxonomy, concepts in (data.get("facts") or {}).items():
        for concept, body in (concepts or {}).items():
            for unit, rows in ((body or {}).get("units") or {}).items():
                for row in rows:
                    key = (taxonomy, concept, unit) + tuple(row.get(f) for f in _KEY_FIELDS)
                    index.setdefault(key, set()).add(row.get("val"))
    return index


def diff_facts(a: dict, b: dict, *, limit: int | None = 50) -> dict:
    """Compare two companyfacts documents.

    A restatement is a fact key (taxonomy, concept, unit, end, start, form, fy, fp)
    present in both whose set of values differs."""
    ia, ib = _fact_index(a), _fact_index(b)
    restated = sorted(k for k in ia.keys() & ib.keys() if ia[k] != ib[k])
    added = sorted(ib.keys() - ia.keys(), key=lambda k: tuple(str(x) for x in k))
    removed = sorted(ia.keys() - ib.keys(), key=lambda k: tuple(str(x) for x in k))
    restated = sorted(restated, key=lambda k: tuple(str(x) for x in k))

    def rec(k, **extra):
        return dict(zip(("taxonomy", "concept", "unit") + _KEY_FIELDS, k), **extra)

    cut = (lambda xs: xs[:limit]) if limit is not None else (lambda xs: xs)
    return dict(
        summary=dict(keys_a=len(ia), keys_b=len(ib), restated=len(restated),
                     added=len(added), removed=len(removed)),
        restated=[rec(k, values_a=sorted(ia[k], key=str), values_b=sorted(ib[k], key=str)) for k in cut(restated)],
        added=[rec(k, values=sorted(ib[k], key=str)) for k in cut(added)],
        removed=[rec(k, values=sorted(ia[k], key=str)) for k in cut(removed)],
    )


def resolve_snapshot_ref(cik, ref: str) -> Path:
    """A snapshot given as a store-relative path, a bare file name, or a sha prefix."""
    key = cik10(cik)
    ref = str(ref).replace("\\", "/")
    candidates = [r for r in snapshots_for(key)
                  if r["path"] == ref or r["path"].split("/")[-1] == ref or r["sha256"].startswith(ref)]
    if len(candidates) == 1:
        return _snapshot_file(candidates[0]["path"])
    if len(candidates) > 1:
        raise CompanyfactsStoreError("Snapshot reference %s is ambiguous for %s" % (ref, key))
    path = Path(ref)
    if path.is_file():
        return path
    raise CompanyfactsStoreError("No snapshot %s for %s" % (ref, key))
