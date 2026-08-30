"""Correction-leaf schema + constrained template registry (Agent B2 remediation output).

The B2 analog of ``pipeline/verdict_leaf.py``. A B2 worker emits ONE correction leaf per
``(cik, mechanism)`` packet: a CONSTRAINED template instance (audited JSON, NEVER code)
that the trial wrapper applies and the B3 held-out gate then validates by deterministic
re-run. This module is the pure deterministic schema + the registry that BOUNDS what a
template may contain. It never applies a correction and never writes production artifacts.

This is Layer 2 of the agentic-data-quality design: per-CIK corrections carrying schema,
mechanism, evidence, confidence, and an audit trail -- the agent proposes a bounded
template, deterministic checks (here) + the held-out re-run (B3) decide whether it lands.

Design (mirrors verdict_leaf):
- ``fix_class`` MUST bind a registered ``Template`` (HARD error otherwise) -- a correction
  with no template to apply is meaningless. This is stricter than verdict_leaf's soft
  ``mechanism``, on purpose.
- The template is locked down: only the registered param keys are allowed (no extras), the
  required ones must be present, declared-numeric params must be numbers, declared enums
  are checked, and EVERY string value is scanned for code/SQL/file-path injection. A
  constrained template is data, not an instruction.
- ``stage`` (the precedence stage; see B2_B3_build_plan.md) is derived from fix_class; if
  the leaf states it, it must match.

See ``docs/adjudication_architecture/B2_B3_build_plan.md``. ASCII-only.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from pipeline.verdict_leaf import KNOWN_FIX_CLASSES, _is_number, _valid_citation

# fix_class -> precedence stage. Stage 1 (structural: change WHICH rows exist) must be
# applied + the ledger regenerated BEFORE stage 2 (per-row values), which precede the
# stage-3 rule/anchor track. ``unknown`` is unstaged (0) and never bindable.
FIX_CLASS_STAGE: dict[str, int] = {
    "dedup": 1, "subtotal_filter": 1, "comparative_period_filter": 1, "missing_position_add": 1,
    "spv_lookthrough": 1, "layer_exclusion": 1,
    "rate_rescale": 2, "all_pik_normalization": 2, "column_remap": 2, "unit_rescale": 2,
    "classification_fix": 2, "source_anchored_value": 2,
    "rule_scope": 3, "anchor_fix": 3, "identifier_rate_grammar": 3,
    "unknown": 0,
}

# Bounded vocabularies for nested template structures.
# row_id (2026-08-21): the rebuild-stable content-derived id on unified holdings
# (ROW- + md5[:16] of the natural key). Preferred selector anchor -- immune to the
# issuer-text normalization drift behind the round-3/4 selector-noop refusals.
ROW_SELECTOR_KEYS = frozenset({
    "issuer_name", "bdc_investment_identifier", "row_id", "report_date",
    "table_index", "row_index",
})
_ROW_ID_RE = re.compile(r"^ROW-[0-9a-f]{16}$")
ALLOWED_POSITION_KEYS = frozenset({
    "issuer_name", "fair_value", "cost", "principal_amount", "interest_rate", "pik_rate",
    "report_date", "instrument_description", "asset_class",
    # Anti-fabrication grounding (2026-08-13, parity with agent_rule row_add): every
    # added position must name the staging row it recovers; bdc_dimensions_raw makes
    # the row countable by the gates. The 1965934/1993402 fabricated-FV incidents are
    # why these are REQUIRED, not optional.
    "source_row_id", "bdc_dimensions_raw",
})
# spv_lookthrough: one decision per consolidated legal entity.
ENTITY_KEYS = frozenset({"legal_entity", "decision"})
ENTITY_DECISIONS = frozenset({"use_equity", "keep_lookthrough"})
_RATE_FIELDS = frozenset({"interest_rate", "pik_rate", "basis_spread"})
_CLASS_FIELDS = frozenset({"asset_class", "index_classification", "exposure_type"})
# 2026-08-13 (q4b2exp round-1 lesson): remap/rescale fields must be UNIFIED-FRAME
# columns. Round 1 accepted any string, so workers named the FILING's columns
# ("spread", "footnotes", "Fa") and every leaf failed its applier. The template is a
# contract with the holdings schema, not a description of the source table.
_REMAP_FIELDS = frozenset({
    "fair_value", "cost", "principal_amount", "shares_held",
    "interest_rate", "pik_rate", "basis_spread", "pct_of_net_assets",
})
# 2026-08-13 (blast-radius lesson): stage-2 value fixes MUST declare the quarters they
# are evidenced for -- explicit dates, never "all". Unscoped round-2 fixes rewrote
# already-correct 2023 history (Goldman principal x1000 et al.). The applier enforces
# the scope structurally; the gate proves off-scope invariance.
STAGE2_SCOPED_CLASSES = frozenset({
    "rate_rescale", "unit_rescale", "column_remap", "classification_fix",
    "all_pik_normalization", "source_anchored_value",
})
# source_anchored_value (2026-08-21): the general-but-verifiable stage-2 class. The
# worker never authors a number -- each assertion POINTS at a filing cell and the
# verifier (pipeline.source_anchor_verify, run at intake + gate) re-parses the cached
# filing and refuses the leaf unless the cell contains exactly that value AND >=2
# witness cells in the same row match the position's known-correct extracted values
# (the row-fingerprint defense against filer-specific parse corruption).
ASSERTION_SOURCE_KEYS = frozenset({
    "accession_number", "table_index", "row_index", "cell_index",
    "quoted_text", "value", "unit_multiplier",
})
ASSERTION_SOURCE_REQUIRED = frozenset({
    "accession_number", "table_index", "row_index", "cell_index", "quoted_text", "value",
})
WITNESS_KEYS = frozenset({"cell_index", "field", "value"})
UNIT_MULTIPLIERS = frozenset({1, 1000, 1000000})
MAX_ASSERTIONS = 20
MIN_WITNESSES = 2
_ACCESSION_RE = re.compile(r"^\d{10}-?\d{2}-?\d{6}$")
_QUARTER_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass(frozen=True)
class Template:
    """The bound for one fix_class's ``template`` params."""
    stage: int
    apply_fn: str                       # intended applier in the trial wrapper (named, not called here)
    required: frozenset[str]            # param keys that MUST be present
    allowed: frozenset[str]             # the FULL set of permitted param keys (extras rejected)
    numeric: frozenset[str] = frozenset()           # params that must be numbers
    enums: dict[str, frozenset[str]] = field(default_factory=dict)  # param -> allowed values


