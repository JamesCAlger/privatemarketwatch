"""One wrapper's reading declarations as rule rows, correction rows and a not-loaded list."""
import json
import re

from . import CORRECTION_COLUMNS, RULE_COLUMNS, LoadError, content_id

_ACCESSION = re.compile(r"\d{10}-\d{2}-\d{6}")
_DATE = r"\d{4}-\d{2}-\d{2}"
_DATED = re.compile(rf"^(?P<body>.*?)(?: from (?P<from>{_DATE}))?(?: to (?P<to>{_DATE}))?$")

FILER, SELECTED = 20, 30

# key -> (rule_class, target, action; '{}' takes the entry, selector column or '', parameter is the entry?)
_SIMPLE = {
    "filed_rate_reading": ("convention", "interest_rate", "rate_is_{}", "", False),
    "principal_usd_reference": ("convention", "principal_amount_usd", "to_usd", "", True),
    "foreign_unit_values": ("convention", "amount", "{}", "", False),
    "printed_margin_reading": ("convention", "spread", "printed_margin_{}", "", False),
    "cost_in_two_units": ("convention", "cost", "cost_{}", "", False),
    "reference_rate_columns": ("source", "reference_rate", "read_printed_column", "", True),
    "unspecified_reference_labels": ("vocabulary", "reference_rate", "label_is_unspecified", "", True),
    "equity_instrument_labels": ("vocabulary", "instrument_type", "label_is_equity", "", True),
    "printed_industry_labels": ("vocabulary", "industry", "label_is_industry", "", True),
    "detached_schedule_labels": ("scope", "scope", "detached_schedule", "", True),
    "reporting_entity_suffixes": ("scope", "scope", "set_scope_by_label_suffix", "sel_label", True),
    "reporting_entity_identifier_suffixes": ("scope", "scope", "set_scope_by_identifier_suffix", "sel_label", True),
    "cash_identifiers": ("scope", "is_cash", "set_is_cash", "sel_label", False),
}
_FILING_LISTS = {
    "units_tagged_as_par": ("shares", "units_tagged_as_par"),
    "bracketed_unsigned_values": ("amount", "bracketed_unsigned"),
}
_PROCEDURES = {"rate_only_contexts", "gics_industry_carry_back"}

# New-style fund rules (slice 2, Task 5): the top-level `reading_rules` list of the new pipeline's wrapper copy
# (warehouse/wrappers/<cik>.json). Each entry is an object; entry key -> rule column.
_RULE_SELECTORS = {
    "concept_namespace": "sel_concept_namespace", "concept_local": "sel_concept_local", "accession": "sel_accession",
    "axis": "sel_axis", "member": "sel_member", "label": "sel_label", "feature": "sel_feature",
}
_RULE_KEYS = {"target", "action", "parameter", "valid_from", "valid_to", "evidence"} | set(_RULE_SELECTORS)
# A namespace selector names the filer's own domain: a literal scheme and host, then a path in which '*' (glob) may
# stand for the dated part. Never a wildcard in the host, so a rule cannot reach another filer's taxonomy.
_NAMESPACE_SELECTOR = re.compile(r"https?://[A-Za-z0-9.-]+\.[A-Za-z]{2,}/[A-Za-z0-9._/*-]*")
_CONCEPT_LOCAL = re.compile(r"[A-Za-z][A-Za-z0-9]*")


def _rule(cik, key, rule_class, target, action, parameter="", priority=FILER, **cols):
    row = {c: "" for c in RULE_COLUMNS}
    row.update(cik=cik, validity_basis="assumed_all_quarters", target=target, action=action,
               parameter=parameter, origin=f"wrapper:{key}", rule_class=rule_class, priority=priority)
    row.update(cols)
    if row["valid_from"] or row["valid_to"]:
        row["validity_basis"] = "stated"
    row["rule_id"] = content_id(row, RULE_COLUMNS, "rule_id")
    return row


def _correction(cik, key, accession, context_id, field, value, kind, **cols):
    row = {c: "" for c in CORRECTION_COLUMNS}
    row.update(cik=cik, accession=accession, context_id=context_id, field=field, value=value,
               kind=kind, store=f"wrapper:{key}")
    row.update(cols)
    row["correction_id"] = content_id(row, CORRECTION_COLUMNS, "correction_id")
    return row


