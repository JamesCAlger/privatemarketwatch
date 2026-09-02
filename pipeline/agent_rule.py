"""Agent-authored AUDITABLE rule: the output of the agentic investigation path.

The agent investigates a conservation discrepancy (with agent_data_query + evidence_cli),
finds the root cause, and authors one or more RULES here -- NOT a templated mechanism from a
fixed registry, and NOT routed through the deterministic B2 battery. A rule is an explicit,
reviewable predicate over the holdings columns plus its scope, evidence, rationale, and the
per-quarter measured impact. It reads like code (a SQL boolean predicate), a human can audit
it, and a GENERAL applier executes it deterministically. B3 (the conservation re-check) gates
the result -- the un-gameable validator stays; only the mechanism-deciding is now agentic.

Rule (one JSON object)::

    {"cik": "1377936", "rule_id": "saratoga-clo-2013-lookthrough",
     "rule_type": "row_exclusion", "action": "exclude",
     "predicate_sql": "bdc_dimensions_raw LIKE '%legalentityaxis=SaratogaInvestmentCorpCLO20131LtdMember%'",
     "scope": {"quarters": ["all"]},
     "evidence": [{"source": "filing", "quote": "Consolidated Schedule of Investments ... CLO 2013-1"}],
     "rationale": "Levered consolidated CLO; collateral funded by third-party notes; parent equity ~0.",
     "measured_impact": {"2026-02-28": {"rows": 246, "fv": 376435958, "residual_before": 358770363,
                                        "residual_after": -17665595}},
     "confidence": 0.9}

ASCII-only. The applier is read-only over a registered frame; it only SELECTS which rows to drop.
"""
from __future__ import annotations

import ast
import json
import operator as _op
import re
from pathlib import Path

import duckdb
import pandas as pd

from pipeline.agent_b_held_out import gate_correction

# Common keys every rule carries; per-type keys (predicate_sql / field+factor / match_fields+keep)
# are checked in validate_rule by rule_type.
REQUIRED_COMMON = ("cik", "rule_id", "rule_type", "action", "scope", "evidence",
                   "rationale", "confidence")
# rule_type -> its required action verb.
_ACTION_FOR = {"row_exclusion": "exclude", "value_rescale": "rescale", "dedup": "dedup",
               "row_add": "add", "value_expression": "set"}
RULE_TYPES = frozenset(_ACTION_FOR)
ACTIONS = frozenset(_ACTION_FOR.values())
# Numeric/value fields the agent may RESCALE (fix a scale error) -- never identity/date columns.
RESCALE_FIELDS = frozenset({"fair_value", "cost", "principal_amount", "shares_held",
                            "interest_rate", "pik_rate", "basis_spread", "pct_of_net_assets"})
# Columns the agent may use to DEFINE a duplicate key for dedup.
DEDUP_KEY_FIELDS = frozenset({"report_date", "issuer_name", "instrument_description", "fair_value",
                              "cost", "principal_amount", "cusip", "bdc_investment_identifier",
                              "bdc_dimensions_raw", "asset_category", "index_classification"})
# Fields a recovered (added-back) position may carry. `source_row_id` (the iXBRL/staging row the
# value is recovered FROM) is mandatory grounding -- an add must point at a real source row, not
# fabricate one. `bdc_dimensions_raw` is mandatory so the added row is COUNTED by the gate.
ADD_POSITION_KEYS = frozenset({"report_date", "fair_value", "cost", "principal_amount",
                               "shares_held", "issuer_name", "instrument_description",
                               "bdc_dimensions_raw", "bdc_investment_identifier", "source_row_id"})
# The predicate is a boolean SQL expression -- forbid anything that is not pure row-selection.
_PRED_FORBIDDEN = re.compile(
    r"(?i)\b(attach|detach|copy|install|load|pragma|set|create|insert|update|delete|drop|"
    r"alter|truncate|export|import|call|read_csv|read_csv_auto|read_parquet|read_json|"
    r"read_text|parquet_scan|csv_scan|glob|system|select)\b|;|--|/\*|\*/")
