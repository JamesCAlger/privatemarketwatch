"""SP3 proper: regenerate the override shapes from profile documents and prove they equal the originals.

This is the guard that inception cannot change production silently: every converted override file (spec 7.1
dispositions entry / wrapper_block / correction) is rebuilt from the documents and compared with the file read,
order-preserving (dispatch.prefix_rules order is behaviour), and the directory-parameterised production loaders are
run on both trees. Shared files are spliced: non-pilot records stay as read; the pilot records come back from the
corrections at their recorded index and must tile the removed indexes exactly. No file under data/overrides is
written; the CLI writes the materialised tree only under its run root.

Fix round 1 (review on b76a0af) added four load-bearing guarantees this module did not have before:

- I1: `load_and_materialise` reads each document back through `profile_document.load_document` (the
  production reader) before materialising, so a serialisation bug that only shows up after an actual write
  + reread is caught, not just an in-memory one.
- I2: every regenerated path's hash is checked against whatever the document itself recorded for that
  path (`disposition[].ordered_sha256`, wrapper block `content_sha256` / `source_files[].ordered_sha256`)
  -- `materialise_overrides` no longer trusts those recorded hashes, it verifies them.
- I3: `filesystem_expected_paths` answers "what should round-trip for these ciks" from the scanner
  (`profile_families.scan_overrides`), independent of any document. Comparing against THIS, not against
  `expected_paths(documents)` (which is derived from the same documents being checked), is what actually
  catches a document that silently dropped a file it should have converted.
- I4/I5/I6: `roundtrip_check` names the first differing JSON-pointer-ish path for every "differs" result;
  `loader_parity` reports `absent` (not a vacuous match) when neither tree has a family's file for a cik,
  calls the two directory-parameterised production loaders that exist beyond the four already covered
  (`identifier_signature.load_anchors`, `load_bdc_xbrl_oracle_exceptions`), and reads grammars with the
  same plain-utf-8 encoding `pipeline/identifier_rate.py` uses (not `profile_families.read_json`'s
  utf-8-sig), so a BOM-prefixed fixture is flagged rather than silently accepted.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

from scripts.profile_pilot import envelope
from scripts.profile_pilot import profile_document as pd
from scripts.profile_pilot import profile_families as pf
from scripts.profile_pilot.profile_families import REPO_PREFIX, cik10
from scripts.profile_pilot.translate import pointer, value_sha256

CONVERTED_ACTIONS = ("entry", "wrapper_block", "correction")
COMPARISON = ("order-preserving parsed JSON (translate.value_sha256); raw bytes are not compared "
              "(CRLF and indentation are not behaviour)")

ABSENT, MATCH, MISMATCH = "absent", "match", "mismatch"


class RoundTripError(pd.ProfileDocumentError):
    """The documents cannot regenerate the override files unambiguously, or a recorded hash is stale."""


def _hash(value, where) -> str:
    try:
        return value_sha256(value)
    except (TypeError, ValueError) as exc:
        raise RoundTripError(str(where) + ": content is not hashable JSON (" + type(exc).__name__ + ": "
                             + str(exc) + ")") from exc


def _digests(items, where) -> list:
    return sorted(_hash(i, where) for i in items)


# ---------------------------------------------------------------- per-filer (non-shared) files

def _per_filer_files(document: dict) -> dict:
    out = {}
    disposition_hash = {d["path"]: d["ordered_sha256"] for d in document["disposition"]
                        if d.get("ordered_sha256") is not None}

    def put(rel, value):
        if rel in out:
            raise RoundTripError(document["cik"] + " produces " + rel + " twice")
        value = copy.deepcopy(value)
        expected = disposition_hash.get(rel)
        if expected is not None and _hash(value, rel) != expected:
            raise RoundTripError(document["cik"] + " regenerated " + rel + " does not match its recorded "
                                 "disposition ordered_sha256 (I2: the document's own record is stale)")
        out[rel] = value

    for e in envelope.materialize_entries(document["events"]):
        if e["recorded_until"] is not None or e["provenance"] != "inherited":
            continue
        for item in e["evidence"]:
            if item.get("kind") == "override_file" and item.get("value_is_file") is True:
                path = item["path"]
                if not path.startswith(REPO_PREFIX):
                    raise RoundTripError(document["cik"] + " inherited evidence path " + repr(path)
                                         + " is missing the " + REPO_PREFIX + " prefix")
                put(path[len(REPO_PREFIX):], e["value"])
    for b in document["wrapper_section"]["blocks"]:
        if b["recorded_until"] is not None:
            continue
        if _hash(b["content"], b["block_id"]) != b["content_sha256"]:
            raise RoundTripError(document["cik"] + " wrapper block " + b["block_id"] + " content_sha256 is "
                                 "stale (does not match its own recorded content)")
        if b["family"] == "bdc_xbrl_wrapper":
            sf = b["source_files"][0]
            if _hash(b["content"], sf["path"]) != sf["ordered_sha256"]:
                raise RoundTripError(document["cik"] + " wrapper block " + b["block_id"] + " source_files "
                                     "ordered_sha256 is stale")
            put(sf["path"], b["content"])
        elif b["family"] == "agent_investigate_rules":
            by_path = {sf["path"]: sf["ordered_sha256"] for sf in b["source_files"]}
            if sorted(by_path) != sorted(b["content"]["files"]):
                raise RoundTripError(document["cik"] + " wrapper block " + b["block_id"] + " content files do "
                                     "not match its source_files list")
            for rel, rule in b["content"]["files"].items():
                expected = by_path[rel]
                if _hash(rule, rel) != expected:
                    raise RoundTripError(document["cik"] + " wrapper block " + b["block_id"] + " file " + rel
                                         + " source_files ordered_sha256 is stale")
                put(rel, rule)
        else:
            raise RoundTripError(document["cik"] + " unknown wrapper block family " + repr(b["family"]))
    for c in document["corrections"]:
        if c["recorded_until"] is None and c["source"]["record_index"] is None:
            put(c["source"]["path"], c["value"])
    return out


# ---------------------------------------------------------------- shared files (spliced)

def _collect_shared_items(documents) -> dict:
    items = {}
    for doc in documents:
        for c in doc["corrections"]:
            if c["recorded_until"] is None and c["source"]["record_index"] is not None:
                items.setdefault(c["source"]["path"], []).append((c["source"]["record_index"], c["value"]))
    return items


def _shared_disposition_hashes(documents) -> dict:
    out = {}
    for doc in documents:
        for d in doc["disposition"]:
            h = d.get("ordered_sha256")
            if h is None:
                continue
            if d["path"] in out and out[d["path"]] != h:
                raise RoundTripError("conflicting ordered_sha256 recorded for shared file " + d["path"])
            out[d["path"]] = h
    return out


def pilot_record_counts(documents) -> dict:
    """{shared path -> number of pilot records the given documents contribute to it} (M5)."""
    return {name: len(entries) for name, entries in _collect_shared_items(documents).items()}


def _splice(records: list, ciks: set, items: list) -> list:
    kept = {}
    for i, r in enumerate(records):
        if not isinstance(r, dict):
            raise RoundTripError("shared record " + str(i) + " is not an object: " + type(r).__name__)
        if cik10(r.get("cik")) not in ciks:
            kept[i] = r
    removed = set(range(len(records))) - set(kept)
    filled = {}
    for index, record in items:
        if index not in removed:
            if index in kept:
                raise RoundTripError("record index " + str(index) + " belongs to a non-pilot record of "
                                     "the original")
            raise RoundTripError("record index " + str(index) + " is out of range for the original ("
                                 + str(len(records)) + " records)")
        if index in filled:
            raise RoundTripError("record index " + str(index) + " is targeted by more than one correction")
        filled[index] = record
    merged = dict(kept)      # not dict(kept, **filled): the keys are record indexes (ints), not keywords
    merged.update(filled)
    if sorted(merged) != list(range(len(records))):
        raise RoundTripError("pilot records do not tile the original; missing indexes "
                             + repr(sorted(removed - set(filled))[:5]))
    return [copy.deepcopy(merged[i]) for i in range(len(records))]


def materialise_overrides(documents: list, *, shared_originals: dict) -> dict:
    """M2: a malformed document or shared original (missing key, wrong container type, an envelope event
    log that does not replay) is reported as RoundTripError, never as a bare KeyError / TypeError /
    AttributeError / EnvelopeError, so the CLI's ProfileDocumentError mapping (A11) covers it."""
    try:
        return _materialise(documents, shared_originals)
    except RoundTripError:
        raise
    except (KeyError, IndexError, TypeError, AttributeError, envelope.EnvelopeError) as exc:
        raise RoundTripError("malformed document or shared original (" + type(exc).__name__ + ": "
                             + str(exc) + ")") from exc


