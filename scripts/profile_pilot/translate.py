"""Task 7: filer profile -> production wrapper v3 adapter (a measurement artifact, never promoted).

`to_wrapper_v3(profile, base_wrapper, report_date, form_type)` writes into a copy of the
base wrapper ONLY the fields the production wrapper schema can express, each from one
profile entry resolved for (report_date, form_type) on both clocks through the Task 2
envelope (`materialize_entries` + `resolve_for_row`; precedence is never re-implemented).

What the wrapper cannot express is recorded, never flattened or dropped:
  - mixed_partition: an entry for the key carries a non-null `applies_to` (a flat wrapper
    field cannot hold a partition-specific value, and writing the null-partition value
    would flatten the partition);
  - form_specific: an entry for the key carries a `form_type` (wrapper v3 has no form
    qualifier; the value would leak to every other form);
  - presentation_view_declaration: any `presentation_views.*` entry;
  - no_wrapper_representation: a value the translation vocabulary cannot map.
In every such case the base value stays and is listed in the inherited overlay.

Every generated field NOT set from a profile entry is an inherited-overlay field (JSON
pointer + sha256 of its order-preserving JSON). Coverage = profile-driven fields / all
generated fields, reported beside parity with the base wrapper, so a mostly copied wrapper
cannot look like a replacement. Pilot metadata lives only in the sidecar; unknown wrapper
keys are refused (UnknownWrapperKeyError).

Loader admission runs the production `_load_specs_from_json(directory)` inside
`restored_wrapper_context()`, which snapshots and restores the loader module's state.
Field granularity: a field is a path to a non-object value (lists are atomic).
"""
from __future__ import annotations

from contextlib import contextmanager
import copy
from dataclasses import dataclass, field
import hashlib
import json
import logging
from pathlib import Path

from scripts.profile_pilot import envelope, m1
from scripts.profile_pilot.paths import PathError, PilotPaths, confined, write_once_json

TRANSLATE_VERSION = "translate.v0"
SIDECAR_SCHEMA = "profile_wrapper_sidecar_v0"
CODE_ROOT = Path(__file__).resolve().parents[2]
WRAPPER_SCHEMA_RELATIVE = "schemas/bdc_xbrl_wrapper/wrapper_v3.schema.json"
LOADER_RELATIVE = "pipeline/bdc_xbrl_wrapper.py"
ERAS = ("q1", "same_era")
DISCLAIMER = ("Generated wrappers are measurement artifacts: never promoted, never written under "
              "data/overrides/. Coverage counts fields set from profile entries; it is not evidence "
              "that the profile or the generated wrapper is correct.")
# Wrapper field <- profile key. Kept in agreement with m1.FAMILIES profile_key (tested).
TRANSLATIONS = (
    dict(wrapper_path=("cik",), profile_key="fund_level_concepts.entity_cik", convert="cik10"),
    dict(wrapper_path=("entity_name",), profile_key="fund_level_concepts.entity_registrant_name",
         convert="text"),
    dict(wrapper_path=("identifier_format", "delimiter"), profile_key="identifier_format.delimiter",
         convert="text"),
    dict(wrapper_path=("identifier_format", "alternate_delimiters"),
         profile_key="identifier_format.alternate_delimiters", convert="string_list"),
    dict(wrapper_path=("identifier_format", "field_order"), profile_key="identifier_format.field_order",
         convert="string_list"),
    dict(wrapper_path=("dispatch", "aggregate_markers"), profile_key="subtotals_and_headings.aggregate_labels",
         convert="lower_string_list"),
    dict(wrapper_path=("dispatch", "non_private_markers"),
         profile_key="subtotals_and_headings.non_private_markers", convert="lower_string_list"),
    dict(wrapper_path=("dispatch", "prefix_rules"), profile_key="subtotals_and_headings.prefix_rules",
         convert="ordered_pairs"),
    dict(wrapper_path=("invariants", "fv_reconciliation", "source_field"),
         profile_key="fund_level_concepts.investments_at_fair_value_concept", convert="concept_to_field"),
)
BY_PROFILE_KEY = {t["profile_key"]: t for t in TRANSLATIONS}
VIEW_SECTIONS = ("presentation_views",)


class TranslateError(ValueError):
    """The profile or base wrapper cannot be translated as supplied."""


