"""SP3 proper: inception converter -- existing override files and the Q4-2025 census -> profile document v1.

Pure (no file access); the CLI (profile_document_run) reads the files and passes their parsed content. Spec 4
inception: the override file's value becomes the entry value, its citations the evidence, its content hash the
pre-image; a filer with no file on an axis gets a census-derived entry or an insufficient-evidence stub.
Dispositions (spec 7.1, plan decisions P1-P11): knowledge files -> entries (rate_convention, grammars, anchors) or
one-off corrections (B2, aggregate rows, oracle exceptions); executable files -> wrapper blocks (wrapper,
agent_investigate_rules). Key order inside override content is preserved everywhere (prefix_rules is first-match).

wrapper_block hashing: `content_sha256` and each source file's `ordered_sha256` are both `translate.value_sha256`
(order-preserving JSON serialisation, ensure_ascii, compact separators) of the parsed content -- the same hash
Task 7's round trip recomputes from the materialised override file to verify a block reproduces its source
byte-for-byte after canonical serialisation. The source file's raw-bytes `sha256` is carried separately (as given
by the caller) and is never recomputed here.
"""
from __future__ import annotations

import copy
import re

from scripts.profile_pilot import profile_document as pd
from scripts.profile_pilot.profile_families import REPO_PREFIX, cik10
from scripts.profile_pilot.translate import value_sha256

SIGNOFF_TAGS = ("signoff-2025-12-31", "signoff-2026-03-31")
PRE_IMAGE_REASON = ("criterion 5 pre-image check (row_id present, pre-image unchanged) runs on the rebuilt quarter "
                    "in sub-project 6")
SHARED_MECHANISM = {"bdc_aggregate_row_overrides.json": ("aggregate_row", "aggregate_row_exclusion"),
                    "bdc_xbrl_oracle_exceptions.json": ("oracle_exception", "reconciliation_scope_exception")}
_ROW_ID_SQL = re.compile(r"\brow_id\s+IN\s*\(", re.IGNORECASE)


class InceptionError(ValueError):
    """The override inputs cannot be converted without guessing."""


def _number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def rule_expressibility(rule: dict) -> dict:
    quarters = (rule.get("scope") or {}).get("quarters") or []
    if (rule.get("rule_type") == "row_exclusion" and _ROW_ID_SQL.search(rule.get("predicate_sql") or "")
            and len(quarters) == 1):
        return dict(expressible_as="one_off_correction",
                    reason="row_id-keyed exclusion scoped to one quarter (spec 4.2); conversion is sub-project 6")
    return dict(expressible_as=None, reason="executable rule_type " + repr(rule.get("rule_type"))
                + " stays in the wrapper section (spec 7.1)")


def wrapper_block(cik, *, family, files, recorded_at, attested_under) -> dict:
    files = sorted(files, key=lambda x: x["path"])
    if family == "bdc_xbrl_wrapper":
        if len(files) != 1:
            raise InceptionError("exactly one wrapper file per filer: " + repr([x["path"] for x in files]))
        content = copy.deepcopy(files[0]["content"])
        if cik10(content.get("cik")) != cik:
            raise InceptionError("wrapper cik " + repr(content.get("cik")) + " is not " + cik)
        expressibility = None
    elif family == "agent_investigate_rules":
        for x in files:
            if cik10(x["content"].get("cik")) != cik:
                raise InceptionError("rule cik " + repr(x["content"].get("cik")) + " is not " + cik + ": "
                                     + x["path"])
        content = {"files": {x["path"]: copy.deepcopy(x["content"]) for x in files}}
        expressibility = {x["path"]: rule_expressibility(x["content"]) for x in files}
    else:
        raise InceptionError("unknown block family " + repr(family))
    sources = [dict(path=x["path"], sha256=x["sha256"], ordered_sha256=value_sha256(x["content"])) for x in files]
    evidence = [dict(kind="override_file", path=REPO_PREFIX + s["path"], sha256=s["sha256"],
                     ordered_sha256=s["ordered_sha256"]) for s in sources]
    evidence.append(dict(kind="attestation", tags=sorted(attested_under),
                         rule="tag lists the sign-off tags whose blob parses order-identical to the file read"))
    return dict(block_id=cik + ":wrapper:" + family + ":v1", family=family, version=1, content=content,
                content_sha256=value_sha256(content), source_files=sources, valid_from=None, valid_to=None,
                recorded_at=recorded_at, recorded_until=None, supersedes=None, supersession_kind=None,
                attested_under=sorted(attested_under), evidence=evidence, expressibility=expressibility)


def _b2_dates(leaf: dict) -> list:
    template = leaf.get("template") or {}
    selector = template.get("row_selector") or {}
    dates = set((leaf.get("scope") or {}).get("quarters") or [])
    for value in (template.get("report_date"), selector.get("report_date")):
        if value:
            dates.add(value)
    return sorted(dates)