def _materialise(documents: list, shared_originals: dict) -> dict:
    out = {}
    ciks = {d["cik"] for d in documents}
    for doc in documents:
        for rel, value in _per_filer_files(doc).items():
            if rel in out:
                raise RoundTripError("two documents produce " + rel)
            out[rel] = value
    items = _collect_shared_items(documents)
    shared_hash = _shared_disposition_hashes(documents)
    for name in sorted(shared_originals):
        original = shared_originals[name]
        records = original["overrides"] if isinstance(original, dict) else original
        owned = any(isinstance(r, dict) and cik10(r.get("cik")) in ciks for r in records)
        if name not in items and not owned:
            continue   # M1: this document set has no business with this shared file -- never a false "extra"
        spliced = _splice(records, ciks, items.get(name, []))
        value = dict(original, overrides=spliced) if isinstance(original, dict) else spliced
        expected = shared_hash.get(name)
        if expected is not None and _hash(value, name) != expected:
            raise RoundTripError(name + ": regenerated shared file does not match its recorded "
                                 "ordered_sha256 (I2)")
        out[name] = value
    for name in items:
        if name not in shared_originals:
            raise RoundTripError("no original read for shared file " + name)
    return out


def load_and_materialise(document_paths, *, shared_originals: dict) -> dict:
    """I1: load each path with profile_document.load_document (the production reader) before
    materialising, so a serialisation bug that only shows up after an actual write + reread is caught,
    not just one in the in-memory document build_document returns."""
    docs = [pd.load_document(Path(p)) for p in document_paths]
    return materialise_overrides(docs, shared_originals=shared_originals)


