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
     "evidence": [{"source": "code" | "query" | "filing", "quote": "...",
                   "accession": "...", "verbatim": "...", "cik": "...", "quarter": "YYYY-MM-DD"}],
     "rows": [{"cik": "...", "quarter": "YYYY-MM-DD",
               "row_id": "ROW-..." | "source_identifier": "..." | "fund_level": true,
               "issuer": "...", "instrument": "..."}],                  (required for new entries)
     "rerun": "command that reproduces the evidence",
     "supersedes_real_error_verdict": true,   (optional; needs evidence with source "filing")
     "addresses_verdict": {"YYYY-MM-DD": "what the earlier reviewer found and why it does not stand"},
     "carry_forward": {"from": "YYYY-MM-DD", "check": "...", "params": {...}},   (optional)
     "legacy_unscoped": true,                  (only entries frozen in the legacy registry)
     "revoked": {...} / "revoked_members": [...] / "statement_history": [...],   (history; see below)
     "decided_by": "...", "decided_on": "YYYY-MM-DD"}

Reach is limited on purpose. ``informational`` says the rule reports a fact, not a defect, so it
may cover every fund and quarter. ``as_filed`` and ``not_applicable`` are judgments about specific
filings: they must name their funds and their quarters, so a new quarter or another fund is
reviewed again and is never cleared by an old decision alone.

The acceptance bar (owner ruling D-253, 2026-11-10). An ``as_filed`` or ``not_applicable`` entry
must, for EACH (cik, quarter) member it lists:
  (a) carry at least one filing quote for that member: evidence with source "filing", the
      ``accession``, the ``verbatim`` printed text (20 characters or more), and the member's
      ``quarter`` (and ``cik`` when the entry names more than one fund). The validator checks the
      shape; ``member_quote_problems`` (used by the owner queue) checks each verbatim is on the
      cached page of that fund's filing.
  (b) name the rows it covers in ``rows``. The ledger closes a finding with the entry only when
      every row the finding flags (``pipeline.finding_rows``) is among the rows named for that
      member; a recurrence on other rows, or rows that cannot be resolved, stays open.
Entries accepted before the ruling are grandfathered: they carry ``legacy_unscoped: true``, are
listed with their members in ``data/reference/disposition_legacy_unscoped.json``, and keep working
unscoped. The flag is honoured only for a listed id and only over its frozen members, so it cannot
be added to a new entry or used to widen an old one. ``informational`` entries are exempt.

``carry_forward`` is the one way such an entry reaches a later quarter: it names a deterministic
check (``pipeline.disposition_validity``) that restates the entry's reason as a test of every
flagged row. The entry covers a quarter on or after ``from`` only when that check passed on that
fund-quarter's own outputs. With no recorded pass the quarter is reviewed as before.

