"""Production consumers for PROMOTED agent fixes (gap 1).

Three families of gate-PASS agent fixes each have a git-tracked override store; this
module is their single production consumer, so trial and production share one code path:

- ``data/overrides/agent_anchor/<cik>/<quarter>.json`` -- Anchor Adjudicator grand
  totals (closure-verified). Consumed by the shadow conservation engine as the
  top-priority ``verified_override`` anchor kind (Layer D).
- ``data/overrides/agent_b2_corrections/<cik>/<fix_class>.json`` -- gate-PASS B2
  correction leaves. The raw-staging family (``comparative_period_filter``) is applied
  inside BDC staging while the frame still carries raw XBRL ``period`` (Layer B).
- ``data/overrides/agent_investigate_rules/<cik>/<rule_id>.json`` -- gate-PASS
  investigator rules (``pipeline.agent_rule`` vocabulary), applied at the tail of
  ``build_unified_holdings()`` scoped per CIK to BDC-source rows (Layer C).

Every application emits audit rows; ``write_application_audit`` persists them next to
the unified output each rebuild, diffed against the rule's authoring-time
``measured_impact``. A promoted rule that matches 0 rows or 10x the authored rows means
upstream extraction shifted under it: WARN and route to re-validation, never apply
silently.

Loaders take an explicit ``*_dir`` parameter defaulting to the config path so
fixture-based tests can pass an empty store. ASCII-only logs.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Optional

import pandas as pd

from pipeline import config

logger = logging.getLogger(__name__)

# Applied rows vs authoring-time rows beyond this ratio (either direction) flags drift.
DRIFT_ROW_RATIO = 10.0

_DIGITS_RE = re.compile(r"\D")

AUDIT_COLUMNS = ["layer", "cik", "rule_id", "rule_type", "status", "rows_changed",
                 "fv_affected", "authoring_rows", "authoring_fv", "drift", "message"]

# Fields whose modification by a correction layer is stamped into
# corrected_fields. Value fields feed the provenance re-verifier (a corrected
# row legitimately disagrees with its anchor -- scoping doc risk 4);
# classification fields are marked for audit symmetry.
CORRECTED_TRACKED_FIELDS = [
    "fair_value", "cost", "principal_amount", "shares_held",
    "pct_of_net_assets", "interest_rate", "basis_spread", "pik_rate",
    "maturity_date", "reference_rate_type", "coupon_type",
    "issuer_name", "instrument_description", "bdc_unrealized_gain_loss",
    "asset_category", "issuer_category", "index_classification",
    "exposure_type", "asset_class", "lien_position", "instrument_type",
    "is_subsidiary",
]


def append_corrected_fields(df: pd.DataFrame, idx, fields: list) -> None:
    """Append field names to df['corrected_fields'] at idx (';'-joined, deduped,
    order-preserving). Creates the column if absent."""
    if "corrected_fields" not in df.columns:
        df["corrected_fields"] = ""

    def _merge(val: object) -> str:
        parts = [p for p in str(val or "").split(";") if p]
        parts.extend(f for f in fields if f and f not in parts)
        return ";".join(parts)

    df.loc[idx, "corrected_fields"] = df.loc[idx, "corrected_fields"].map(_merge)


def mark_corrected_fields(before_tracked: pd.DataFrame,
                          after: pd.DataFrame) -> pd.DataFrame:
    """Stamp after['corrected_fields'] with tracked fields whose value changed
    vs the pre-applier snapshot. Index-aligned (appliers preserve the original
    index; added rows appear as new labels and are marked '_row:added').
    NA-safe string comparison; per-CIK sub-frames only -- never the full frame.

    Index-reset guard: agent_rule.apply_rules resets the frame to a 0-based
    integer index (reset_index + ignore_index in concat for row_add). When the
    index overlap with before_tracked is empty but lengths are compatible, align
    positionally so we do not mass-mark every row as '_row:added'.
    """
    common = after.index.intersection(before_tracked.index)

    # Detect index reset: no overlap, non-empty before, and after is at least as
    # long as before (appliers only drop or append rows, never reorder).
    index_reset = (
        len(common) == 0
        and len(before_tracked) > 0
        and len(after) >= len(before_tracked)
    )

    if index_reset:
        # Compare the first len(before) rows positionally.
        n = len(before_tracked)
        after_cmp = after.iloc[:n].set_axis(before_tracked.index)
        for col in before_tracked.columns:
            if col not in after_cmp.columns:
                continue
            b = before_tracked[col].astype("string").str.strip().fillna("")
            a = after_cmp[col].astype("string").str.strip().fillna("")
            changed_before_idx = before_tracked.index[(a != b).to_numpy()]
            # Map back to after's positional index for stamping.
            changed_pos = after.index[:n][
                before_tracked.index.isin(changed_before_idx)
                if len(changed_before_idx) < len(before_tracked.index)
                else slice(None)
            ]
            # Simpler: use a boolean mask over the first n rows.
            changed_mask = (a != b).to_numpy()
            changed_after_idx = after.index[:n][changed_mask]
            if len(changed_after_idx):
                append_corrected_fields(after, changed_after_idx, [col])
        # Tail rows beyond before length are genuinely added.
        if len(after) > n:
            append_corrected_fields(after, after.index[n:], ["_row:added"])
        return after

    # Normal case: index labels are preserved.
    added = after.index.difference(before_tracked.index)
    if len(added):
        append_corrected_fields(after, added, ["_row:added"])
    for col in before_tracked.columns:
        if col not in after.columns:
            continue
        b = before_tracked.loc[common, col].astype("string").str.strip().fillna("")
        a = after.loc[common, col].astype("string").str.strip().fillna("")
        changed = common[(a != b).to_numpy()]
        if len(changed):
            append_corrected_fields(after, changed, [col])
    return after


def mark_corrected_fields_by_ordinal(
    before_tracked: pd.DataFrame,
    corrected: pd.DataFrame,
    tracked_cols: list,
) -> pd.DataFrame:
    """Stamp corrected['corrected_fields'] using an ordinal key ('_cf_ord') that survives
    index resets, row drops, and row adds from agent_rule.apply_rules.

    before_tracked must contain '_cf_ord' (range(len(sub)) assigned before apply_rules).
    apply_rules passes unknown columns through (only drops '_rid'), so _cf_ord persists
    in corrected. Rows with NaN _cf_ord are genuinely added (row_add rule); inner-joined
    rows are compared field-by-field; dropped rows simply have no match and are silent.

    This replaces the positional-alignment guard in mark_corrected_fields for the Layer C
    rules path, which is the only path where apply_rules can both drop and add rows.
    """
    if "corrected_fields" not in corrected.columns:
        corrected["corrected_fields"] = ""

    # Added rows: _cf_ord is NaN (row_add appended with ignore_index=True -> no _cf_ord).
    if "_cf_ord" in corrected.columns:
        added_mask = corrected["_cf_ord"].isna()
    else:
        # Fallback: _cf_ord was not passed through (should not happen; see docstring).
        added_mask = pd.Series(False, index=corrected.index)

    if added_mask.any():
        append_corrected_fields(corrected, corrected.index[added_mask.to_numpy()], ["_row:added"])

    # Existing rows: inner-merge on _cf_ord to pair each surviving row with its before snapshot.
    if "_cf_ord" in corrected.columns and not corrected[~added_mask].empty:
        surviving = corrected.loc[~added_mask].copy()
        # before_tracked has _cf_ord as a regular column (set before apply_rules call).
        merged = surviving.reset_index(names=["_orig_idx"]).merge(
            before_tracked, on="_cf_ord", suffixes=("_after", "_before"), how="inner"
        )
        for col in tracked_cols:
            col_after = col + "_after" if (col + "_after") in merged.columns else col
            col_before = col + "_before" if (col + "_before") in merged.columns else None
            if col_before is None or col_before not in merged.columns:
                continue
            a = merged[col_after].astype("string").str.strip().fillna("")
            b = merged[col_before].astype("string").str.strip().fillna("")
            changed_rows = merged.loc[(a != b).to_numpy(), "_orig_idx"]
            if len(changed_rows):
                append_corrected_fields(corrected, pd.Index(changed_rows), [col])

    return corrected


def normalize_cik10(raw) -> str:
    """10-digit zero-padded CIK from any int/str form (empty stays empty)."""
    digits = _DIGITS_RE.sub("", str(raw or ""))
    return digits.zfill(10) if digits else ""


# --------------------------------------------------------------------------- anchors (Layer D)

def load_anchor_overrides(overrides_dir: Optional[Path] = None) -> list[dict]:
    """Adjudicated grand totals: [{cik, report_date, anchor_value}] (cik 10-digit).

    Files live at ``<dir>/<cik>/<quarter>.json`` with fields ``cik``,
    ``target_quarter``, ``grand_total`` (see scripts/agent_anchor/run_anchor.py
    promote). Malformed files are skipped with a WARN, never guessed at.
    """
    base = Path(overrides_dir) if overrides_dir is not None else config.AGENT_ANCHOR_OVERRIDES_DIR
    out: list[dict] = []
    for p in sorted(base.glob("*/*.json")) if base.exists() else []:
        try:
            # utf-8-sig: sandbox workers sometimes write JSON with a UTF-8 BOM.
            leaf = json.loads(p.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("anchor override unreadable, skipped: %s (%s)", p, exc)
            continue
        cik = normalize_cik10(leaf.get("cik") or p.parent.name)
        quarter = str(leaf.get("target_quarter") or p.stem).strip()
        total = leaf.get("grand_total")
        if not cik or not quarter or not isinstance(total, (int, float)):
            logger.warning("anchor override missing cik/target_quarter/grand_total, skipped: %s", p)
            continue
        out.append({"cik": cik, "report_date": quarter, "anchor_value": float(total)})
    return out


# --------------------------------------------------------------------------- corrections (Layer B)

def load_promoted_corrections(corrections_dir: Optional[Path] = None) -> list[dict]:
    """Gate-PASS B2 correction leaves from ``<dir>/<cik>/<fix_class>.json``."""
    base = (Path(corrections_dir) if corrections_dir is not None
            else config.AGENT_B2_CORRECTIONS_DIR)
    out: list[dict] = []
    for p in sorted(base.glob("*/*.json")) if base.exists() else []:
        try:
            leaf = json.loads(p.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("promoted correction unreadable, skipped: %s (%s)", p, exc)
            continue
        if isinstance(leaf, dict):
            out.append(leaf)
    return out


def apply_promoted_stage2_corrections(
    combined: pd.DataFrame, corrections: list[dict],
) -> tuple[pd.DataFrame, list[dict]]:
    """Apply gate-PASS POST-STAGING correction leaves to the unified frame (2026-08-13).

    Production consumer for the non-comparative correction classes (rate/unit rescale,
    column remap, classification fix, all-PIK normalization, missing-position add,
    dedup, spv_lookthrough). Scoping is structural, like apply_promoted_rules: each
    leaf is evaluated ONLY against its own CIK's BDC-source rows. Runs BEFORE Layer C
    rules so rules see corrected values. Emits one audit row per leaf with noop drift
    detection (a promoted correction that changes nothing has gone stale)."""
    from pipeline.agent_b2_appliers import POST_STAGING_APPLIERS

    audits: list[dict] = []
    todo = [c for c in corrections
            if str(c.get("fix_class") or "") in POST_STAGING_APPLIERS
            and str(c.get("fix_class")) != "comparative_period_filter"]
    if not todo or combined.empty or "cik" not in combined.columns:
        return combined, audits
    cik_norm = combined["cik"].astype(str).str.replace(r"\D", "", regex=True).str.zfill(10)
    is_bdc = (combined["source"].astype(str).str.lower() == "bdc") if "source" in combined.columns \
        else pd.Series(True, index=combined.index)
    by_cik: dict[str, list[dict]] = {}
    for c in todo:
        cik = normalize_cik10(c.get("cik"))
        if cik:
            by_cik.setdefault(cik, []).append(c)
    replaced: list[pd.DataFrame] = []
    drop_mask = pd.Series(False, index=combined.index)
    for cik in sorted(by_cik):
        mask = (cik_norm == cik) & is_bdc
        sub = combined.loc[mask]
        if sub.empty:
            for c in by_cik[cik]:
                audits.append({"layer": "unified_b2_corrections", "cik": cik,
                               "rule_id": str(c.get("fix_class")), "rule_type": "b2_correction",
                               "status": "no_rows", "rows_changed": 0, "fv_affected": 0.0,
                               "drift": "noop", "message": "no BDC rows for CIK in frame"})
            continue
        corrected = sub
        # JIT row_id (2026-08-21): row_id is assigned at the END of the build, so the
        # mid-build frame lacks the column and a row_id selector would error as
        # "column missing" here while the B3 gate replay (published frame, which HAS
        # row_id) passes. Materialize it on this CIK's sub-frame only when a leaf
        # selects by it; natural keys group by (cik, source, report_date), so the
        # sub-frame ids equal the published full-frame ids. Parity caveat: if another
        # leaf on the SAME CIK changes a key field (principal/shares), the published
        # id can drift from the pre-correction id -- the noop-drift audit flags that.
        _jit_row_id = False
        if "row_id" not in corrected.columns and any(
                str((((c.get("template") or {}).get("row_selector")) or {}).get("row_id") or "")
                for c in by_cik[cik]):
            from pipeline.unified_holdings import _assign_row_ids
            corrected = _assign_row_ids(corrected.copy())
            _jit_row_id = True
        for c in sorted(by_cik[cik], key=lambda x: str(x.get("fix_class"))):
            fc = str(c.get("fix_class"))
            from pipeline.agent_b2_appliers import apply_scoped
            _before = corrected[
                [tc for tc in CORRECTED_TRACKED_FIELDS if tc in corrected.columns]
            ].copy()
            corrected, audit = apply_scoped(corrected, c)
            corrected = mark_corrected_fields(_before, corrected)
            # fill structural identity on added rows (missing_position_add)
            if "cik" in corrected.columns and corrected["cik"].isna().any():
                added = corrected["cik"].isna()
                corrected.loc[added, "cik"] = cik
                if "source" in corrected.columns:
                    corrected.loc[added & corrected["source"].isna(), "source"] = "bdc"
            rows = int(audit.get("rows_changed") or audit.get("rows_dropped") or 0)
            status = str(audit.get("status") or "")
            audits.append({"layer": "unified_b2_corrections", "cik": cik,
                           "rule_id": fc, "rule_type": "b2_correction", "status": status,
                           "rows_changed": rows,
                           "fv_affected": abs(float(audit.get("fv_delta")
                                                    or audit.get("fv_dropped") or 0.0)),
                           "drift": ("noop" if status == "ok" and rows == 0 else ""),
                           "message": str(audit.get("message") or "")})
            if status != "ok":
                logger.warning("promoted b2 correction %s (cik=%s) did not apply: %s",
                               fc, cik, audit.get("message"))
        if _jit_row_id:
            # transient selector anchor only -- the end-of-build assignment owns the
            # published column; keeping it here would raggedly concat with untouched rows
            corrected = corrected.drop(
                columns=[c for c in ("row_id", "row_id_basis")
                         if c in corrected.columns])
        replaced.append(corrected)
        drop_mask |= mask
    if replaced:
        # Preserve the frame's original row order (2026-08-13 blast-radius lesson: a
        # concat that reorders rows perturbs downstream tie-breaks -- mode/first-value
        # fills -- at CIKs no correction touched). Added rows (NaN original index)
        # sort to the end.
        untouched = combined.loc[~drop_mask]
        merged = pd.concat([untouched, *replaced])
        combined = merged.sort_index(kind="mergesort").reset_index(drop=True)
    return combined, audits


def raw_staging_exclusions(corrections: list[dict]) -> list[dict]:
    """Deterministic (cik, report_date) targets for the raw-staging comparative filter."""
    targets: set[tuple[str, str]] = set()
    for c in corrections:
        if str(c.get("fix_class") or "") != "comparative_period_filter":
            continue
        cik = normalize_cik10(c.get("cik"))
        rd = str((c.get("template") or {}).get("report_date") or "").strip()
        if cik and rd:
            targets.add((cik, rd))
    return [{"cik": cik, "report_date": rd} for cik, rd in sorted(targets)]


def apply_raw_staging_exclusions(con, exclusions: list[dict]) -> list[dict]:
    """DELETE comparative-period rows from the staging ``bdc_raw`` DuckDB table.

    For each promoted (cik, report_date): drop rows of that filer-quarter whose raw
    XBRL ``period`` differs from ``report_date`` -- the same predicate as
    ``pipeline.agent_b2_appliers.apply_comparative_period_filter``, expressed in SQL
    against the pre-staging frame (unified holdings no longer carry ``period``).

    NULL/empty ``period`` rows ARE dropped for the target quarter: the pandas applier
    compares ``astype(str)`` so NULL never equals report_date, and staging's generic
    pre-filter deliberately KEEPS NULL-period rows -- those are exactly the
    comparative leaks this promoted, gate-validated fix targets.
    """
    audits: list[dict] = []
    if not exclusions:
        return audits
    cols = {r[0] for r in con.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'bdc_raw'"
    ).fetchall()}
    if "period" not in cols or "report_date" not in cols:
        return [{"layer": "raw_bdc_staging", "cik": e["cik"], "rule_id": "comparative_period_filter",
                 "rule_type": "comparative_period_filter", "status": "error",
                 "rows_changed": 0, "fv_affected": None, "authoring_rows": None,
                 "authoring_fv": None, "drift": "",
                 "message": "bdc_raw lacks period/report_date columns"} for e in exclusions]
    for e in exclusions:
        cik, rd = str(e["cik"]), str(e["report_date"]).replace("'", "''")
        where = (
            "LPAD(REGEXP_REPLACE(CAST(cik AS VARCHAR), '[^0-9]', '', 'g'), 10, '0') = "
            f"'{cik}' AND CAST(report_date AS VARCHAR) = '{rd}' "
            "AND (period IS NULL OR CAST(period AS VARCHAR) = '' "
            "     OR CAST(period AS VARCHAR) <> CAST(report_date AS VARCHAR))"
        )
        n, fv = con.execute(
            f"SELECT COUNT(*), SUM(TRY_CAST(fair_value AS DOUBLE)) FROM bdc_raw WHERE {where}"
        ).fetchone()
        con.execute(f"DELETE FROM bdc_raw WHERE {where}")
        audits.append({"layer": "raw_bdc_staging", "cik": cik,
                       "rule_id": f"comparative_period_filter/{e['report_date']}",
                       "rule_type": "comparative_period_filter", "status": "ok",
                       "rows_changed": int(n or 0),
                       "fv_affected": float(fv) if fv is not None else None,
                       "authoring_rows": None, "authoring_fv": None,
                       "drift": "noop" if not n else "",
                       "message": ""})
        if not n:
            logger.warning("promoted comparative_period_filter matched 0 rows: cik=%s %s "
                           "(upstream extraction may have shifted)", cik, e["report_date"])
        else:
            logger.info("raw-staging comparative filter: cik=%s %s dropped %d rows",
                        cik, e["report_date"], n)
    return audits


# --------------------------------------------------------------------------- rules (Layer C)

def load_promoted_rules(rules_dir: Optional[Path] = None) -> dict[str, list[dict]]:
    """{cik10: [rules]} from ``<dir>/<cik>/<rule_id>.json``.

    Within a CIK, rules apply in sorted-filename order -- the same order
    ``agent_rule.load_rules`` used when B3 gated them, so production application
    preserves gate-time semantics.
    """
    base = Path(rules_dir) if rules_dir is not None else config.AGENT_INVESTIGATE_RULES_DIR
    out: dict[str, list[dict]] = {}
    for p in sorted(base.glob("*/*.json")) if base.exists() else []:
        # Operator pull convention: rules quarantined into `_pulled_<reason>_<date>/`
        # are retired from production application. Without this guard the dir name
        # normalizes into a garbage CIK (e.g. 0020260722) and the pulled rule keeps
        # loading, permanently failing the promoted-rule health gate.
        if p.parent.name.startswith("_"):
            continue
        try:
            rule = json.loads(p.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("promoted rule unreadable, skipped: %s (%s)", p, exc)
            continue
        cik = normalize_cik10(p.parent.name)
        if cik:
            out.setdefault(cik, []).append(rule)
    return out


def _authoring_impact(rule: dict) -> tuple[Optional[int], Optional[float]]:
    """(rows, fv) totals from the rule's authoring-time measured_impact, if present."""
    mi = rule.get("measured_impact")
    if not isinstance(mi, dict) or not mi:
        return None, None
    rows = fv = 0.0
    for q in mi.values():
        if not isinstance(q, dict):
            return None, None
        rows += float(q.get("rows") or 0)
        fv += abs(float(q.get("fv") or 0))
    return int(rows), fv


