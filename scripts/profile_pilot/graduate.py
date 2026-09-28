"""Graduation [E] (spec 6.5): does a live correction generalise as a filer-profile entry?

For every live B2 leaf and investigate rule of the eight pilot CIKs (the frozen M3
denominator) this module, deterministically:

1. expresses the correction as a candidate envelope entry, or records why it cannot
   be expressed (parser/template only; date text is never stripped by replacement);
2. executes the ORIGINAL correction through the real production applier and the
   CANDIDATE through its envelope predicate on the same pre-correction frame, and
   compares the selected source-row multisets and action/value effects exactly;
3. evaluates the candidate on every other available quarter at the same stage and
   requires a mechanism witness per selected row plus the gate's anchor basis/band;
4. classifies: generalises / quarter_bound / conflicts / insufficient_evidence /
   not_expressible. No class is ever assigned from an aggregate total alone.

Origin frames (owner ruling Q5 / controller ruling 9): staging-stage corrections use
the pinned bdc_holdings slice; unified-stage corrections use staging_bdc._prepare_bdc
output for that slice, with the once-per-fund-quarter unified_transform_effect check.
build_unified_holdings is never run.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re
import time

import pandas as pd

from scripts.profile_pilot import envelope
from scripts.profile_pilot.cohort import PILOT_CIKS
from scripts.profile_pilot.manifest import (ANCHOR_DIR, B2_DIR, INVESTIGATE_DIR, StageInvalidated,
                                            sha256_file)
from scripts.profile_pilot.protection import requires_lease

GRADUATE_VERSION = "graduate-v1"
CANON_VERSION = "Decimal(text).normalize() v1; null distinct from zero"
RID = "_pilot_rid"
STAGING, UNIFIED = "staging", "unified"
CLASSES = ("generalises", "quarter_bound", "conflicts", "insufficient_evidence", "not_expressible")
AXIS_PREFIX = "investmentidentifieraxis="
KEY_COLUMNS = ("accession_number", "src_context_id")
GATED_COLUMNS = ("bdc_dimensions_raw", "bdc_investment_identifier")
DIAGNOSTIC_COLUMNS = ("issuer_name", "asset_category", "fair_value_currency")
VALUE_FIELDS = ("fair_value", "cost", "principal_amount", "shares_held", "interest_rate", "pik_rate",
                "basis_spread", "asset_category", "bdc_dimensions_raw", "bdc_investment_identifier")
MAX_FRAME_ROWS = 10000  # per fund-quarter frames only; never a row loop above this
LIST_CAP = 200
# Staging-cost estimate calibrated on 2026-09-28 diagnostics (222 rows 16.2 s,
# 2254 rows 17.2 s); deliberately conservative.
EST_BASE_SECONDS, EST_SECONDS_PER_ROW = 20.0, 0.005
_NO_CACHE = Path(__file__).resolve().parent / "_no_instance_cache_bound"


class NotExpressible(ValueError):
    def __init__(self, reason: str, detail: str = ""):
        super().__init__(reason + (": " + detail if detail else ""))
        self.reason, self.detail = reason, detail


# ------------------------------------------------------------------ small helpers

def with_rids(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.reset_index(drop=True).copy()
    frame[RID] = range(len(frame))
    return frame


def canon(value):
    """Spec 6.4 canonical decimal text; None for null; 'unparseable:' prefix otherwise."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    if text == "":
        return None
    try:
        number = Decimal(text)
    except InvalidOperation:
        return "unparseable:" + text
    return str(number.normalize()) if number.is_finite() else "unparseable:" + text


def _text(value) -> str:
    return "" if canon_is_null(value) else str(value)


def canon_is_null(value) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def cik10(value) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    return digits.zfill(10) if digits else ""


def _cik_mask(frame: pd.DataFrame, cik: str) -> pd.Series:
    return frame["cik"].astype(str).str.replace(r"\D", "", regex=True).str.zfill(10) == cik


def _key(record: dict, stage: str) -> tuple:
    cols = KEY_COLUMNS + (("period",) if stage == STAGING else ())
    return tuple(None if canon_is_null(record.get(c)) or str(record.get(c)) == "" else str(record.get(c))
                 for c in cols)


def _sort_keys(keys) -> list:
    return sorted([list(k) for k in keys], key=lambda k: [(p is None, p or "") for p in k])


def _records(frame: pd.DataFrame) -> list[dict]:
    if len(frame) > MAX_FRAME_ROWS:
        raise ValueError("frame exceeds the per fund-quarter row bound: " + str(len(frame)))
    return frame.to_dict("records")


# ------------------------------------------------------------------ inventory (M3 denominator)

def body_id(body: dict) -> str:
    return ("b2_" + str(body.get("fix_class"))) if "fix_class" in body else ("rule_" + str(body.get("rule_id")))


def inventory_item(body: dict, *, path: str, sha256: str) -> dict:
    family = "b2_leaf" if "fix_class" in body else "investigate_rule"
    fix_class = str(body.get("fix_class") or body.get("rule_type"))
    scope = list((body.get("scope") or {}).get("quarters") or [])
    if family == "b2_leaf" and not scope and (body.get("template") or {}).get("report_date"):
        scope = [str(body["template"]["report_date"])]
    return dict(item_id=cik10(body.get("cik")) + ":" + body_id(body), cik=cik10(body.get("cik")),
                family=family, fix_class=fix_class,
                stage=STAGING if fix_class == "comparative_period_filter" else UNIFIED,
                scope_quarters=scope, path=path, sha256=sha256)


