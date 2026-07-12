"""Agent B2 post-staging correction appliers (deterministic, cached-only).

The post-staging half of B2 remediation: PURE transforms over a single CIK's UNIFIED
holdings DataFrame, applied in a TRIAL only (never production). Extraction-domain
mechanisms (subtotal_filter, classification_fix, column_remap) are NOT here -- those are
wrapper patches consumed by the existing ``bdc_xbrl_wrapper`` machinery +
``rebuild_unified_cik_trial.py``. This module owns only the mechanisms the wrapper cannot
express: cross-period dedup and comparative-period filtering (derived-rate normalization
follows once its index_returns coupling is handled).

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
    comparative-period rows are not collapsed."""
    match_fields = list(template.get("match_fields") or [])
    keep = template.get("keep", "first")
    audit: dict = {"fix_class": "dedup", "match_fields": match_fields, "keep": keep,
                   "rows_in": int(len(df))}
    missing = [c for c in match_fields if c not in df.columns]
    if not match_fields or missing:
        audit.update(status="error", rows_dropped=0, rows_out=int(len(df)),
                     message=(f"missing match_fields columns: {missing}" if missing
                              else "no match_fields"))
        return df, audit
    dup_mask = df.duplicated(subset=match_fields, keep=keep)
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


POST_STAGING_APPLIERS: dict[str, Callable[[pd.DataFrame, dict], tuple[pd.DataFrame, dict]]] = {
    "dedup": apply_dedup,
    "comparative_period_filter": apply_comparative_period_filter,
    "spv_lookthrough": apply_spv_lookthrough,
}


def run_corrections(
    df: pd.DataFrame, corrections: list[dict], *, stage: int | None = None,
) -> tuple[pd.DataFrame, list[dict]]:
    """Apply post-staging corrections (validated correction-leaf dicts) to one CIK's
    holdings, in precedence-stage order. ``stage`` (if given) restricts to that stage --
    the B2 driver applies ONE stage, regenerates the ledger, re-triages, then advances.
    Corrections whose fix_class is not a post-staging applier are skipped (recorded)."""
    audits: list[dict] = []
    ordered = sorted(corrections, key=lambda c: stage_for(str(c.get("fix_class") or "")))
    for c in ordered:
        fc = str(c.get("fix_class") or "")
        if stage is not None and stage_for(fc) != stage:
            continue
        applier = POST_STAGING_APPLIERS.get(fc)
        if applier is None:
            audits.append({"fix_class": fc, "status": "skipped",
                           "message": "not a post-staging applier (wrapper-patch or rule track)"})
            continue
        df, audit = applier(df, c.get("template") or {})
        audit["cik"] = c.get("cik")
        audits.append(audit)
    return df, audits