_CIK_RE = re.compile(r"^\d{1,10}$")

# value_expression: a BOUNDED arithmetic formula (gap-5 vocab). The agent may set a numeric field
# to a pure expression over the row's OWN whitelisted numeric columns + numeric literals (+ - * /
# and parentheses) -- e.g. fix a mis-derived fair_value via `principal_amount * 0.985`. The
# generality lives in a VALIDATED AST (same safety model as predicate_sql), NOT agent-authored
# code, so it stays deterministic + reviewable. Anything beyond this escalates (proposed_mechanism).
EXPR_COLUMNS = RESCALE_FIELDS                                  # columns an expression may reference
_EXPR_BINOPS = {ast.Add: _op.add, ast.Sub: _op.sub, ast.Mult: _op.mul, ast.Div: _op.truediv}
_EXPR_UNARY = {ast.USub: _op.neg, ast.UAdd: _op.pos}


def _expr_errors(expr) -> list[str]:
    """Validate a value expression: pure arithmetic over whitelisted numeric columns + numeric
    literals. Reject calls, attributes, subscripts, comparisons, unknown names, non-numeric."""
    s = str(expr or "").strip()
    if not s:
        return ["expression is empty"]
    try:
        tree = ast.parse(s, mode="eval")
    except SyntaxError as e:
        return [f"expression does not parse ({e.msg})"]
    errs: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Load)):
            continue
        if isinstance(node, tuple(_EXPR_BINOPS) + tuple(_EXPR_UNARY)):
            continue
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
                errs.append("only numeric literals are allowed in an expression")
        elif isinstance(node, ast.Name):
            if node.id not in EXPR_COLUMNS:
                errs.append(f"expression references unknown column {node.id!r}; "
                            f"allowed: {sorted(EXPR_COLUMNS)}")
        else:
            errs.append(f"disallowed expression element: {type(node).__name__}")
    return errs


def _eval_expr(expr: str, frame: pd.DataFrame) -> pd.Series:
    """Evaluate a validated expression vectorized over ``frame`` (one value per row)."""
    body = ast.parse(str(expr), mode="eval").body

    def ev(n):
        if isinstance(n, ast.BinOp):
            return _EXPR_BINOPS[type(n.op)](ev(n.left), ev(n.right))
        if isinstance(n, ast.UnaryOp):
            return _EXPR_UNARY[type(n.op)](ev(n.operand))
        if isinstance(n, ast.Constant):
            return float(n.value)
        if isinstance(n, ast.Name):
            return pd.to_numeric(frame[n.id], errors="coerce")
        raise ValueError(f"bad expression node {type(n).__name__}")

    res = ev(body)
    if not isinstance(res, pd.Series):                        # constant-only expression
        res = pd.Series(res, index=frame.index)
    return res


def _rule_impact(audit: dict):
    """Rows actually changed by a rule (None if not an applier audit). 0 => no-op."""
    for k in ("rows_excluded", "rows_rescaled", "rows_set", "rows_added"):
        if k in audit:
            return int(audit[k] or 0)
    return None