TEMPLATE_REGISTRY: dict[str, Template] = {
    # --- stage 1: structural ---
    # row_selector added 2026-08-21 (q4b2r4an lesson: a match-key-only dedup for two
    # cited AAH rows collapsed 563 duplicate groups; a selector bounds the blast
    # radius to the grounded rows).
    "dedup": Template(
        1, "apply_dedup", frozenset({"match_fields"}),
        frozenset({"match_fields", "keep", "row_selector"}),
        enums={"keep": frozenset({"first", "last"})}),
    "subtotal_filter": Template(
        1, "apply_subtotal_filter", frozenset({"patterns"}), frozenset({"patterns", "match_mode"}),
        enums={"match_mode": frozenset({"exact", "contains"})}),
    "comparative_period_filter": Template(
        1, "apply_comparative_filter", frozenset({"report_date"}), frozenset({"report_date"})),
    "missing_position_add": Template(
        1, "apply_missing_position_add", frozenset({"positions"}), frozenset({"positions"})),
    "spv_lookthrough": Template(
        1, "apply_spv_lookthrough", frozenset({"entities"}), frozenset({"entities"})),
    # Row-provenance layer exclusion (spec 2026-08-30): closed structural-selector
    # whitelist + mandatory anchor-equality proof (enforced at the B3 value gate).
    "layer_exclusion": Template(
        1, "apply_layer_exclusion",
        frozenset({"scope_quarters", "selector", "anchor_proof"}),
        frozenset({"scope_quarters", "selector", "anchor_proof"})),
    # --- stage 2: per-row value/scale/mapping ---
    "rate_rescale": Template(
        2, "apply_rate_rescale", frozenset({"field", "factor"}),
        frozenset({"field", "factor", "row_selector"}),
        numeric=frozenset({"factor"}), enums={"field": _RATE_FIELDS}),
    "all_pik_normalization": Template(
        2, "apply_all_pik_normalization", frozenset({"row_selector"}),
        frozenset({"row_selector", "cash_rate", "pik_rate", "set_interest_to_cash"}),
        numeric=frozenset({"cash_rate", "pik_rate"})),
    "column_remap": Template(
        2, "apply_column_remap", frozenset({"from_field", "to_field"}),
        frozenset({"from_field", "to_field", "row_selector"}),
        enums={"from_field": _REMAP_FIELDS, "to_field": _REMAP_FIELDS}),
    "unit_rescale": Template(
        2, "apply_unit_rescale", frozenset({"field", "factor"}),
        frozenset({"field", "factor", "row_selector"}), numeric=frozenset({"factor"}),
        enums={"field": _REMAP_FIELDS}),
    "classification_fix": Template(
        2, "apply_classification_fix", frozenset({"field", "value"}),
        frozenset({"field", "value", "row_selector"}), enums={"field": _CLASS_FIELDS}),
    "source_anchored_value": Template(
        2, "apply_source_anchored_value", frozenset({"assertions"}),
        frozenset({"assertions"})),
    # --- stage 3: rule / anchor (not a holdings-data correction) ---
    "rule_scope": Template(
        3, "propose_rule_scope", frozenset({"rule_name"}),
        frozenset({"rule_name", "exclude_asset_class", "band"})),
    "anchor_fix": Template(
        3, "propose_anchor_fix", frozenset({"anchor_used", "corrected_anchor_value"}),
        frozenset({"anchor_used", "corrected_anchor_value"}),
        numeric=frozenset({"corrected_anchor_value"})),
    # identifier_rate_grammar (2026-08-21): route a rate-in-identifier dialect defect to
    # the Agent A lane (repair/extend data/overrides/identifier_rate_grammars/<cik>.json,
    # then the deterministic A3 gate). A PROPOSAL, never applied to holdings data --
    # the sav-canary escalations (0001588272 "Fixed + 1600" -> extracted 1.6) showed
    # these defects previously died in the human basket with no routable class.
    # dialect_example = the verbatim identifier token evidencing the dialect;
    # target_field = the unified-frame field the dialect populates;
    # observed_value = the wrong extracted value (optional, evidence);
    # expected_semantics = short statement of what the token means (optional).
    "identifier_rate_grammar": Template(
        3, "propose_identifier_grammar_fix",
        frozenset({"dialect_example", "target_field"}),
        frozenset({"dialect_example", "target_field", "observed_value",
                   "expected_semantics"}),
        numeric=frozenset({"observed_value"}),
        enums={"target_field": _REMAP_FIELDS}),
}