def _applied_impact(audit: dict) -> tuple[int, float]:
    """(rows changed, abs FV affected) from one agent_rule applier audit."""
    rows = 0
    for k in ("rows_excluded", "rows_rescaled", "rows_set", "rows_added"):
        if k in audit:
            rows = int(audit[k] or 0)
            break
    fv = sum(abs(float(b.get("fv") or 0)) for b in (audit.get("per_quarter") or {}).values())
    return rows, fv


def _drift(rule: dict, applied_rows: int) -> str:
    """'' (ok) | 'noop' | 'row_drift' -- the re-validation routing signal."""
    if applied_rows == 0:
        return "noop"
    authored, _ = _authoring_impact(rule)
    if authored and (applied_rows > DRIFT_ROW_RATIO * authored
                     or applied_rows * DRIFT_ROW_RATIO < authored):
        return "row_drift"
    return ""


def apply_promoted_rules(
    combined: pd.DataFrame, rules_by_cik: dict[str, list[dict]],
) -> tuple[pd.DataFrame, list[dict]]:
    """Apply promoted investigator rules to the unified frame, per CIK, BDC rows only.

    Scoping is structural, not trust-based: a rule authored against one filer's
    dimension strings is only ever evaluated against that CIK's BDC-source rows, so it
    cannot touch N-PORT rows or another filer no matter what its predicate says. The
    full frame is never scanned row-by-row -- each CIK's slice is small.
    """
    audits: list[dict] = []
    if not rules_by_cik or combined.empty or "cik" not in combined.columns:
        return combined, audits
    from pipeline.agent_rule import apply_rules

    cik_norm = combined["cik"].astype(str).str.replace(r"\D", "", regex=True).str.zfill(10)
    is_bdc = (combined["source"].astype(str).str.lower() == "bdc") if "source" in combined.columns \
        else pd.Series(True, index=combined.index)

    replaced_parts: list[pd.DataFrame] = []
    drop_mask = pd.Series(False, index=combined.index)
    for cik in sorted(rules_by_cik):
        rules = rules_by_cik[cik]
        mask = (cik_norm == cik) & is_bdc
        sub = combined.loc[mask]
        if sub.empty:
            for r in rules:
                audits.append({"layer": "unified_agent_rules", "cik": cik,
                               "rule_id": str(r.get("rule_id")), "rule_type": str(r.get("rule_type")),
                               "status": "no_rows", "rows_changed": 0, "fv_affected": 0.0,
                               "authoring_rows": _authoring_impact(r)[0],
                               "authoring_fv": _authoring_impact(r)[1],
                               "drift": "noop", "message": "no BDC rows for CIK in frame"})
                logger.warning("promoted rule %s: no BDC rows for cik=%s in frame",
                               r.get("rule_id"), cik)
            continue
        tracked_cols = [tc for tc in CORRECTED_TRACKED_FIELDS if tc in sub.columns]
        # Ordinal-key diff: immune to index resets, row drops, and row adds.
        # apply_rules does reset_index(drop=True) which makes the returned index
        # 0-based; a positional-only guard fails when rows are dropped (len shrinks).
        # Stamping _cf_ord before the call lets us inner-merge on a stable ordinal
        # key after the call so dropped rows vanish cleanly, added rows have NaN _cf_ord.
        sub = sub.copy()
        sub["_cf_ord"] = range(len(sub))
        before_tracked = sub[tracked_cols + ["_cf_ord"]].copy()
        corrected, rule_audits = apply_rules(sub, rules)
        corrected = mark_corrected_fields_by_ordinal(before_tracked, corrected, tracked_cols)
        # row_add positions carry only holdings fields (see agent_rule.ADD_POSITION_KEYS);
        # identity columns are filled STRUCTURALLY from the rule's own CIK scope so an
        # added row can never orphan out of its filer.
        added = corrected["cik"].isna()
        if added.any():
            corrected.loc[added, "cik"] = cik
            if "source" in corrected.columns:
                corrected.loc[added & corrected["source"].isna(), "source"] = "bdc"
            if "entity_name" in corrected.columns:
                names = sub["entity_name"].dropna() if "entity_name" in sub.columns else []
                if len(names):
                    corrected.loc[added & corrected["entity_name"].isna(),
                                  "entity_name"] = sorted(names.mode())[0]
        for r, a in zip(rules, rule_audits):
            rows, fv = _applied_impact(a)
            authored_rows, authored_fv = _authoring_impact(r)
            drift = _drift(r, rows) if a.get("status") == "ok" else ""
            audits.append({"layer": "unified_agent_rules", "cik": cik,
                           "rule_id": str(a.get("rule_id")), "rule_type": str(r.get("rule_type")),
                           "status": str(a.get("status")), "rows_changed": rows,
                           "fv_affected": fv, "authoring_rows": authored_rows,
                           "authoring_fv": authored_fv, "drift": drift,
                           "message": "; ".join(a.get("errors") or []) or str(a.get("message") or "")})
            if a.get("status") != "ok":
                logger.warning("promoted rule %s (cik=%s) did not apply: %s",
                               a.get("rule_id"), cik, a.get("errors") or a.get("message"))
            elif drift:
                logger.warning("promoted rule %s (cik=%s) DRIFT=%s: applied rows=%d vs "
                               "authored rows=%s -- route to re-validation",
                               a.get("rule_id"), cik, drift, rows, authored_rows)
        # Drop the transient ordinal key before concat; combined.columns won't have it.
        corrected = corrected.drop(columns=["_cf_ord"], errors="ignore")
        drop_mask = drop_mask | mask
        replaced_parts.append(corrected)

    if not replaced_parts:
        return combined, audits
    out = pd.concat([combined.loc[~drop_mask], *replaced_parts], ignore_index=True)
    return out[combined.columns], audits


# --------------------------------------------------------------------------- audit artifact

def write_application_audit(audit_rows: list[dict], path: Path) -> None:
    """Persist the per-rebuild application audit (small frame; pandas is fine)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(audit_rows, columns=AUDIT_COLUMNS).to_csv(path, index=False)
    n_drift = sum(1 for r in audit_rows if r.get("drift"))
    logger.info("agent-fix application audit: %d entries (%d flagged) -> %s",
                len(audit_rows), n_drift, path.name)
