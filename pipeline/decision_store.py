"""Decision store: the one place decisions about findings are written and read.

Physical layout (git-tracked, append-only)::

    data/decisions/<cik10>.jsonl     decisions about one fund's findings
    data/decisions/_shared.jsonl     decisions with no single fund (check repairs, cohort rulings)
    data/decisions/verdict_files/    reviewer verdict files, byte-for-byte (hashes are evidence)

One JSON object per line. A line is never edited or removed; a change of mind is a new entry whose
``supersedes`` names the old ``decision_id``.

Native types (stored here): ``verdict`` (a fund agent's conclusion on a finding and its independent
review), ``owner_ruling``, ``check_repair_request``, ``fix_record``.

Adapted types (stored in their own validated stores, exposed here read-only through ``load_all``):
``disposition`` (pipeline.finding_dispositions), ``verdict_retirement``
(pipeline.verdict_retirements), ``disposition_proposal`` (data/overrides/finding_dispositions_proposed).

``facts_by_finding`` turns the standing entries into ``pipeline.finding_status.Facts`` per ledger
row; ``finding_status.status_of`` turns state plus facts into the status anyone quotes.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import re
from pathlib import Path

from pipeline import finding_status

NATIVE_TYPES = ("verdict", "owner_ruling", "check_repair_request", "owner_request", "fix_record")
ADAPTED_TYPES = ("disposition", "verdict_retirement", "disposition_proposal")
TYPES = NATIVE_TYPES + ADAPTED_TYPES
RULINGS = ("accept", "reject", "more", "approve", "decline")
REQUEST_RESOLUTIONS = ("open", "approved", "implemented", "declined")
OPEN_RESOLUTIONS = ("open", "approved")
REVIEW_OUTCOMES = ("supported", "rejected", "")
EVIDENCE_SOURCES = ("filing", "query", "code", "measurement", "commit")
SHARED_FILE = "_shared.jsonl"
INCOMPLETE = finding_status.INCOMPLETE_PROPOSAL

_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_STAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
_CIK = re.compile(r"\d{10}")
_ACTOR = re.compile(r"(owner|delegate:\S.*|check:\S.*|agent:\S.*)")
# who may write which native type
_ALLOWED = {
    "owner": set(NATIVE_TYPES),
    "delegate": set(NATIVE_TYPES),
    "check": {"verdict", "check_repair_request", "owner_request", "fix_record"},
    "agent": {"verdict", "check_repair_request", "owner_request", "fix_record"},
}


def default_dir() -> Path:
    from pipeline import config
    return config.DATA_DIR / "decisions"


def _actor_kind(actor: str) -> str:
    return actor.split(":", 1)[0]


def _text(entry: dict, key: str) -> str:
    return str(entry.get(key) or "").strip()


def validate(entry) -> list[str]:
    """Problems with one native entry; empty when it is valid."""
    if not isinstance(entry, dict):
        return ["entry is not an object"]
    errs = []
    kind = entry.get("type")
    if kind not in NATIVE_TYPES:
        return ["type must be one of %s" % (NATIVE_TYPES,)]
    for key in ("statement", "decided_by", "decided_on"):
        if not _text(entry, key):
            errs.append("missing " + key)
    if _text(entry, "decided_by") and not _ACTOR.fullmatch(_text(entry, "decided_by")):
        errs.append("decided_by must be owner, delegate:<id>, check:<name> or agent:<id>")
    if _text(entry, "decided_on") and not _DATE.fullmatch(_text(entry, "decided_on")):
        errs.append("decided_on must be YYYY-MM-DD")
    if _text(entry, "cik") and not _CIK.fullmatch(_text(entry, "cik")):
        errs.append("cik must be a 10-digit CIK or empty")
    ids = entry.get("finding_ids", [])
    if not isinstance(ids, list) or not all(isinstance(i, str) and i.strip() for i in ids):
        errs.append("finding_ids must be a list of review ids")
    quarters = entry.get("quarters", [])
    if not isinstance(quarters, list) or not all(_DATE.fullmatch(str(q)) for q in quarters):
        errs.append("quarters must be a list of YYYY-MM-DD dates")
    evidence = entry.get("evidence", [])
    if not isinstance(evidence, list) or not all(
            isinstance(e, dict) and e.get("source") in EVIDENCE_SOURCES and str(e.get("quote") or "").strip()
            for e in evidence):
        errs.append("evidence must be a list of {source in %s, quote}" % (EVIDENCE_SOURCES,))
    elif any(e["source"] == "filing" and not str(e.get("accession") or "").strip() for e in evidence):
        errs.append("filing evidence needs an accession")
    if kind == "verdict":
        if not ids:
            errs.append("a verdict names its finding_ids")
        if entry.get("conclusion") not in finding_status.CONCLUSIONS:
            errs.append("conclusion must be one of %s" % (finding_status.CONCLUSIONS,))
        if entry.get("review_outcome", "") not in REVIEW_OUTCOMES:
            errs.append("review_outcome must be supported, rejected or empty")
        if entry.get("review_outcome") and not _text(entry, "reviewed_by"):
            errs.append("a review_outcome needs reviewed_by")
    elif kind == "owner_ruling":
        if entry.get("ruling") not in RULINGS:
            errs.append("ruling must be one of %s" % (RULINGS,))
        if not _text(entry, "words"):
            errs.append("an owner_ruling records the words")
        if not (_text(entry, "reason_key") or _text(entry, "request_id") or ids):
            errs.append("an owner_ruling names a reason_key, a request_id or finding_ids")
    elif kind in ("check_repair_request", "owner_request"):
        if not _text(entry, "request_id"):
            errs.append("missing request_id")
        if kind == "check_repair_request" and not _text(entry, "check"):
            errs.append("missing check (the rule or file to repair)")
        if entry.get("resolution") not in REQUEST_RESOLUTIONS:
            errs.append("resolution must be one of %s" % (REQUEST_RESOLUTIONS,))
    elif kind == "fix_record":
        expects = entry.get("expects")
        if not isinstance(expects, dict) or not isinstance(expects.get("finding_ids"), list) \
                or not isinstance(expects.get("ciks"), list) or not (expects["finding_ids"] or expects["ciks"]):
            errs.append("expects must give finding_ids and ciks, at least one non-empty")
        if not (_text(entry, "commit") or entry.get("files")):
            errs.append("a fix_record names a commit or the files changed")
        if not _text(entry, "tested_in"):
            errs.append("a fix_record names the sandbox it was tested in")
    return errs


def decision_id(entry: dict) -> str:
    body = {k: v for k, v in entry.items() if k not in ("decision_id", "recorded_at")}
    digest = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=True).encode("utf-8")).hexdigest()[:10]
    return "DC-%s-%s" % (_text(entry, "cik") or "shared", digest)


def _file_for(entry: dict, directory: Path) -> Path:
    return directory / ((_text(entry, "cik") + ".jsonl") if _text(entry, "cik") else SHARED_FILE)


def load_native(directory: Path | None = None) -> list[dict]:
    """Every native entry, in file then line order. A line that is not valid raises: a decision that
    cannot be read must not be mistaken for one that does not exist."""
    directory = Path(directory) if directory is not None else default_dir()
    out: list[dict] = []
    seen: set[str] = set()
    if not directory.exists():
        return out
    for path in sorted(directory.glob("*.jsonl")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            entry = json.loads(line)
            problems = validate(entry)
            if problems:
                raise ValueError("Invalid decision in %s line %d: %s" % (path, number, "; ".join(problems)))
            if entry.get("decision_id") in seen:
                raise ValueError("Duplicate decision id %s in %s" % (entry.get("decision_id"), path))
            seen.add(entry["decision_id"])
            entry["origin"] = "native"
            out.append(entry)
    return out


def append(entry: dict, *, actor: str, directory: Path | None = None, quote_ok=None,
           now: datetime.datetime | None = None) -> dict:
    """Validate and append one native entry; returns it with ``decision_id`` and ``recorded_at``.

    ``actor`` is who is writing (owner, delegate:<id>, check:<name>, agent:<id>) and must equal the
    entry's ``decided_by``: nobody records a decision in another's name. ``quote_ok(cik, accession,
    quote) -> bool`` checks filing quotes against the cached page; a quote it refuses is rejected.
    """
    directory = Path(directory) if directory is not None else default_dir()
    entry = {k: v for k, v in entry.items() if k not in ("decision_id", "recorded_at", "origin")}
    problems = validate(entry)
    if problems:
        raise ValueError("Invalid decision: " + "; ".join(problems))
    if not _ACTOR.fullmatch(actor) or actor != entry["decided_by"]:
        raise PermissionError("actor %r does not match decided_by %r" % (actor, entry["decided_by"]))
    if entry["type"] not in _ALLOWED[_actor_kind(actor)]:
        raise PermissionError("%s may not record a %s" % (_actor_kind(actor), entry["type"]))
    if quote_ok is not None:
        for item in entry.get("evidence", []):
            if item["source"] == "filing" and not quote_ok(_text(entry, "cik"), item["accession"], item["quote"]):
                raise ValueError("filing quote not found on the cached page: %s %r" % (
                    item["accession"], item["quote"][:80]))
    existing = load_native(directory)
    ids = {e["decision_id"] for e in existing}
    if entry.get("supersedes") and entry["supersedes"] not in ids:
        raise ValueError("supersedes names an unknown decision: %s" % entry["supersedes"])
    entry["decision_id"] = decision_id(entry)
    if entry["decision_id"] in ids:
        raise ValueError("this decision is already recorded: %s" % entry["decision_id"])
    entry["recorded_at"] = (now or datetime.datetime.now()).strftime("%Y-%m-%dT%H:%M:%S")
    directory.mkdir(parents=True, exist_ok=True)
    with open(_file_for(entry, directory), "a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(entry, sort_keys=True, ensure_ascii=True) + "\n")
    return entry


def standing(entries: list[dict]) -> list[dict]:
    """Entries no later entry supersedes."""
    gone = {e["supersedes"] for e in entries if e.get("supersedes")}
    return [e for e in entries if e.get("decision_id") not in gone]


# ---------------------------------------------------------------- adapters

def _adapt_dispositions(directory) -> list[dict]:
    from pipeline import finding_dispositions as fd
    out = []
    for entry in fd.load(directory):
        out.append({"type": "disposition", "origin": "finding_dispositions",
                    "decision_id": str(entry.get("disposition_id")), "cik": "",
                    "ciks": list(entry.get("ciks") or []), "engine": entry.get("engine"),
                    "rule_name": entry.get("rule_name"), "quarters": list(entry.get("quarters") or []),
                    "class": entry.get("class"), "statement": entry.get("statement"),
                    "decided_by": entry.get("decided_by"), "decided_on": entry.get("decided_on"),
                    "revoked": fd.is_revoked(entry), "finding_ids": []})
    return out


def _adapt_retirements(directory) -> list[dict]:
    from pipeline import verdict_retirements as vr
    return [{"type": "verdict_retirement", "origin": "verdict_retirements",
             "decision_id": str(entry.get("retirement_id")), "cik": str(entry.get("cik") or ""),
             "engine": entry.get("engine"), "rule_name": entry.get("rule_name"),
             "quarters": [str(entry.get("report_date") or "")[:10]], "statement": entry.get("reason"),
             "decided_by": entry.get("decided_by"), "decided_on": entry.get("decided_on"),
             "finding_ids": [rid]} for rid, entry in sorted(vr.load(directory).items())]


def proposals_dir() -> Path:
    from pipeline import config
    return config.OVERRIDES_DIR / "finding_dispositions_proposed"


def proposal_ready(entry: dict) -> bool:
    """A store-class proposal's shape meets the disposition bar (class, per-member filing quote,
    rows, rerun). The quote-on-page check is made when the owner accepts, not here."""
    from pipeline import finding_dispositions as fd
    candidate = {k: v for k, v in entry.items() if k not in ("reason_key", "recommended")}
    candidate.setdefault("decided_by", "owner")
    candidate.setdefault("decided_on", "2000-01-01")
    if not _text(candidate, "decided_by"):
        candidate["decided_by"] = "owner"
    if not _DATE.fullmatch(_text(candidate, "decided_on")):
        candidate["decided_on"] = "2000-01-01"
    return not fd.validate(candidate)


def _adapt_proposals(directory) -> list[dict]:
    directory = Path(directory) if directory is not None else proposals_dir()
    out = []
    if not directory.exists():
        return out
    for path in sorted(directory.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        for entry in data.get("dispositions", []) if isinstance(data, dict) else []:
            klass = str(entry.get("class") or "")
            out.append({"type": "disposition_proposal", "origin": "proposals:" + path.name,
                        "decision_id": str(entry.get("disposition_id")), "cik": "",
                        "ciks": [str(c).zfill(10) for c in entry.get("ciks") or []],
                        "engine": entry.get("engine"), "rule_name": entry.get("rule_name"),
                        "quarters": [str(q)[:10] for q in entry.get("quarters") or []],
                        "class": klass, "reason_key": str(entry.get("reason_key") or ""),
                        "statement": entry.get("statement"), "finding_ids": [],
                        "ready": klass in finding_status.STORE_CLASSES and proposal_ready(entry)})
    return out


def load_all(directory: Path | None = None, *, dispositions_dir=None, retirements_dir=None,
             proposals=None) -> list[dict]:
    """Native entries plus the adapted stores, each with ``origin``."""
    return (load_native(directory) + _adapt_dispositions(dispositions_dir)
            + _adapt_retirements(retirements_dir) + _adapt_proposals(proposals))


# ---------------------------------------------------------------- facts

def _reason_rulings(entries: list[dict]) -> dict[str, str]:
    """Latest owner ruling per proposal reason key."""
    out: dict[str, tuple[str, str]] = {}
    for e in entries:
        if e.get("type") == "owner_ruling" and _text(e, "reason_key"):
            stamp = _text(e, "recorded_at") or _text(e, "decided_on")
            if e["reason_key"] not in out or stamp >= out[e["reason_key"]][0]:
                out[e["reason_key"]] = (stamp, e["ruling"])
    return {key: ruling for key, (_stamp, ruling) in out.items()}


def _proposal_class(proposal: dict, rulings: dict[str, str]) -> str:
    """What a proposal contributes to a finding's status ("" when nothing)."""
    klass = proposal.get("class") or ""
    ruling = rulings.get(proposal.get("reason_key") or "", "")
    if klass in finding_status.MISFIRE_CLASSES:
        return klass                      # the check misfires whatever was ruled on the proposal
    if klass not in finding_status.STORE_CLASSES or ruling in ("reject", "decline", "accept"):
        return ""                         # rejected: gone; accepted: the disposition itself closes it
    if ruling == "more" or not proposal.get("ready"):
        return INCOMPLETE
    return klass