def validate_rule(obj) -> list[str]:
    """Return reasons the rule is invalid (empty list = valid). Dispatches per rule_type:
    row_exclusion (predicate), value_rescale (predicate + field + factor), dedup (match_fields +
    keep, optional predicate to scope candidates)."""
    errs: list[str] = []
    if not isinstance(obj, dict):
        return ["rule is not a JSON object"]
    for k in REQUIRED_COMMON:
        if k not in obj:
            errs.append(f"missing required key: {k}")
    if not _CIK_RE.match(str(obj.get("cik") or "").strip()):
        errs.append(f"cik must be 1-10 digits, got {obj.get('cik')!r}")
    rt = str(obj.get("rule_type"))
    if rt not in RULE_TYPES:
        errs.append(f"rule_type must be one of {sorted(RULE_TYPES)}")
    elif str(obj.get("action")) != _ACTION_FOR[rt]:
        errs.append(f"action for {rt} must be {_ACTION_FOR[rt]!r}, got {obj.get('action')!r}")

    scope = obj.get("scope")
    if not isinstance(scope, dict) or not isinstance(scope.get("quarters"), list) or not scope.get("quarters"):
        errs.append("scope.quarters must be a non-empty list (use ['all'] for every quarter)")
    if not isinstance(obj.get("evidence"), list) or not obj.get("evidence"):
        errs.append("evidence must be a non-empty list")
    if not str(obj.get("rationale") or "").strip():
        errs.append("rationale is empty")
    c = obj.get("confidence")
    if not isinstance(c, (int, float)) or not (0.0 <= float(c) <= 1.0):
        errs.append("confidence must be a number in [0,1]")

    # predicate: required for row_exclusion + value_rescale + value_expression; optional for dedup.
    pred = obj.get("predicate_sql")
    pred_text = str(pred or "").strip()
    if rt in ("row_exclusion", "value_rescale", "value_expression") and not pred_text:
        errs.append(f"predicate_sql is required for {rt}")
    if pred_text and _PRED_FORBIDDEN.search(pred_text):
        errs.append("predicate_sql must be a pure boolean row predicate "
                    "(no SELECT/DML/DDL/file-access/`;`/comment)")

    if rt == "value_rescale":
        if str(obj.get("field")) not in RESCALE_FIELDS:
            errs.append(f"field must be one of {sorted(RESCALE_FIELDS)}, got {obj.get('field')!r}")
        f = obj.get("factor")
        if not isinstance(f, (int, float)) or float(f) == 0:
            errs.append("factor must be a non-zero number")
    elif rt == "value_expression":
        if str(obj.get("field")) not in RESCALE_FIELDS:
            errs.append(f"field must be one of {sorted(RESCALE_FIELDS)}, got {obj.get('field')!r}")
        errs.extend(_expr_errors(obj.get("expression")))
    elif rt == "dedup":
        mf = obj.get("match_fields")
        if not isinstance(mf, list) or not mf:
            errs.append("match_fields must be a non-empty list")
        else:
            bad = [m for m in mf if m not in DEDUP_KEY_FIELDS]
            if bad:
                errs.append(f"match_fields not allowed (must be in {sorted(DEDUP_KEY_FIELDS)}): {bad}")
        if str(obj.get("keep")) not in ("first", "last"):
            errs.append("keep must be 'first' or 'last'")
    elif rt == "row_add":
        positions = obj.get("positions")
        if not isinstance(positions, list) or not positions:
            errs.append("positions must be a non-empty list")
        else:
            for i, p in enumerate(positions):
                if not isinstance(p, dict):
                    errs.append(f"positions[{i}] must be an object")
                    continue
                # Extra keys are NOT fatal: recovering from staging naturally carries the whole
                # source row, and the applier already ignores any non-holdings column. Only the
                # REQUIRED grounding fields below make a row_add valid. (Was a hard error; that
                # rejected otherwise-correct recoveries -- see 1715933 2025-03-31 cash-equiv.)
                if not str(p.get("report_date") or "").strip():
                    errs.append(f"positions[{i}] missing report_date")
                if not isinstance(p.get("fair_value"), (int, float)):
                    errs.append(f"positions[{i}].fair_value must be a number")
                if not str(p.get("bdc_dimensions_raw") or "").strip():
                    errs.append(f"positions[{i}] missing bdc_dimensions_raw (so the row is counted)")
                if not str(p.get("source_row_id") or "").strip():
                    errs.append(f"positions[{i}] missing source_row_id (the iXBRL/staging row recovered)")
                if not (str(p.get("issuer_name") or "").strip()
                        or str(p.get("bdc_investment_identifier") or "").strip()):
                    errs.append(f"positions[{i}] needs issuer_name or bdc_investment_identifier")
    return errs


