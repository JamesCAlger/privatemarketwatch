"""Agent B2 post-staging correction appliers (deterministic, cached-only).

The post-staging half of B2 remediation: PURE transforms over a single CIK's UNIFIED
holdings DataFrame, applied in a TRIAL first and, after a B3 gate PASS + promotion, in
production (``agent_promoted.apply_promoted_stage2_corrections``). Extraction-domain
subtotal filtering stays a wrapper patch; everything else the correction-leaf vocabulary
can express is implemented here (2026-08-13 expansion: rate/unit rescale, column remap,
classification fix, all-PIK normalization, missing-position add -- the applier gap that
left 121/143 tier-4 packets undispatchable).

Each applier: ``(df, validated template) -> (df_corrected, audit)``. Pure -- no IO, no
production writes; the caller (``rebuild_unified_cik_trial --corrections`` or the B2
driver) owns persistence. Templates are assumed already validated by
``pipeline.correction_leaf.validate_correction`` -- appliers still fail safe (record an
error in the audit and return the frame unchanged) rather than raising on bad data.

See ``docs/adjudication_architecture/B2_B3_build_plan.md``. ASCII-only.
"""

from __future__ import annotations

from typing import Callable

import pandas as pd

from pipeline.correction_leaf import stage_for


def _fv_sum(df: pd.DataFrame, mask) -> float | None:
    if "fair_value" not in df.columns:
        return None
    return float(pd.to_numeric(df.loc[mask, "fair_value"], errors="coerce").fillna(0).sum())


def apply_dedup(df: pd.DataFrame, template: dict) -> tuple[pd.DataFrame, dict]:
    """Drop rows duplicated on ``template['match_fields']`` (keep first/last). match_fields
    must scope a true duplicate (typically INCLUDING report_date) so legitimate
    comparative-period rows are not collapsed.

    Optional ``row_selector`` (2026-08-21) restricts which rows may be DROPPED: group
    membership is still judged over the whole (already quarter-scoped) frame, but only
    selector-matched rows are eligible for deletion. Bounds the blast radius to the
    grounded rows (q4b2r4an: a key-only dedup for two cited rows collapsed 563 groups)."""
    match_fields = list(template.get("match_fields") or [])
    keep = template.get("keep", "first")
    row_selector = template.get("row_selector")
    audit: dict = {"fix_class": "dedup", "match_fields": match_fields, "keep": keep,
                   "rows_in": int(len(df))}
    if row_selector is not None:
        audit["row_selector"] = row_selector
    missing = [c for c in match_fields if c not in df.columns]
    if not match_fields or missing:
        audit.update(status="error", rows_dropped=0, rows_out=int(len(df)),
                     message=(f"missing match_fields columns: {missing}" if missing
                              else "no match_fields"))
        return df, audit
    dup_mask = df.duplicated(subset=match_fields, keep=keep)
    if row_selector is not None:
        sel_mask, err = _selector_mask(df, row_selector)
        if err or not sel_mask.any():
            audit.update(status="error", rows_dropped=0, rows_out=int(len(df)),
                         message=err or "row_selector matched no rows")
            return df, audit
        audit["rows_selected"] = int(sel_mask.sum())
        dup_mask = dup_mask & sel_mask
    audit.update(status="ok", rows_dropped=int(dup_mask.sum()),
                 rows_out=int((~dup_mask).sum()), fv_dropped=_fv_sum(df, dup_mask))
    return df.loc[~dup_mask].copy(), audit


def apply_comparative_period_filter(df: pd.DataFrame, template: dict) -> tuple[pd.DataFrame, dict]:
    """Drop prior-period comparative rows for the template report_date.

    This must run while the frame still carries raw XBRL ``period``. Unified holdings drop
    that column, so trial rebuilds apply this to the CIK's raw BDC staging rows before
    rebuilding the unified ledger.
    """
    target_report_date = str(template.get("report_date") or "").strip()
    audit: dict = {
        "fix_class": "comparative_period_filter",
        "report_date": target_report_date,
        "rows_in": int(len(df)),
    }
    if not target_report_date:
        audit.update(status="error", rows_dropped=0, rows_out=int(len(df)),
                     message="missing template.report_date")
        return df, audit
    if "period" not in df.columns or "report_date" not in df.columns:
        audit.update(status="error", rows_dropped=0, rows_out=int(len(df)),
                     message="missing period/report_date columns")
        return df, audit
    target_mask = df["report_date"].astype(str) == target_report_date
    drop_mask = target_mask & (df["period"].astype(str) != df["report_date"].astype(str))
    audit.update(status="ok", rows_dropped=int(drop_mask.sum()),
                 rows_out=int((~drop_mask).sum()), fv_dropped=_fv_sum(df, drop_mask))
    return df.loc[~drop_mask].copy(), audit