# ---------------------------------------------------------------- expected-path sets

def expected_paths(documents) -> list:
    """Doc-derived: paths the GIVEN documents' own disposition says they convert. Convenient, but a
    document that silently dropped a conversion is invisible to this set -- use
    `filesystem_expected_paths` for the actual loss-detection comparison (I3)."""
    return sorted({d["path"] for doc in documents for d in doc["disposition"] if d["action"] in CONVERTED_ACTIONS})


def filesystem_expected_paths(root, ciks) -> list:
    """I3: independent of any document. What `profile_families.scan_overrides` says SHOULD round-trip for
    `ciks` -- a loaded (is_loaded) file owned by one of `ciks`, or a SHARED_FILES path any of `ciks` is
    mentioned in. A document whose build silently dropped a convertible file still shows up here, which is
    the point: compare materialised output against an `originals` dict built from THIS set, not from
    `expected_paths(documents)` (derived from the same documents under test)."""
    wanted = {cik10(c) for c in ciks}
    hits = pf.scan_overrides(Path(root), wanted)
    out = set()
    for hit in hits:
        if hit["action"] not in CONVERTED_ACTIONS:
            continue
        if hit["path"] in pf.SHARED_FILES:
            if set(hit["ciks"]) & wanted:
                out.add(hit["path"])
        elif hit["owner"] in wanted:
            out.add(hit["path"])
    return sorted(out)


# ---------------------------------------------------------------- comparison with pinpointing (I4)

def _same_scalar(a, b) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return type(a) is type(b) and a == b
    return a == b


def _at(path) -> str:
    """translate.pointer renders the document root as "" (RFC 6901); in a message that reads as a missing
    location, so the root is shown as "/" here. Every non-root pointer is unchanged."""
    return pointer(path) or "/"


def _first_difference(a, b, path=()):
    if isinstance(a, dict) and isinstance(b, dict):
        if list(a) != list(b):
            only_a = [k for k in a if k not in b]
            only_b = [k for k in b if k not in a]
            if only_a or only_b:
                k = (only_a or only_b)[0]
                return pointer(path + (k,)) + " present on only one side"
            return _at(path) + " key order differs"
        for k in a:
            d = _first_difference(a[k], b[k], path + (k,))
            if d:
                return d
        return None
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return _at(path) + " length differs (" + str(len(a)) + " vs " + str(len(b)) + ")"
        for i, (x, y) in enumerate(zip(a, b)):
            d = _first_difference(x, y, path + (i,))
            if d:
                return d
        return None
    if isinstance(a, dict) != isinstance(b, dict) or isinstance(a, list) != isinstance(b, list):
        return _at(path) + " type differs"
    if not _same_scalar(a, b):
        return _at(path) + " value differs (" + repr(a) + " vs " + repr(b) + ")"
    return None


def roundtrip_check(materialised: dict, originals: dict) -> dict:
    files, first_difference = {}, {}
    for rel in sorted(set(materialised) | set(originals)):
        if rel not in materialised:
            files[rel] = "missing"
        elif rel not in originals:
            files[rel] = "extra"
        else:
            same = _hash(materialised[rel], rel) == _hash(originals[rel], rel)
            files[rel] = "identical" if same else "differs"
            if not same:
                first_difference[rel] = (_first_difference(materialised[rel], originals[rel])
                                         or "(hashes differ but no pointer was found)")
    counts = {s: sum(v == s for v in files.values()) for s in ("identical", "differs", "missing", "extra")}
    return dict(ok=bool(files) and counts["identical"] == len(files), counts=counts, files=files,
                comparison=COMPARISON, first_difference=first_difference)