def _scope_sql(scope: dict) -> str:
    qs = (scope or {}).get("quarters") or ["all"]
    if "all" in qs:
        return "TRUE"
    quoted = ",".join("'" + str(q).replace("'", "''") + "'" for q in qs)
    return f"CAST(report_date AS VARCHAR) IN ({quoted})"


def _match_rows(work: pd.DataFrame, predicate_sql, scope) -> list:
    """(rid, pre-value fair_value, report_date) for rows matching predicate AND scope."""
    conn = duckdb.connect()
    conn.register("h", work)
    where = []
    if predicate_sql and str(predicate_sql).strip():
        where.append(f"({predicate_sql})")
    where.append(f"({_scope_sql(scope)})")
    q = (f"SELECT _rid, TRY_CAST(fair_value AS DOUBLE) AS fv, CAST(report_date AS VARCHAR) AS rd "
         f"FROM h WHERE {' AND '.join(where)}")
    try:
        rows = conn.execute(q).fetchall()
    finally:
        conn.close()
    return rows


def _per_quarter(rows) -> dict:
    pq: dict[str, dict] = {}
    for _rid, fv, rd in rows:
        b = pq.setdefault(rd, {"rows": 0, "fv": 0.0})
        b["rows"] += 1
        b["fv"] = round(b["fv"] + float(fv or 0), 2)
    return pq


def _apply_exclusion(work, r):
    rows = _match_rows(work, r.get("predicate_sql"), r.get("scope"))
    drop = {int(x[0]) for x in rows}
    out = work[~work["_rid"].isin(drop)].copy()
    return out, {"rule_id": r.get("rule_id"), "rule_type": "row_exclusion", "status": "ok",
                 "rows_excluded": len(drop), "per_quarter": _per_quarter(rows)}


def _apply_rescale(work, r):
    """Multiply `field` by `factor` for matching rows -- fixes a scale error WITHOUT dropping the
    position (e.g. a fair_value extracted 1000x too large -> factor 0.001)."""
    rows = _match_rows(work, r.get("predicate_sql"), r.get("scope"))
    rids = {int(x[0]) for x in rows}
    field, factor = str(r["field"]), float(r["factor"])
    mask = work["_rid"].isin(rids)
    work.loc[mask, field] = pd.to_numeric(work.loc[mask, field], errors="coerce") * factor
    return work, {"rule_id": r.get("rule_id"), "rule_type": "value_rescale", "status": "ok",
                  "field": field, "factor": factor, "rows_rescaled": int(mask.sum()),
                  "per_quarter": _per_quarter(rows)}      # fv = PRE-rescale value of affected rows


def _apply_value_expression(work, r):
    """Set `field` to a validated arithmetic expression over the row's own numeric columns for
    matching rows -- fixes a mis-DERIVED value (e.g. fair_value that should equal principal*price)
    WITHOUT dropping the position. More general than value_rescale (computed, not constant*field)
    while staying a bounded, reviewable formula."""
    rows = _match_rows(work, r.get("predicate_sql"), r.get("scope"))
    rids = {int(x[0]) for x in rows}
    field, expr = str(r["field"]), str(r["expression"])
    mask = work["_rid"].isin(rids)
    if mask.any():
        work.loc[mask, field] = _eval_expr(expr, work.loc[mask]).to_numpy()
    return work, {"rule_id": r.get("rule_id"), "rule_type": "value_expression", "status": "ok",
                  "field": field, "expression": expr, "rows_set": int(mask.sum()),
                  "per_quarter": _per_quarter(rows)}      # fv = PRE-set value of affected rows


