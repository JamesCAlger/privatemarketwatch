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
    "spv_lookthrough": 1,
    "rate_rescale": 2, "all_pik_normalization": 2, "column_remap": 2, "unit_rescale": 2,
    "classification_fix": 2,
    "rule_scope": 3, "anchor_fix": 3,
    "unknown": 0,
}

# Bounded vocabularies for nested template structures.
ROW_SELECTOR_KEYS = frozenset({
    "issuer_name", "bdc_investment_identifier", "report_date", "table_index", "row_index",
})
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
    "all_pik_normalization",
})
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
    "dedup": Template(
        1, "apply_dedup", frozenset({"match_fields"}), frozenset({"match_fields", "keep"}),
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
    # --- stage 3: rule / anchor (not a holdings-data correction) ---
    "rule_scope": Template(
        3, "propose_rule_scope", frozenset({"rule_name"}),
        frozenset({"rule_name", "exclude_asset_class", "band"})),
    "anchor_fix": Template(
        3, "propose_anchor_fix", frozenset({"anchor_used", "corrected_anchor_value"}),
        frozenset({"anchor_used", "corrected_anchor_value"}),
        numeric=frozenset({"corrected_anchor_value"})),
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
    if "row_selector" in keys:
        sel = template.get("row_selector")
        if not isinstance(sel, dict):
            rep.errors.append("template.row_selector must be an object")
        elif not sel:
            rep.errors.append("template.row_selector must identify at least one field")
        else:
            bad = set(sel) - ROW_SELECTOR_KEYS
            if bad:
                rep.errors.append(f"template.row_selector has unknown key(s): {sorted(bad)}")
            # 2026-08-13 (q4b2exp round-1 lesson): coordinates identify EVIDENCE, not
            # holdings rows -- a selector must carry at least one matchable identity key.
            if not ({"issuer_name", "bdc_investment_identifier"} & set(sel)):
                rep.errors.append(
                    "template.row_selector must include issuer_name or "
                    "bdc_investment_identifier (table/row coordinates cannot select "
                    "holdings rows)")
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


def validate_dir(corrections_dir: Path) -> dict[str, Any]:
    """Validate every ``*.json`` correction under ``corrections_dir`` (recursively, since
    corrections live at ``<cik>/<mechanism>.json``). Read-only."""
    corrections_dir = Path(corrections_dir)
    reports: list[CorrectionReport] = []
    files = sorted(corrections_dir.glob("**/*.json")) if corrections_dir.exists() else []
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
