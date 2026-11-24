"""The two agent stores production applies to holdings (pipeline/agent_promoted.py), for the scope funds only.

Slice 5 Task 2 (decision 1, owner 2026-11-24): their value entries are loaded as corrections, their row-selecting rules
are loaded into the table correction_rule for the record and applied by no model.

- agent_b2_corrections/<cik>/<fix_class>.json (production: load_promoted_corrections). fix_class
  all_pik_normalization becomes kind value corrections keyed by the leaf's row_id (a production holdings row id,
  resolved in Task 3). What production's applier (pipeline/agent_b2_appliers.py apply_all_pik_normalization) sets on
  the selected row: pik_rate = template pik_rate (when given); and, when set_interest_to_cash is true and cash_rate is
  given, interest_rate = cash_rate with interest_rate_kind = 'cash' (a cash-leg observation; production's financial
  step later derives the all-in rate from cash plus PIK). In this layer's names that is pik_rate, interest_rate_cash
  and interest_rate_kind. fix_class comparative_period_filter becomes a correction_rule row (it removes rows).
- agent_investigate_rules/<cik>/<rule_id>.json (production: load_promoted_rules). rule_type row_add becomes kind
  add_row corrections: one row per field of each listed position, keyed by the position's accession_number and
  src_context_id, the position's fields sharing one add_group_id. rule_type row_exclusion becomes a correction_rule row.

Which files are read: <store>/<dir>/<file>.json one level down, as production globs (*/*.json). A file is skipped,
as pipeline/rule_admission.py admitted skips it, when its name or its folder starts with '_' (retired, pulled) or its
name contains '.proposed.'; also when its name contains '.review.' (a review record, not a leaf; production has no
such rule, and no live file is named so today). A store with an admission_manifest.json is a LoadError: production
would then admit by that manifest, which this loader does not read. Every other surprise is a LoadError, never a skip:
an unknown fix class or rule type, a template key not understood, a position without src_context_id.
"""
import json
from pathlib import Path

from . import CORRECTION_COLUMNS, CORRECTION_RULE_COLUMNS, LoadError, content_id
from .store import text_sha256

B2_STORE = "agent_b2_corrections"
RULES_STORE = "agent_investigate_rules"
# The keys of a row_add position that locate it; every other key is a field.
POSITION_KEYS = ("cik", "report_date", "accession_number", "src_context_id")
# all_pik_normalization template keys; table_index and row_index are evidence coordinates production ignores.
_PIK_TEMPLATE_KEYS = {"row_selector", "cash_rate", "pik_rate", "set_interest_to_cash"}
_SELECTOR_IGNORED = {"table_index", "row_index"}


def _cik10(raw):
    digits = "".join(ch for ch in str(raw or "") if ch.isdigit())
    return digits.zfill(10) if digits else ""


def skip_reason(path):
    """Why a file of a store is not loaded, or '' when it is. path: the file; its folder is the fund folder."""
    name = path.name
    if name.startswith("_") or path.parent.name.startswith("_"):
        return "retired or pulled (name or folder starts with _)"
    if ".proposed." in name.lower():
        return "proposal (.proposed. in the name)"
    if ".review." in name.lower():
        return "review record (.review. in the name)"
    return ""