def _correction(cik, n, tag, *, family, mechanism, fix_class, dates, target, row_keyed, value, source,
                recorded_at, run_id, author) -> dict:
    one_off = len(dates) == 1
    kind = "one_off" if one_off else ("multi_quarter" if dates else "undated")
    day = dates[0] if one_off else None
    return dict(correction_id="%s:corr:%s:%03d" % (cik, tag, n), kind=kind, family=family, mechanism=mechanism,
                fix_class=fix_class, report_date=day, valid_from=day, valid_to=day, report_dates=list(dates),
                target=target, row_keyed=row_keyed, value=copy.deepcopy(value), source=source,
                pre_image=dict(status="unchecked", reason=PRE_IMAGE_REASON), recurrence_group=None, promotion=None,
                state="accepted" if one_off else "candidate",
                admission_basis="inherited_production" if one_off else "not_one_off_at_inception",
                confidence=_number(value.get("confidence")),
                provenance=dict(who=pd.CONVERTER_VERSION, source_author=str(value.get("created_by") or author),
                                when=recorded_at, run_id=run_id, source=REPO_PREFIX + source["path"]),
                recorded_at=recorded_at, recorded_until=None, supersedes=None)


def correction_records(cik, *, b2_files, shared, recorded_at, run_id) -> list[dict]:
    out = []
    for n, item in enumerate(sorted(b2_files, key=lambda x: x["path"]), 1):
        leaf = item["content"]
        if cik10(leaf.get("cik")) != cik:
            raise InceptionError("B2 leaf cik differs from its filer: " + item["path"])
        selector = (leaf.get("template") or {}).get("row_selector")
        if selector is not None and not isinstance(selector, dict):
            raise InceptionError("row_selector must be an object, not " + type(selector).__name__ + ": "
                                 + item["path"])
        dates = _b2_dates(leaf)
        out.append(_correction(cik, n, "b2", family="agent_b2_corrections", mechanism=leaf.get("mechanism"),
                               fix_class=leaf.get("fix_class"), dates=dates,
                               target=dict(selector) if selector else {"report_dates": dates},
                               row_keyed=bool(selector and selector.get("row_id")), value=leaf,
                               source=dict(path=item["path"], sha256=item["sha256"], record_index=None),
                               recorded_at=recorded_at, run_id=run_id, author="agent"))
    for name in sorted(shared):
        tag, mechanism = SHARED_MECHANISM[name]
        for n, (index, record) in enumerate(shared[name]["records"], 1):
            if cik10(record.get("cik")) != cik:
                raise InceptionError(name + " record " + str(index) + " belongs to another filer")
            if tag == "aggregate_row":
                target = {k: record.get(k) for k in ("report_date", "accession_number", "match_text", "match_mode")}
                fix = record.get("action")
            else:
                target = {"report_date": record.get("report_date"), "oracle_reason": record.get("oracle_reason")}
                fix = record.get("oracle_reason")
            day = record.get("report_date")
            out.append(_correction(cik, n, tag, family=name, mechanism=mechanism, fix_class=fix,
                                   dates=[day] if day else [], target=target, row_keyed=False, value=record,
                                   source=dict(path=name, sha256=shared[name]["sha256"], record_index=index),
                                   recorded_at=recorded_at, run_id=run_id, author="agent"))
    return mark_recurrence(out)


def _signature(c: dict) -> str:
    if c["family"] == "bdc_aggregate_row_overrides.json":
        return str(c["target"].get("match_text"))
    if c["family"] == "bdc_xbrl_oracle_exceptions.json":
        return str(c["target"].get("oracle_reason"))
    return str(c["fix_class"])


def mark_recurrence(corrections: list[dict]) -> list[dict]:
    """Group one-off corrections by (family, mechanism, signature); flag groups spanning >= 2 report dates.

    Known limitation: for B2 corrections the signature is `fix_class` alone. Two genuinely unrelated
    one-off fixes that happen to share a fix_class (on different rows, different quarters) are grouped
    into one recurrence_group and flagged proposed_recurring_owner_tier. Nothing here promotes them;
    owner sign-off (SP6) must check target/row overlap before treating the group as a real recurrence.
    """
    groups: dict = {}
    for c in corrections:
        if c["kind"] == "one_off":
            groups.setdefault((c["family"], c["mechanism"], _signature(c)), []).append(c)
    for key, members in groups.items():
        if len({m["report_date"] for m in members}) >= 2:
            gid = members[0]["correction_id"].split(":corr:")[0] + ":recur:" + value_sha256(list(key))[:12]
            for m in members:
                m.update(recurrence_group=gid, promotion="proposed_recurring_owner_tier")
    return corrections