# fix_class -> applier. ONLY post-staging mechanisms; extraction-domain (wrapper-patch) and
# rule-level fix_classes are intentionally absent (handled elsewhere).
def apply_spv_lookthrough(df: pd.DataFrame, template: dict) -> tuple[pd.DataFrame, dict]:
    """Resolve a consolidated-subsidiary look-through double-count. Per ``entities`` decision:
    ``use_equity`` -> drop the legalentityaxis-tagged collateral (keep the filer's equity line);
    ``keep_lookthrough`` -> drop the parent equity line(s) for the entity (keep the granular
    underlying). Fail-safe on a missing dimension column. See pipeline/agent_b2_diagnose."""
    from pipeline.agent_b2_diagnose import _legal_entity, map_legalentity_to_equity
    audit: dict = {"fix_class": "spv_lookthrough", "rows_in": int(len(df)), "decisions": []}
    ents = template.get("entities") or []
    if "bdc_dimensions_raw" not in df.columns or not ents:
        audit.update(status="error", rows_dropped=0, rows_out=int(len(df)),
                     message="no entities or missing bdc_dimensions_raw")
        return df, audit
    le = df["bdc_dimensions_raw"].map(_legal_entity)
    parent = df[le.isna()]
    drop = pd.Series(False, index=df.index)
    for e in ents:
        member, decision = str(e.get("legal_entity") or ""), str(e.get("decision") or "")
        if decision == "use_equity":
            drop = drop | (le == member)
        elif decision == "keep_lookthrough":
            drop = drop | pd.Series(df.index.isin(map_legalentity_to_equity(member, parent)), index=df.index)
        audit["decisions"].append({"legal_entity": member, "decision": decision})
    audit.update(status="ok", rows_dropped=int(drop.sum()), rows_out=int((~drop).sum()),
                 fv_dropped=_fv_sum(df, drop))
    return df.loc[~drop].copy(), audit


def _one_selector_mask(df: pd.DataFrame, row_selector: dict | None) -> tuple[pd.Series, str]:
    """AND-of-equalities mask over ROW_SELECTOR_KEYS that are holdings columns.

    Empty/missing selector selects ALL rows (the correction is already scoped to one
    CIK; the value gate still verifies only the expected field changed). A selector
    containing ONLY evidence coordinates (table/row index) cannot select and errors.
    """
    sel = dict(row_selector or {})
    sel.pop("table_index", None)
    sel.pop("row_index", None)
    if not sel:
        if row_selector:  # coordinates-only selector: nothing matchable
            return pd.Series(False, index=df.index), "row_selector has no matchable keys"
        return pd.Series(True, index=df.index), ""
    mask = pd.Series(True, index=df.index)
    for key, want in sel.items():
        if key not in df.columns:
            return pd.Series(False, index=df.index), f"row_selector column missing: {key}"
        mask &= df[key].fillna("").astype(str).str.strip() == str(want).strip()
    return mask, ""


def _selector_mask(df: pd.DataFrame, row_selector) -> tuple[pd.Series, str]:
    """Selector mask: one selector object, or a list of selector objects OR-combined
    (2026-08-21, q4b2r4an lesson -- a leaf may bind every cited row instead of
    widening to a whole quarter or fixing one row and abandoning the rest). List
    semantics: OR across entries, AND within an entry; any entry error fails the
    whole selector (fail-safe, no partial application)."""
    if isinstance(row_selector, list):
        if not row_selector:
            return pd.Series(False, index=df.index), "row_selector list is empty"
        combined = pd.Series(False, index=df.index)
        for i, sel in enumerate(row_selector):
            m, err = _one_selector_mask(df, sel)
            if err:
                return pd.Series(False, index=df.index), f"row_selector[{i}]: {err}"
            combined |= m
        return combined, ""
    return _one_selector_mask(df, row_selector)