def _text(cik, key, entry):
    if not isinstance(entry, str) or not entry.strip():
        raise LoadError(f"{cik} {key}: expected text, got {entry!r}")
    return entry.strip()


def _bad(cik, key, entry):
    return LoadError(f"{cik} {key}: cannot read entry {entry!r}")


def _accession(cik, key, entry):
    text = _text(cik, key, entry)
    if not _ACCESSION.fullmatch(text):
        raise _bad(cik, key, entry)
    return text


def _reading_rules(cik, entries):
    """Rule rows (origin wrapper:reading_rules) for a wrapper's `reading_rules` list. Raises LoadError on anything
    unknown. Which actions exist is not checked here: dbt tests every action against seeds/reading_action.csv."""
    key = "reading_rules"
    if not isinstance(entries, list) or not entries:
        raise LoadError(f"{cik} {key}: expected a non-empty list, got {entries!r}")
    rules = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise _bad(cik, key, entry)
        unknown = sorted(set(entry) - _RULE_KEYS)
        if unknown:
            raise LoadError(f"{cik} {key}: unknown field(s) {', '.join(unknown)} in {entry!r}")
        if any(not isinstance(v, str) for v in entry.values()):
            raise _bad(cik, key, entry)
        e = {k: v.strip() for k, v in entry.items()}
        for required in ("target", "action", "evidence"):
            if not e.get(required):
                raise LoadError(f"{cik} {key}: {required} is required in {entry!r}")
        namespace, local = e.get("concept_namespace", ""), e.get("concept_local", "")
        if bool(namespace) != bool(local):
            # filed_layer.md ruling 12: a concept is matched on namespace and local name together, never one alone
            raise LoadError(f"{cik} {key}: concept_namespace and concept_local go together in {entry!r}")
        if namespace and not _NAMESPACE_SELECTOR.fullmatch(namespace):
            raise LoadError(f"{cik} {key}: concept_namespace must be a literal scheme and host then a path: {namespace!r}")
        if local and not _CONCEPT_LOCAL.fullmatch(local):
            raise LoadError(f"{cik} {key}: concept_local is one local name, no prefix: {local!r}")
        if e.get("accession") and not _ACCESSION.fullmatch(e["accession"]):
            raise _bad(cik, key, entry)
        for d in ("valid_from", "valid_to"):
            if e.get(d) and not re.fullmatch(_DATE, e[d]):
                raise LoadError(f"{cik} {key}: {d} must read YYYY-MM-DD in {entry!r}")
        cols = {col: e[k] for k, col in _RULE_SELECTORS.items() if e.get(k)}
        row = _rule(cik, key, "fund_rule", e["target"], e["action"], parameter=e.get("parameter", ""),
                    priority=SELECTED if cols else FILER, evidence=e["evidence"],
                    valid_from=e.get("valid_from", ""), valid_to=e.get("valid_to", ""), **cols)
        rules.append(row)
    return rules


