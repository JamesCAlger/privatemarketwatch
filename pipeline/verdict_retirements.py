"""Retired reviewer verdicts: a recorded owner decision that a real-error verdict no longer holds.

A reviewer's ``real_error`` verdict (``data/output/review_queue/verdicts/<review_id>.json``) stays
binding on its finding until the error is fixed. The findings ledger therefore keeps a finding with
an unretired real-error verdict outstanding even when its check stops firing (state
``real_error_check_silent``): a check that stopped firing after a repair may have been taught to
miss the error, not the error fixed. This store is the one way such a verdict is set aside without
a promoted fix: the owner decides that the error the verdict cites is no longer present (or was never
an error), on evidence checked against the published data.

Store: ``data/overrides/verdict_retirements/*.json``; each file is ``{"retirements": [...]}``.
One entry::

    {"retirement_id": "VR-001",
     "review_id": "RVQ_REV_66eeb8c7f2ab",
     "verdict_sha256": "<sha256 of the verdict file's bytes when it was retired>",
     "cik": "0001950803", "engine": "oracle", "rule_name": "B02", "report_date": "2025-12-31",
     "reason": "one sentence a reader can check",
     "evidence": [{"source": "query" | "filing" | "code" | "measurement" | "commit",
                   "quote": "...", "accession": "...", "verbatim": true}],
     "rerun": "command that reproduces the evidence",
     "owner_words": "the owner's ruling, verbatim",
     "decided_by": "owner", "decided_on": "YYYY-MM-DD"}

Matching is exact on purpose. An entry retires one verdict file: the review id must match, and the
verdict file's current sha256 must equal ``verdict_sha256``. A re-adjudication that rewrites the
verdict is therefore not retired by an old decision. When the ledger knows the finding's fund,
engine, rule and quarter they must agree with the entry too; a mismatch fails closed (not retired).

A retirement removes the verdict, nothing else. The finding is then unadjudicated: ``open`` while
its check still fires, ``verdict_retired`` (terminal) once it does not.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

RETIRED_STATE = "verdict_retired"
EVIDENCE_SOURCES = ("query", "filing", "code", "measurement", "commit")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_CIK = re.compile(r"\d{10}")
_SHA = re.compile(r"[0-9a-f]{64}")
_RID = re.compile(r"(RVQ_[A-Z]+_[0-9a-f]{12}|BDCSRC_\S+)")


def default_dir() -> Path:
    from pipeline import config
    return config.OVERRIDES_DIR / "verdict_retirements"


def verdict_sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate(entry) -> list[str]:
    """Problems with one entry; empty when it is valid."""
    if not isinstance(entry, dict):
        return ["entry is not an object"]
    errs = []
    for key in ("retirement_id", "review_id", "engine", "rule_name", "reason", "rerun",
                "owner_words", "decided_by", "decided_on"):
        if not str(entry.get(key) or "").strip():
            errs.append("missing " + key)
    if entry.get("review_id") and not _RID.fullmatch(str(entry["review_id"])):
        errs.append("review_id is not a review-queue id")
    if not _SHA.fullmatch(str(entry.get("verdict_sha256") or "")):
        errs.append("verdict_sha256 must be the 64-hex sha256 of the verdict file")
    if not _CIK.fullmatch(str(entry.get("cik") or "")):
        errs.append("cik must be a 10-digit CIK")
    if not _DATE.fullmatch(str(entry.get("report_date") or "")):
        errs.append("report_date must be YYYY-MM-DD")
    if not _DATE.fullmatch(str(entry.get("decided_on") or "")):
        errs.append("decided_on must be YYYY-MM-DD")
    if str(entry.get("decided_by") or "").strip() and entry.get("decided_by") != "owner":
        errs.append("decided_by must be 'owner': only the owner retires a real-error verdict")
    evidence = entry.get("evidence")
    if (not isinstance(evidence, list) or not evidence or not all(
            isinstance(e, dict) and e.get("source") in EVIDENCE_SOURCES and str(e.get("quote") or "").strip()
            for e in evidence)):
        errs.append("evidence must be a non-empty list of {source in %s, quote}" % (EVIDENCE_SOURCES,))
    return errs


def load(directory: Path | None = None) -> dict[str, dict]:
    """Every valid entry, keyed by review id. An invalid file or entry raises: a retirement that
    cannot be read must not be mistaken for one that does not exist."""
    directory = Path(directory) if directory is not None else default_dir()
    out: dict[str, dict] = {}
    seen: set[str] = set()
    if not directory.exists():
        return out
    for path in sorted(directory.glob("*.json")):
        if path.name.startswith("_"):
            continue
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        items = data.get("retirements") if isinstance(data, dict) else None
        if not isinstance(items, list):
            raise ValueError("Retirement file has no retirements list: " + str(path))
        for entry in items:
            problems = validate(entry)
            if problems:
                raise ValueError("Invalid verdict retirement in %s (%s): %s" % (
                    path, entry.get("retirement_id") if isinstance(entry, dict) else "?", "; ".join(problems)))
            if entry["retirement_id"] in seen:
                raise ValueError("Duplicate retirement id: " + entry["retirement_id"])
            if entry["review_id"] in out:
                raise ValueError("Two retirements for one verdict: " + entry["review_id"])
            seen.add(entry["retirement_id"])
            out[entry["review_id"]] = entry
    return out


def match(retirements: dict[str, dict], review_id: str, *, verdict_path: Path | None,
          cik=None, engine=None, rule_name=None, report_date=None) -> dict | None:
    """The entry retiring this verdict file, or None. Exact: review id, verdict file hash, and any
    known finding identity (fund, engine, rule, quarter) must all agree."""
    entry = retirements.get(review_id)
    if entry is None or verdict_path is None or not Path(verdict_path).exists():
        return None
    if verdict_sha256(verdict_path) != entry["verdict_sha256"]:
        return None
    known = {"cik": str(cik or "").zfill(10) if cik else "", "engine": engine or "",
             "rule_name": rule_name or "", "report_date": str(report_date or "")[:10]}
    for key, value in known.items():
        if value and value != str(entry[key]):
            return None
    return entry