def _value_fix_audit(fix_class: str, df: pd.DataFrame, template: dict) -> dict:
    sel = template.get("row_selector")
    return {"fix_class": fix_class, "rows_in": int(len(df)),
            "row_selector": (list(sel) if isinstance(sel, list) else dict(sel or {}))}


def apply_rate_rescale(df: pd.DataFrame, template: dict) -> tuple[pd.DataFrame, dict]:
    """Multiply a rate field (interest_rate/pik_rate/basis_spread) by ``factor`` for the
    selected rows -- fixes a scale error (e.g. decimal-vs-percent) without dropping the
    position. FV is never touched."""
    field, factor = str(template.get("field") or ""), template.get("factor")
    audit = _value_fix_audit("rate_rescale", df, template)
    audit.update(field=field, factor=factor)
    if field not in df.columns or not isinstance(factor, (int, float)) or not factor:
        audit.update(status="error", rows_changed=0,
                     message=f"missing field column or bad factor: {field!r}/{factor!r}")
        return df, audit
    mask, err = _selector_mask(df, template.get("row_selector"))
    if err:
        audit.update(status="error", rows_changed=0, message=err)
        return df, audit
    out = df.copy()
    vals = pd.to_numeric(out.loc[mask, field], errors="coerce")
    changed = mask.copy()
    changed.loc[mask] = vals.notna()
    out.loc[changed, field] = vals[vals.notna()] * float(factor)
    audit.update(status="ok", rows_changed=int(changed.sum()), rows_out=int(len(out)),
                 fv_delta=0.0)
    return out, audit


def apply_unit_rescale(df: pd.DataFrame, template: dict) -> tuple[pd.DataFrame, dict]:
    """Multiply a numeric field by ``factor`` for the selected rows (unit mismatch, e.g.
    thousands-vs-units). When the field is fair_value the FV delta is recorded and the
    conservation gate applies on top of the value gate."""
    field, factor = str(template.get("field") or ""), template.get("factor")
    audit = _value_fix_audit("unit_rescale", df, template)
    audit.update(field=field, factor=factor)
    if field not in df.columns or not isinstance(factor, (int, float)) or not factor:
        audit.update(status="error", rows_changed=0,
                     message=f"missing field column or bad factor: {field!r}/{factor!r}")
        return df, audit
    mask, err = _selector_mask(df, template.get("row_selector"))
    if err:
        audit.update(status="error", rows_changed=0, message=err)
        return df, audit
    out = df.copy()
    before = _fv_sum(out, mask) if field == "fair_value" else None
    vals = pd.to_numeric(out.loc[mask, field], errors="coerce")
    changed = mask.copy()
    changed.loc[mask] = vals.notna()
    out.loc[changed, field] = vals[vals.notna()] * float(factor)
    after = _fv_sum(out, mask) if field == "fair_value" else None
    audit.update(status="ok", rows_changed=int(changed.sum()), rows_out=int(len(out)),
                 fv_delta=(round(after - before, 2) if before is not None else 0.0))
    return out, audit


def apply_column_remap(df: pd.DataFrame, template: dict) -> tuple[pd.DataFrame, dict]:
    """Move a value parsed into the wrong column: for selected rows with a non-null
    ``from_field``, copy it into ``to_field`` and clear ``from_field``. Overwrites of a
    populated to_field are recorded in the audit (the value gate flags them)."""
    from_field, to_field = str(template.get("from_field") or ""), str(template.get("to_field") or "")
    audit = _value_fix_audit("column_remap", df, template)
    audit.update(from_field=from_field, to_field=to_field)
    if from_field not in df.columns or to_field not in df.columns or from_field == to_field:
        audit.update(status="error", rows_changed=0,
                     message=f"bad from/to fields: {from_field!r} -> {to_field!r}")
        return df, audit
    mask, err = _selector_mask(df, template.get("row_selector"))
    if err:
        audit.update(status="error", rows_changed=0, message=err)
        return df, audit
    out = df.copy()
    movable = mask & out[from_field].notna() & (out[from_field].astype(str).str.strip() != "")
    overwrote = movable & out[to_field].notna() & (out[to_field].astype(str).str.strip() != "")
    out.loc[movable, to_field] = out.loc[movable, from_field]
    out.loc[movable, from_field] = None
    audit.update(status="ok", rows_changed=int(movable.sum()),
                 rows_overwritten=int(overwrote.sum()), rows_out=int(len(out)), fv_delta=0.0)
    return out, audit


