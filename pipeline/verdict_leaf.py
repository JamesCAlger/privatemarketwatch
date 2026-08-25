"""Verdict-leaf schema + validator (Agent B1 adjudication output).

The verdict leaf is the shared adjudication vocabulary defined in
``docs/adjudication_architecture/B_and_C_validation_agents.md`` (section 2). The
45-bundle trial (``data/output/shadow/trial_2026-06-18/verdicts/``) emitted this
shape, but nothing in code ENFORCED it -- agent discipline did. This module is the
deterministic enforcement: the screen a B1 worker must pass before its verdict is
collected, and the check used by ``scripts/agent_b/run_review.py finalize``.

Design notes:

- The load-bearing rule is the grounding invariant: ``real_error`` requires either
  >=1 culprit_citation OR an explicit anchor-disagreement proof. No raw grounding
  -> the verdict is not admissible as ``real_error`` (forced ``ambiguous`` upstream).
  This is a HARD error here, by design -- it is the one thing the worker cannot
  satisfy by asserting confidence.
- ``mechanism`` vocabulary is checked SOFTLY (warning, not error). The trial used
  mechanisms outside the spec enum (e.g. ``cash_equivalent_leak``, a subtotal-leak
  sub-case); rejecting those would discard valid adjudications. The enum is a
  guide, not a contract -- the structure is the contract.
- Pure: this module never writes production artifacts. Callers pass paths.

ASCII-only logs/messages (Windows cp1252).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

VERDICTS = ("real_error", "false_alarm", "ambiguous")

# For an ``ambiguous`` verdict, WHY it is ambiguous. The load-bearing distinction:
#   source_checked    -- the worker read raw source and it genuinely does not decide
#                        the question. A real adjudication outcome -> human review.
#   source_unavailable -- the worker could NOT read raw source (cache miss, evidence
#                        CLI failure, sandbox/env error). NOT an adjudication outcome;
#                        a coverage/infra state -> retry/escalate, excluded from precision.
# Required on ``ambiguous`` so the two are never conflated again. A B0 auto short-circuit
# (no raw source even exists) is ``source_unavailable`` + ``auto``.
AMBIGUITY_BASES = ("source_checked", "source_unavailable")

# Spec enum (section 2) PLUS observed trial extensions. Unknown values warn, not fail.
KNOWN_MECHANISMS = frozenset({
    # spec enum
    "subtotal_leak", "dimension_double_count", "comparative_leak", "unit_scale",
    "rate_scale", "anchor_bad", "genuine_value_defect", "extraction_gap",
    "classification_lookthrough", "unknown",
    # observed trial / gold extensions (sub-cases of the above)
    "cash_equivalent_leak",
    # gold-label mechanisms for the PIK all-in convention + C113 range. NOTE these are
    # MECHANISM names, not verdicts: false_alarm_cash_leg pairs with verdict=real_error
    # (cash leg stored as interest_rate); false_alarm_rule_range pairs with
    # verdict=false_alarm (C113 0-25% too strict for CLO/structured-credit).
    "false_alarm_cash_leg", "false_alarm_rule_range",
})

# verified_override = a promoted Anchor-Adjudicator grand total (gap 1 Layer D), the
# top-priority anchor in the shadow conservation engine.
KNOWN_ANCHORS = frozenset({"companyfacts_fv", "schedule_total", "extract_total_fv",
                           "verified_override"})

# Advisory remediation classes a worker may attach to a finding so B2 starts from the
# diagnosis instead of re-deriving it. Soft vocabulary (warn, not fail). These name the
# CONSTRAINED TEMPLATE B2 would bind; the worker NEVER authors the fix itself.
# Stage prefixes (see B2/B3 build plan): structural fixes must precede value/aggregate ones.
KNOWN_FIX_CLASSES = frozenset({
    # stage 1 -- population/structure (change WHICH rows exist; must run first)
    "dedup", "subtotal_filter", "comparative_period_filter", "missing_position_add",
    "spv_lookthrough",
    # stage 2 -- per-row value/scale/mapping (change row VALUES)
    "rate_rescale", "all_pik_normalization", "column_remap", "unit_rescale",
    "classification_fix", "source_anchored_value",
    # stage 3 -- not a data fix: the rule/anchor is what is wrong
    "rule_scope", "anchor_fix", "identifier_rate_grammar",
    "unknown",
})

# Verdicts the worker may legitimately produce with no grounding.
_UNGROUNDED_OK = frozenset({"false_alarm", "ambiguous"})

REQUIRED_KEYS = ("review_id", "verdict", "confidence")


@dataclass
class VerdictReport:
    review_id: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _is_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _has_anchor_disagreement(v: dict[str, Any]) -> bool:
    """An explicit anchor-disagreement proof: an anchor was named and the observed
    value differs from the anchor value. This is the non-citation path to a valid
    ``real_error`` (a diffuse defect with no single culprit row)."""
    if not str(v.get("anchor_used") or "").strip():
        return False
    obs, anc = v.get("observed_value"), v.get("anchor_value")
    if not (_is_number(obs) and _is_number(anc)):
        return False
    return obs != anc


def _valid_citation(c: Any) -> bool:
    """A citation is usable if it carries a textual quote OR a table/row coordinate.
    cell_indices/context_id are optional (the trial omitted them)."""
    if not isinstance(c, dict):
        return False
    if str(c.get("quoted_text") or "").strip():
        return True
    return _is_number(c.get("table_index")) and _is_number(c.get("row_index"))


def _validate_findings(obj: dict[str, Any], rep: "VerdictReport") -> list[dict]:
    """Validate the optional ``findings`` list: structured sub-defects carrying the
    worker's diagnosis for B2 (mechanism + detail + fix_class + citation), so a
    multi-defect row (e.g. PIK-in-interest AND a duplicate) is not flattened into one
    ``mechanism`` + prose. ADVISORY: a hint to B2, never a patch -- B2 re-grounds and B3
    gates. Returns the list of valid citations contributed by findings (they count toward
    grounding). Soft on ``fix_class``/``mechanism`` vocabulary (warn), hard on shape."""
    findings = obj.get("findings")
    if findings is None:
        return []
    if not isinstance(findings, list):
        rep.errors.append("findings must be a list")
        return []
    cites: list[dict] = []
    for i, f in enumerate(findings):
        if not isinstance(f, dict):
            rep.errors.append(f"findings[{i}] must be an object")
            continue
        mech = str(f.get("mechanism") or "").strip()
        if mech and mech not in KNOWN_MECHANISMS:
            rep.warnings.append(f"findings[{i}].mechanism not in known vocabulary: {mech}")
        fc = str(f.get("fix_class") or "").strip()
        if fc and fc not in KNOWN_FIX_CLASSES:
            rep.warnings.append(f"findings[{i}].fix_class not in known vocabulary: {fc}")
        cit = f.get("citation")
        if cit is not None:
            if _valid_citation(cit):
                cites.append(cit)
            else:
                rep.warnings.append(f"findings[{i}].citation carries no quote or table/row coordinate")
    return cites


def validate_verdict(
    obj: Any,
    *,
    expected_review_id: str | None = None,
    known_review_ids: Iterable[str] | None = None,
) -> VerdictReport:
    """Validate one verdict object against the leaf schema + grounding invariant."""
    rid = ""
    if isinstance(obj, dict):
        rid = str(obj.get("review_id") or "").strip()
    rep = VerdictReport(review_id=rid)

    if not isinstance(obj, dict):
        rep.errors.append("verdict is not a JSON object")
        return rep

    for k in REQUIRED_KEYS:
        if k not in obj:
            rep.errors.append(f"missing required key: {k}")

    if not rid:
        rep.errors.append("review_id is empty")
    if expected_review_id is not None and rid and rid != expected_review_id:
        rep.errors.append(f"review_id {rid!r} does not match expected {expected_review_id!r}")
    if known_review_ids is not None and rid and rid not in set(known_review_ids):
        rep.errors.append(f"review_id not in worklist: {rid}")

    verdict = obj.get("verdict")
    if verdict not in VERDICTS:
        rep.errors.append(f"verdict must be one of {VERDICTS}, got {verdict!r}")

    # The ambiguity-basis invariant: an ``ambiguous`` verdict MUST say WHY (checked the
    # source vs could not reach it). A decided verdict (real_error/false_alarm) cannot
    # claim the source was unavailable -- you cannot ground or refute without reading it.
    basis = obj.get("ambiguity_basis")
    if verdict == "ambiguous":
        if basis not in AMBIGUITY_BASES:
            rep.errors.append(
                f"ambiguous requires ambiguity_basis in {AMBIGUITY_BASES}, got {basis!r}"
            )
        elif basis == "source_unavailable" and obj.get("escalate") is not True:
            rep.warnings.append("ambiguity_basis=source_unavailable should set escalate=true")
    elif verdict in ("real_error", "false_alarm") and basis == "source_unavailable":
        rep.errors.append(
            f"{verdict} cannot carry ambiguity_basis=source_unavailable (a decided "
            "verdict requires raw source); use ambiguous if source was unreadable"
        )

    conf = obj.get("confidence")
    if not _is_number(conf):
        rep.errors.append("confidence must be a number")
    elif not (0.0 <= float(conf) <= 1.0):
        rep.errors.append(f"confidence out of [0,1]: {conf}")

    if "escalate" in obj and not isinstance(obj.get("escalate"), bool):
        rep.errors.append("escalate must be a boolean")
    if "localized" in obj and not isinstance(obj.get("localized"), bool):
        rep.errors.append("localized must be a boolean")

    citations = obj.get("culprit_citations", [])
    if citations is None:
        citations = []
    if not isinstance(citations, list):
        rep.errors.append("culprit_citations must be a list")
        citations = []
    valid_citations = [c for c in citations if _valid_citation(c)]
    if citations and not valid_citations:
        rep.errors.append("culprit_citations present but none carry a quote or table/row coordinate")

    # Optional structured sub-defects (advisory hint to B2). A finding's citation also
    # grounds a real_error, so a worker may carry its evidence in findings[] instead of
    # duplicating it into culprit_citations.
    finding_citations = _validate_findings(obj, rep)

    # The grounding invariant (the keystone).
    if verdict == "real_error":
        grounded = bool(valid_citations) or bool(finding_citations) or _has_anchor_disagreement(obj)
        if not grounded:
            rep.errors.append(
                "real_error requires >=1 valid culprit_citation (or findings[].citation) OR "
                "an anchor-disagreement proof (anchor_used + observed_value != anchor_value); "
                "none present"
            )
        mech = str(obj.get("mechanism") or "").strip()
        if not mech:
            rep.errors.append("real_error requires a non-empty mechanism")
        elif mech not in KNOWN_MECHANISMS:
            rep.warnings.append(f"mechanism not in known vocabulary: {mech}")

    if verdict in _UNGROUNDED_OK and obj.get("mechanism"):
        mech = str(obj.get("mechanism")).strip()
        if mech and mech not in KNOWN_MECHANISMS:
            rep.warnings.append(f"mechanism not in known vocabulary: {mech}")

    anchor = str(obj.get("anchor_used") or "").strip()
    if anchor and anchor not in KNOWN_ANCHORS:
        rep.warnings.append(f"anchor_used not in known vocabulary: {anchor}")

    if not str(obj.get("rationale") or "").strip():
        rep.warnings.append("rationale is empty")

    return rep


def validate_dir(
    verdicts_dir: Path,
    *,
    expected_review_ids: Iterable[str] | None = None,
    restrict_to_expected: bool = False,
) -> dict[str, Any]:
    """Validate every ``*.json`` verdict in a directory.

    Returns a summary dict: per-file reports, cross-file errors (duplicate/missing),
    and aggregate counts. Read-only.

    ``restrict_to_expected`` scopes validation to the ``expected_review_ids`` files only,
    ignoring any other verdicts in the directory. Use this when the verdicts dir is SHARED
    across batches: a batch finalize should not flag another batch's verdicts as
    ``not in worklist``. Missing expected verdicts are still reported.
    """
    verdicts_dir = Path(verdicts_dir)
    expected = set(expected_review_ids) if expected_review_ids is not None else None
    reports: list[VerdictReport] = []
    seen: set[str] = set()
    cross_errors: list[str] = []

    files = sorted(verdicts_dir.glob("*.json")) if verdicts_dir.exists() else []
    if restrict_to_expected and expected is not None:
        files = [p for p in files if p.stem in expected]
    for path in files:
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            r = VerdictReport(review_id=path.stem)
            r.errors.append(f"unreadable/invalid JSON: {exc}")
            reports.append(r)
            continue
        rep = validate_verdict(obj, known_review_ids=expected)
        rid = rep.review_id or path.stem
        if rid in seen:
            cross_errors.append(f"duplicate verdict for review_id: {rid}")
        seen.add(rid)
        reports.append(rep)

    if expected is not None:
        for missing in sorted(expected - seen):
            cross_errors.append(f"missing verdict for review_id: {missing}")

    n_err_files = sum(1 for r in reports if r.errors)
    return {
        "verdicts_dir": str(verdicts_dir),
        "n_files": len(files),
        "n_valid": sum(1 for r in reports if r.ok),
        "n_error_files": n_err_files,
        "cross_errors": cross_errors,
        "reports": reports,
        "ok": n_err_files == 0 and not cross_errors,
    }


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float, float]:
    """Wilson score interval for k/n. Returns (point, lo, hi). (point=nan if n==0)."""
    if n == 0:
        return (float("nan"), 0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (p, (c - h) / d, (c + h) / d)
