"""SP3 proper: the spec 7.1 override-family disposition table and the scanner that applies it.

scan_overrides walks <root> (a data/overrides directory), finds every file that mentions a pilot CIK (path segment or
content: JSON strings and "cik" values, never other JSON numbers; non-JSON text line by line) and classifies it by the
table. It FAILS CLOSED: a mentioning file in a family without a class, or in a family that must not mention a pilot
filer, raises FamilyError (7.1: "a family added later without a class fails"). Process-artifact files above
MAX_SCAN_BYTES are never content-scanned (position_id_registry/registry.csv is ~112 MB); any other family above the
cap raises. Because an oversize file's absence of a mention cannot be proven, it is conservatively recorded as
mentioning every filer the scan was asked about, with its own disposition row of `not_loaded` and its size noted in
`reason`, instead of the family's normal action (pre-flight ruling A13). Paths with an underscore-prefixed segment
after the family, or a `.proposed.` file name, are
`not_loaded` (production skips them: pipeline/rule_admission.admitted, agent_promoted.load_promoted_rules).
Read-only; files are read as production reads them (utf-8-sig).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from scripts.profile_pilot.translate import value_sha256

REPO_PREFIX = "data/overrides/"
CLASSES = ("knowledge", "executable", "process_artifact", "not_applicable")
ACTIONS = ("entry", "correction", "wrapper_block", "excluded", "not_loaded", "foreign_mention")
SHARED_FILES = ("bdc_aggregate_row_overrides.json", "bdc_xbrl_oracle_exceptions.json")
MAX_SCAN_BYTES = 20_000_000
NOT_LOADED_REASON = ("production loaders skip underscore-prefixed or .proposed. paths "
                     "(pipeline/rule_admission.admitted)")
_NA = ("no pilot filer present (spec 7.1); classified when a filer that uses it enters the cohort")
FAMILY_CLASSES = {
    "rate_convention": dict(cls="knowledge", action="entry", reason="source of the meaning.interest_rate entry"),
    "identifier_rate_grammars": dict(cls="knowledge", action="entry",
                                     reason="source of the identifier_format.dialect entry"),
    "identifier_anchors": dict(cls="knowledge", action="entry",
                               reason="source of the identifier_format.anchors entry (same axis as grammars)"),
    "bdc_aggregate_row_overrides.json": dict(cls="knowledge", action="correction",
                                             reason="point-dated subtotal exclusions -> one-off corrections (P5)"),
    "bdc_xbrl_oracle_exceptions.json": dict(cls="knowledge", action="correction",
                                            reason="point-dated reconciliation-scope exceptions -> one-off corrections (P5)"),
    "agent_b2_corrections": dict(cls="knowledge", action="correction", reason="spec 4.2 corrections"),
    "identifier_spread_corrections.json": dict(cls="knowledge", action="must_be_absent",
                                               reason="gated off 2026-09-29 (e379e8a); retired per spec section 7"),
    "bdc_xbrl_wrappers": dict(cls="executable", action="wrapper_block", reason="wrapper section block (D-consolidate)"),
    "agent_investigate_rules": dict(cls="executable", action="wrapper_block",
                                    reason="second wrapper block (spec 7.1; P6)"),
    "agent_anchor": dict(cls="process_artifact", action="excluded",
                         reason="fleet output, regenerated per pass, not knowledge (spec 7.1)"),
    "wrapper_cohorts": dict(cls="process_artifact", action="excluded",
                            reason="cohort membership manifest, not per-filer semantics (spec 7.1)"),
    "position_id_registry": dict(cls="process_artifact", action="excluded",
                                 reason="opt-in matching state, read only by the row-continuity detector (spec 7.1)"),
    "enforcement_registry": dict(cls="not_applicable", action="must_be_absent", reason=_NA),
    "bdc_xbrl_html_section_bridges": dict(cls="not_applicable", action="must_be_absent", reason=_NA),
    "fund_highlights_wrappers": dict(cls="not_applicable", action="must_be_absent", reason=_NA),
    "row_corrections.csv": dict(cls="not_applicable", action="must_be_absent", reason=_NA),
    "entity_overrides.json": dict(cls="not_applicable", action="must_be_absent", reason=_NA),
}
FILE_CLASSES = {
    "bdc_xbrl_wrappers/unlisted_bdc_xbrl_reference.json": dict(
        cls="process_artifact", action="excluded",
        reason="SP3 classification (not in spec 7.1): unlisted-BDC reference listing for frontend filtering "
               "(config.UNLISTED_BDC_REFERENCE_FILE), not per-filer semantics; owner to confirm"),
}
_DIGITS = re.compile(r"\d{6,10}")


class FamilyError(ValueError):
    """An override file mentions a pilot filer in a family the disposition table does not allow."""


def cik10(value) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text.zfill(10) if text.isdigit() and len(text) <= 10 else None


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def raw_sha256(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def family_of(relative: str) -> str:
    return relative.split("/", 1)[0]


def owner_cik(relative: str) -> str | None:
    parts = relative.split("/")
    if len(parts) == 1:
        return None
    for part in parts[1:-1] + [parts[-1].rsplit(".", 1)[0]]:
        if _DIGITS.fullmatch(part):
            return part.zfill(10)
    return None


def is_loaded(relative: str) -> bool:
    parts = relative.split("/")
    return not any(p.startswith("_") for p in parts[1:]) and ".proposed." not in parts[-1].lower()


def classify_path(relative: str) -> dict | None:
    if relative in FILE_CLASSES:
        return FILE_CLASSES[relative]
    family = family_of(relative)
    if family in FAMILY_CLASSES:
        return FAMILY_CLASSES[family]
    if family.startswith("_"):
        return dict(cls="process_artifact", action="not_loaded", reason="retired store (underscore-prefixed family)")
    return None


def _patterns(ciks) -> dict:
    return {c: re.compile(r"(?<![0-9])0*" + str(int(c)) + r"(?![0-9])") for c in ciks}


def _strings(value, key=None):
    if isinstance(value, dict):
        for k, v in value.items():
            yield str(k)
            yield from _strings(v, k)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v, key)
    elif isinstance(value, str):
        yield value
    elif key == "cik" and isinstance(value, int) and not isinstance(value, bool):
        yield str(value)


def _content_mentions(path: Path, patterns: dict) -> set:
    found = set()
    if path.suffix.lower() == ".json":
        try:
            texts = _strings(read_json(path))
        except (ValueError, UnicodeDecodeError):
            texts = [path.read_text(encoding="utf-8-sig", errors="replace")]
        for text in texts:
            found |= {c for c, pat in patterns.items() if c not in found and pat.search(text)}
        return found
    with open(path, encoding="utf-8-sig", errors="replace") as stream:
        for line in stream:
            found |= {c for c, pat in patterns.items() if c not in found and pat.search(line)}
    return found


def scan_overrides(root: Path, ciks) -> list[dict]:
    root = Path(root)
    patterns = _patterns([cik10(c) for c in ciks])
    hits = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root).as_posix()
        spec = classify_path(rel)
        mentioned = {c for c, pat in patterns.items() if pat.search(rel)}
        oversize = path.stat().st_size > MAX_SCAN_BYTES
        if oversize:
            if spec is None or spec["cls"] != "process_artifact":
                raise FamilyError("file above MAX_SCAN_BYTES outside a process-artifact family: " + rel)
            # A13: content is never read (too large to scan), so absence cannot be proven. Record it
            # conservatively for every filer this scan was asked about, rather than let it go silent.
            mentioned = set(patterns)
        else:
            mentioned |= _content_mentions(path, patterns)
        if not mentioned:
            continue
        if spec is None:
            raise FamilyError("unclassified override family with pilot filer mentions: " + rel
                              + " (" + ", ".join(sorted(mentioned)) + ")")
        if spec["action"] == "must_be_absent":
            raise FamilyError(rel + " must not mention a pilot filer (" + spec["reason"] + "): "
                              + ", ".join(sorted(mentioned)))
        loaded = is_loaded(rel)
        if oversize:
            # A13: content was never read and absence cannot be proven, so this file never earns the
            # family's normal action -- it is always not_loaded, with its size recorded for the record
            # (a sibling file in the same family below the cap still gets the family's ordinary action).
            action = "not_loaded"
            reason = ("file above MAX_SCAN_BYTES (" + str(path.stat().st_size) + " bytes); content never "
                      "read, recorded conservatively for every filer this scan was asked about: " + spec["reason"])
        else:
            action = spec["action"] if loaded else "not_loaded"
            reason = spec["reason"] if loaded else NOT_LOADED_REASON
        hits.append(dict(path=rel, family=family_of(rel), cls=spec["cls"], action=action, ciks=sorted(mentioned),
                         owner=owner_cik(rel), reason=reason))
    return hits


def collect_override_inputs(root: Path, cik: str, hits: list[dict]) -> dict:
    root, cik = Path(root), cik10(cik)
    files, shared, disposition = {}, {}, []
    for hit in hits:
        if cik not in hit["ciks"]:
            continue
        rel = hit["path"]
        record = dict(path=rel, family=hit["family"], cls=hit["cls"], action=hit["action"],
                      sha256=raw_sha256(root / rel), ordered_sha256=None, targets=[], reason=hit["reason"],
                      record_indexes=None)
        if hit["action"] in ("excluded", "not_loaded"):
            disposition.append(record)
            continue
        if hit["owner"] not in (None, cik):
            disposition.append(dict(record, action="foreign_mention",
                                    reason="file belongs to filer " + hit["owner"] + "; mention recorded, not converted"))
            continue
        content = read_json(root / rel)
        record["ordered_sha256"] = value_sha256(content)
        if rel in SHARED_FILES:
            records = content["overrides"] if isinstance(content, dict) else content
            items = [[i, r] for i, r in enumerate(records) if cik10(r.get("cik")) == cik]
            if not items:   # mentioned only inside another filer's record (e.g. an accession in evidence text)
                disposition.append(dict(record, action="foreign_mention",
                                        reason="mentioned outside any record whose cik is this filer"))
                continue
            shared[rel] = dict(sha256=record["sha256"], records=items)
            record["record_indexes"] = [i for i, _ in items]
        else:
            files.setdefault(hit["family"], []).append(dict(path=rel, sha256=record["sha256"], content=content))
        disposition.append(record)
    return dict(files=files, shared=shared, disposition=disposition)