History is kept, never deleted. ``revoked`` (whole entry) and ``revoked_members`` (moved out of
``ciks``/``quarters``) record ``revoked_on``, ``revoked_by`` (the owner's words) and ``reason``;
a revoked entry or member matches nothing, including by carry-forward. ``statement_history``
records a statement that was rewritten (``statement``, ``replaced_on``, ``replaced_by``, ``reason``).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

CLASSES = ("informational", "as_filed", "not_applicable")
STATE_BY_CLASS = {"informational": "dispositioned_informational", "as_filed": "dispositioned_as_filed",
                  "not_applicable": "dispositioned_not_applicable"}
DISPOSITIONED_STATES = frozenset(STATE_BY_CLASS.values())
SCOPED_CLASSES = ("as_filed", "not_applicable")
MIN_VERBATIM = 20
# An answer to an earlier reviewer's verdict, as the fund gate requires it (fund_gate.check_ledger).
MIN_VERDICT_ANSWER = 60
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_CIK = re.compile(r"\d{10}")
_UNSET = object()


def default_dir() -> Path:
    from pipeline import config
    return config.OVERRIDES_DIR / "finding_dispositions"


def default_legacy_path() -> Path:
    from pipeline import config
    return config.REFERENCE_DIR / "disposition_legacy_unscoped.json"


def load_legacy(path: Path | None = None) -> dict[str, dict]:
    """Frozen members of the grandfathered entries: {disposition_id: {"ciks": set, "quarters": set}}."""
    path = Path(path) if path is not None else default_legacy_path()
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    return {key: {"ciks": set(value.get("ciks") or []), "quarters": set(value.get("quarters") or [])}
            for key, value in (raw.get("entries") or {}).items()}


def members(entry: dict) -> list[tuple[str, str]]:
    """(cik, quarter) pairs the entry lists (wildcards excluded)."""
    return [(c, q) for c in entry.get("ciks") or [] if c != "*" for q in entry.get("quarters") or [] if q != "all"]


def is_revoked(entry: dict) -> bool:
    return bool(entry.get("revoked"))


def is_legacy(entry: dict) -> bool:
    return entry.get("legacy_unscoped") is True


def is_scoped(entry: dict) -> bool:
    """Whether the ledger applies the row test: a non-legacy as_filed / not_applicable entry."""
    return entry.get("class") in SCOPED_CLASSES and not is_legacy(entry)


def _filing_items(entry: dict) -> list[dict]:
    return [e for e in entry.get("evidence") or [] if isinstance(e, dict) and e.get("source") == "filing"]


def _item_member(item: dict, entry: dict) -> tuple[str, str] | None:
    """The (cik, quarter) a filing quote is cited for; None when it names no quarter."""
    quarter = str(item.get("quarter") or "")
    if not _DATE.fullmatch(quarter):
        return None
    if str(item.get("cik") or "").strip():
        return str(item["cik"]).strip().zfill(10), quarter
    ciks = [c for c in entry.get("ciks") or [] if c != "*"]
    return (ciks[0], quarter) if len(ciks) == 1 else None


def _member_quotes(entry: dict) -> dict[tuple[str, str], list[dict]]:
    found: dict[tuple[str, str], list[dict]] = {}
    for item in _filing_items(entry):
        if not str(item.get("accession") or "").strip() or len(str(item.get("verbatim") or "").strip()) < MIN_VERBATIM:
            continue
        member = _item_member(item, entry)
        if member is not None:
            found.setdefault(member, []).append(item)
    return found


def row_keys(entry: dict, cik, quarter) -> frozenset[str]:
    """Keys of the rows the entry names for one member (see pipeline.finding_rows)."""
    from pipeline.finding_rows import descriptor_key
    cik, quarter = str(cik or "").zfill(10), str(quarter or "")[:10]
    keys = set()
    for row in entry.get("rows") or []:
        if isinstance(row, dict) and str(row.get("cik") or "").zfill(10) == cik and str(row.get("quarter") or "") == quarter:
            key = descriptor_key(row)
            if key:
                keys.add(key)
    return frozenset(keys)


def _validate_history(entry: dict) -> list[str]:
    errs = []
    revoked = entry.get("revoked")
    if revoked is not None:
        if not isinstance(revoked, dict):
            errs.append("revoked must be an object")
        else:
            for key in ("revoked_by", "reason"):
                if not str(revoked.get(key) or "").strip():
                    errs.append("revoked needs " + key)
            if not _DATE.fullmatch(str(revoked.get("revoked_on") or "")):
                errs.append("revoked.revoked_on must be YYYY-MM-DD")
    live = set(members(entry))
    for record in entry.get("revoked_members") or []:
        if not isinstance(record, dict):
            errs.append("revoked_members entries must be objects")
            continue
        ciks, quarters = record.get("ciks"), record.get("quarters")
        if not (isinstance(ciks, list) and ciks and all(_CIK.fullmatch(str(c)) for c in ciks)):
            errs.append("revoked_members.ciks must list 10-digit CIKs")
            continue
        if not (isinstance(quarters, list) and quarters and all(_DATE.fullmatch(str(q)) for q in quarters)):
            errs.append("revoked_members.quarters must list YYYY-MM-DD dates")
            continue
        for key in ("revoked_by", "reason"):
            if not str(record.get(key) or "").strip():
                errs.append("revoked_members needs " + key)
        if not _DATE.fullmatch(str(record.get("revoked_on") or "")):
            errs.append("revoked_members.revoked_on must be YYYY-MM-DD")
        if live & {(c, q) for c in ciks for q in quarters}:
            errs.append("a revoked member is still listed in ciks x quarters")
    if entry.get("revoked_members") is not None and not isinstance(entry.get("revoked_members"), list):
        errs.append("revoked_members must be a list")
    history = entry.get("statement_history")
    if history is not None:
        if not isinstance(history, list) or not all(
                isinstance(h, dict) and str(h.get("statement") or "").strip() and str(h.get("replaced_by") or "").strip()
                and str(h.get("reason") or "").strip() and _DATE.fullmatch(str(h.get("replaced_on") or "")) for h in history):
            errs.append("statement_history must list {statement, replaced_on, replaced_by, reason}")
    return errs


def _validate_bar(entry: dict) -> list[str]:
    """The D-253 bar for a non-legacy as_filed / not_applicable entry (shape only; no page read)."""
    errs = []
    listed = members(entry)
    quotes = _member_quotes(entry)
    missing = [m for m in listed if m not in quotes]
    if missing:
        errs.append("needs a filing quote (accession, verbatim of %d+ characters, quarter) for each member; missing: %s"
                    % (MIN_VERBATIM, ", ".join("%s %s" % m for m in missing[:6]) + (" ..." if len(missing) > 6 else "")))
    rows = entry.get("rows")
    if not isinstance(rows, list) or not rows:
        errs.append("rows must name the rows the entry covers, for each member")
        return errs
    from pipeline.finding_rows import descriptor_key
    for row in rows:
        if not isinstance(row, dict) or descriptor_key(row) is None:
            errs.append("each rows item needs one of row_id, source_identifier or fund_level: true")
            break
        named = sum(1 for k in ("row_id", "source_identifier") if str(row.get(k) or "").strip()) + (row.get("fund_level") is True)
        if named != 1:
            errs.append("each rows item names exactly one of row_id, source_identifier or fund_level")
            break
        if (str(row.get("cik") or "").zfill(10), str(row.get("quarter") or "")) not in set(listed):
            errs.append("rows item for a member the entry does not list: %s %s" % (row.get("cik"), row.get("quarter")))
            break
    unnamed = [m for m in listed if not row_keys(entry, *m)]
    if unnamed:
        errs.append("rows names nothing for member(s): " + ", ".join("%s %s" % m for m in unnamed[:6])
                    + (" ..." if len(unnamed) > 6 else ""))
    return errs


def validate(entry, *, legacy=_UNSET) -> list[str]:
    """Problems with one entry; empty when it is valid.

    ``legacy``: the grandfathered registry ({id: {"ciks", "quarters"}}); by default the one in
    data/reference. An entry flagged ``legacy_unscoped`` must be listed there and stay within its
    frozen members; every other as_filed / not_applicable entry must meet the D-253 bar."""
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
    if kind in SCOPED_CLASSES:
        if isinstance(ciks, list) and "*" in ciks:
            errs.append(str(kind) + " must name its funds")
        if isinstance(quarters, list) and "all" in quarters:
            errs.append(str(kind) + " must name its quarters")
    evidence = entry.get("evidence")
    if (not isinstance(evidence, list) or not evidence or not all(
            isinstance(e, dict) and str(e.get("source") or "").strip() and str(e.get("quote") or "").strip() for e in evidence)):
        errs.append("evidence must be a non-empty list of {source, quote}")
    has_filing = isinstance(evidence, list) and any(isinstance(e, dict) and e.get("source") == "filing" for e in evidence)
    if entry.get("supersedes_real_error_verdict") not in (None, False, True):
        errs.append("supersedes_real_error_verdict must be true or false")
    if entry.get("supersedes_real_error_verdict") and not has_filing:
        errs.append("superseding a real-error verdict needs filing evidence")
    answers = entry.get("addresses_verdict")
    if answers is not None:
        if not isinstance(answers, dict) or not all(_DATE.fullmatch(str(q)) and isinstance(t, str) for q, t in answers.items()):
            errs.append("addresses_verdict must map YYYY-MM-DD to the answer text")
        elif any(len(t.strip()) >= MIN_VERDICT_ANSWER for t in answers.values()) and not has_filing:
            errs.append("answering a real-error verdict needs filing evidence")
    if entry.get("carry_forward") is not None:
        from pipeline import disposition_validity
        errs.extend(disposition_validity.validate_carry_forward(entry["carry_forward"]))
        if kind == "informational":
            errs.append("informational already covers every quarter; carry_forward does not apply")
    if not _DATE.fullmatch(str(entry.get("decided_on") or "")):
        errs.append("decided_on must be YYYY-MM-DD")
    errs.extend(_validate_history(entry))
    if entry.get("legacy_unscoped") not in (None, True):
        errs.append("legacy_unscoped must be true or absent")
    if errs:
        return errs
    if is_legacy(entry):
        registry = load_legacy() if legacy is _UNSET else (legacy or {})
        frozen = registry.get(str(entry["disposition_id"]))
        if frozen is None:
            errs.append("legacy_unscoped is only for entries frozen in the legacy registry")
        elif not (set(ciks) <= frozen["ciks"] and set(quarters) <= frozen["quarters"]):
            errs.append("a legacy entry may not list a fund or quarter beyond its frozen members")
    elif kind in SCOPED_CLASSES and not is_revoked(entry):
        errs.extend(_validate_bar(entry))
    return errs


def member_quote_problems(entry: dict, page_text, normalise) -> list[str]:
    """Members without a verbatim found on the cached page of that fund's filing.

    ``page_text(cik, accession)`` returns the normalised page or None; ``normalise`` folds a quote
    the same way (scripts/v05_evidence/fund_gate.py). Empty when every member has a verified quote."""
    problems = []
    quotes = _member_quotes(entry)
    for member in members(entry):
        verified = False
        for item in quotes.get(member, []):
            page = page_text(member[0], str(item["accession"]).strip())
            text = normalise(str(item["verbatim"]))
            if page and len(text) >= MIN_VERBATIM and text in page:
                verified = True
                break
        if not verified:
            problems.append("%s %s: no verbatim found on a cached page of this fund" % member)
    return problems


def answers_verdict(entry: dict, quarter) -> bool:
    """Whether the entry answers an earlier real-error verdict for this quarter, with filing evidence:
    ``supersedes_real_error_verdict`` (every quarter it lists) or an ``addresses_verdict`` answer for
    the quarter (the fund gate's form, ``fund_gate.check_ledger``)."""
    if entry.get("supersedes_real_error_verdict"):
        return True   # the validator requires filing evidence for the flag
    if not _filing_items(entry):
        return False
    answer = (entry.get("addresses_verdict") or {}).get(str(quarter or "")[:10])
    return isinstance(answer, str) and len(answer.strip()) >= MIN_VERDICT_ANSWER


def closes(entry: dict, state: str, quarter=None) -> bool:
    """Whether this entry may close a finding currently in ``state`` (rows aside; see covers_rows).

    An earlier reviewer's 'real error' verdict with no fix is left standing unless the entry
    is informational (the verdict then only confirms the fact the rule reports) or answers that
    verdict with filing evidence: ``supersedes_real_error_verdict``, or an ``addresses_verdict``
    answer for the finding's quarter."""
    if state in ("open", "needs_human", "evidence_backlog", "b1_route_missing"):
        return True
    # real_error_check_silent: the same verdict, its check no longer firing (findings_ledger).
    if state in ("real_error_unremediated", "real_error_check_silent"):
        return entry["class"] == "informational" or answers_verdict(entry, quarter)
    # A fix that was drafted (staged) or drafted and withdrawn (pulled) never changed the data. It
    # yields only to an entry that replaces the verdict behind it, which requires filing evidence.
    if state in ("remediation_staged", "remediation_pulled"):
        return bool(entry.get("supersedes_real_error_verdict"))
    return False


def covers_rows(entry: dict, *, cik, quarter, flagged, carried_forward: bool = False) -> tuple[bool, str]:
    """Whether a closing entry covers the rows the finding flags. Returns (ok, reason).

    Legacy and informational entries are unscoped. A quarter reached by carry-forward is covered
    by its passed check, which tests every flagged row. Otherwise every flagged row must be named
    for this member; unresolvable rows (``flagged`` None) fail closed."""
    if not is_scoped(entry):
        return True, "legacy_unscoped" if is_legacy(entry) else "unscoped_class"
    if carried_forward:
        return True, "carry_forward_check"
    if flagged is None:
        return False, "rows_unresolved"
    named = row_keys(entry, cik, quarter)
    outside = set(flagged) - named
    if outside:
        return False, "rows_outside:%d" % len(outside)
    return True, "rows_within"


def load(directory: Path | None = None, *, legacy=_UNSET) -> list[dict]:
    """Every valid entry in the store. An invalid file or entry raises: a disposition that cannot
    be read must not be mistaken for one that does not exist."""
    directory = Path(directory) if directory is not None else default_dir()
    registry = load_legacy() if legacy is _UNSET else (legacy or {})
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
            problems = validate(entry, legacy=registry)
            if problems:
                raise ValueError("Invalid disposition in %s (%s): %s" % (
                    path, entry.get("disposition_id") if isinstance(entry, dict) else "?", "; ".join(problems)))
            key = entry["disposition_id"]
            if key in seen:
                raise ValueError("Duplicate disposition id: " + key)
            seen.add(key)
            entries.append(entry)
    return entries


def _revoked_member(entry: dict, cik: str, quarter: str) -> bool:
    return any(cik in (r.get("ciks") or []) and quarter in (r.get("quarters") or [])
               for r in entry.get("revoked_members") or [])


def match(entries: list[dict], *, cik, engine, rule_name, report_date, passes=frozenset()) -> dict | None:
    """The first entry covering this finding, or None. A specific fund wins over '*'.

    ``passes`` holds (disposition_id, cik, quarter) whose carry-forward check passed; an entry
    reaches a quarter it does not list only through one of those. A revoked entry or member
    matches nothing."""
    cik = str(cik or "").zfill(10)
    quarter = str(report_date or "")[:10]
    found = None
    for entry in entries:
        if entry["engine"] != (engine or "") or entry["rule_name"] != (rule_name or ""):
            continue
        if is_revoked(entry) or _revoked_member(entry, cik, quarter):
            continue
        if "all" not in entry["quarters"] and quarter not in entry["quarters"]:
            carry = entry.get("carry_forward")
            if not (carry and quarter >= carry["from"] and (entry["disposition_id"], cik, quarter) in passes):
                continue
        if cik in entry["ciks"]:
            return entry
        if "*" in entry["ciks"] and found is None:
            found = entry
    return found