REQUIRED_KEYS = ("cik", "mechanism", "fix_class", "template", "source_review_ids",
                 "evidence_citations", "confidence")

_CIK_RE = re.compile(r"^\d{1,10}$")
# Defense-in-depth: a constrained template's string VALUES must never carry code/SQL/paths.
_FORBIDDEN_CODE_RE = re.compile(
    r"(?i)\b(select|insert|update|delete|drop|alter|create)\b[\s\S]*\b(from|into|table|set|where)\b"
    r"|\bimport\s+\w|\bdef\s+\w+\s*\(|\blambda\b|subprocess|os\.system|__import__|\beval\s*\(|\bexec\s*\(")
_FORBIDDEN_PATH_RE = re.compile(r"(?i)\.(py|sql|sh|ps1|exe|csv|json|parquet)\b|data/output|[a-z]:\\")


@dataclass
class CorrectionReport:
    cik: str
    mechanism: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _scan_for_injection(node: Any, rep: CorrectionReport, path: str = "template") -> None:
    """Recursively scan every string value for code/SQL/file-path content."""
    if isinstance(node, dict):
        for k, v in node.items():
            _scan_for_injection(v, rep, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            _scan_for_injection(v, rep, f"{path}[{i}]")
    elif isinstance(node, str):
        if _FORBIDDEN_CODE_RE.search(node):
            rep.errors.append(f"{path}: value looks like code/SQL (forbidden in a constrained template)")
        elif _FORBIDDEN_PATH_RE.search(node):
            rep.errors.append(f"{path}: value looks like a file path (forbidden in a constrained template)")


def _validate_one_selector(sel: Any, rep: CorrectionReport, path: str) -> None:
    if not isinstance(sel, dict):
        rep.errors.append(f"{path} must be an object")
        return
    if not sel:
        rep.errors.append(f"{path} must identify at least one field")
        return
    bad = set(sel) - ROW_SELECTOR_KEYS
    if bad:
        rep.errors.append(f"{path} has unknown key(s): {sorted(bad)}")
    # 2026-08-13 (q4b2exp round-1 lesson): coordinates identify EVIDENCE, not
    # holdings rows -- a selector must carry at least one matchable identity key.
    if not ({"issuer_name", "bdc_investment_identifier", "row_id"} & set(sel)):
        rep.errors.append(
            f"{path} must include row_id, issuer_name, or "
            "bdc_investment_identifier (table/row coordinates cannot select "
            "holdings rows)")
    # row_id is a fixed-format hash; a malformed one can only be a typo or
    # fabrication and would silently select nothing -- reject at the screen.
    if "row_id" in sel and not _ROW_ID_RE.match(str(sel.get("row_id") or "").strip()):
        rep.errors.append(
            f"{path}.row_id must match ROW-<16 hex chars> "
            "(copy it verbatim from the grounded identifier list)")


def _validate_row_selector(sel: Any, rep: CorrectionReport) -> None:
    """A row_selector is one selector object OR a non-empty list of selector objects
    (OR-combined by the applier). The list form (2026-08-21, q4b2r4an lesson) lets a
    leaf bind every cited row instead of widening scope to a whole quarter or fixing
    one row and abandoning the rest."""
    if isinstance(sel, list):
        if not sel:
            rep.errors.append("template.row_selector list must be non-empty")
            return
        for i, s in enumerate(sel):
            _validate_one_selector(s, rep, f"template.row_selector[{i}]")
        return
    _validate_one_selector(sel, rep, "template.row_selector")


def _validate_assertions(assertions: Any, rep: CorrectionReport) -> None:
    """source_anchored_value assertions. Each points at a filing cell (never authors a
    number the filing does not contain) and carries >=2 witness cells binding the cited
    row to the position's known-correct extracted values. The verifier re-parses the
    cached filing and refuses on any mismatch; this validates only structure."""
    if not isinstance(assertions, list) or not assertions:
        rep.errors.append("template.assertions must be a non-empty list")
        return
    if len(assertions) > MAX_ASSERTIONS:
        rep.errors.append(f"template.assertions exceeds max {MAX_ASSERTIONS} per leaf")
    for i, a in enumerate(assertions):
        path = f"template.assertions[{i}]"
        if not isinstance(a, dict):
            rep.errors.append(f"{path} must be an object")
            continue
        bad = set(a) - {"row_selector", "field", "source", "witnesses"}
        if bad:
            rep.errors.append(f"{path} has unknown key(s): {sorted(bad)}")
        _validate_row_selector(a.get("row_selector"), rep)
        field = str(a.get("field") or "")
        if field not in _REMAP_FIELDS:
            rep.errors.append(f"{path}.field must be one of {sorted(_REMAP_FIELDS)}, got {field!r}")
        src = a.get("source")
        if not isinstance(src, dict):
            rep.errors.append(f"{path}.source must be an object")
            src = {}
        else:
            bad = set(src) - ASSERTION_SOURCE_KEYS
            if bad:
                rep.errors.append(f"{path}.source has unknown key(s): {sorted(bad)}")
            missing = ASSERTION_SOURCE_REQUIRED - set(src)
            if missing:
                rep.errors.append(f"{path}.source missing required key(s): {sorted(missing)}")
            for k in ("table_index", "row_index", "cell_index"):
                v = src.get(k)
                if k in src and (not isinstance(v, int) or isinstance(v, bool) or v < 0):
                    rep.errors.append(f"{path}.source.{k} must be a non-negative integer")
            if "accession_number" in src and not _ACCESSION_RE.match(
                    str(src.get("accession_number") or "").strip()):
                rep.errors.append(
                    f"{path}.source.accession_number must be an SEC accession "
                    "(copy it from the evidence CLI overview)")
            if not str(src.get("quoted_text") or "").strip():
                rep.errors.append(f"{path}.source.quoted_text must be the cited cell's text")
            if not _is_number(src.get("value")):
                rep.errors.append(f"{path}.source.value must be a number (the literal filing value)")
            mult = src.get("unit_multiplier", 1)
            if mult not in UNIT_MULTIPLIERS:
                rep.errors.append(
                    f"{path}.source.unit_multiplier must be one of {sorted(UNIT_MULTIPLIERS)}")
            elif field in _RATE_FIELDS and mult != 1:
                rep.errors.append(
                    f"{path}.source.unit_multiplier must be 1 for rate field {field!r}")
        witnesses = a.get("witnesses")
        if not isinstance(witnesses, list) or len(witnesses) < MIN_WITNESSES:
            rep.errors.append(
                f"{path}.witnesses must list >= {MIN_WITNESSES} known-value cells in the "
                "cited row (the row-fingerprint that proves the parse describes the "
                "same position)")
            continue
        for j, w in enumerate(witnesses):
            wpath = f"{path}.witnesses[{j}]"
            if not isinstance(w, dict):
                rep.errors.append(f"{wpath} must be an object")
                continue
            if set(w) != WITNESS_KEYS:
                rep.errors.append(f"{wpath} must have exactly keys {sorted(WITNESS_KEYS)}")
                continue
            if not isinstance(w.get("cell_index"), int) or isinstance(w.get("cell_index"), bool) \
                    or w["cell_index"] < 0:
                rep.errors.append(f"{wpath}.cell_index must be a non-negative integer")
            if str(w.get("field") or "") not in _REMAP_FIELDS:
                rep.errors.append(f"{wpath}.field must be one of {sorted(_REMAP_FIELDS)}")
            elif str(w.get("field")) == field:
                rep.errors.append(
                    f"{wpath}.field must differ from the asserted field {field!r} "
                    "(witnessing with the value being corrected is circular)")
            if not _is_number(w.get("value")):
                rep.errors.append(f"{wpath}.value must be a number")
            if isinstance(src, dict) and w.get("cell_index") == src.get("cell_index"):
                rep.errors.append(
                    f"{wpath}.cell_index must differ from the asserted source cell")


# layer_exclusion nested bounds (spec 2026-08-30). Selector: closed STRUCTURAL
# whitelist, exact-match only. anchor_proof: deterministic gap kinds, positive
# numeric cited_value, non-empty citation. tolerance_pct is capped harder at the
# gate (0.5%); here we only require it be a number if present.
LAYER_EXCLUSION_SELECTOR_KEYS = frozenset({"axis_profile", "source_table", "is_subsidiary"})
LAYER_EXCLUSION_PROOF_KINDS = frozenset({"named_anchor_gap", "companyfacts_fv_gap"})
_LAYER_PROOF_KEYS = frozenset({"kind", "cited_value", "tolerance_pct", "citation"})


def _validate_layer_exclusion(template: dict, rep: CorrectionReport) -> None:
    quarters = template.get("scope_quarters")
    if not isinstance(quarters, list) or not quarters or not all(
            isinstance(q, str) and _QUARTER_RE.match(q) for q in quarters):
        rep.errors.append("template.scope_quarters must be a non-empty list of YYYY-MM-DD dates")
    sel = template.get("selector")
    if not isinstance(sel, dict):
        rep.errors.append("template.selector must be an object")
    else:
        bad = set(sel) - LAYER_EXCLUSION_SELECTOR_KEYS
        if bad:
            rep.errors.append(
                f"template.selector key(s) outside the closed whitelist: {sorted(bad)}")
        if not any(v is not None for k, v in sel.items()
                   if k in LAYER_EXCLUSION_SELECTOR_KEYS):
            rep.errors.append("template.selector needs at least one non-null whitelisted field")
    proof = template.get("anchor_proof")
    if not isinstance(proof, dict):
        rep.errors.append("template.anchor_proof is required (fail-closed)")
        return
    bad = set(proof) - _LAYER_PROOF_KEYS
    if bad:
        rep.errors.append(f"template.anchor_proof has unknown key(s): {sorted(bad)}")
    if str(proof.get("kind")) not in LAYER_EXCLUSION_PROOF_KINDS:
        rep.errors.append(
            f"template.anchor_proof.kind must be one of {sorted(LAYER_EXCLUSION_PROOF_KINDS)}")
    if not _is_number(proof.get("cited_value")) or float(proof.get("cited_value") or 0) <= 0:
        rep.errors.append("template.anchor_proof.cited_value must be a positive number")
    if "tolerance_pct" in proof and not _is_number(proof.get("tolerance_pct")):
        rep.errors.append("template.anchor_proof.tolerance_pct must be a number")
    if not str(proof.get("citation") or "").strip():
        rep.errors.append("template.anchor_proof.citation is required")


def _validate_template(fix_class: str, template: Any, tpl: Template, rep: CorrectionReport) -> None:
    if not isinstance(template, dict):
        rep.errors.append("template must be an object")
        return
    keys = set(template)
    extra = keys - tpl.allowed
    if extra:
        rep.errors.append(f"template has unexpected param(s) for {fix_class}: {sorted(extra)}")
    missing = tpl.required - keys
    if missing:
        rep.errors.append(f"template missing required param(s) for {fix_class}: {sorted(missing)}")
    for k in tpl.numeric & keys:
        if not _is_number(template.get(k)):
            rep.errors.append(f"template.{k} must be a number")
    for k, allowed_vals in tpl.enums.items():
        if k in keys and str(template.get(k)) not in allowed_vals:
            rep.errors.append(f"template.{k} must be one of {sorted(allowed_vals)}, got {template.get(k)!r}")
    # Nested structures.
    if fix_class == "layer_exclusion":
        _validate_layer_exclusion(template, rep)
    if "row_selector" in keys:
        _validate_row_selector(template.get("row_selector"), rep)
    if "assertions" in keys:
        _validate_assertions(template.get("assertions"), rep)
    if "positions" in keys:
        positions = template.get("positions")
        if not isinstance(positions, list) or not positions:
            rep.errors.append("template.positions must be a non-empty list")
        else:
            for i, p in enumerate(positions):
                if not isinstance(p, dict):
                    rep.errors.append(f"template.positions[{i}] must be an object")
                    continue
                bad = set(p) - ALLOWED_POSITION_KEYS
                if bad:
                    rep.errors.append(f"template.positions[{i}] has unknown key(s): {sorted(bad)}")
                for req in ("issuer_name", "fair_value", "report_date",
                            "source_row_id", "bdc_dimensions_raw"):
                    if not str(p.get(req) or "").strip() and not _is_number(p.get(req)):
                        rep.errors.append(f"template.positions[{i}] missing {req}")
    if "entities" in keys:
        ents = template.get("entities")
        if not isinstance(ents, list) or not ents:
            rep.errors.append("template.entities must be a non-empty list")
        else:
            for i, e in enumerate(ents):
                if not isinstance(e, dict):
                    rep.errors.append(f"template.entities[{i}] must be an object")
                    continue
                bad = set(e) - ENTITY_KEYS
                if bad:
                    rep.errors.append(f"template.entities[{i}] has unknown key(s): {sorted(bad)}")
                if not str(e.get("legal_entity") or "").strip():
                    rep.errors.append(f"template.entities[{i}] missing legal_entity")
                if str(e.get("decision")) not in ENTITY_DECISIONS:
                    rep.errors.append(
                        f"template.entities[{i}].decision must be one of {sorted(ENTITY_DECISIONS)}")
    _scan_for_injection(template, rep)


def validate_correction(
    obj: Any, *, expected_cik: str | None = None, expected_fix_class: str | None = None,
) -> CorrectionReport:
    """Validate one correction leaf against the schema + the template registry."""
    cik = str(obj.get("cik")) if isinstance(obj, dict) else ""
    mech = str(obj.get("mechanism") or "") if isinstance(obj, dict) else ""
    rep = CorrectionReport(cik=cik, mechanism=mech)

    if not isinstance(obj, dict):
        rep.errors.append("correction is not a JSON object")
        return rep

    for k in REQUIRED_KEYS:
        if k not in obj:
            rep.errors.append(f"missing required key: {k}")

    if not _CIK_RE.match(str(obj.get("cik") or "").strip()):
        rep.errors.append(f"cik must be 1-10 digits, got {obj.get('cik')!r}")
    if expected_cik is not None and str(obj.get("cik") or "").strip().lstrip("0") != str(expected_cik).lstrip("0"):
        rep.errors.append(f"cik {obj.get('cik')!r} does not match expected {expected_cik!r}")

    if not mech:
        rep.errors.append("mechanism is empty")

    fix_class = str(obj.get("fix_class") or "").strip()
    if expected_fix_class is not None and fix_class != str(expected_fix_class):
        rep.errors.append(
            f"fix_class {fix_class!r} does not match expected {str(expected_fix_class)!r}"
        )
    tpl = TEMPLATE_REGISTRY.get(fix_class)
    if fix_class not in KNOWN_FIX_CLASSES:
        rep.errors.append(f"fix_class not in known vocabulary: {fix_class!r}")
    if tpl is None:
        rep.errors.append(f"fix_class {fix_class!r} has no registered template to bind")
    else:
        # stage must match the registry if stated.
        if "stage" in obj and obj.get("stage") != tpl.stage:
            rep.errors.append(f"stage {obj.get('stage')!r} does not match fix_class {fix_class} (stage {tpl.stage})")
        _validate_template(fix_class, obj.get("template"), tpl, rep)

    if fix_class in STAGE2_SCOPED_CLASSES:
        quarters = (obj.get("scope") or {}).get("quarters") if isinstance(obj.get("scope"), dict) else None
        if not isinstance(quarters, list) or not quarters:
            rep.errors.append(
                f"{fix_class} requires scope.quarters: the explicit list of quarters "
                "this fix is evidenced for (a value fix may only touch quarters whose "
                "filings show the defect)")
        else:
            bad = [q for q in quarters if not _QUARTER_RE.match(str(q or ""))]
            if bad:
                rep.errors.append(
                    f"scope.quarters must be explicit YYYY-MM-DD dates (never 'all'); "
                    f"got {bad}")

    srids = obj.get("source_review_ids")
    if not isinstance(srids, list) or not [s for s in srids if str(s or "").strip()]:
        rep.errors.append("source_review_ids must be a non-empty list of review_ids")

    cites = obj.get("evidence_citations", [])
    if not isinstance(cites, list):
        rep.errors.append("evidence_citations must be a list")
        cites = []
    if not [c for c in cites if _valid_citation(c)]:
        rep.errors.append("evidence_citations must carry >=1 valid citation (quote or table/row coordinate)")

    conf = obj.get("confidence")
    if not _is_number(conf):
        rep.errors.append("confidence must be a number")
    elif not (0.0 <= float(conf) <= 1.0):
        rep.errors.append(f"confidence out of [0,1]: {conf}")

    if not str(obj.get("rationale") or "").strip():
        rep.warnings.append("rationale is empty")

    return rep


def stage_for(fix_class: str) -> int:
    """The precedence stage of a fix_class (0 = unstaged/unknown)."""
    return FIX_CLASS_STAGE.get(fix_class, 0)


# --- escalation leaf (2026-08-21) -------------------------------------------------
# The alternate worker output for a packet whose binding fix_class CANNOT express the
# defect the worker verified (q4b2r4an lessons: the NAV-per-share defect forced a
# factor-1.0 no-op; the revolver row-shape defect has no fix_class at all). An
# escalation is a DIAGNOSIS, never applied to data -- it routes the packet to the
# human/template-authoring basket instead of producing a plausible-looking no-op.
ESCALATION_REQUIRED_KEYS = ("cik", "fix_class", "mechanism", "diagnosis",
                            "evidence_citations", "confidence")
ESCALATION_SUFFIX = ".escalation.json"


def validate_escalation(
    obj: Any, *, expected_cik: str | None = None, expected_fix_class: str | None = None,
) -> CorrectionReport:
    """Validate one escalation leaf. ``fix_class`` is the REQUESTED (inexpressible)
    class, kept binding so the escalation stays joined to its packet. ``diagnosis``
    must state the verified defect with the filing-vs-extracted evidence; the optional
    ``suggested_fix_class`` is free-vocabulary (it may name a class that does not
    exist yet -- that is the point)."""
    cik = str(obj.get("cik")) if isinstance(obj, dict) else ""
    mech = str(obj.get("mechanism") or "") if isinstance(obj, dict) else ""
    rep = CorrectionReport(cik=cik, mechanism=mech)
    if not isinstance(obj, dict):
        rep.errors.append("escalation is not a JSON object")
        return rep
    for k in ESCALATION_REQUIRED_KEYS:
        if k not in obj:
            rep.errors.append(f"missing required key: {k}")
    if not _CIK_RE.match(str(obj.get("cik") or "").strip()):
        rep.errors.append(f"cik must be 1-10 digits, got {obj.get('cik')!r}")
    if expected_cik is not None and \
            str(obj.get("cik") or "").strip().lstrip("0") != str(expected_cik).lstrip("0"):
        rep.errors.append(f"cik {obj.get('cik')!r} does not match expected {expected_cik!r}")
    if expected_fix_class is not None and \
            str(obj.get("fix_class") or "").strip() != str(expected_fix_class):
        rep.errors.append(
            f"fix_class {obj.get('fix_class')!r} does not match expected "
            f"{str(expected_fix_class)!r} (an escalation keeps the packet's requested class)")
    if len(str(obj.get("diagnosis") or "").strip()) < 40:
        rep.errors.append(
            "diagnosis must state the verified defect with filing-vs-extracted "
            "evidence (>= 40 chars)")
    cites = obj.get("evidence_citations", [])
    if not isinstance(cites, list) or not [c for c in cites if _valid_citation(c)]:
        rep.errors.append("evidence_citations must carry >=1 valid citation (quote or table/row coordinate)")
    conf = obj.get("confidence")
    if not _is_number(conf):
        rep.errors.append("confidence must be a number")
    elif not (0.0 <= float(conf) <= 1.0):
        rep.errors.append(f"confidence out of [0,1]: {conf}")
    return rep


def validate_dir(corrections_dir: Path) -> dict[str, Any]:
    """Validate every ``*.json`` correction under ``corrections_dir`` (recursively, since
    corrections live at ``<cik>/<mechanism>.json``). Read-only."""
    corrections_dir = Path(corrections_dir)
    reports: list[CorrectionReport] = []
    files = sorted(p for p in corrections_dir.glob("**/*.json")
                   if not p.name.endswith(ESCALATION_SUFFIX)) if corrections_dir.exists() else []
    for path in files:
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            r = CorrectionReport(cik=path.parent.name, mechanism=path.stem)
            r.errors.append(f"unreadable/invalid JSON: {exc}")
            reports.append(r)
            continue
        reports.append(validate_correction(obj))
    n_err = sum(1 for r in reports if r.errors)
    return {
        "corrections_dir": str(corrections_dir),
        "n_files": len(files),
        "n_valid": sum(1 for r in reports if r.ok),
        "n_error_files": n_err,
        "reports": reports,
        "ok": n_err == 0,
    }