def _apply_dedup(work, r):
    """Drop rows duplicated on `match_fields` (keep first/last), among candidates in scope (and
    the optional predicate). True duplicate collapse -- one row survives per key."""
    rows = _match_rows(work, r.get("predicate_sql"), r.get("scope"))
    cand = {int(x[0]) for x in rows}
    mf, keep = list(r["match_fields"]), str(r.get("keep", "first"))
    sub = work[work["_rid"].isin(cand)]
    # S17 tie-break: which duplicate survives keep=first/last must not depend on
    # the caller's physical row order. Stable-sort candidates by [match_fields,
    # anchor] to fix the survivor deterministically, compute the drop mask on the
    # SORTED frame, then map it back by _rid. The RETURNED frame keeps the
    # caller's incoming order (sort is for mask determination only) so downstream
    # index-aligned appliers/concat are not perturbed (agent_promoted lesson).
    if "row_id" in sub.columns:
        anchor = sub["row_id"].fillna("").astype(str)
    else:
        anchor = pd.Series("", index=sub.index, dtype=object)
        for col in ("accession_number", "src_context_id", "nport_holding_id"):
            if col in sub.columns:
                anchor = anchor + sub[col].fillna("").astype(str) + "|"
    sub_sorted = sub.assign(_anchor=anchor.values).sort_values(
        list(mf) + ["_anchor"], kind="mergesort"
    )
    dup = sub_sorted.duplicated(subset=mf, keep=keep)
    drop = set(sub_sorted.loc[dup, "_rid"].astype(int))
    dropped_rows = [x for x in rows if int(x[0]) in drop]
    out = work[~work["_rid"].isin(drop)].copy()
    return out, {"rule_id": r.get("rule_id"), "rule_type": "dedup", "status": "ok",
                 "match_fields": mf, "keep": keep, "rows_excluded": len(drop),
                 "per_quarter": _per_quarter(dropped_rows)}


def _apply_add(work, r):
    """Recover under-counted positions (FV < anchor): append rows the extractor dropped, each
    grounded by a `source_row_id` (the iXBRL/staging row it recovers). Values are agent-supplied
    from the source; `source_row_id`/evidence make it auditable and the gate checks the FV impact."""
    positions = r.get("positions") or []
    cols = [c for c in work.columns if c != "_rid"]
    next_rid = (int(work["_rid"].max()) + 1) if len(work) else 0
    new_rows, pq, ignored = [], {}, set()
    for p in positions:
        row = {c: None for c in cols}
        for k, v in p.items():
            if k in cols:                       # source_row_id is metadata, not a holdings column
                row[k] = v
            elif k != "source_row_id":          # extra source columns the holdings schema lacks
                ignored.add(k)
        row["_rid"] = next_rid
        next_rid += 1
        new_rows.append(row)
        b = pq.setdefault(str(p.get("report_date")), {"rows": 0, "fv": 0.0})
        b["rows"] += 1
        b["fv"] = round(b["fv"] + float(p.get("fair_value") or 0), 2)
    if new_rows:
        work = pd.concat([work, pd.DataFrame(new_rows)], ignore_index=True)
    return work, {"rule_id": r.get("rule_id"), "rule_type": "row_add", "status": "ok",
                  "rows_added": len(new_rows), "per_quarter": pq,
                  "ignored_keys": sorted(ignored),     # extra position keys not in the holdings schema
                  "source_row_ids": [p.get("source_row_id") for p in positions]}


_APPLIERS = {"row_exclusion": _apply_exclusion, "value_rescale": _apply_rescale,
             "dedup": _apply_dedup, "row_add": _apply_add,
             "value_expression": _apply_value_expression}