def apply_classification_fix(df: pd.DataFrame, template: dict) -> tuple[pd.DataFrame, dict]:
    """Set a classification field (asset_class/index_classification/exposure_type) to
    ``value`` for the selected rows. Prior values are recorded for the audit trail."""
    field, value = str(template.get("field") or ""), template.get("value")
    audit = _value_fix_audit("classification_fix", df, template)
    audit.update(field=field, value=value)
    if field not in df.columns or value is None or not str(value).strip():
        audit.update(status="error", rows_changed=0,
                     message=f"missing field column or empty value: {field!r}/{value!r}")
        return df, audit
    mask, err = _selector_mask(df, template.get("row_selector"))
    if err:
        audit.update(status="error", rows_changed=0, message=err)
        return df, audit
    out = df.copy()
    prior = out.loc[mask, field].fillna("").astype(str).value_counts().head(5).to_dict()
    out.loc[mask, field] = str(value)
    audit.update(status="ok", rows_changed=int(mask.sum()), prior_values=prior,
                 rows_out=int(len(out)), fv_delta=0.0)
    return out, audit


def apply_all_pik_normalization(df: pd.DataFrame, template: dict) -> tuple[pd.DataFrame, dict]:
    """Normalize a mis-parsed cash/PIK rate split for the selected rows, in the
    pipeline's CURRENT storage convention (interest_rate = cash leg, pik_rate separate --
    the all-in migration is a separate, atomic project; see
    interest-rate-cashpay-convention). ``pik_rate`` sets the PIK leg;
    ``cash_rate`` + ``set_interest_to_cash`` rewrites interest_rate to the cash leg."""
    audit = _value_fix_audit("all_pik_normalization", df, template)
    cash_rate, pik_rate = template.get("cash_rate"), template.get("pik_rate")
    set_cash = bool(template.get("set_interest_to_cash"))
    audit.update(cash_rate=cash_rate, pik_rate=pik_rate, set_interest_to_cash=set_cash)
    if pik_rate is None and not (set_cash and cash_rate is not None):
        audit.update(status="error", rows_changed=0,
                     message="template sets neither pik_rate nor cash-leg interest")
        return df, audit
    mask, err = _selector_mask(df, template.get("row_selector"))
    if err or not mask.any():
        audit.update(status="error", rows_changed=0,
                     message=err or "row_selector matched no rows")
        return df, audit
    out = df.copy()
    if pik_rate is not None and "pik_rate" in out.columns:
        out.loc[mask, "pik_rate"] = float(pik_rate)
    if set_cash and cash_rate is not None and "interest_rate" in out.columns:
        out.loc[mask, "interest_rate"] = float(cash_rate)
    audit.update(status="ok", rows_changed=int(mask.sum()), rows_out=int(len(out)),
                 fv_delta=0.0)
    return out, audit