class UnknownWrapperKeyError(TranslateError):
    """The generated wrapper would carry a key the production schema does not define."""


# ---------------------------------------------------------------- small helpers

def value_sha256(value) -> str:
    """Order-preserving: object key order is behaviour for prefix_rules (first match wins)."""
    text = json.dumps(value, ensure_ascii=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(text.encode("ascii")).hexdigest()


def pointer(path) -> str:
    return "".join("/" + str(p).replace("~", "~0").replace("/", "~1") for p in path)


def fields(value, path=()) -> dict:
    """pointer -> value for every path to a non-object value (non-empty objects are walked)."""
    if isinstance(value, dict) and value:
        out = {}
        for key, child in value.items():
            out.update(fields(child, path + (key,)))
        return out
    return {pointer(path): value}


def _get(wrapper: dict, path):
    node = wrapper
    for part in path:
        if not isinstance(node, dict) or part not in node:
            return False, None
        node = node[part]
    return True, node


def _set(wrapper: dict, path, value) -> None:
    node = wrapper
    for part in path[:-1]:
        node = node.setdefault(part, {})
    node[path[-1]] = value


def _wrapper_schema() -> dict:
    return json.loads((CODE_ROOT / WRAPPER_SCHEMA_RELATIVE).read_text(encoding="utf-8"))


def schema_verdict(wrapper: dict) -> dict:
    """Validate against the production schema; unknown keys raise, other failures are recorded."""
    import jsonschema
    validator = jsonschema.Draft202012Validator(_wrapper_schema())
    errors = sorted(validator.iter_errors(wrapper), key=lambda e: list(e.absolute_path))
    unknown = [e for e in errors if e.validator == "additionalProperties"]
    if unknown:
        raise UnknownWrapperKeyError("generated wrapper carries keys outside wrapper v3: "
                                     + "; ".join(pointer(e.absolute_path) + ": " + e.message for e in unknown))
    return dict(verdict="pass" if not errors else "fail",
                errors=[pointer(e.absolute_path) + ": " + e.message for e in errors])


# ---------------------------------------------------------------- value conversion

def _convert(spec: dict, value):
    """(converted, via, detail) or (None, None, reason) when the wrapper cannot represent it."""
    kind = spec["convert"]
    if kind == "cik10":
        ok = isinstance(value, str) and value.isdigit() and len(value) <= 10
        return (value.zfill(10), "direct", None) if ok else (None, None, "not a CIK string")
    if kind == "text":
        return (value, "direct", None) if isinstance(value, str) and value else (None, None, "not text")
    if kind in ("string_list", "lower_string_list"):
        if not (isinstance(value, list) and all(isinstance(v, str) and v for v in value)):
            return None, None, "not a list of strings"
        return ([v.lower() for v in value] if kind == "lower_string_list" else list(value)), "direct", None
    if kind == "ordered_pairs":
        ok = isinstance(value, list) and all(isinstance(p, list) and len(p) == 2 and all(isinstance(x, str) for x in p)
                                             for p in value)
        if not ok or len({p[0] for p in value}) != len(value):
            return None, None, "not ordered distinct [prefix, family] pairs"
        return {p[0]: p[1] for p in value}, "direct", None
    if kind == "concept_to_field":
        table = m1.EQUIVALENCE[".".join(spec["wrapper_path"])]
        local = value.split(":", 1)[-1] if isinstance(value, str) else None
        hits = [f for f, concepts in table["mapping"].items() if local in concepts]
        if len(hits) != 1:
            return None, None, "concept " + repr(value) + " not in the inherited equivalence table"
        return hits[0], "inherited_equivalence", table["source"]
    raise TranslateError("unknown converter " + repr(kind))


# ---------------------------------------------------------------- resolution (Task 2 only)

def _applicable(entry: dict, report_date: str, as_of) -> bool:
    """Valid-time and transaction-time applicability, via the Task 2 resolver.

    The probe neutralises applies_to and form_type so this asks only "does the entry apply
    at (report_date, as_of)"; partition and form are then judged for expressibility.
    """
    probe = dict(entry, applies_to=None, form_type=None)
    return envelope.resolve_for_row([probe], {}, entry["key"], report_date, None, as_of).found


def _resolve(entries: list, key: str, report_date: str, form_type, as_of) -> dict:
    live = [e for e in entries if e["key"] == key and _applicable(e, report_date, as_of)]
    if not live:
        return dict(status="no_entry")
    reasons = []
    if any(e["applies_to"] is not None for e in live):
        reasons.append("mixed_partition")
    if any(e["form_type"] is not None for e in live):
        reasons.append("form_specific")
    if key.split(".", 1)[0] in VIEW_SECTIONS:
        reasons.append("presentation_view_declaration")
    if reasons:
        return dict(status="not_expressible", reasons=reasons, entries=live)
    try:
        found = envelope.resolve_for_row(live, {}, key, report_date, form_type, as_of)
    except envelope.AmbiguousResolutionError as exc:
        raise TranslateError(str(exc)) from exc
    return dict(status="resolved", entry=found.entry, entries=live)


# ---------------------------------------------------------------- the adapter

def _canonical(value) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"))


def _entries(profile: dict, as_of) -> list:
    entries = envelope.materialize_entries(profile["events"], as_of)
    if as_of is None and "entries" in profile and sorted(map(_canonical, entries)) != sorted(
            map(_canonical, profile["entries"])):
        raise TranslateError("profile entries are not the materialized view of its events")
    return entries


def _stubs_for(profile: dict, key: str) -> list:
    return [s["stub_id"] for s in profile.get("packet_stubs") or [] if key in (s.get("bears_on") or [])]


def to_wrapper_v3(profile: dict, base_wrapper: dict, report_date: str, form_type, *, as_of: str | None = None) -> dict:
    """Return {"wrapper": generated v3 wrapper, "sidecar": pilot metadata}. Pure: no I/O but the schema."""
    entries = _entries(profile, as_of)
    wrapper = copy.deepcopy(base_wrapper)
    translated, not_expressible, no_wrapper_field, no_entry = [], [], [], []
    driven: dict[str, str] = {}  # pointer -> via
    for key in sorted({e["key"] for e in entries}):
        outcome = _resolve(entries, key, report_date, form_type, as_of)
        if outcome["status"] == "no_entry":
            continue
        spec = BY_PROFILE_KEY.get(key)
        path = spec["wrapper_path"] if spec else None
        ids = sorted(e["entry_id"] for e in outcome["entries"])
        if outcome["status"] == "resolved" and spec is None:
            no_wrapper_field.append(dict(profile_key=key, entry_ids=ids))
            continue
        if outcome["status"] == "resolved":
            value, via, detail = _convert(spec, outcome["entry"]["value"])
            if via is None:
                outcome = dict(status="not_expressible", reasons=["no_wrapper_representation"],
                               entries=outcome["entries"], detail=detail)
        if outcome["status"] == "not_expressible":
            present, base_value = _get(base_wrapper, path) if path else (False, None)
            not_expressible.append(dict(
                profile_key=key, entry_ids=ids, reasons=outcome["reasons"], detail=outcome.get("detail"),
                wrapper_pointer=pointer(path) if path else None,
                partitions=[e["applies_to"] for e in outcome["entries"]],
                form_types=sorted({e["form_type"] for e in outcome["entries"] if e["form_type"] is not None}),
                values=[e["value"] for e in outcome["entries"]],
                base_retained=(dict(pointer=pointer(path), present=present,
                                    sha256=value_sha256(base_value) if present else None) if path else None)))
            continue
        chosen = outcome["entry"]
        present, base_value = _get(base_wrapper, path)
        _set(wrapper, path, value)
        for p in fields(value, path):
            driven[p] = via
        translated.append(dict(
            profile_key=key, section=key.split(".", 1)[0], wrapper_pointer=pointer(path), entry_id=chosen["entry_id"],
            entry_provenance=chosen["provenance"], inherited_from=chosen["inherited_from"], via=via,
            equivalence_source=detail if via == "inherited_equivalence" else None,
            value_sha256=value_sha256(value), base_present=present,
            base_value_sha256=value_sha256(base_value) if present else None,
            equal_to_base=present and value_sha256(base_value) == value_sha256(value)))
    handled = {t["profile_key"] for t in translated} | {n["profile_key"] for n in not_expressible}
    for spec in TRANSLATIONS:
        if spec["profile_key"] not in handled:
            present, _ = _get(base_wrapper, spec["wrapper_path"])
            no_entry.append(dict(profile_key=spec["profile_key"], wrapper_pointer=pointer(spec["wrapper_path"]),
                                 base_present=present, stub_ids=_stubs_for(profile, spec["profile_key"])))
    validation = schema_verdict(wrapper)
    generated, base_fields = fields(wrapper), fields(base_wrapper)
    overlay = [dict(pointer=p, sha256=value_sha256(v)) for p, v in generated.items() if p not in driven]
    equal = [p for p, v in generated.items() if p in base_fields and value_sha256(base_fields[p]) == value_sha256(v)]
    union = set(generated) | set(base_fields)
    total = len(generated)
    sidecar = dict(
        schema=SIDECAR_SCHEMA, translate_version=TRANSLATE_VERSION, cik=profile.get("cik"), era=profile.get("era"),
        report_date=report_date, form_type=form_type, as_of=as_of,
        profile=dict(report_date=profile.get("report_date"), form_type=profile.get("form_type"),
                     recorded_at=profile.get("recorded_at"), profile_version=profile.get("profile_version")),
        translated=translated, not_expressible=not_expressible, no_wrapper_field=no_wrapper_field,
        no_entry=no_entry,
        sections_translated=sorted({t["section"] for t in translated}),
        entries_used=len(translated),
        inherited_overlay=dict(field_count=len(overlay), fields=overlay,
                               rule="every generated field not set from a profile entry; sha256 of its "
                                    "order-preserving compact JSON"),
        coverage=dict(fields_total=total, profile_driven=len(driven),
                      profile_driven_via_inherited=sum(1 for v in driven.values() if v != "direct"),
                      inherited=len(overlay), ratio=round(len(driven) / total, 6) if total else 0.0),
        parity=dict(fields_total=len(union), fields_equal_to_base=len(equal),
                    fields_added=len(set(generated) - set(base_fields)),
                    profile_driven_total=len(translated),
                    profile_driven_equal_to_base=sum(1 for t in translated if t["equal_to_base"])),
        schema_validation=validation, disclaimer=DISCLAIMER)
    return dict(wrapper=wrapper, sidecar=sidecar)


# ---------------------------------------------------------------- writing (run root only)

def _write_once_ordered(paths: PilotPaths, relative: str, value: dict) -> Path:
    """Like paths.write_once_json but WITHOUT sort_keys: wrapper key order is behaviour."""
    target = confined(paths, relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    target = confined(paths, relative)
    text = json.dumps(value, indent=2, ensure_ascii=True, allow_nan=False) + "\n"
    try:
        with open(target, "x", encoding="ascii", newline="\n") as stream:
            stream.write(text)
    except FileExistsError as exc:
        raise PathError("refusing to overwrite frozen file: " + str(target)) from exc
    return target


def wrapper_relative(cik: str, era: str) -> str:
    if era not in ERAS:
        raise ValueError("era must be one of " + repr(ERAS) + ": " + repr(era))
    return "translate/wrappers_" + era + "/" + cik + ".json"


def sidecar_relative(cik: str, era: str) -> str:
    if era not in ERAS:
        raise ValueError("era must be one of " + repr(ERAS) + ": " + repr(era))
    return "translate/" + cik + "/" + era + ".sidecar.json"


def write_overlay(paths: PilotPaths, cik: str, era: str, result: dict, *, extra: dict | None = None) -> dict:
    """Write the generated wrapper (order preserved) and its sidecar, both write-once under the run root."""
    wrapper_rel, sidecar_rel = wrapper_relative(cik, era), sidecar_relative(cik, era)
    target = _write_once_ordered(paths, wrapper_rel, result["wrapper"])
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    sidecar = dict(result["sidecar"], generated_wrapper=dict(relative=wrapper_rel, sha256=digest), **(extra or {}))
    side = write_once_json(paths, sidecar_rel, sidecar)
    return dict(wrapper=dict(path=str(target), relative=wrapper_rel, sha256=digest),
                sidecar=dict(path=str(side), relative=sidecar_rel,
                             sha256=hashlib.sha256(side.read_bytes()).hexdigest()), sidecar_body=sidecar)


# ---------------------------------------------------------------- production loader admission

@dataclass
class LoaderContext:
    module: object
    loader: object
    records: list = field(default_factory=list)
    mutations: list = field(default_factory=list)


class _Capture(logging.Handler):
    def __init__(self, sink: list):
        super().__init__(logging.DEBUG)
        self.sink = sink

    def emit(self, record):
        self.sink.append(record.getMessage())


STATE_ATTRS = ("WRAPPER_SPECS", "_WRAPPER_DEFINITIONS_DIR")


@contextmanager
def restored_wrapper_context():
    """Snapshot pipeline.bdc_xbrl_wrapper module state and its logger; restore in finally.

    Yields a LoaderContext with the production loader and the captured log messages.
    `mutations` names the module attributes found changed at exit (then restored).
    """
    from pipeline import bdc_xbrl_wrapper as module
    logger = logging.getLogger(module.__name__)
    saved = {name: getattr(module, name) for name in STATE_ATTRS}
    log_state = (logger.level, list(logger.handlers), logger.propagate, logger.disabled)
    ctx = LoaderContext(module=module, loader=module._load_specs_from_json)
    handler = _Capture(ctx.records)
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    try:
        yield ctx
    finally:
        for name, value in saved.items():
            if getattr(module, name) is not value:
                ctx.mutations.append(name)
                setattr(module, name, value)
        logger.removeHandler(handler)
        logger.setLevel(log_state[0])
        logger.propagate, logger.disabled = log_state[2], log_state[3]
        logger.handlers[:] = log_state[1]


def _spec_view(spec) -> dict:
    def pat(p):
        return None if p is None else [p.pattern, p.flags]
    return dict(cik=spec.cik, rule_prefix=spec.rule_prefix, version=spec.version,
                prefix_rules=list(spec.prefix_rules.items()),
                leaf_markers_by_family={k: list(v) for k, v in spec.leaf_markers_by_family.items()},
                entity_signals_re=pat(spec.entity_signals_re), aggregate_markers=list(spec.aggregate_markers),
                non_private_markers=list(spec.non_private_markers), category_marker_re=pat(spec.category_marker_re),
                fallback_family_patterns=[[pat(p), f] for p, f in spec.fallback_family_patterns],
                canonical_strip_re=pat(spec.canonical_strip_re), no_prefix_is_aggregate=spec.no_prefix_is_aggregate,
                category_marker_before_total=spec.category_marker_before_total)


def _skip_reason(path: Path, messages: list) -> str:
    related = [m for m in messages if path.name in m]
    if related:
        return " | ".join(related)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return "unreadable: " + str(exc)
    if raw.get("schema_version") != "bdc-xbrl-wrapper.v3":
        return "loader skipped silently: schema_version is not bdc-xbrl-wrapper.v3"
    if raw.get("dispatch") is None:
        return "loader skipped silently: no dispatch section"
    return "loader returned no spec for this CIK (keyed by the file's cik field)"


def admit_directory(directory, ciks, *, base_dir=None) -> dict:
    """Run the production loader over `directory` (and `base_dir` for spec parity) in one context."""
    directory = Path(directory)
    out = dict(directory=str(directory), base_dir=str(base_dir) if base_dir else None, directory_error=None,
               base_error=None, ciks={})
    with restored_wrapper_context() as ctx:
        try:
            specs = ctx.loader(directory)
        except Exception as exc:  # the loader aborts the whole directory on one bad file
            specs, out["directory_error"] = None, type(exc).__name__ + ": " + str(exc)
        base_specs = {}
        if base_dir is not None:
            try:
                base_specs = ctx.loader(Path(base_dir))
            except Exception as exc:
                out["base_error"] = type(exc).__name__ + ": " + str(exc)
        messages = list(ctx.records)
    out["log_messages"] = messages
    out["state_mutations"] = ctx.mutations
    for cik in ciks:
        path = directory / (cik + ".json")
        if specs is None:
            verdict = dict(admitted=False, error="directory load raised: " + out["directory_error"])
        elif cik in specs:
            verdict = dict(admitted=True, error=None, spec=_spec_view(specs[cik]))
        else:
            verdict = dict(admitted=False, error=_skip_reason(path, messages))
        if verdict["admitted"] and base_dir is not None:
            base = base_specs.get(cik)
            if base is None:
                verdict["spec_parity"] = dict(equal=None, reason="base wrapper not admitted by the loader")
            else:
                mine, theirs = verdict["spec"], _spec_view(base)
                differing = sorted(k for k in mine if mine[k] != theirs[k])
                verdict["spec_parity"] = dict(equal=not differing, differing_fields=differing)
        out["ciks"][cik] = verdict
    return out
