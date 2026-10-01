"""SP3 proper: regenerate the override shapes from profile documents and prove they equal the originals.

This is the guard that inception cannot change production silently: every converted override file (spec 7.1
dispositions entry / wrapper_block / correction) is rebuilt from the documents and compared with the file read,
order-preserving (dispatch.prefix_rules order is behaviour), and the directory-parameterised production loaders are
run on both trees. Shared files are spliced: non-pilot records stay as read; the pilot records come back from the
corrections at their recorded index and must tile the removed indexes exactly. No file under data/overrides is
written; the CLI writes the materialised tree only under its run root.
"""
from __future__ import annotations

import copy
from pathlib import Path

from scripts.profile_pilot import envelope
from scripts.profile_pilot.profile_families import REPO_PREFIX, cik10
from scripts.profile_pilot.translate import value_sha256

CONVERTED_ACTIONS = ("entry", "wrapper_block", "correction")
COMPARISON = ("order-preserving parsed JSON (translate.value_sha256); raw bytes are not compared "
              "(CRLF and indentation are not behaviour)")


class RoundTripError(ValueError):
    """The documents cannot regenerate the override files unambiguously."""


def _per_filer_files(document: dict) -> dict:
    out = {}

    def put(rel, value):
        if rel in out:
            raise RoundTripError(document["cik"] + " produces " + rel + " twice")
        out[rel] = copy.deepcopy(value)

    for e in envelope.materialize_entries(document["events"]):
        if e["recorded_until"] is not None or e["provenance"] != "inherited":
            continue
        for item in e["evidence"]:
            if item.get("kind") == "override_file" and item.get("value_is_file") is True:
                put(item["path"][len(REPO_PREFIX):], e["value"])
    for b in document["wrapper_section"]["blocks"]:
        if b["recorded_until"] is not None:
            continue
        if b["family"] == "bdc_xbrl_wrapper":
            put(b["source_files"][0]["path"], b["content"])
        else:
            for rel, rule in b["content"]["files"].items():
                put(rel, rule)
    for c in document["corrections"]:
        if c["recorded_until"] is None and c["source"]["record_index"] is None:
            put(c["source"]["path"], c["value"])
    return out


def _splice(records: list, ciks: set, items: list) -> list:
    keep = {i: r for i, r in enumerate(records) if cik10(r.get("cik")) not in ciks}
    for index, record in items:
        if index in keep:
            raise RoundTripError("record index " + str(index) + " is not a pilot record of the original")
        keep[index] = record
    if sorted(keep) != list(range(len(records))):
        raise RoundTripError("pilot records do not tile the original; missing indexes "
                             + repr(sorted(set(range(len(records))) - set(keep))[:5]))
    return [copy.deepcopy(keep[i]) for i in range(len(records))]


def materialise_overrides(documents: list, *, shared_originals: dict) -> dict:
    out, items = {}, {}
    ciks = {d["cik"] for d in documents}
    for doc in documents:
        for rel, value in _per_filer_files(doc).items():
            if rel in out:
                raise RoundTripError("two documents produce " + rel)
            out[rel] = value
        for c in doc["corrections"]:
            if c["recorded_until"] is None and c["source"]["record_index"] is not None:
                items.setdefault(c["source"]["path"], []).append((c["source"]["record_index"], c["value"]))
    for name in sorted(set(items) | set(shared_originals)):
        if name not in shared_originals:
            raise RoundTripError("no original read for shared file " + name)
        original = shared_originals[name]
        records = original["overrides"] if isinstance(original, dict) else original
        spliced = _splice(records, ciks, items.get(name, []))
        out[name] = dict(original, overrides=spliced) if isinstance(original, dict) else spliced
    return out


def expected_paths(documents) -> list:
    return sorted({d["path"] for doc in documents for d in doc["disposition"] if d["action"] in CONVERTED_ACTIONS})


def roundtrip_check(materialised: dict, originals: dict) -> dict:
    files = {}
    for rel in sorted(set(materialised) | set(originals)):
        if rel not in materialised:
            files[rel] = "missing"
        elif rel not in originals:
            files[rel] = "extra"
        else:
            same = value_sha256(materialised[rel]) == value_sha256(originals[rel])
            files[rel] = "identical" if same else "differs"
    counts = {s: sum(v == s for v in files.values()) for s in ("identical", "differs", "missing", "extra")}
    return dict(ok=bool(files) and counts["identical"] == len(files), counts=counts, files=files,
                comparison=COMPARISON)


def _digests(items) -> list:
    return sorted(value_sha256(i) for i in items)


def loader_parity(original_root, materialised_root, ciks) -> dict:
    from pipeline import agent_promoted, rate_convention
    from scripts.profile_pilot import translate
    original_root, materialised_root = Path(original_root), Path(materialised_root)
    ciks = sorted(cik10(c) for c in ciks)
    out = {}
    wrappers = translate.admit_directory(materialised_root / "bdc_xbrl_wrappers", ciks,
                                         base_dir=original_root / "bdc_xbrl_wrappers")
    out["bdc_xbrl_wrappers"] = {
        c: bool(v.get("admitted")) and (v.get("spec_parity") or {}).get("equal") is True
        for c, v in wrappers["ciks"].items() if (original_root / "bdc_xbrl_wrappers" / (c + ".json")).is_file()}
    orig = [leaf for leaf in agent_promoted.load_promoted_corrections(original_root / "agent_b2_corrections")
            if cik10(leaf.get("cik")) in ciks]
    mat = agent_promoted.load_promoted_corrections(materialised_root / "agent_b2_corrections")
    out["agent_b2_corrections"] = _digests(orig) == _digests(mat)
    orig_rules = agent_promoted.load_promoted_rules(original_root / "agent_investigate_rules")
    mat_rules = agent_promoted.load_promoted_rules(materialised_root / "agent_investigate_rules")
    out["agent_investigate_rules"] = {c: _digests(orig_rules.get(c, [])) == _digests(mat_rules.get(c, []))
                                      for c in ciks}
    orig_conv = rate_convention.load_convention_overrides(original_root / "rate_convention")
    mat_conv = rate_convention.load_convention_overrides(materialised_root / "rate_convention")
    out["rate_convention"] = {c: value_sha256(orig_conv.get(str(int(c)))) == value_sha256(mat_conv.get(str(int(c))))
                              for c in ciks}
    flat = [v for v in out.values() if isinstance(v, bool)]
    flat += [x for v in out.values() if isinstance(v, dict) for x in v.values()]
    out["ok"] = all(flat)
    out["not_loader_checked"] = ["identifier_rate_grammars", "identifier_anchors",
                                 "bdc_aggregate_row_overrides.json", "bdc_xbrl_oracle_exceptions.json"]
    out["note"] = ("families without a directory-parameterised production loader are covered by the "
                   "order-preserving file round trip only")
    return out
