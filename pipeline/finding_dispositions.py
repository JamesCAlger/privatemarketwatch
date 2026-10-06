"""Standing dispositions for findings: a recorded, evidenced reason a finding needs no fix.

A finding is one (fund, rule, quarter). Its review id changes whenever the queue is rebuilt, so a
verdict file keyed by review id does not carry forward. A disposition is keyed by what the finding
is: fund, engine, rule and quarter. The findings ledger reads this store and gives a matching,
otherwise open finding a terminal state.

Store: ``data/overrides/finding_dispositions/*.json``; each file is ``{"dispositions": [...]}``.
One entry::

    {"disposition_id": "D-009",
     "class": "informational" | "as_filed" | "not_applicable",
     "ciks": ["0001838126"] or ["*"],
     "engine": "row_validation", "rule_name": "C107",
     "quarters": ["2023-03-31", ...] or ["all"],
     "statement": "one sentence a reader can check",
     "evidence": [{"source": "code" | "query" | "filing", "quote": "..."}],
     "rerun": "command that reproduces the evidence",
     "supersedes_real_error_verdict": true,   (optional; needs evidence with source "filing")
     "decided_by": "...", "decided_on": "YYYY-MM-DD"}

Reach is limited on purpose. ``informational`` says the rule reports a fact, not a defect, so it
may cover every fund and quarter. ``as_filed`` and ``not_applicable`` are judgments about specific
filings: they must name their funds and their quarters, so a new quarter or another fund is
reviewed again and is never cleared by an old decision.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

CLASSES = ("informational", "as_filed", "not_applicable")
STATE_BY_CLASS = {"informational": "dispositioned_informational", "as_filed": "dispositioned_as_filed",
                  "not_applicable": "dispositioned_not_applicable"}
DISPOSITIONED_STATES = frozenset(STATE_BY_CLASS.values())
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_CIK = re.compile(r"\d{10}")


def default_dir() -> Path:
    from pipeline import config
    return config.OVERRIDES_DIR / "finding_dispositions"


def validate(entry) -> list[str]:
    """Problems with one entry; empty when it is valid."""
    if not isinstance(entry, dict):
        return ["entry is not an object"]
    errs = []
    for key in ("disposition_id", "class", "engine", "rule_name", "statement", "rerun", "decided_by", "decided_on"):
        if not str(entry.get(key) or "").strip():
            errs.append("missing " + key)
    kind = entry.get("class")
    if kind not in CLASSES:
        errs.append("class must be one of " + ", ".join(CLASSES))
    ciks, quarters = entry.get("ciks"), entry.get("quarters")
    if not isinstance(ciks, list) or not ciks or not all(c == "*" or _CIK.fullmatch(str(c)) for c in ciks):
        errs.append("ciks must be a non-empty list of 10-digit CIKs, or ['*']")
    if not isinstance(quarters, list) or not quarters or not all(q == "all" or _DATE.fullmatch(str(q)) for q in quarters):
        errs.append("quarters must be a non-empty list of YYYY-MM-DD dates, or ['all']")
    if kind in ("as_filed", "not_applicable"):
        if isinstance(ciks, list) and "*" in ciks:
            errs.append(str(kind) + " must name its funds")
        if isinstance(quarters, list) and "all" in quarters:
            errs.append(str(kind) + " must name its quarters")
    evidence = entry.get("evidence")
    if (not isinstance(evidence, list) or not evidence or not all(
            isinstance(e, dict) and str(e.get("source") or "").strip() and str(e.get("quote") or "").strip() for e in evidence)):
        errs.append("evidence must be a non-empty list of {source, quote}")
    if entry.get("supersedes_real_error_verdict") not in (None, False, True):
        errs.append("supersedes_real_error_verdict must be true or false")
    if entry.get("supersedes_real_error_verdict") and not (
            isinstance(evidence, list) and any(isinstance(e, dict) and e.get("source") == "filing" for e in evidence)):
        errs.append("superseding a real-error verdict needs filing evidence")
    if not _DATE.fullmatch(str(entry.get("decided_on") or "")):
        errs.append("decided_on must be YYYY-MM-DD")
    return errs


def closes(entry: dict, state: str) -> bool:
    """Whether this entry may close a finding currently in ``state``.

    An earlier reviewer's 'real error' verdict with no fix is left standing unless the entry
    is informational (the verdict then only confirms the fact the rule reports) or says, with
    filing evidence, that the published value is what the fund filed."""
    if state in ("open", "needs_human", "evidence_backlog", "b1_route_missing"):
        return True
    if state == "real_error_unremediated":
        return entry["class"] == "informational" or bool(entry.get("supersedes_real_error_verdict"))
    return False


def load(directory: Path | None = None) -> list[dict]:
    """Every valid entry in the store. An invalid file or entry raises: a disposition that cannot
    be read must not be mistaken for one that does not exist."""
    directory = Path(directory) if directory is not None else default_dir()
    entries, seen = [], set()
    if not directory.exists():
        return entries
    for path in sorted(directory.glob("*.json")):
        if path.name.startswith("_"):
            continue
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        items = data.get("dispositions") if isinstance(data, dict) else None
        if not isinstance(items, list):
            raise ValueError("Disposition file has no dispositions list: " + str(path))
        for entry in items:
            problems = validate(entry)
            if problems:
                raise ValueError("Invalid disposition in %s (%s): %s" % (
                    path, entry.get("disposition_id") if isinstance(entry, dict) else "?", "; ".join(problems)))
            key = entry["disposition_id"]
            if key in seen:
                raise ValueError("Duplicate disposition id: " + key)
            seen.add(key)
            entries.append(entry)
    return entries


def match(entries: list[dict], *, cik, engine, rule_name, report_date) -> dict | None:
    """The first entry covering this finding, or None. A specific fund wins over '*'."""
    cik = str(cik or "").zfill(10)
    quarter = str(report_date or "")[:10]
    found = None
    for entry in entries:
        if entry["engine"] != (engine or "") or entry["rule_name"] != (rule_name or ""):
            continue
        if "all" not in entry["quarters"] and quarter not in entry["quarters"]:
            continue
        if cik in entry["ciks"]:
            return entry
        if "*" in entry["ciks"] and found is None:
            found = entry
    return found