def _text(value, where):
    """A position or template value as text. Only scalars; null is refused (production would store it as empty)."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float, str)):
        return str(value).strip() if isinstance(value, str) else repr(value)
    raise LoadError(f"{where}: value {value!r} is not a scalar")


def _json(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True) if value not in (None, "") else ""


def _correction(**cols):
    row = {c: "" for c in CORRECTION_COLUMNS}
    row.update(cols)
    row["correction_id"] = content_id(row, CORRECTION_COLUMNS, "correction_id")
    return row


def _rule(**cols):
    row = {c: "" for c in CORRECTION_RULE_COLUMNS}
    row.update(cols)
    row["rule_row_id"] = content_id(row, CORRECTION_RULE_COLUMNS, "rule_row_id")
    return row


def _quarters(obj, where):
    scope = obj.get("scope") or {}
    quarters = scope.get("quarters") if isinstance(scope, dict) else None
    if quarters is None:
        return []
    if not isinstance(quarters, list) or not all(isinstance(q, str) and q.strip() for q in quarters):
        raise LoadError(f"{where}: scope.quarters is not a list of dates")
    return [q.strip() for q in quarters]


def _b2_leaf(leaf, cik, source_file):
    """(corrections, rules) of one B2 leaf."""
    fix_class = str(leaf.get("fix_class") or "")
    template = leaf.get("template") or {}
    if not isinstance(template, dict):
        raise LoadError(f"{source_file}: template is not an object")
    reason, evidence = str(leaf.get("rationale") or ""), _json(leaf.get("evidence_citations"))
    if fix_class == "comparative_period_filter":
        if set(template) != {"report_date"}:
            raise LoadError(f"{source_file}: comparative_period_filter template keys {sorted(template)}")
        return [], [_rule(cik=cik, store=B2_STORE, rule_id=fix_class, rule_type=fix_class, action="exclude",
                          scope_quarters=str(template["report_date"]).strip(), predicate=_json(template),
                          predicate_form="template", evidence=evidence, reason=reason, source_file=source_file)]
    if fix_class != "all_pik_normalization":
        raise LoadError(f"{source_file}: fix_class {fix_class!r} is not one the loader knows")
    unknown = set(template) - _PIK_TEMPLATE_KEYS
    if unknown:
        raise LoadError(f"{source_file}: template key(s) {sorted(unknown)} not understood")
    selector = template.get("row_selector")
    if not isinstance(selector, dict) or set(selector) - _SELECTOR_IGNORED != {"row_id"} \
            or not str(selector.get("row_id") or "").strip():
        raise LoadError(f"{source_file}: row_selector must be one object selecting by row_id alone")
    row_id = str(selector["row_id"]).strip()
    quarters = _quarters(leaf, source_file)
    if len(quarters) != 1:
        raise LoadError(f"{source_file}: a row_id leaf must name exactly one quarter, found {quarters}")
    cash, pik, set_cash = template.get("cash_rate"), template.get("pik_rate"), template.get("set_interest_to_cash")
    if set_cash is not None and not isinstance(set_cash, bool):
        raise LoadError(f"{source_file}: set_interest_to_cash is not true or false")
    if cash is not None and not set_cash:
        # production's applier ignores cash_rate without set_interest_to_cash; loading it would set what production does not
        raise LoadError(f"{source_file}: cash_rate without set_interest_to_cash")
    fields = []
    if pik is not None:
        fields.append(("pik_rate", _text(pik, source_file)))
    if set_cash and cash is not None:
        fields += [("interest_rate_cash", _text(cash, source_file)), ("interest_rate_kind", "cash")]
    if not fields:
        raise LoadError(f"{source_file}: template sets neither pik_rate nor the cash leg")
    out = [_correction(cik=cik, report_date=quarters[0], field=f, value=v, kind="value", store=B2_STORE,
                       reason=reason, evidence=evidence, row_id=row_id, source_file=source_file)
           for f, v in fields]
    return out, []


def _investigate_rule(rule, cik, source_file):
    """(corrections, rules) of one investigator rule."""
    rule_type = str(rule.get("rule_type") or "")
    rule_id = str(rule.get("rule_id") or Path(source_file).stem)
    quarters = _quarters(rule, source_file)
    reason, evidence = str(rule.get("rationale") or ""), _json(rule.get("evidence"))
    if rule_type == "row_exclusion":
        predicate = rule.get("predicate_sql")
        if not isinstance(predicate, str) or not predicate.strip():
            raise LoadError(f"{source_file}: row_exclusion without predicate_sql")
        return [], [_rule(cik=cik, store=RULES_STORE, rule_id=rule_id, rule_type=rule_type,
                          action=str(rule.get("action") or ""), scope_quarters=",".join(quarters),
                          predicate=predicate.strip(), predicate_form="sql", evidence=evidence, reason=reason,
                          source_file=source_file)]
    if rule_type != "row_add":
        raise LoadError(f"{source_file}: rule_type {rule_type!r} is not one the loader knows")
    positions = rule.get("positions")
    if not isinstance(positions, list) or not positions:
        raise LoadError(f"{source_file}: row_add without positions")
    out = []
    for i, p in enumerate(positions):
        where = f"{source_file} positions[{i}]"
        if not isinstance(p, dict):
            raise LoadError(f"{where}: not an object")
        accession = str(p.get("accession_number") or "").strip()
        context_id = str(p.get("src_context_id") or "").strip()
        report_date = str(p.get("report_date") or "").strip()
        if not accession or not context_id or not report_date:
            raise LoadError(f"{where}: accession_number, src_context_id and report_date are all required")
        if p.get("cik") not in (None, "") and _cik10(p.get("cik")) != cik:
            raise LoadError(f"{where}: cik {p.get('cik')!r} is not the folder's fund")
        if quarters and "all" not in quarters and report_date not in quarters:
            raise LoadError(f"{where}: report_date {report_date} is outside the rule's scope {quarters}")
        if not isinstance(p.get("fair_value"), (int, float)) or isinstance(p.get("fair_value"), bool):
            raise LoadError(f"{where}: fair_value is not a number")
        group = f"{rule_id}:{accession}:{context_id}"
        for key in sorted(p):
            if key in POSITION_KEYS:
                continue
            out.append(_correction(cik=cik, report_date=report_date, accession=accession, context_id=context_id,
                                   field=key, value=_text(p[key], f"{where}.{key}"), kind="add_row",
                                   store=RULES_STORE, reason=reason, evidence=evidence, add_group_id=group,
                                   source_file=source_file))
    return out, []


_READERS = {B2_STORE: _b2_leaf, RULES_STORE: _investigate_rule}


def read_agent_store(store, base, ciks):
    """(corrections, rules, hashes, skipped) of one agent store for the scope funds.

    hashes maps <store>/<dir>/<file> to the text hash of every file of a scope fund (loaded or skipped); skipped maps
    the skipped ones to the reason. A missing store folder is a LoadError (the CLI always names both)."""
    base = Path(base)
    if store not in _READERS:
        raise LoadError(f"unknown agent store {store!r}")
    if not base.is_dir():
        raise LoadError(f"{store}: no folder at {base.as_posix()}")
    if (base / "admission_manifest.json").exists():
        raise LoadError(f"{store}: admission_manifest.json present; production would admit by it, the loader does not")
    wanted = set(ciks)
    corrections, rules, hashes, skipped = [], [], {}, {}
    for path in sorted(base.glob("*/*.json")):
        if path.parent.name.startswith("_"):
            continue  # a pulled folder at the top of the store: not a fund folder (production skips it too)
        cik = _cik10(path.parent.name)
        if cik not in wanted:
            continue
        source_file = f"{store}/{path.parent.name}/{path.name}"
        hashes[source_file] = text_sha256(path)
        why = skip_reason(path)
        if why:
            skipped[source_file] = why
            continue
        try:
            obj = json.loads(path.read_text(encoding="utf-8-sig"))
        except ValueError as exc:
            raise LoadError(f"{source_file}: not readable JSON ({exc})") from exc
        if not isinstance(obj, dict):
            raise LoadError(f"{source_file}: top level is not an object")
        if obj.get("cik") not in (None, "") and _cik10(obj.get("cik")) != cik:
            raise LoadError(f"{source_file}: cik {obj.get('cik')!r} is not the folder's fund")
        c, r = _READERS[store](obj, cik, source_file)
        corrections += c
        rules += r
    return corrections, rules, hashes, skipped