def apply_rules(df: pd.DataFrame, rules: list[dict]) -> tuple[pd.DataFrame, list[dict]]:
    """Apply validated rules (row_exclusion / value_rescale / dedup) to one CIK's holdings, in
    order. Pure; trial-only. Per-rule PER-QUARTER audit -- never a blanket cross-quarter number."""
    work = df.reset_index(drop=True).copy()
    work["_rid"] = range(len(work))
    audits: list[dict] = []
    for r in rules:
        errs = validate_rule(r)
        if errs:
            audits.append({"rule_id": r.get("rule_id"), "status": "invalid", "errors": errs})
            continue
        applier = _APPLIERS.get(str(r.get("rule_type")))
        if applier is None:
            audits.append({"rule_id": r.get("rule_id"), "status": "skipped",
                           "message": f"unsupported rule_type {r.get('rule_type')!r}"})
            continue
        try:
            work, audit = applier(work, r)
        except Exception as exc:
            audit = {"rule_id": r.get("rule_id"), "status": "error", "message": str(exc)}
        # No-op flag: a rule that matched/changed ZERO rows is a non-fix. Surfaced so the loop can
        # reject it (self-verify) and tell the worker to find the real mechanism or escalate --
        # instead of letting a confident no-op reach the gate (the template-author failure mode).
        if audit.get("status") == "ok":
            audit["noop"] = (_rule_impact(audit) == 0)
        audits.append(audit)
    corrected = work.drop(columns=["_rid"]).copy()
    return corrected, audits


# Categories that stay in the published holdings but are NOT "investments at fair value" and so are
# EXCLUDED from the conservation sum (the companyfacts InvestmentOwnedAtFairValue anchor excludes them
# in ~92% of cik-quarters). Cash-equivalents = T-bills, money-market sweeps held for cash management.
# Without this, B2 would DROP real cash positions to reconcile to a cash-excluding anchor.
CONSERVATION_EXCLUDED_CATEGORIES = frozenset({"CASH"})


def value_sum_by_quarter(df: pd.DataFrame) -> dict[str, float]:
    """Conservation value_sum per report_date: sum(fair_value) over gate-counted rows, EXCLUDING
    cash-equivalents (kept in holdings, not part of 'investments at fair value') and
    is_subsidiary=1 look-through rows (retain-and-flag, 2026-08-29: the consolidated
    anchor already contains them once, so summing them again double-counts)."""
    sub = df[df["bdc_dimensions_raw"].notna()] if "bdc_dimensions_raw" in df.columns else df
    if "asset_category" in sub.columns:
        sub = sub[~sub["asset_category"].astype(str).str.upper().isin(CONSERVATION_EXCLUDED_CATEGORIES)]
    if "is_subsidiary" in sub.columns:
        sub = sub[pd.to_numeric(sub["is_subsidiary"], errors="coerce").fillna(0) != 1]
    fv = pd.to_numeric(sub["fair_value"], errors="coerce").fillna(0)
    return {str(k): float(v) for k, v in fv.groupby(sub["report_date"].astype(str)).sum().items()}


def build_snapshots(df: pd.DataFrame, anchors: dict[str, float], threshold_pct: float = 1.0) -> dict:
    """One conservation snapshot per quarter that has an anchor."""
    vs = value_sum_by_quarter(df)
    out = {}
    for q, anchor in anchors.items():
        v = vs.get(str(q), 0.0)
        flagged = abs(v - anchor) > (threshold_pct / 100.0) * abs(anchor)
        out[str(q)] = {"flags": ["fv_conservation"] if flagged else [],
                       "conservation": {"value_sum": v, "anchor_value": anchor},
                       "fv_at_risk": abs(v - anchor) if flagged else 0.0}
    return out