def facts_by_finding(entries: list[dict], ledger_rows: list[dict], *, build_time: str = "") -> dict:
    """``finding_status.Facts`` for each ledger row, keyed by review_id.

    ``build_time`` (YYYY-MM-DDTHH:MM:SS) is when the ledger's holdings were built: a fix recorded
    after it is still waiting for a build. Empty: no fix counts as queued.
    """
    live = standing(entries)
    rulings = _reason_rulings(live)
    fix_ids: set[str] = set()
    repair_ids: set[str] = set()
    owner_ids: set[str] = set()
    verdicts: dict[str, tuple[str, dict]] = {}
    proposals: dict[tuple, list[dict]] = {}
    request_state: dict[str, tuple[str, dict]] = {}
    for e in live:
        kind = e.get("type")
        stamp = _text(e, "recorded_at") or _text(e, "decided_on")
        if kind == "fix_record":
            if build_time and _text(e, "recorded_at") > build_time:
                fix_ids.update(e["expects"]["finding_ids"])
        elif kind in ("check_repair_request", "owner_request"):
            rid = e["request_id"]
            if rid not in request_state or stamp >= request_state[rid][0]:
                request_state[rid] = (stamp, e)
        elif kind == "verdict":
            for fid in e["finding_ids"]:
                if fid not in verdicts or stamp >= verdicts[fid][0]:
                    verdicts[fid] = (stamp, e)
        elif kind == "disposition_proposal":
            for cik in e.get("ciks", []):
                for quarter in e.get("quarters", []):
                    proposals.setdefault((cik, e.get("engine"), e.get("rule_name"), quarter), []).append(e)
    for _stamp, e in request_state.values():
        if e["resolution"] in OPEN_RESOLUTIONS:
            (repair_ids if e["type"] == "check_repair_request" else owner_ids).update(e.get("finding_ids", []))
    order = {klass: i for i, klass in enumerate(
        ("rule_problem", "false_alarm", "as_filed", "not_applicable", "informational", INCOMPLETE, ""))}
    out = {}
    for row in ledger_rows:
        rid = row["review_id"]
        key = (str(row.get("cik") or "").zfill(10), row.get("engine"), row.get("rule_name"),
               str(row.get("report_date") or "")[:10])
        classes = [_proposal_class(p, rulings) for p in proposals.get(key, [])]
        klass = min(classes, key=lambda c: order[c]) if classes else ""
        verdict = verdicts.get(rid, ("", {}))[1]
        out[rid] = finding_status.Facts(
            fix_queued=rid in fix_ids, check_repair=rid in repair_ids, owner_request=rid in owner_ids,
            proposal_class=klass,
            conclusion=verdict.get("conclusion", ""),
            conclusion_supported=verdict.get("review_outcome") == "supported")
    return out