def _read(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def correction_inventory(code_root, *, ciks=PILOT_CIKS) -> dict:
    """Live corrections via the production loader contract, with explicit dirs and hashes."""
    from pipeline import agent_promoted
    from pipeline.rule_admission import admitted
    code_root = Path(code_root)
    b2_base, rule_base = code_root / B2_DIR, code_root / INVESTIGATE_DIR
    loaded_b2 = agent_promoted.load_promoted_corrections(b2_base)
    loaded_rules = agent_promoted.load_promoted_rules(rule_base)
    wanted = set(ciks)
    items, excluded, matched, explained = [], [], Counter(), Counter()
    for base, family in ((b2_base, "b2"), (rule_base, "rule")):
        pilot_dirs = [d for d in sorted(base.iterdir()) if d.is_dir() and cik10(d.name) in wanted
                      and not d.name.startswith("_")]
        for directory in pilot_dirs:
            for path in sorted(p for p in directory.rglob("*.json") if p.is_file()):
                rel = path.relative_to(code_root).as_posix()
                if path.parent != directory:
                    excluded.append(dict(path=rel, reason="outside_loader_glob_or_underscore_dir"))
                    continue
                if not admitted(path, base):
                    excluded.append(dict(path=rel, reason="proposed_or_retired"))
                    continue
                if ".review." in path.name.lower():  # controller ruling R2
                    excluded.append(dict(path=rel, reason="review_record_not_a_correction"))
                    explained[json.dumps(_read(path), sort_keys=True)] += 1
                    continue
                body = _read(path)
                pool = loaded_b2 if family == "b2" else loaded_rules.get(cik10(directory.name), [])
                if body not in pool:
                    excluded.append(dict(path=rel, reason="loader_did_not_return_it"))
                    continue
                matched[json.dumps(body, sort_keys=True)] += 1
                item = inventory_item(body, path=rel, sha256=sha256_file(path))
                if item["cik"] != cik10(directory.name):
                    raise StageInvalidated("correction cik disagrees with its directory: " + rel)
                items.append(item)
    # Reverse liveness: every body the loaders return for the pilot CIKs must be an
    # inventory item or an explained (.review.) exclusion; the M3 denominator is the metric.
    returned = Counter(json.dumps(b, sort_keys=True) for b in loaded_b2 if cik10(b.get("cik")) in wanted)
    returned.update(json.dumps(b, sort_keys=True) for c, bodies in loaded_rules.items() if c in wanted
                    for b in bodies)
    remainder = returned - matched - explained
    if remainder:
        ids_left = sorted(body_id(json.loads(k)) for k in remainder.elements())
        raise StageInvalidated("loader returned " + str(sum(remainder.values())) + " live pilot-CIK "
                               "correction(s) the inventory did not enumerate: " + ", ".join(ids_left[:10]))
    ids = [i["item_id"] for i in items]
    if len(ids) != len(set(ids)):
        raise StageInvalidated("duplicate correction ids in the inventory")
    per_cik = Counter(i["cik"] for i in items)
    return dict(version=GRADUATE_VERSION, denominator=len(items), items=items, excluded=excluded,
                directories=dict(b2=str(b2_base), investigate=str(rule_base)),
                loader_contract=["pipeline.agent_promoted.load_promoted_corrections(dir)",
                                 "pipeline.agent_promoted.load_promoted_rules(dir)",
                                 "pipeline.rule_admission.admitted(path, base)",
                                 "ruling R2: .review. names are not live"],
                per_cik={c: per_cik.get(c, 0) for c in sorted(wanted)})


def live_bodies(code_root, inventory: dict, *, cik: str) -> tuple[list, list]:
    """(B2 leaves, rules) for one CIK, re-read and hash-verified against the frozen inventory."""
    b2, rules = [], []
    for item in inventory["items"]:
        if item["cik"] != cik:
            continue
        path = Path(code_root) / item["path"]
        if sha256_file(path) != item["sha256"]:
            raise StageInvalidated("correction changed after freezing: " + item["path"])
        (b2 if item["family"] == "b2_leaf" else rules).append(_read(path))
    return b2, rules


# ------------------------------------------------------------------ translation

def _split_top(text: str, word: str) -> list[str]:
    """Split on a top-level SQL keyword (outside quotes and parentheses)."""
    pattern = re.compile(r"\s+" + word + r"\s+", re.IGNORECASE)
    parts, depth, quote, start, i = [], 0, False, 0, 0
    while i < len(text):
        ch = text[i]
        if ch == "'":
            quote = not quote
        elif not quote and ch == "(":
            depth += 1
        elif not quote and ch == ")":
            depth -= 1
        elif not quote and depth == 0:
            match = pattern.match(text, i)
            if match:
                parts.append(text[start:i])
                start = i = match.end()
                continue
        i += 1
    if quote or depth:
        raise NotExpressible("unparsed_predicate", "unbalanced quotes or parentheses")
    parts.append(text[start:])
    return [p.strip() for p in parts]


def _strip_parens(text: str) -> str:
    text = text.strip()
    while text.startswith("(") and text.endswith(")") and _balanced(text[1:-1]):
        text = text[1:-1].strip()
    return text


def _balanced(text: str) -> bool:
    depth, quote = 0, False
    for ch in text:
        if ch == "'":
            quote = not quote
        elif not quote:
            depth += {"(": 1, ")": -1}.get(ch, 0)
            if depth < 0:
                return False
    return depth == 0 and not quote


_DATE = r"'(\d{4}-\d{2}-\d{2})'"
_TEMPORAL_EQ = re.compile(r"report_date\s*=\s*" + _DATE, re.IGNORECASE)
_TEMPORAL_IN = re.compile(r"report_date\s+IN\s*\(\s*" + _DATE + r"(\s*,\s*" + _DATE + r")*\s*\)",
                          re.IGNORECASE)
_LIKE = re.compile(r"bdc_dimensions_raw\s+(I?LIKE)\s+'((?:[^']|'')*)'", re.IGNORECASE)
_EXACT = re.compile(r"bdc_dimensions_raw\s*=\s*'((?:[^']|'')*)'", re.IGNORECASE)
_DERIVED = re.compile(r"\b(asset_category|index_classification|asset_class|issuer_category|"
                      r"exposure_type|instrument_type)\b", re.IGNORECASE)


def _like_term(clause: str) -> str:
    clause = _strip_parens(clause)
    like = _LIKE.fullmatch(clause)
    if not like:
        if _EXACT.fullmatch(clause):
            raise NotExpressible("exact_typed_member_no_predicate_kind", clause)
        raise NotExpressible("unparsed_predicate", clause)
    operator, pattern = like.group(1).upper(), like.group(2).replace("''", "'")
    if pattern.startswith("%"):
        raise NotExpressible("substring_match_no_predicate_kind", clause)
    if operator == "ILIKE":
        raise NotExpressible("case_insensitive_match_no_predicate_kind", clause)
    if not pattern.endswith("%"):
        raise NotExpressible("exact_typed_member_no_predicate_kind", clause)
    body = pattern[:-1]
    if "%" in body or "_" in body or "\\" in body:
        raise NotExpressible("like_wildcard_in_literal", clause)
    if not body.startswith(AXIS_PREFIX) or "|" in body or not body[len(AXIS_PREFIX):]:
        raise NotExpressible("non_identifier_axis_prefix", clause)
    return body[len(AXIS_PREFIX):]


def parse_predicate(sql: str) -> dict:
    """Restricted template: [report_date = D | IN (...)] AND <LIKE-prefix [OR ...]>."""
    if not str(sql or "").strip():
        raise NotExpressible("no_mechanism_clause", "empty predicate")
    temporal, mechanisms = [], []
    for conjunct in _split_top(_strip_parens(str(sql)), "AND"):
        clause = _strip_parens(conjunct)
        if _TEMPORAL_EQ.fullmatch(clause) or _TEMPORAL_IN.fullmatch(clause):
            temporal.extend(re.findall(r"\d{4}-\d{2}-\d{2}", clause))
        elif re.search(r"\breport_date\b", clause, re.IGNORECASE):
            raise NotExpressible("unparsed_temporal_clause", clause)
        elif re.search(r"\brow_id\b", clause, re.IGNORECASE):
            raise NotExpressible("row_id_pinned", clause)
        elif _DERIVED.search(clause):
            raise NotExpressible("derived_classification_predicate", clause)
        else:
            mechanisms.append([_like_term(d) for d in _split_top(clause, "OR")])
    if len(mechanisms) != 1:
        raise NotExpressible("no_mechanism_clause" if not mechanisms else "multiple_mechanism_clauses")
    vocabulary = mechanisms[0]
    if len(set(vocabulary)) != len(vocabulary):
        raise NotExpressible("unparsed_predicate", "repeated prefix")
    return dict(temporal=sorted(set(temporal)), vocabulary=vocabulary)


COMPARATIVE_VALUE = dict(distinguisher="period_differs_from_report_date", null_or_empty_period="comparative",
                         view="current_period_view_excludes_comparative",
                         note="describes the prior-period view; prior-period facts are not deleted")


def _not_expressible(reason: str, detail: str = "") -> dict:
    return dict(status="not_expressible", reason=reason, detail=detail)


def express_candidate(item: dict, body: dict, *, recorded_at: str) -> dict:
    """Candidate envelope entry (author census, status derived) or not_expressible."""
    fix = item["fix_class"]
    scope = [str(q) for q in (body.get("scope") or {}).get("quarters") or []]
    scope_all = "all" in scope
    try:
        if item["family"] == "b2_leaf":
            template = body.get("template") or {}
            if fix == "missing_position_add":
                raise NotExpressible("row_add_no_structural_counterpart")
            if fix != "comparative_period_filter":
                selector = template.get("row_selector")
                raise NotExpressible("row_pinned_value_fix" if selector else
                                     "value_transformation_no_structural_counterpart", fix)
            if set(template) != {"report_date"}:
                raise NotExpressible("unparsed_template_fields", repr(sorted(template)))
            rd = str(template["report_date"])
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", rd) or (scope and set(scope) != {rd}):
                raise NotExpressible("unparsed_temporal_clause", rd)
            key, applies_to, value, temporal = "comparative_periods", None, COMPARATIVE_VALUE, [rd]
        else:
            rtype = str(body.get("rule_type"))
            if rtype == "row_add":
                raise NotExpressible("row_add_no_structural_counterpart")
            if rtype in ("value_rescale", "value_expression"):
                raise NotExpressible("value_fix_no_structural_counterpart", rtype)
            if rtype != "row_exclusion":
                raise NotExpressible("unparsed_rule_type", rtype)
            parsed = parse_predicate(body.get("predicate_sql"))
            text = (str(body.get("rule_id")) + " " + str(body.get("rationale"))).lower()
            if "duplicate" in text:
                key = "presentation_views"
                value = dict(view="alternate_axis_duplicate", current_view_action="exclude",
                             retained_counterpart_required=True)
            elif "subtotal" in text or "rollup" in text:
                key = "subtotals_and_headings"
                value = dict(marker="subtotal_or_heading", current_view_action="exclude")
            else:
                raise NotExpressible("mechanism_undeclared", "rationale names no mechanism")
            applies_to = dict(kind="prefix", vocabulary=parsed["vocabulary"])
            temporal = sorted(set(parsed["temporal"]) & set(scope)) if parsed["temporal"] and not scope_all \
                else (parsed["temporal"] or scope)
            if not temporal:
                raise NotExpressible("temporal_scope_empty", "embedded dates outside scope")
    except NotExpressible as exc:
        return _not_expressible(exc.reason, exc.detail)
    evidence = [dict(kind="translated_correction", item_id=item["item_id"], path=item["path"],
                     sha256=item["sha256"], translator=GRADUATE_VERSION)]
    events = envelope.make_assertion([], cik=item["cik"], key=key, value=value, valid_from=None,
                                     recorded_at=recorded_at, applies_to=applies_to,
                                     support=dict(kind="context_count", count=0), evidence=evidence)
    envelope.validate_profile(events)
    return dict(status="expressible", key=key, applies_to=applies_to, value=value,
                temporal_scope=["all"] if scope_all else sorted(temporal), scope_all=scope_all,
                events=events, entry=envelope.materialize_entries(events)[0])


# ------------------------------------------------------------------ selections

def original_selection(item: dict, body: dict, frame: pd.DataFrame) -> dict:
    """Execute the ORIGINAL correction through its real production applier."""
    from pipeline import agent_promoted
    if item["stage"] == STAGING:
        import duckdb
        con = duckdb.connect()
        try:
            con.register("_pilot_frame", frame)
            con.execute("CREATE TABLE bdc_raw AS SELECT * FROM _pilot_frame")
            audits = agent_promoted.apply_raw_staging_exclusions(
                con, agent_promoted.raw_staging_exclusions([body]))
            kept = {r[0] for r in con.execute('SELECT "' + RID + '" FROM bdc_raw').fetchall()}
        finally:
            con.close()
        return dict(action="exclude", rids=sorted(set(frame[RID]) - kept), value_changes=0,
                    additions=0, audits=audits)
    if item["family"] != "investigate_rule":
        raise NotImplementedError("unified B2 leaves have no expressible candidate")
    out, audits = agent_promoted.apply_promoted_plan(frame.copy(), [], {item["cik"]: [body]})
    kept_frame = out[out[RID].notna()]
    kept = set(int(r) for r in kept_frame[RID])
    before = frame.set_index(RID)
    changes = 0
    for record in _records(kept_frame):
        prior = before.loc[int(record[RID])]
        if any(canon(record.get(f)) != canon(prior.get(f)) if f in ("fair_value", "cost",
               "principal_amount", "shares_held", "interest_rate", "pik_rate", "basis_spread")
               else _text(record.get(f)) != _text(prior.get(f)) for f in VALUE_FIELDS if f in frame):
            changes += 1
    return dict(action="exclude", rids=sorted(set(frame[RID]) - kept), value_changes=changes,
                additions=int(out[RID].isna().sum()), audits=audits)


def _identifier(record: dict) -> str:
    for field in ("bdc_investment_identifier", "investment_identifier"):
        if field in record and not canon_is_null(record[field]):
            return str(record[field])
    return ""


def candidate_selection(candidate: dict, frame: pd.DataFrame, *, cik: str) -> dict:
    """Evaluate the envelope entry per row (per-CIK restriction kept)."""
    entries = envelope.materialize_entries(candidate["events"])
    selected = []
    for record in _records(frame.loc[_cik_mask(frame, cik)]):
        row = dict(investment_identifier=_identifier(record),
                   dimensions_raw=_text(record.get("dimensions_raw", record.get("bdc_dimensions_raw"))))
        found = envelope.resolve_for_row(entries, row, candidate["key"], str(record["report_date"])[:10],
                                         None, None).found
        if not found:
            continue
        if candidate["key"] == "comparative_periods":
            period = _text(record.get("period"))
            if period == "" or period != str(record["report_date"]):
                selected.append(int(record[RID]))
        else:
            selected.append(int(record[RID]))
    return dict(action="exclude", rids=sorted(selected))


def compare_effects(frame: pd.DataFrame, original: dict, candidate: dict, *, stage: str) -> dict:
    """Exact comparison of selected source-row multisets and action/value effects."""
    by_rid = {int(r[RID]): r for r in _records(frame)}
    all_keys = Counter(_key(r, stage) for r in by_rid.values())
    orig, cand = set(original["rids"]), set(candidate["rids"])
    ko = Counter(_key(by_rid[r], stage) for r in orig)
    kc = Counter(_key(by_rid[r], stage) for r in cand)
    selected = orig | cand
    collisions = sorted({_key(by_rid[r], stage) for r in selected
                         if all_keys[_key(by_rid[r], stage)] > 1 and None not in _key(by_rid[r], stage)})

    def fv_sum(rids):
        values = [canon(by_rid[r].get("fair_value")) for r in rids]
        return str(sum((Decimal(v) for v in values if v and not v.startswith("unparseable")),
                       Decimal(0)).normalize())

    effects_equal = (original["action"] == candidate["action"] and not original.get("value_changes")
                     and not original.get("additions"))
    return dict(fidelity=orig == cand and ko == kc and effects_equal, rid_sets_equal=orig == cand,
                key_multisets_equal=ko == kc, effects_equal=effects_equal,
                original_count=len(orig), candidate_count=len(cand), overlap=len(orig & cand),
                only_original=_sort_keys((ko - kc).elements())[:LIST_CAP],
                only_candidate=_sort_keys((kc - ko).elements())[:LIST_CAP],
                original_keys=_sort_keys(ko.elements())[:LIST_CAP],
                candidate_keys=_sort_keys(kc.elements())[:LIST_CAP],
                key_collisions=_sort_keys(collisions)[:LIST_CAP],
                unkeyed_selected=sum(1 for r in selected if None in _key(by_rid[r], stage)),
                selected_fv_original=fv_sum(orig), selected_fv_candidate=fv_sum(cand),
                original_value_changes=original.get("value_changes", 0),
                original_additions=original.get("additions", 0))


# ------------------------------------------------------------------ witnesses

def _match(options: dict) -> dict:
    """Maximum one-to-one assignment of selected rows to counterparts (Kuhn)."""
    owner: dict = {}

    def assign(rid, seen):
        for option in options[rid]:
            if option in seen:
                continue
            seen.add(option)
            if option not in owner or assign(owner[option], seen):
                owner[option] = rid
                return True
        return False

    for rid in sorted(options):
        assign(rid, set())
    return {rid: option for option, rid in owner.items()}


def gather_witnesses(candidate: dict, frame: pd.DataFrame, rids) -> dict:
    """A mechanism-specific source witness for EVERY selected row (zero-FV included)."""
    from pipeline.agent_rule import name_key
    records = {int(r[RID]): r for r in _records(frame)}
    chosen = sorted(set(int(r) for r in rids))
    witness, missing, contradicted = {}, {}, {}
    key = candidate["key"]
    if key == "comparative_periods":
        current = {_text(r.get("accession_number")) for r in records.values()
                   if _text(r.get("period")) == str(r.get("report_date"))}
        for rid in chosen:
            r = records[rid]
            period, rd = _text(r.get("period")), str(r.get("report_date"))
            try:
                parsed = date.fromisoformat(period) if len(period) == 10 else None
            except ValueError:
                parsed = None
            if parsed is None:
                missing[rid] = "null_or_unparseable_period"
            elif period > rd:
                contradicted[rid] = "period_after_report_date"
            elif _text(r.get("accession_number")) not in current:
                missing[rid] = "accession_not_current_source"
            else:
                witness[rid] = dict(kind="comparative_period", period=period, report_date=rd,
                                    accession=_text(r.get("accession_number")))
    elif key == "presentation_views":
        vocabulary = sorted(candidate["applies_to"]["vocabulary"], key=len, reverse=True)
        chosen_set = set(chosen)
        retained = [r for rid, r in records.items() if rid not in chosen_set]
        options = {}
        for rid in chosen:
            r = records[rid]
            ident = _identifier(r)
            term = next((t for t in vocabulary if ident.startswith(t)), "")
            tokens = name_key(ident[len(term):].strip(" ,-|:"))
            if not tokens:
                missing[rid] = "no_identity_tokens"
                continue
            same = [c for c in retained if _text(c.get("accession_number")) == _text(r.get("accession_number"))
                    and tokens <= name_key(_identifier(c))]
            options[rid] = [int(c[RID]) for c in same
                            if canon(c.get("fair_value")) == canon(r.get("fair_value"))
                            and canon(r.get("fair_value")) is not None]
            if not options[rid]:
                missing[rid] = "counterpart_fv_differs" if same else "no_retained_counterpart"
        assigned = _match({rid: o for rid, o in options.items() if o})
        for rid in options:
            if rid in assigned:
                c = records[assigned[rid]]
                witness[rid] = dict(kind="retained_counterpart", counterpart=list(_key(c, UNIFIED)),
                                    fair_value=canon(c.get("fair_value")))
            elif rid not in missing:
                missing[rid] = "counterpart_already_assigned"
    else:  # subtotals_and_headings: no census hierarchy in Stage A
        missing = {rid: "subtotal_hierarchy_witness_unavailable" for rid in chosen}
    zero = [rid for rid in chosen if canon(records[rid].get("fair_value")) == "0"]
    return dict(kind=key, selected=len(chosen), witnessed=len(witness), missing=len(missing),
                contradicted=len(contradicted), zero_fv_selected=len(zero),
                zero_fv_unwitnessed=sum(1 for rid in zero if rid not in witness),
                missing_reasons=dict(Counter(missing.values())),
                contradiction_reasons=dict(Counter(contradicted.values())),
                rows=[dict(key=list(_key(records[rid], STAGING if key == "comparative_periods" else UNIFIED)),
                           fair_value=canon(records[rid].get("fair_value")),
                           witness=witness.get(rid), missing=missing.get(rid),
                           contradicted=contradicted.get(rid)) for rid in chosen][:LIST_CAP])


# ------------------------------------------------------------------ anchors

def load_anchor_contracts(code_root, *, ciks=PILOT_CIKS) -> dict:
    """FULL anchor JSON per (cik10, quarter), with path and sha256."""
    out = {}
    for cik in ciks:
        directory = Path(code_root) / ANCHOR_DIR / str(int(cik))
        for path in sorted(directory.glob("*.json")) if directory.is_dir() else []:
            body = _read(path)
            quarter = str(body.get("target_quarter") or path.stem)
            out[(cik, quarter)] = dict(body, _path=path.relative_to(code_root).as_posix(),
                                       _sha256=sha256_file(path))
    return out


def gate_band() -> dict:
    from pipeline import config
    return dict(band_pct=float(config.FV_CONSERVATION_BAND_PCT),
                source="pipeline.config.FV_CONSERVATION_BAND_PCT (fv_conservation engine band, "
                       "consumed by pipeline.quarter_acceptance)")


MEMBERSHIP_SOURCE = "pipeline.accounting_membership.build (called unchanged)"
MEMBERSHIP_COLUMNS = ("accounting_scope_id", "accounting_record_class")
MEMBERSHIP_HOLDING_COLUMNS = ("cik", "report_date", *MEMBERSHIP_COLUMNS, "fair_value",
                              "fair_value_currency", "index_classification")
ANCHOR_LEVEL_REASONS = ("anchor_evidence_unavailable", "anchor_basis_unresolved")


def _anchor_row(anchor: dict) -> dict:
    """The anchor contract fields exactly as recorded; nothing absent is defaulted."""
    return dict(cik=cik10(anchor.get("cik")), quarter=str(anchor.get("target_quarter") or ""),
                anchor_basis=anchor.get("basis"), anchor_kind=anchor.get("anchor_kind"),
                source_evidence=anchor.get("source_evidence"), currency=anchor.get("currency"))


def production_membership(anchor: dict, frame: pd.DataFrame) -> dict:
    """Per-row anchor membership from the production gate module, not a paraphrase.

    `pipeline.accounting_membership.build` reads CSV paths; the holdings and the one
    anchor row are handed to it on an in-memory fsspec filesystem (no disk write).
    Holdings lacking accounting_scope_id/accounting_record_class are passed with those
    columns NULL and the result is `anchor_membership_unresolved`: no proxy (such as
    is_subsidiary) is ever substituted. Anchor-level reasons take production's precedence.
    """
    import uuid
    import duckdb
    import fsspec
    from pipeline.accounting_membership import build
    absent = [c for c in MEMBERSHIP_COLUMNS if c not in frame.columns]
    counts = dict(included=0, excluded=0, unknown=0)
    out = dict(source=MEMBERSHIP_SOURCE, missing_holding_columns=absent, membership=counts, reasons={})
    if frame.empty:
        return dict(out, total=Decimal(0), cause="anchor_membership_unresolved" if absent else None)
    holdings = pd.DataFrame({c: (frame[c].to_numpy() if c in frame.columns else None)
                             for c in MEMBERSHIP_HOLDING_COLUMNS})
    holdings.insert(0, "row_id", ["pilot-" + str(i) for i in range(len(frame))])  # call-local identity
    fs = fsspec.filesystem("memory")
    root = "memory://pilot-membership-" + uuid.uuid4().hex
    con = duckdb.connect()
    try:
        con.register_filesystem(fs)
        fs.pipe(root + "/holdings.csv", holdings.to_csv(index=False).encode("ascii", "replace"))
        fs.pipe(root + "/anchors.csv", pd.DataFrame([_anchor_row(anchor)]).to_csv(index=False).encode("ascii"))
        build(con, release_id="pilot", holdings=root + "/holdings.csv", anchors=root + "/anchors.csv")
        rows = con.execute("SELECT membership, reason, count(*), sum(fair_value) FROM accounting_membership "
                           "GROUP BY 1, 2 ORDER BY 1, 2").fetchall()
    finally:
        con.close()
        if fs.exists(root):
            fs.rm(root, recursive=True)
    reasons = Counter()
    total = Decimal(0)
    for membership, reason, n, value in rows:
        counts[membership] += n
        reasons[reason] += n
        if membership == "included":
            total += Decimal(str(value))
    out = dict(out, membership=counts, reasons=dict(sorted(reasons.items())))
    anchor_level = [r for r in ANCHOR_LEVEL_REASONS if r in reasons]
    if sum(counts.values()) != len(frame):
        cause = "membership_rows_unjoined"
    elif anchor_level:
        cause = anchor_level[0]
    elif absent:
        cause = "anchor_membership_unresolved"
    elif counts["unknown"]:
        unknown = Counter({r: n for r, n in reasons.items()
                           if r not in ("declared_anchor_population", "outside_parent_anchor",
                                        "outside_investments_anchor")})
        cause = sorted(unknown.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
    else:
        cause = None
    return dict(out, total=None if cause else total, cause=cause)


def reconcile(anchor: dict, pre: pd.DataFrame, post: pd.DataFrame, band_pct: float) -> dict:
    """The gate's anchor contract and membership (accounting_membership) and its band."""
    basis = anchor.get("basis")
    base = dict(basis=basis, band_pct=band_pct, anchor_path=anchor.get("_path"),
                grand_total=anchor.get("grand_total"), anchor_currency=anchor.get("currency") or None,
                anchor_kind=anchor.get("anchor_kind") or None, membership_source=MEMBERSHIP_SOURCE)
    sides = {}
    for label, frame in (("pre", pre), ("post", post)):
        sides[label] = production_membership(anchor, frame)
        if sides[label]["cause"]:
            side = {k: v for k, v in sides[label].items() if k != "total"}
            return dict(base, status="unassessable", cause=side["cause"], failed_side=label, **{label: side})
    if not isinstance(anchor.get("grand_total"), (int, float)) or not anchor["grand_total"]:
        return dict(base, status="unassessable", cause="anchor_total_missing")
    total = Decimal(str(anchor["grand_total"]))
    results = {}
    for label, side in sides.items():
        value = side["total"]
        residual = (value - total) / total * 100
        results[label] = dict(total=str(value.normalize()), residual_pct=float(residual),
                              within_band=abs(residual) <= Decimal(str(band_pct)),
                              membership=side["membership"], reasons=side["reasons"])
    status = ("reconciles" if results["post"]["within_band"] else
              "contradicted" if results["pre"]["within_band"] else "unassessable")
    return dict(base, status=status, cause=None if status != "unassessable"
                else "anchor_not_reconciled_without_candidate", **results)


# ------------------------------------------------------------------ unified_transform_effect

def _frame_index(frame: pd.DataFrame) -> tuple[dict, Counter]:
    keyed, unkeyed = {}, Counter()
    for r in _records(frame):
        key = _key(r, UNIFIED)
        payload = (canon(r.get("fair_value")),) + tuple(_text(r.get(c)) for c in GATED_COLUMNS)
        if None in key:
            unkeyed[payload] += 1
        else:
            keyed.setdefault(key, []).append((payload, tuple(_text(r.get(c)) for c in DIAGNOSTIC_COLUMNS)))
    return keyed, unkeyed


def _frame_diff(left: pd.DataFrame, right: pd.DataFrame) -> dict:
    a, ua = _frame_index(left)
    b, ub = _frame_index(right)
    only_a, only_b = sorted(set(a) - set(b)), sorted(set(b) - set(a))
    both = sorted(set(a) & set(b))
    mult = [k for k in both if len(a[k]) != len(b[k])]
    fv = [k for k in both if sorted(str(p[0][0]) for p in a[k]) != sorted(str(p[0][0]) for p in b[k])]
    cols = {c: sum(1 for k in both if sorted(p[0][i + 1] for p in a[k]) != sorted(p[0][i + 1] for p in b[k]))
            for i, c in enumerate(GATED_COLUMNS)}
    diag = {c: sum(1 for k in both if sorted(p[1][i] for p in a[k]) != sorted(p[1][i] for p in b[k]))
            for i, c in enumerate(DIAGNOSTIC_COLUMNS)}
    equal = not (only_a or only_b or mult or fv or any(cols.values())) and ua == ub
    return dict(equal=equal, staged_only_keys=len(only_a), reference_only_keys=len(only_b),
                multiplicity_differences=len(mult), fv_differences=len(fv),
                gated_column_differences=cols, diagnostic_column_differences=diag,
                unkeyed_equal=ua == ub, unkeyed_left=sum(ua.values()), unkeyed_right=sum(ub.values()),
                samples=dict(staged_only=[list(k) for k in only_a[:5]],
                             reference_only=[list(k) for k in only_b[:5]],
                             fv=[list(k) for k in fv[:5]],
                             unkeyed_left_only=[list(p) for p in list((ua - ub).elements())[:5]],
                             unkeyed_right_only=[list(p) for p in list((ub - ua).elements())[:5]]))


def _in_scope(body: dict, quarter: str | None) -> bool:
    quarters = [str(q) for q in (body.get("scope") or {}).get("quarters") or []]
    return quarter is None or not quarters or "all" in quarters or quarter in quarters


def _single_quarter(frame: pd.DataFrame) -> str | None:
    quarters = set(frame["report_date"].astype(str).str[:10]) if "report_date" in frame else set()
    return next(iter(quarters)) if len(quarters) == 1 else None


def replay_quarter(staged: pd.DataFrame, *, cik: str, corrections: list, rules: list,
                   quarter: str | None) -> tuple[pd.DataFrame, list, dict]:
    """Production plan on ONE fund-quarter: only leaves/rules whose scope covers it.

    Production runs the plan over every quarter at once; out-of-scope leaves cannot
    touch this quarter's rows, and rows they add for other quarters are dropped here.
    """
    from pipeline.agent_promoted import apply_promoted_plan
    leaves = [c for c in corrections if _in_scope(c, quarter)]
    kept = [r for r in rules if _in_scope(r, quarter)]
    out, audits = apply_promoted_plan(staged.copy(), leaves, {cik: kept} if kept else {})
    if quarter is not None:
        out = out.loc[out["report_date"].astype(str).str[:10] == quarter]
    return out, audits, dict(corrections=[str(c.get("fix_class")) for c in leaves],
                             rules=[str(r.get("rule_id")) for r in kept])


def unified_transform_effect(staged: pd.DataFrame, reference, *, cik: str, corrections: list,
                             rules: list, quarter: str | None = None) -> dict:
    """Staged source keys/FV vs the reference slice (spec 6.4), once per fund-quarter.

    `literal` is the ruling's comparison with no replay. The reference is published
    output, so live corrections alone make it differ; `attributed` replays the live
    corrections through the production plan and gates on exact equality.
    """
    base = dict(canonicalisation=CANON_VERSION, key=list(KEY_COLUMNS),
                gated=["row multiplicity", "fair_value", *GATED_COLUMNS],
                diagnostic=list(DIAGNOSTIC_COLUMNS))
    if reference is None:
        return dict(base, ok=False, cause="reference_slice_missing")
    staged = staged.drop(columns=[RID], errors="ignore")
    quarter = quarter or _single_quarter(staged)
    literal = _frame_diff(staged, reference)
    try:
        replayed, audits, used = replay_quarter(staged, cik=cik, corrections=corrections, rules=rules,
                                                quarter=quarter)
    except Exception as exc:  # recorded, never approximated
        return dict(base, ok=False, cause="replay_error", literal=literal,
                    error=type(exc).__name__ + ": " + str(exc)[:300])
    attributed = _frame_diff(replayed, reference)
    return dict(base, ok=attributed["equal"], cause=None if attributed["equal"] else
                "unified_transform_effect", literal=literal, attributed=attributed, replayed=used,
                replay_audits=[{k: a.get(k) for k in ("rule_id", "status", "rows_changed", "drift")}
                               for a in audits])


# ------------------------------------------------------------------ frame providers

class StaticProvider:
    """Explicit frames (tests and replays). Checks default to supplied-frame acceptance."""

    def __init__(self, frames: dict, *, published: dict | None = None, checks: dict | None = None):
        self.frames, self.published, self.checks = frames, published or {}, checks or {}

    def quarters(self, cik):
        return sorted({q for c, q, _ in self.frames if c == cik})

    def frame(self, cik, quarter, stage):
        frame = self.frames.get((cik, quarter, stage))
        if frame is None:
            return dict(status="unavailable", cause="frame_unavailable")
        return dict(status="ok", frame=frame, lease=dict(requires_lease=False),
                    check=self.checks.get((cik, quarter), dict(ok=True, basis="supplied_frame")))

    def anchor_frames(self, cik, quarter, stage, frame, rids):
        pre = self.published.get((cik, quarter))
        if pre is None:
            return dict(status="unavailable", cause="published_frame_unavailable")
        drop = {_key(r, UNIFIED) for r in _records(frame.loc[frame[RID].isin(list(rids))])}
        keep = [_key(r, UNIFIED) not in drop for r in _records(pre)]
        return dict(status="ok", pre=pre, post=pre.loc[keep])


def production_stager(frame: pd.DataFrame, raw_exclusions: list, cache_dir) -> pd.DataFrame:
    """staging_bdc._prepare_bdc with the instance cache bound explicitly (restored after)."""
    from pipeline import config, staging_bdc
    bound = Path(cache_dir) if cache_dir else _NO_CACHE
    if not cache_dir and bound.exists():
        raise StageInvalidated("the no-cache binding must not exist: " + str(bound))
    original = config.BDC_XBRL_CACHE_DIR
    config.BDC_XBRL_CACHE_DIR = bound
    try:
        return staging_bdc._prepare_bdc(bdc_df=frame.drop(columns=[RID], errors="ignore"),
                                        raw_exclusions=raw_exclusions or None, raw_exclusion_audits=[])
    finally:
        config.BDC_XBRL_CACHE_DIR = original


class SliceProvider:
    """Pinned-slice frames; staging through the production stager with heavy derivation."""

    def __init__(self, *, raw_frames: dict, reference: dict, stager, corrections: list,
                 rules_by_cik: dict, cache_dir):
        self.raw, self.reference, self.stager = raw_frames, reference, stager
        self.corrections, self.rules_by_cik, self.cache_dir = corrections, rules_by_cik, cache_dir
        self._cache: dict = {}
        self.log: list = []

    def quarters(self, cik):
        return sorted(q for c, q in self.raw if c == cik)

    def _for(self, cik):
        from pipeline.agent_promoted import raw_staging_exclusions
        leaves = [c for c in self.corrections if cik10(c.get("cik")) == cik]
        return leaves, self.rules_by_cik.get(cik, []), raw_staging_exclusions(leaves)

    def _lease(self, cik, raw) -> dict:
        # monetary_units.resolve_bdc_units parses one instance per accession carrying a unit ref
        units = pd.Series(False, index=raw.index)
        for column in ("fair_value_unit", "cost_unit"):
            if column in raw:
                units |= raw[column].fillna("").astype(str).str.strip() != ""
        n_instances = int(raw.loc[units, "accession_number"].nunique()) if self.cache_dir else 0
        parse_heavy = bool(n_instances) and requires_lease(ciks=(cik,), instance_count=n_instances)
        parses = n_instances if (n_instances and not parse_heavy) else 0
        est = EST_BASE_SECONDS + EST_SECONDS_PER_ROW * len(raw)
        heavy = requires_lease(ciks=(cik,), instance_count=parses, pipeline_cik_count=1, est_seconds=est)
        return dict(requires_lease=heavy, instances_parsed=parses, est_seconds=round(est, 1),
                    currency_resolution=("main_instance_cache" if parses else
                                         "not_executed_requires_lease" if parse_heavy else
                                         "cache_not_bound"))

    def _stage(self, cik, raw, lease):
        _, _, exclusions = self._for(cik)
        t0 = time.perf_counter()
        staged = self.stager(raw, exclusions,
                             self.cache_dir if lease["currency_resolution"] == "main_instance_cache" else None)
        return staged, round(time.perf_counter() - t0, 1)

    def frame(self, cik, quarter, stage):
        slot = (cik, quarter, stage)
        if slot in self._cache:
            return self._cache[slot]
        raw = self.raw.get((cik, quarter))
        if raw is None:
            result = dict(status="unavailable", cause="frame_unavailable")
        elif stage == STAGING:
            result = dict(status="ok", frame=with_rids(raw), check=None,
                          lease=dict(requires_lease=requires_lease(ciks=(cik,), instance_count=0)))
        else:
            lease = self._lease(cik, raw)
            if lease["requires_lease"]:
                result = dict(status="unavailable", cause="heavy_reconstruction_not_executed", lease=lease)
            else:
                staged, seconds = self._stage(cik, raw, lease)
                leaves, rules, _ = self._for(cik)
                check = unified_transform_effect(staged, self.reference.get((cik, quarter)), cik=cik,
                                                 corrections=leaves, rules=rules, quarter=quarter)
                result = dict(status="ok", frame=with_rids(staged), check=check,
                              lease=dict(lease, seconds=seconds))
            self.log.append(dict(cik=cik, quarter=quarter, status=result["status"],
                                 cause=result.get("cause"), lease=result.get("lease"),
                                 check=result.get("check")))
        self._cache[slot] = result
        return result

    def _replay(self, cik, quarter, staged):
        leaves, rules, _ = self._for(cik)
        out, _, _ = replay_quarter(staged.drop(columns=[RID], errors="ignore"), cik=cik,
                                   corrections=leaves, rules=rules, quarter=quarter)
        return out

    def anchor_frames(self, cik, quarter, stage, frame, rids):
        unified = self.frame(cik, quarter, UNIFIED)
        if unified["status"] != "ok":
            return dict(status="unavailable", cause=unified["cause"])
        if not unified["check"]["ok"]:
            return dict(status="unavailable", cause="unified_transform_effect")
        pre = self._replay(cik, quarter, unified["frame"])
        if stage == UNIFIED:
            drop = {_key(r, UNIFIED) for r in _records(frame.loc[frame[RID].isin(list(rids))])}
            if any(None in k for k in drop):
                return dict(status="unavailable", cause="selected_rows_unkeyed")
            return dict(status="ok", pre=pre, post=pre.loc[[_key(r, UNIFIED) not in drop for r in _records(pre)]])
        remaining = frame.loc[~frame[RID].isin(list(rids))].drop(columns=[RID])
        lease = self._lease(cik, remaining)
        if lease["requires_lease"]:
            return dict(status="unavailable", cause="heavy_reconstruction_not_executed")
        staged, _ = self._stage(cik, remaining, lease)
        return dict(status="ok", pre=pre, post=self._replay(cik, quarter, with_rids(staged)))


# ------------------------------------------------------------------ graduation

def materialize_origin(item: dict, body: dict, candidate: dict, provider, quarter: str) -> dict:
    """Original vs candidate on the pinned pre-correction frame of one origin quarter."""
    got = provider.frame(item["cik"], quarter, item["stage"])
    base = dict(quarter=quarter, stage=item["stage"], lease=got.get("lease"))
    if got["status"] != "ok":
        return dict(base, status="unassessable", cause=got["cause"])
    if item["stage"] == UNIFIED and not got["check"]["ok"]:
        return dict(base, status="unassessable", cause="unified_transform_effect")
    frame = got["frame"].loc[lambda f: f["report_date"].astype(str).str[:10] == quarter]
    original = original_selection(item, body, frame)
    if not original["rids"]:
        return dict(base, status="unassessable", cause="origin_rows_absent")
    authored = ((body.get("measured_impact") or {}).get(quarter) or {}).get("rows")
    if authored is not None and int(authored) != len(original["rids"]):
        return dict(base, status="unassessable", cause="origin_frame_differs_from_authoring",
                    authored_rows=authored, reconstructed_rows=len(original["rids"]))
    result = compare_effects(frame, original, candidate_selection(candidate, frame, cik=item["cik"]),
                             stage=item["stage"])
    return dict(base, status="match" if result["fidelity"] else "mismatch", comparison=result)


def assess_holdout(item: dict, candidate: dict, provider, quarter: str, *, anchors: dict,
                   band_pct: float) -> dict:
    cik, stage = item["cik"], item["stage"]
    got = provider.frame(cik, quarter, stage)
    base = dict(quarter=quarter, lease=got.get("lease"))
    if got["status"] != "ok":
        return dict(base, status="unassessable", cause=got["cause"])
    if stage == UNIFIED and not got["check"]["ok"]:
        return dict(base, status="unassessable", cause="unified_transform_effect")
    frame = got["frame"]
    selected = candidate_selection(candidate, frame, cik=cik)["rids"]
    if not selected:
        return dict(base, status="empty", selected=0)
    witnesses = gather_witnesses(candidate, frame, selected)
    base.update(selected=len(selected), witnessed=witnesses["witnessed"],
                zero_fv_unwitnessed=witnesses["zero_fv_unwitnessed"], witnesses=witnesses)
    if witnesses["contradicted"]:
        return dict(base, status="conflict", cause="witness_contradiction")
    if witnesses["missing"]:
        return dict(base, status="touched_unassessable", cause="missing_witness")
    anchor = anchors.get((cik, quarter))
    if anchor is None:
        return dict(base, status="touched_unassessable", cause="no_anchor")
    frames = provider.anchor_frames(cik, quarter, stage, frame, selected)
    if frames["status"] != "ok":
        return dict(base, status="touched_unassessable", cause=frames["cause"])
    rec = reconcile(anchor, frames["pre"], frames["post"], band_pct)
    base["reconciliation"] = rec
    if rec["status"] == "reconciles":
        return dict(base, status="supported")
    if rec["status"] == "contradicted":
        return dict(base, status="conflict", cause="filer_total_contradicts")
    return dict(base, status="touched_unassessable", cause=rec["cause"])


def classify(origin: list, holdouts: list, *, scope_all: bool) -> dict:
    """Spec 6.5 classes; every insufficient_evidence carries a cause."""
    def insufficient(causes):
        causes = [c for c in causes if c]
        return {"class": "insufficient_evidence", "cause": causes[0], "causes": sorted(set(causes))}

    if any(o["status"] == "mismatch" for o in origin):
        return {"class": "not_expressible", "reason": "fidelity_mismatch", "cause": None}
    if not origin:
        return insufficient(["origin_frame_unavailable"])
    if any(o["status"] != "match" for o in origin):
        return insufficient([o.get("cause") for o in origin if o["status"] != "match"])
    if scope_all:
        return insufficient(["no_holdout_all_quarters_rule"])
    if not holdouts:
        return insufficient(["no_eligible_holdout"])
    if any(h["status"] == "conflict" for h in holdouts):
        conflicts = sorted({h["cause"] for h in holdouts if h["status"] == "conflict"})
        return {"class": "conflicts", "cause": None, "conflict_causes": conflicts}
    open_ = [h for h in holdouts if h["status"] in ("unassessable", "touched_unassessable")]
    supported = [h for h in holdouts if h["status"] == "supported"]
    if not supported and not open_:
        return {"class": "quarter_bound", "cause": None}
    if open_:
        return insufficient([h["cause"] for h in open_])
    if len(supported) < 2:
        return insufficient(["fewer_than_two_supported_quarters"])
    return {"class": "generalises", "cause": None}


def graduate_item(item: dict, body: dict, provider, *, anchors: dict, band_pct: float,
                  recorded_at: str) -> dict:
    candidate = express_candidate(item, body, recorded_at=recorded_at)
    out = dict(item_id=item["item_id"], cik=item["cik"], fix_class=item["fix_class"],
               family=item["family"], stage=item["stage"], path=item["path"], sha256=item["sha256"],
               scope_quarters=item["scope_quarters"], version=GRADUATE_VERSION)
    if candidate["status"] != "expressible":
        return dict(out, candidate=candidate, **{"class": "not_expressible"},
                    reason=candidate["reason"], cause=None)
    out["candidate"] = {k: candidate[k] for k in ("status", "key", "applies_to", "value",
                                                   "temporal_scope", "scope_all", "entry")}
    available = provider.quarters(item["cik"])
    origin_q = available if candidate["scope_all"] else candidate["temporal_scope"]
    origin = [materialize_origin(item, body, candidate, provider, q) for q in origin_q]
    holdouts = [] if candidate["scope_all"] else [
        assess_holdout(item, candidate, provider, q, anchors=anchors, band_pct=band_pct)
        for q in available if q not in origin_q]
    verdict = classify(origin, holdouts, scope_all=candidate["scope_all"])
    return dict(out, origin=origin, holdouts=holdouts, **verdict)


def yield_summary(results: list, *, denominator: int) -> dict:
    if len(results) != denominator:
        raise ValueError("results do not cover the frozen denominator: "
                         + str(len(results)) + " != " + str(denominator))
    def empty():
        return {c: 0 for c in CLASSES}
    overall, per_cik, per_fix = empty(), {}, {}
    for r in results:
        overall[r["class"]] += 1
        per_cik.setdefault(r["cik"], empty())[r["class"]] += 1
        per_fix.setdefault(r["fix_class"], empty())[r["class"]] += 1
    return dict(denominator=denominator, overall=overall, per_cik=per_cik, per_fix_class=per_fix,
                insufficient_evidence_causes={r["item_id"]: r["cause"] for r in results
                                              if r["class"] == "insufficient_evidence"},
                not_expressible_reasons={r["item_id"]: r["reason"] for r in results
                                         if r["class"] == "not_expressible"})


# ------------------------------------------------------------------ light M3 stage

def read_output_slice(output_root: Path, cik: str, quarter: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """One fund-quarter straight from the output CSVs (all VARCHAR); used by cached tests."""
    import duckdb
    con = duckdb.connect(config={"threads": 2, "memory_limit": "2GB"})
    try:
        frames = [con.execute("SELECT * FROM read_csv(?, all_varchar=true, header=true) WHERE "
                              "lpad(cik, 10, '0') = ? AND substr(report_date, 1, 10) = ? LIMIT 10001",
                              [str(Path(output_root) / name), cik, quarter]).fetchdf()
                  for name in ("bdc_holdings.csv", "private_markets_holdings.csv")]
    finally:
        con.close()
    return frames[0], frames[1]


# Inherited staging inputs pinned in the M3 manifest (the wrapper directory is read by
# _prepare_bdc via staging_bdc._WRAPPER_DEFINITIONS_DIR).
STAGING_INPUT_FILES = ("pipeline/staging_bdc.py", "pipeline/monetary_units.py",
                       "pipeline/agent_b2_appliers.py", "pipeline/correction_execution.py",
                       "pipeline/unified_holdings.py", "pipeline/config.py", "pipeline/rule_admission.py",
                       "data/reference/fx_rates.csv", "scripts/profile_pilot/graduate.py")
UNBOUND_STAGING_INPUTS = ("config.AGGREGATE_HEADER_FLAGS_FILE (data/output/aggregate_header_flags.csv)",
                          "config.BDC_IXBRL_FIELD_STATUS_FILE (data/output)")


def inherited_staging_inputs(paths) -> list:
    from pipeline import staging_bdc
    from scripts.profile_pilot.manifest import file_record
    wrapper_dir = Path(staging_bdc._WRAPPER_DEFINITIONS_DIR).resolve()
    if paths.code_root not in wrapper_dir.parents:
        raise StageInvalidated("staging wrapper dir is not under the code root: " + str(wrapper_dir))
    records = [file_record(p, "inherited/wrappers/" + p.name) for p in sorted(wrapper_dir.glob("*.json"))]
    return records + [file_record(paths.code_root / rel, "inherited/" + rel) for rel in STAGING_INPUT_FILES]


def freeze_m3(paths) -> dict:
    """Correction inventory FIRST, then the Task 1 freeze sequence plus inherited inputs."""
    from scripts.profile_pilot import cohort, manifest, verify
    from scripts.profile_pilot.paths import write_once_json
    inventory = correction_inventory(paths.code_root)
    manifest.freeze_inventory(paths, "correction_inventory", inventory)
    primary = cohort.primary_quarter_inventory(paths)  # no scanner: nothing is parsed
    manifest.freeze_inventory(paths, "primary_quarter_inventory", primary)
    manifest.freeze_inventory(paths, "wrapper_key_inventory",
                              manifest.wrapper_key_inventory(paths.code_root))
    built = manifest.build_manifest(paths, primary_inventory=primary)
    built["materialised"] = (manifest.materialise_verified_era_wrappers(paths, built["verified_era"])
                             + verify._materialise_slices(paths))
    built["inherited_staging_inputs"] = inherited_staging_inputs(paths)
    built["inputs"] = built["inputs"] + built["inherited_staging_inputs"]
    built["unbound_staging_inputs"] = list(UNBOUND_STAGING_INPUTS)
    built["inventories"] = manifest.inventory_states(paths)
    built["input_verification"] = manifest.verify_inputs(built)
    built["stage"] = "m3-light"
    built["frozen_utc"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    write_once_json(paths, "manifest.json", built)
    return dict(denominator=inventory["denominator"], per_cik=inventory["per_cik"],
                input_verification=built["input_verification"])


def _load_slices(paths, man: dict, ciks) -> tuple[dict, dict]:
    import duckdb
    frames = []
    for name in ("bdc_holdings", "private_markets_holdings"):
        record = next(r for r in man["materialised"] if r["label"] == "run/inputs/" + name + "_pilot8.parquet")
        if sha256_file(record["path"]) != record["sha256"]:
            raise StageInvalidated("pinned slice changed: " + record["path"])
        con = duckdb.connect(config={"threads": 2, "memory_limit": "2GB"})
        try:
            frame = con.execute("SELECT * FROM read_parquet(?) WHERE lpad(cik, 10, '0') IN (SELECT unnest(?))",
                                [record["path"], sorted(ciks)]).fetchdf()
        finally:
            con.close()
        keys = frame["cik"].astype(str).str.zfill(10) + "|" + frame["report_date"].astype(str).str[:10]
        frames.append({tuple(k.split("|")): part.reset_index(drop=True) for k, part in frame.groupby(keys)})
    return frames[0], frames[1]


def _slim(out: dict) -> dict:
    return {k: out.get(k) for k in ("item_id", "cik", "fix_class", "family", "stage", "class", "cause",
                                    "causes", "reason", "conflict_causes")}


def run_m3(paths) -> dict:
    from scripts.profile_pilot import manifest
    from scripts.profile_pilot.paths import confined, write_json
    t0 = time.perf_counter()
    man = json.loads(confined(paths, "manifest.json").read_text(encoding="ascii"))
    verification = manifest.verify_inputs(man)
    if not verification["ok"]:
        raise StageInvalidated("manifest inputs changed before M3: " + json.dumps(verification))
    inventory = manifest.load_inventory(paths, "correction_inventory")
    pairs = []
    for item in inventory["items"]:
        path = paths.code_root / item["path"]
        if sha256_file(path) != item["sha256"]:
            raise StageInvalidated("correction changed after freezing: " + item["path"])
        pairs.append((item, _read(path)))
    recorded_at = man["frozen_utc"]
    expressible = sorted({i["cik"] for i, b in pairs
                          if express_candidate(i, b, recorded_at=recorded_at)["status"] == "expressible"})
    raw_frames, reference = _load_slices(paths, man, expressible)
    provider = SliceProvider(raw_frames=raw_frames, reference=reference, stager=production_stager,
                             corrections=[b for i, b in pairs if i["family"] == "b2_leaf"],
                             rules_by_cik={c: [b for i, b in pairs if i["family"] == "investigate_rule"
                                               and i["cik"] == c] for c in expressible},
                             cache_dir=paths.cache_root)
    anchors, band = load_anchor_contracts(paths.code_root), gate_band()
    results, gaps = [], []
    for item, body in pairs:
        try:
            out = graduate_item(item, body, provider, anchors=anchors, band_pct=band["band_pct"],
                                recorded_at=recorded_at)
        except Exception as exc:  # an integration gap is a result, never an approximation
            error = type(exc).__name__ + ": " + str(exc)[:300]
            gaps.append(dict(item_id=item["item_id"], error=error))
            out = dict(item_id=item["item_id"], cik=item["cik"], fix_class=item["fix_class"],
                       family=item["family"], stage=item["stage"], error=error,
                       **{"class": "insufficient_evidence"}, cause="integration_gap")
        write_json(paths, "graduation/" + item["cik"] + "/" + item["item_id"].replace(":", "__") + ".json", out)
        results.append(_slim(out))
    summary = yield_summary(results, denominator=inventory["denominator"])
    checks = [dict(cik=e["cik"], quarter=e["quarter"], status=e["status"], cause=e["cause"],
                   lease=e["lease"], ok=(e["check"] or {}).get("ok"),
                   literal=(e["check"] or {}).get("literal"), attributed=(e["check"] or {}).get("attributed"),
                   check_cause=(e["check"] or {}).get("cause"), error=(e["check"] or {}).get("error"),
                   replayed=(e["check"] or {}).get("replayed")) for e in provider.log]
    labels = {r["label"]: r for r in man["inputs"]}
    summary.update(
        run_id=paths.run_id, stage="m3-light", version=GRADUATE_VERSION, band=band,
        items=results, unified_transform_effect=checks,
        lease_needed=[dict(cik=c["cik"], quarter=c["quarter"], lease=c["lease"]) for c in checks
                      if (c["lease"] or {}).get("requires_lease")
                      or (c["lease"] or {}).get("currency_resolution") == "not_executed_requires_lease"],
        integration_gaps=gaps + [dict(kind="staging_output_artifacts_unbound",
                                      inputs=list(UNBOUND_STAGING_INPUTS),
                                      note="absent under the worktree config; any effect on gated "
                                           "columns is caught by unified_transform_effect")],
        reference_vintage={k: {f: labels.get(k, {}).get(f) for f in ("path", "sha256", "bytes")}
                           for k in ("output/bdc_holdings.csv", "output/private_markets_holdings.csv")},
        seconds=round(time.perf_counter() - t0, 1),
        input_verification_after=manifest.verify_inputs(man))
    write_json(paths, "results/m3_summary.json", summary)
    return summary


def main(argv=None) -> int:
    import argparse
    import sys
    from scripts.profile_pilot import protection
    from scripts.profile_pilot.paths import resolve_paths
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="ascii", errors="backslashreplace")
    parser = argparse.ArgumentParser(description="Light M3 graduation stage (Stage A).")
    parser.add_argument("command", choices=("freeze", "run"))
    parser.add_argument("--main-root", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args(argv)
    code_root = Path(__file__).resolve().parents[2]
    paths = resolve_paths(main_repo_root=args.main_root, data_root=args.data_root, code_root=code_root,
                          run_id=args.run_id)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = "verification/" + stamp + "_m3_" + args.command + "_preservation.json"
    with protection.protected_session(paths, receipt=receipt):
        result = freeze_m3(paths) if args.command == "freeze" else run_m3(paths)
    if args.command == "freeze":
        print("frozen: denominator " + str(result["denominator"]) + " | inputs ok "
              + str(result["input_verification"]["ok"]))
    else:
        print("M3: denominator " + str(result["denominator"]) + " | " + json.dumps(result["overall"]))
    print("receipt: " + str(paths.run_root / receipt))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