# ---------------------------------------------------------------- production-loader parity (I5/I6)

def _read_utf8_json(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _anchor_signature(value) -> list:
    return [[label, regex.pattern] for label, regex in value]


def _tally(status_values) -> dict:
    out = {"match": 0, "mismatch": 0, "absent": 0, "error": 0}
    for v in status_values:
        out[v if v in (MATCH, MISMATCH, ABSENT) else "error"] += 1
    return out


def _family_ok(status_values) -> bool:
    return all(v in (MATCH, ABSENT) for v in status_values)


def loader_parity(original_root, materialised_root, ciks) -> dict:
    from pipeline import agent_promoted, identifier_signature, rate_convention
    from pipeline.bdc_xbrl_oracle_exceptions import load_bdc_xbrl_oracle_exceptions
    from scripts.profile_pilot import translate
    original_root, materialised_root = Path(original_root), Path(materialised_root)
    ciks = sorted(cik10(c) for c in ciks)

    # --- bdc_xbrl_wrappers: the production loader's dispatch spec only ---
    wrappers = translate.admit_directory(materialised_root / "bdc_xbrl_wrappers", ciks,
                                         base_dir=original_root / "bdc_xbrl_wrappers")
    wrapper_status = {}
    for c in ciks:
        o_file = original_root / "bdc_xbrl_wrappers" / (c + ".json")
        m_file = materialised_root / "bdc_xbrl_wrappers" / (c + ".json")
        if not o_file.is_file() and not m_file.is_file():
            wrapper_status[c] = ABSENT
        elif not o_file.is_file() or not m_file.is_file():
            wrapper_status[c] = MISMATCH
        else:
            v = wrappers["ciks"].get(c, {})
            wrapper_status[c] = (MATCH if bool(v.get("admitted")) and (v.get("spec_parity") or {}).get("equal")
                                 is True else MISMATCH)

    # --- agent_b2_corrections: pooled, the loader is not cik-keyed ---
    orig_b2_all = agent_promoted.load_promoted_corrections(original_root / "agent_b2_corrections")
    mat_b2_all = agent_promoted.load_promoted_corrections(materialised_root / "agent_b2_corrections")
    orig_b2 = [leaf for leaf in orig_b2_all if cik10(leaf.get("cik")) in ciks]
    mat_b2 = [leaf for leaf in mat_b2_all if cik10(leaf.get("cik")) in ciks]
    if not orig_b2 and not mat_b2:
        b2_status = ABSENT
    else:
        b2_status = (MATCH if _digests(orig_b2, "agent_b2_corrections") == _digests(mat_b2, "agent_b2_corrections")
                     else MISMATCH)
    b2 = dict(status=b2_status, compared=len(orig_b2))

    # --- agent_investigate_rules ---
    orig_rules = agent_promoted.load_promoted_rules(original_root / "agent_investigate_rules")
    mat_rules = agent_promoted.load_promoted_rules(materialised_root / "agent_investigate_rules")
    rules_status = {}
    for c in ciks:
        o, m = orig_rules.get(c, []), mat_rules.get(c, [])
        if not o and not m:
            rules_status[c] = ABSENT
        else:
            rules_status[c] = (MATCH if _digests(o, "agent_investigate_rules/" + c)
                               == _digests(m, "agent_investigate_rules/" + c) else MISMATCH)

    # --- rate_convention ---
    orig_conv = rate_convention.load_convention_overrides(original_root / "rate_convention")
    mat_conv = rate_convention.load_convention_overrides(materialised_root / "rate_convention")
    conv_status = {}
    for c in ciks:
        key = str(int(c))
        o, m = orig_conv.get(key), mat_conv.get(key)
        if o is None and m is None:
            conv_status[c] = ABSENT
        else:
            conv_status[c] = MATCH if _hash(o, "rate_convention/" + c) == _hash(m, "rate_convention/" + c) else MISMATCH

    # --- identifier_anchors: identifier_signature.load_anchors (I5), plain utf-8 inside it (I6) ---
    anchor_status = {}
    for c in ciks:
        o_file = original_root / "identifier_anchors" / (c + ".json")
        m_file = materialised_root / "identifier_anchors" / (c + ".json")
        if not o_file.is_file() and not m_file.is_file():
            anchor_status[c] = ABSENT
            continue
        try:
            o_val = identifier_signature.load_anchors(c, anchor_dir=original_root / "identifier_anchors")
            m_val = identifier_signature.load_anchors(c, anchor_dir=materialised_root / "identifier_anchors")
            anchor_status[c] = (MATCH if _hash(_anchor_signature(o_val), "identifier_anchors/" + c)
                                == _hash(_anchor_signature(m_val), "identifier_anchors/" + c) else MISMATCH)
        except (OSError, ValueError, UnicodeDecodeError, KeyError) as exc:
            anchor_status[c] = "error:" + type(exc).__name__

    # --- identifier_rate_grammars: no directory-parameterised loader exists; read with the production
    #     encoding (plain utf-8, pipeline/identifier_rate.py load_grammar) so a BOM is flagged, not
    #     silently absorbed the way profile_families.read_json's utf-8-sig would absorb it (I6) ---
    grammar_status = {}
    for c in ciks:
        o_file = original_root / "identifier_rate_grammars" / (c + ".json")
        m_file = materialised_root / "identifier_rate_grammars" / (c + ".json")
        if not o_file.is_file() and not m_file.is_file():
            grammar_status[c] = ABSENT
            continue
        try:
            o_val = _read_utf8_json(o_file) if o_file.is_file() else None
            m_val = _read_utf8_json(m_file) if m_file.is_file() else None
            grammar_status[c] = (MATCH if _hash(o_val, "identifier_rate_grammars/" + c)
                                 == _hash(m_val, "identifier_rate_grammars/" + c) else MISMATCH)
        except (OSError, ValueError, UnicodeDecodeError) as exc:
            grammar_status[c] = "error:" + type(exc).__name__

    # --- bdc_xbrl_oracle_exceptions.json: path-parameterised loader (I5) ---
    o_oracle = original_root / "bdc_xbrl_oracle_exceptions.json"
    m_oracle = materialised_root / "bdc_xbrl_oracle_exceptions.json"
    if not o_oracle.is_file() and not m_oracle.is_file():
        oracle_status = ABSENT
    else:
        try:
            o_rows = _digests(load_bdc_xbrl_oracle_exceptions(path=o_oracle).to_dict("records"),
                              "bdc_xbrl_oracle_exceptions.json")
            m_rows = _digests(load_bdc_xbrl_oracle_exceptions(path=m_oracle).to_dict("records"),
                              "bdc_xbrl_oracle_exceptions.json")
            oracle_status = MATCH if o_rows == m_rows else MISMATCH
        except Exception as exc:   # the loader aborts loudly on a malformed active record
            oracle_status = "error:" + type(exc).__name__

    out = dict(
        bdc_xbrl_wrappers=wrapper_status, agent_b2_corrections=b2, agent_investigate_rules=rules_status,
        rate_convention=conv_status, identifier_anchors=anchor_status, identifier_rate_grammars=grammar_status,
        bdc_xbrl_oracle_exceptions=dict(status=oracle_status),
        counts=dict(bdc_xbrl_wrappers=_tally(wrapper_status.values()),
                   agent_investigate_rules=_tally(rules_status.values()),
                   rate_convention=_tally(conv_status.values()),
                   identifier_anchors=_tally(anchor_status.values()),
                   identifier_rate_grammars=_tally(grammar_status.values())),
        wrapper_scope_note=("bdc_xbrl_wrappers parity covers the production loader's dispatch spec only "
                            "(pipeline.bdc_xbrl_wrapper's _load_specs_from_json via translate.admit_directory); "
                            "other readers of the same wrapper JSON (e.g. the oracle module, html bridges) "
                            "are not invoked here"),
        not_loader_checked=["bdc_aggregate_row_overrides.json"],
        note=("bdc_aggregate_row_overrides.json has no directory- or path-parameterised production loader "
              "and is covered only by the order-preserving file round trip (roundtrip_check); "
              "identifier_rate_grammars has no such loader either, but is read here with the production "
              "encoding (plain utf-8, pipeline/identifier_rate.py) rather than profile_families.read_json's "
              "utf-8-sig, so a BOM-prefixed file is flagged rather than silently accepted (I6)"))
    out["ok"] = (_family_ok(wrapper_status.values()) and _family_ok([b2["status"]])
                and _family_ok(rules_status.values()) and _family_ok(conv_status.values())
                and _family_ok(anchor_status.values()) and _family_ok(grammar_status.values())
                and _family_ok([oracle_status]))
    return out