def apply_source_anchored_value(df: pd.DataFrame, template: dict) -> tuple[pd.DataFrame, dict]:
    """Set each assertion's holdings field to the FILING's own value (source.value x
    unit_multiplier) for the selected rows. The worker never authors a number the
    filing does not contain: ``pipeline.source_anchor_verify`` re-parses the cached
    filing at intake + gate and refuses the leaf on any cell/witness mismatch, so this
    applier trusts an already-verified leaf. All-or-nothing: any unresolvable
    assertion fails the whole leaf unchanged (no partial application)."""
    assertions = list(template.get("assertions") or [])
    audit: dict = {"fix_class": "source_anchored_value", "rows_in": int(len(df)),
                   "n_assertions": len(assertions), "assertions": []}
    if not assertions:
        audit.update(status="error", rows_changed=0, message="no assertions")
        return df, audit
    resolved: list[tuple[pd.Series, str, float]] = []
    for i, a in enumerate(assertions):
        field = str((a or {}).get("field") or "")
        src = (a or {}).get("source") or {}
        value, mult = src.get("value"), src.get("unit_multiplier", 1)
        if field not in df.columns:
            audit.update(status="error", rows_changed=0,
                         message=f"assertions[{i}]: field column missing: {field!r}")
            return df, audit
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            audit.update(status="error", rows_changed=0,
                         message=f"assertions[{i}]: bad source.value: {value!r}")
            return df, audit
        mask, err = _selector_mask(df, (a or {}).get("row_selector"))
        if err or not mask.any():
            audit.update(status="error", rows_changed=0,
                         message=f"assertions[{i}]: {err or 'row_selector matched no rows'}")
            return df, audit
        resolved.append((mask, field, float(value) * float(mult)))
    out = df.copy()
    total_changed = 0
    for i, (mask, field, target) in enumerate(resolved):
        before = out.loc[mask, field].head(3).tolist()
        out.loc[mask, field] = target
        total_changed += int(mask.sum())
        audit["assertions"].append({"index": i, "field": field, "value_set": target,
                                    "rows_changed": int(mask.sum()),
                                    "before_sample": before})
    fv_masks = [m for m, f, _ in resolved if f == "fair_value"]
    if fv_masks:
        union = fv_masks[0]
        for m in fv_masks[1:]:
            union = union | m
        fv_delta = round((_fv_sum(out, union) or 0.0) - (_fv_sum(df, union) or 0.0), 2)
    else:
        fv_delta = 0.0
    audit.update(status="ok", rows_changed=total_changed, rows_out=int(len(out)),
                 fv_delta=fv_delta)
    return out, audit


def missing_position_source_collisions(df: pd.DataFrame, positions: list[dict]) -> list[str]:
    """Return proposed source ids that are already represented in a holdings frame.

    ``source_row_id`` is reconciliation metadata and is normally not retained on
    unified holdings.  For BDC rows its stable equivalent is
    ``src:{accession_number}:{src_context_id}``; check both forms so a B2 add
    cannot turn a false ``missing_from_pipeline`` claim into a duplicate position.
    """
    existing: set[str] = set()
    if "source_row_id" in df.columns:
        existing.update(df["source_row_id"].fillna("").astype(str).str.strip())
    if "source" in df.columns:
        existing.update(df["source"].fillna("").astype(str).str.strip())
    if {"accession_number", "src_context_id"}.issubset(df.columns):
        accession = df["accession_number"].fillna("").astype(str).str.strip()
        context = df["src_context_id"].fillna("").astype(str).str.strip()
        existing.update(("src:" + accession + ":" + context)[(accession != "") & (context != "")])
    return sorted({str(p.get("source_row_id") or "").strip() for p in positions} & existing - {""})


def apply_missing_position_add(df: pd.DataFrame, template: dict) -> tuple[pd.DataFrame, dict]:
    """Append under-counted positions. Every position MUST carry ``source_row_id`` (the
    staging row being recovered -- no fabrication; parity with agent_rule row_add) plus
    report_date and a numeric fair_value; the value gate re-verifies each source_row_id
    against raw staging. source_row_id is grounding metadata, not a holdings column."""
    positions = list(template.get("positions") or [])
    audit = _value_fix_audit("missing_position_add", df, template)
    ungrounded = [i for i, p in enumerate(positions)
                  if not str((p or {}).get("source_row_id") or "").strip()]
    if not positions or ungrounded:
        audit.update(status="error", rows_changed=0,
                     message=(f"positions missing source_row_id at index(es) {ungrounded}"
                              if ungrounded else "no positions"))
        return df, audit
    cols = list(df.columns)
    new_rows, fv_added = [], 0.0
    for p in positions:
        row = {c: None for c in cols}
        for k, v in p.items():
            if k in cols:
                row[k] = v
        new_rows.append(row)
        fv_added += float(p.get("fair_value") or 0)
    if new_rows:
        # Fresh tail indices (not ignore_index): callers restore the frame's original
        # row order by sort_index after per-CIK application.
        start = (int(pd.to_numeric(pd.Series(df.index), errors="coerce").max()) + 1
                 if len(df) else 0)
        add = pd.DataFrame(new_rows, columns=cols,
                           index=range(start, start + len(new_rows)))
        out = pd.concat([df, add])
    else:
        out = df.copy()
    audit.update(status="ok", rows_changed=len(new_rows), rows_out=int(len(out)),
                 fv_delta=round(fv_added, 2),
                 source_row_ids=[str(p.get("source_row_id")) for p in positions])
    return out, audit