def flatten(cik, wrapper):
    """(rules, corrections, not_loaded) for one wrapper. Raises LoadError on anything unknown."""
    rules, corrections, not_loaded = [], [], []
    if "reading_rules" in wrapper:
        rules += _reading_rules(cik, wrapper["reading_rules"])
    encodings = wrapper.get("source_encodings") or {}
    if not isinstance(encodings, dict):
        raise LoadError(f"{cik}: source_encodings is not an object")

    for key, entries in encodings.items():
        if not isinstance(entries, list):
            raise LoadError(f"{cik} {key}: expected a list, got {type(entries).__name__}")

        if key in _SIMPLE:
            rule_class, target, action, selector, entry_is_parameter = _SIMPLE[key]
            for entry in entries:
                text = _text(cik, key, entry)
                cols = {selector: text} if selector else {}
                rules.append(_rule(cik, key, rule_class, target, action.format(text),
                                   parameter=text if entry_is_parameter else "",
                                   priority=SELECTED if selector else FILER, **cols))

        elif key == "pik_only_tag_reading":
            for entry in entries:
                rules.append(_rule(cik, key, "convention", "pik_rate", f"pik_only_is_{_text(cik, key, entry)}",
                                   priority=SELECTED, sel_feature="pik_tag_only"))

        elif key == "reference_rate_codes":
            for entry in entries:
                m = _DATED.match(_text(cik, key, entry))
                body = m.group("body").strip()
                if "=" not in body or " " in body.split("=", 1)[0]:
                    raise _bad(cik, key, entry)
                rules.append(_rule(cik, key, "vocabulary", "reference_rate", "map_code", parameter=body,
                                   valid_from=m.group("from") or "", valid_to=m.group("to") or ""))

        elif key == "legal_entity_members":
            for entry in entries:
                m = re.fullmatch(r"([^=\s]+)=(\S+) -> (.+)", _text(cik, key, entry))
                if not m:
                    raise _bad(cik, key, entry)
                rules.append(_rule(cik, key, "scope", "scope", "set_scope", parameter=m.group(3).strip(),
                                   priority=SELECTED, sel_axis=m.group(1), sel_member=m.group(2)))

        elif key == "par_tagged_as_units":
            for entry in entries:
                text = _text(cik, key, entry)
                if _ACCESSION.fullmatch(text):
                    rules.append(_rule(cik, key, "filing_scoped", "principal_amount", "par_tagged_as_units",
                                       parameter="whole_filing", priority=SELECTED, sel_accession=text))
                elif re.fullmatch(r"[a-z_]+", text):
                    rules.append(_rule(cik, key, "value_test", "principal_amount", "par_tagged_as_units",
                                       parameter=text, priority=SELECTED, sel_feature=text))
                else:
                    raise _bad(cik, key, entry)

        elif key in _FILING_LISTS:
            target, action = _FILING_LISTS[key]
            for entry in entries:
                rules.append(_rule(cik, key, "filing_scoped", target, action, priority=SELECTED,
                                   sel_accession=_accession(cik, key, entry)))

        elif key in _PROCEDURES:
            for entry in entries:
                not_loaded.append({"cik": cik, "wrapper_key": key, "entry": _text(cik, key, entry),
                                   "reason": "needs_procedure"})

        elif key == "pik_margin_reading":
            for entry in entries:
                text = _text(cik, key, entry)
                m = re.fullmatch(rf"not ({_ACCESSION.pattern}) (\S+)", text)
                if m:
                    corrections.append(_correction(cik, key, m.group(1), m.group(2), key, "", "exception"))
                elif re.fullmatch(r"[a-z_]+", text):
                    not_loaded.append({"cik": cik, "wrapper_key": key, "entry": text, "reason": "needs_procedure"})
                else:
                    raise _bad(cik, key, entry)

        elif key == "untagged_values":
            for entry in entries:
                m = re.fullmatch(rf"({_ACCESSION.pattern}) (\S+) ([a-z_]+) (\S+)(?: ([A-Z]{{3}}))?", _text(cik, key, entry))
                if not m:
                    raise _bad(cik, key, entry)
                corrections.append(_correction(cik, key, m.group(1), m.group(2), m.group(3), m.group(4), "value",
                                               value_unit=m.group(5) or ""))

        elif key == "relabelled_contexts":
            for entry in entries:
                parts = _text(cik, key, entry).split(" :: ")
                head = re.fullmatch(rf"({_ACCESSION.pattern}) (\S+)", parts[0])
                if len(parts) != 3 or not head or not parts[1].strip() or not parts[2].strip():
                    raise _bad(cik, key, entry)
                corrections.append(_correction(cik, key, head.group(1), head.group(2), "identifier",
                                               parts[2].strip(), "relabel", expected_value=parts[1].strip()))

        elif key == "rate_verification_anchors":
            for entry in entries:
                if not isinstance(entry, dict) or not {"accession", "context", "field"} <= set(entry):
                    raise _bad(cik, key, entry)
                source = "; ".join(f"{k}={entry[k]}" for k in ("source_context", "source_concept", "source_units")
                                   if entry.get(k))
                corrections.append(_correction(cik, key, str(entry["accession"]), str(entry["context"]),
                                               str(entry["field"]), "", "evidence", reason=source,
                                               evidence=str(entry.get("evidence", ""))))

        else:
            raise LoadError(f"{cik}: unknown wrapper key source_encodings.{key}")

    fmt = wrapper.get("identifier_format")
    if fmt is not None:
        if not isinstance(fmt, dict):
            raise LoadError(f"{cik}: identifier_format is not an object")
        rules.append(_rule(cik, "identifier_format", "source", "identifier", "identifier_format",
                           parameter=json.dumps(fmt, sort_keys=True, separators=(",", ":"), ensure_ascii=False)))
    return rules, corrections, not_loaded