def gate_rules(baseline_df, corrected_df, *, cik, target_quarter, anchors=None, threshold_pct=1.0,
               max_removed_frac=0.6, anchor_candidates=None, anchor_agree_tol=None):
    """B3 over the agent's rules: baseline vs corrected snapshots -> the un-gameable verdict.

    Augments `gate_correction` with three agentic-path guards (gate_correction itself is left
    untouched, so the B2 path is unaffected):
    - `anchor_validated` (FIRST line of defence): is the anchor the loop reconciles to actually
      TRUE? Pass `anchor_candidates` ({quarter -> {anchor_name -> value}}) and the gate validates
      each quarter's anchor for INDEPENDENCE (see pipeline.anchor_validation). If the TARGET
      quarter's anchor is contested or absent (tier NONE), the gate FAILS -- the loop is forbidden
      from reconciling to a number it cannot trust. This is what turns "delete-to-balance against a
      bad anchor" into an explicit escalation BEFORE the deletion guards have to catch the damage.
      When `anchor_candidates` is given, the per-quarter STRONG-consensus values become the anchors
      used for every snapshot (overriding `anchors`). Back-compat: omit it and pass `anchors`
      (quarter -> float) for the legacy single-anchor behaviour with no validation.
    - `no_over_addition`: a rule must not ADD value past the anchor (symmetric to the existing
      `no_over_deletion`). Catches `row_add` add-to-balance overshoot.
    - `anchor_sanity`: reconciling the target quarter must not require deleting > ``max_removed_frac``
      of its baseline FV. A reconciliation that drops most of the holdings means the ANCHOR is
      almost certainly wrong (the 1743415 case: $406M schedule "reconciled" to a $13.96M anchor by
      deleting 97%). Escalate rather than delete-to-balance against a bad anchor. Heuristic ->
      FAIL=escalate, not silent data loss; tune the fraction per cohort.
    """
    # Anchor validation: derive the snapshot anchors from validated STRONG consensus when the
    # caller provides candidate values; otherwise fall back to the legacy single-anchor dict.
    anchor_verdicts = {}
    if anchor_candidates is not None:
        from pipeline.anchor_validation import DEFAULT_AGREE_TOL, classify_many
        tol = anchor_agree_tol if anchor_agree_tol is not None else DEFAULT_AGREE_TOL
        anchor_verdicts = classify_many(anchor_candidates, agree_tol=tol)
        anchors = {q: v.consensus for q, v in anchor_verdicts.items() if v.consensus is not None}
    anchors = anchors or {}

    base = build_snapshots(baseline_df, anchors, threshold_pct)
    trial = build_snapshots(corrected_df, anchors, threshold_pct)
    tol = threshold_pct / 100.0
    res = gate_correction(cik=str(cik), target_quarter=str(target_quarter),
                          target_flags={"fv_conservation"}, baseline=base, trial=trial,
                          anchor_undershoot_tol_frac=tol)

    # anchor_validated -- is the TARGET anchor itself TRUE before we let the loop reconcile to it?
    # Only enforced when the caller supplies anchor_candidates (independent values to cross-check).
    # A contested/absent anchor (tier NONE) means the residual is undefined: FAIL=escalate, so the
    # loop never delete-to-balances against a number it cannot trust.
    if anchor_candidates is not None:
        tv = anchor_verdicts.get(str(target_quarter))
        if tv is None or tv.tier == "NONE":
            why = tv.reason if tv else "no anchor candidates for the target quarter"
            res._fail("anchor_validated", f"target anchor not validated ({why})")
        else:
            res._pass("anchor_validated")
            if tv.tier == "MEDIUM":
                res.reasons.append(f"anchor_validated=MEDIUM: {tv.reason}")

    # no_over_addition -- a rule that increases value_sum must not push any quarter PAST the anchor.
    over_add = {}
    for q, ts in trial.items():
        tc, bc = ts.get("conservation"), base.get(q, {}).get("conservation")
        if not (tc and bc):
            continue
        a = float(tc.get("anchor_value", 0) or 0)
        tvs, bvs = float(tc.get("value_sum", 0) or 0), float(bc.get("value_sum", 0) or 0)
        if a and tvs > a * (1 + tol) and tvs > bvs + 1.0:        # rule ADDED value AND overshoots
            over_add[q] = round(tvs - a, 2)
    if over_add:
        res._fail("no_over_addition", f"value_sum pushed ABOVE anchor (add-to-balance) in: {over_add}")
    else:
        res._pass("no_over_addition")

    # anchor_sanity -- did reconciling the target quarter require deleting too much of its FV?
    bt = base.get(str(target_quarter), {}).get("conservation")
    tt = trial.get(str(target_quarter), {}).get("conservation")
    if bt and tt:
        bvs, tvs = float(bt.get("value_sum", 0) or 0), float(tt.get("value_sum", 0) or 0)
        a = float(tt.get("anchor_value", 0) or 0)
        removed = (bvs - tvs) / bvs if bvs > 0 else 0.0
        if removed > max_removed_frac:
            res._fail("anchor_sanity",
                      f"reconciliation removed {removed * 100:.0f}% of {target_quarter} FV "
                      f"({bvs:.0f} -> {tvs:.0f}) to reach anchor {a:.0f}; the anchor is likely wrong "
                      f"vs the holdings -- escalate, do not delete-to-balance")
        else:
            res._pass("anchor_sanity")
    return res