POST_STAGING_APPLIERS: dict[str, Callable[[pd.DataFrame, dict], tuple[pd.DataFrame, dict]]] = {
    "dedup": apply_dedup,
    "comparative_period_filter": apply_comparative_period_filter,
    "spv_lookthrough": apply_spv_lookthrough,
    "rate_rescale": apply_rate_rescale,
    "unit_rescale": apply_unit_rescale,
    "column_remap": apply_column_remap,
    "classification_fix": apply_classification_fix,
    "all_pik_normalization": apply_all_pik_normalization,
    "missing_position_add": apply_missing_position_add,
    "source_anchored_value": apply_source_anchored_value,
}


def apply_scoped(
    df: pd.DataFrame, correction: dict,
) -> tuple[pd.DataFrame, dict]:
    """Apply one correction with STRUCTURAL quarter-scope enforcement (2026-08-13).

    Rows outside ``correction['scope']['quarters']`` are physically excluded from the
    applier's view and re-joined unchanged afterwards (original row order preserved) --
    an over-broad selector cannot touch an out-of-scope quarter no matter what the
    worker wrote. A scoped correction whose quarters match no rows is an 'ok' no-op
    audit (surfaced by drift detection downstream). Corrections without an explicit
    quarter scope (the stage-1 structural family) apply unscoped as before."""
    fc = str(correction.get("fix_class") or "")
    applier = POST_STAGING_APPLIERS.get(fc)
    template = correction.get("template") or {}
    if applier is None:
        return df, {"fix_class": fc, "status": "skipped",
                    "message": "not a post-staging applier (wrapper-patch or rule track)"}
    quarters = [str(q) for q in (correction.get("scope") or {}).get("quarters", [])
                if q and str(q) != "all"]
    if not quarters or "report_date" not in df.columns:
        out, audit = applier(df, template)
        return out, audit
    in_scope = df["report_date"].astype(str).isin(quarters)
    applied, audit = applier(df.loc[in_scope], template)
    out = pd.concat([df.loc[~in_scope], applied]).sort_index(kind="mergesort")
    audit["scope_quarters"] = quarters
    audit["rows_out_of_scope_protected"] = int((~in_scope).sum())
    return out, audit


def run_corrections(
    df: pd.DataFrame, corrections: list[dict], *, stage: int | None = None,
) -> tuple[pd.DataFrame, list[dict]]:
    """Apply post-staging corrections (validated correction-leaf dicts) to one CIK's
    holdings, in precedence-stage order, each under structural quarter-scope
    enforcement (``apply_scoped``). ``stage`` (if given) restricts to that stage --
    the B2 driver applies ONE stage, regenerates the ledger, re-triages, then advances.
    Corrections whose fix_class is not a post-staging applier are skipped (recorded)."""
    audits: list[dict] = []
    ordered = sorted(corrections, key=lambda c: stage_for(str(c.get("fix_class") or "")))
    for c in ordered:
        fc = str(c.get("fix_class") or "")
        if stage is not None and stage_for(fc) != stage:
            continue
        df, audit = apply_scoped(df, c)
        audit["cik"] = c.get("cik")
        # Fill structural identity on added rows (missing_position_add) -- parity with
        # the production path (agent_promoted): without it the trial frame carries a
        # NULL-cik row, the cik column floats, and the gate's CIK filter drops the
        # whole frame (2026-08-30).
        cik = str(c.get("cik") or "")
        if cik and "cik" in df.columns and df["cik"].isna().any():
            added = df["cik"].isna()
            df = df.copy()
            df.loc[added, "cik"] = cik.zfill(10) if cik.isdigit() else cik
            if "source" in df.columns:
                df.loc[added & df["source"].isna(), "source"] = "bdc"
        audits.append(audit)
    return df, audits