# --- escalation: proposed_mechanism (gap-5 channel) ------------------------------------
# When NO rule type (incl. the bounded value_expression) can express the real mechanism, the
# worker writes ONE escalation instead of a confident no-op. It is NOT applied; the driver
# surfaces it for a human, and it is the intake queue for adding a new core applier. Honest stop
# beats wrong fix -- the same discipline as anchor escalation.
_ESCALATION_REQUIRED = ("cik", "target_quarter", "kind", "summary", "evidence",
                        "why_no_vocab_fits", "confidence")
# `category` routes the escalation deterministically (no prose-sniffing): "anchor" -> the anchor-
# adjudicator (the conservation target reconciles to the wrong/incomplete anchor); "vocab" -> a new
# applier is needed; "other" -> human. Optional (defaults to "other").
ESCALATION_CATEGORIES = frozenset({"anchor", "vocab", "other"})


def validate_escalation(obj) -> list[str]:
    errs: list[str] = []
    if not isinstance(obj, dict):
        return ["escalation is not a JSON object"]
    for k in _ESCALATION_REQUIRED:
        if k not in obj:
            errs.append(f"missing required key: {k}")
    if str(obj.get("kind")) != "proposed_mechanism":
        errs.append("kind must be 'proposed_mechanism'")
    if not _CIK_RE.match(str(obj.get("cik") or "").strip()):
        errs.append(f"cik must be 1-10 digits, got {obj.get('cik')!r}")
    for k in ("summary", "why_no_vocab_fits"):
        if not str(obj.get(k) or "").strip():
            errs.append(f"{k} is empty")
    if not isinstance(obj.get("evidence"), list) or not obj.get("evidence"):
        errs.append("evidence must be a non-empty list")
    c = obj.get("confidence")
    if not isinstance(c, (int, float)) or not (0.0 <= float(c) <= 1.0):
        errs.append("confidence must be a number in [0,1]")
    if "category" in obj and str(obj.get("category")) not in ESCALATION_CATEGORIES:
        errs.append(f"category must be one of {sorted(ESCALATION_CATEGORIES)}")
    return errs


def is_anchor_escalation(obj) -> bool:
    """True iff this escalation routes to the anchor-adjudicator (category == 'anchor')."""
    return isinstance(obj, dict) and str(obj.get("category")) == "anchor"


def load_escalations(esc_dir: Path) -> list[dict]:
    esc_dir = Path(esc_dir)
    out = []
    for p in sorted(esc_dir.glob("*.json")) if esc_dir.exists() else []:
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return out


def load_rules(rules_dir: Path) -> list[dict]:
    rules_dir = Path(rules_dir)
    out = []
    for p in sorted(rules_dir.glob("*.json")) if rules_dir.exists() else []:
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return out
