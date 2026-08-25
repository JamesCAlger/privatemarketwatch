"""Agent B2 remediation driver: discover -> (apply -> retriage -> gate) -> promote.

The deterministic orchestration for B2/B3. The PURE, unit-tested core lives here:
 - ``group_real_errors`` -- group real_error verdicts into (cik, fix_class) packets,
   stage-ordered, joined to their bundle metadata (cik/report_date/rule).
 - ``build_conservation_snapshots`` -- re-triage Tier-0 conservation deterministically from a
   holdings frame + the independent anchor (recompute value_sum vs stored anchor_value).
 - ``gate_conservation_packet`` -- build baseline+trial snapshots and run the B3 held-out gate.
 - ``promote_passes`` -- promote only PASS staged corrections into their production
   consumer store: wrapper-patch fixes apply the patched wrapper in place
   (data/overrides/bdc_xbrl_wrappers), everything else copies the leaf to
   data/overrides/agent_b2_corrections (consumed by build_unified_holdings).

The heavy step (``apply``) shells out to ``rebuild_unified_cik_trial.py --corrections`` to
produce trial holdings; that is operator-run (cached pipeline rebuild), not unit-tested here.
Snapshots for baseline vs trial holdings feed the pure gate.

Tier-0 conservation is the first target; other rules get their own snapshot builders later.
Cache-only, read-only on production until ``promote``. ASCII-only.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from pipeline import config
from pipeline.agent_b2_diagnose import diagnose, select_mechanism, _load_raw_cik
from pipeline.agent_b2_wrapper_patch import PROD_WRAPPER_DIR, apply_subtotal_filter
from pipeline.agent_b_held_out import gate_correction
from pipeline.correction_leaf import stage_for

DEFAULT_BASE = config.OUTPUT_DIR / "agent_b2"
DEFAULT_VERDICTS = config.OUTPUT_DIR / "review_queue" / "verdicts"
DEFAULT_CORRECTIONS = DEFAULT_BASE / "corrections"
DEFAULT_OVERRIDES = config.AGENT_B2_CORRECTIONS_DIR
DEFAULT_CONSERVATION = config.OUTPUT_DIR / "shadow" / "conservation_gate_results.csv"
TRIAL_REBUILD = config.PROJECT_ROOT / "scripts" / "rebuild_unified_cik_trial.py"
# Wrong-diagnosis loop (2026-08-21): a value-gate refusal that implicates the B1 VERDICT
# (fix authored for a defect the data does not show) appends here; the pass preflight
# warns while it is non-empty. Re-dispatching the review_ids to B1 stays an operator
# action -- verdict files are NEVER deleted or edited by this lane.
READJUDICATION_WORKLIST = DEFAULT_BASE / "readjudication_worklist.csv"
READJUDICATION_COLUMNS = ["cik", "fix_class", "source_review_ids", "batch_id",
                          "gated_utc", "reason"]

# Which layer applies each fix_class. wrapper_patch -> edit the per-CIK wrapper (staging);
# post_staging -> transform the unified holdings (agent_b2_appliers); rule_track -> a
# rule/anchor config edit (not a holdings correction). The applier that actually runs is
# WRAPPER_PATCH_APPLIERS / agent_b2_appliers.POST_STAGING_APPLIERS -- a fix_class in a flavor
# bucket without a registered applier is reported as not-yet-implemented, never silently
# dropped.
# Bridge for verdicts that PREDATE the findings[]/fix_class field (e.g. the smoke45
# conservation real_errors): derive a PROVISIONAL fix_class from the verdict's mechanism so
# they become packets -- but a derived fix_class on a Stage-3 SYMPTOM flag is only a GUESS
# (this is what produced the no-op subtotal patch on 0001377936). Such packets are marked
# `needs_diagnosis`; the deterministic anchor-scored battery (agent_b2_diagnose) resolves the
# real mechanism, or escalates, BEFORE a worker is dispatched. See annotate_with_diagnosis.
MECHANISM_TO_FIX_CLASS = {
    "subtotal_leak": "subtotal_filter",
    "cash_equivalent_leak": "subtotal_filter",
}
# Mechanisms that are Stage-3 symptom flags: a derived fix_class is provisional until the
# diagnosis battery measures which structural mechanism actually closes the residual.
SYMPTOM_MECHANISMS = {"subtotal_leak", "cash_equivalent_leak", "fv_conservation",
                      "conservation_overshoot"}

# 2026-08-13: classification_fix and column_remap moved from the (never-implemented)
# wrapper-patch aspiration to concrete post-staging frame appliers; rule_scope moved to
# the human policy stream (it asks to change a VALIDATION RULE's scope -- a detector
# decision, not a data fix -- and belongs in the end-of-quarter escalation basket).
WRAPPER_PATCH_FIX_CLASSES = {"subtotal_filter"}
POST_STAGING_FIX_CLASSES = {"dedup", "comparative_period_filter", "spv_lookthrough",
                            "rate_rescale", "unit_rescale", "all_pik_normalization",
                            "missing_position_add", "classification_fix", "column_remap",
                            "source_anchored_value"}
# identifier_rate_grammar (2026-08-21): a rate-in-identifier dialect proposal routed to
# the Agent A lane (grammar repair + deterministic A3 gate), never applied to holdings.
RULE_TRACK_FIX_CLASSES = {"anchor_fix", "identifier_rate_grammar"}
POLICY_FIX_CLASSES = {"rule_scope"}
WRAPPER_PATCH_APPLIERS = {"subtotal_filter": apply_subtotal_filter}

WORKLIST_COLUMNS = ["cik", "fix_class", "stage", "mechanism", "fix_class_derived",
                    "quarters", "rule_names", "n_findings", "source_review_ids"]


def implemented_fix_classes() -> set[str]:
    """Fix classes that can be validated AND applied in a trial run today."""
    from pipeline.agent_b2_appliers import POST_STAGING_APPLIERS

    return set(WRAPPER_PATCH_APPLIERS) | set(POST_STAGING_APPLIERS)


# --------------------------------------------------------------------------- pure core

def group_real_errors(verdicts: dict[str, dict], meta: dict[str, dict]) -> list[dict]:
    """Group real_error verdicts into ``(cik, fix_class)`` packets, joined to bundle meta.

    ``verdicts``: review_id -> verdict leaf. ``meta``: review_id -> {cik, report_date,
    rule_name} (from the B1 batch worklist / review queue). A multi-defect verdict (two
    findings) contributes to two packets. Verdicts with no actionable ``fix_class`` are
    grouped under fix_class ``None`` (stage 0) -- they need a human, not a template."""
    packets: dict[tuple, dict] = {}
    for rid, v in verdicts.items():
        if v.get("verdict") != "real_error":
            continue
        m = meta.get(rid)
        if not m:
            continue
        cik = str(m.get("cik") or "").strip()
        if not cik:
            continue
        findings = v.get("findings") or []
        fix_classes = [f.get("fix_class") for f in findings if f.get("fix_class")]
        derived = False
        if not fix_classes:
            fb = MECHANISM_TO_FIX_CLASS.get(str(v.get("mechanism") or ""))
            fix_classes = [fb] if fb else [None]
            derived = fb is not None
        needs_dx = derived and str(v.get("mechanism") or "") in SYMPTOM_MECHANISMS
        for fc in fix_classes:
            key = (cik, fc)
            p = packets.setdefault(key, {
                "cik": cik, "fix_class": fc, "stage": stage_for(fc or ""),
                "mechanism": v.get("mechanism", ""), "fix_class_derived": derived,
                "needs_diagnosis": needs_dx,
                "review_ids": [],
                "quarters": set(), "rule_names": set()})
            if rid not in p["review_ids"]:
                p["review_ids"].append(rid)
            if m.get("report_date"):
                p["quarters"].add(str(m["report_date"]))
            if m.get("rule_name"):
                p["rule_names"].add(str(m["rule_name"]))
    out = []
    for p in packets.values():
        out.append({**p, "quarters": sorted(p["quarters"]), "rule_names": sorted(p["rule_names"]),
                    "n_findings": len(p["review_ids"])})
    # stage order (1 before 2 before 3), then cik for stability
    return sorted(out, key=lambda p: (p["stage"] if p["stage"] else 99, p["cik"], str(p["fix_class"])))


def annotate_with_diagnosis(packet: dict, diagnosis: dict) -> dict:
    """Resolve a `needs_diagnosis` (Stage-3 symptom) packet with the deterministic battery's
    decision, REPLACING the guessed fix_class. ``use`` -> the measured reconciling mechanism
    (no longer derived); ``escalate`` -> fix_class None (route to a human, never dispatch a
    guessed template). Packets that are not needs_diagnosis are returned unchanged."""
    if not packet.get("needs_diagnosis"):
        return packet
    sel = select_mechanism(diagnosis)
    out = dict(packet)
    out["diagnosis"] = {
        "action": sel["action"], "reason": sel["reason"],
        "residual": diagnosis.get("residual"),
        "residual_after_composition": diagnosis.get("residual_after_composition"),
        "reconciles": diagnosis.get("reconciles"),
    }
    out["needs_diagnosis"] = False
    if sel["action"] == "use" and sel["fix_classes"]:
        out["fix_class"] = sel["fix_classes"][0]
        out["fix_class_candidates"] = list(sel["fix_classes"])
        out["stage"] = stage_for(sel["fix_classes"][0])
        out["fix_class_derived"] = False          # measured, not guessed
    else:
        out["fix_class"] = None                    # escalate -> human, not a template
        out["stage"] = stage_for("")
    return out


def diagnose_packet(packet: dict, *, holdings_path: Path, conservation_path: Path = DEFAULT_CONSERVATION,
                    raw_path: Path | None = None, target_quarter: str | None = None) -> dict:
    """IO wrapper: load a CIK's gate-counted holdings (+ optional raw staging) and run the
    anchor-scored battery for one quarter. Pure scoring lives in agent_b2_diagnose."""
    cik = str(packet["cik"])
    q = target_quarter or (packet.get("quarters") or [None])[-1]
    anchors = load_conservation_anchors(conservation_path, cik)
    anchor = anchors.get(str(q))
    if anchor is None:
        return {"reconciles": False, "escalate": True,
                "escalation_reason": f"no fv_conservation anchor for {cik} {q}"}
    df = (pd.read_parquet(holdings_path) if str(holdings_path).endswith(".parquet")
          else pd.read_csv(holdings_path, low_memory=False))
    df = df[df["report_date"].astype(str) == str(q)].copy()
    raw_df = _load_raw_cik(raw_path, cik, str(q)) if raw_path else None
    return diagnose(df, anchor, raw_df=raw_df, report_date=str(q))


def load_conservation_anchors(path: Path, cik: str, *, rule_name: str = "fv_conservation") -> dict[str, float]:
    """{report_date: anchor_value} for a CIK from the conservation gate results (the
    independent fund total; unchanged by our row edits)."""
    anchors: dict[str, float] = {}
    if not Path(path).exists():
        return anchors
    cik_norm = str(cik).lstrip("0")
    with open(path, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if r.get("rule_name") != rule_name:
                continue
            if str(r.get("cik") or "").lstrip("0") != cik_norm:
                continue
            av = (r.get("anchor_value") or "").strip()
            if av:
                try:
                    anchors[str(r.get("report_date"))] = float(av)
                except ValueError:
                    pass
    return anchors


def filter_holdings_cik(df: pd.DataFrame, cik: str) -> pd.DataFrame:
    """Restrict a holdings frame to one CIK (the gate sums fair_value per quarter, so an
    all-CIK frame would mix filers). Normalizes both sides (strip non-digits, drop leading
    zeros)."""
    if "cik" not in df.columns:
        return df
    target = str(cik).lstrip("0")
    norm = df["cik"].astype(str).str.replace(r"\D", "", regex=True).str.lstrip("0")
    return df[norm == target]


def build_conservation_snapshots(
    holdings_df: pd.DataFrame, anchors: dict[str, float], *, threshold_pct: float = 1.0,
) -> dict[str, dict]:
    """Per-quarter conservation snapshot from a holdings frame: recompute value_sum vs the
    stored anchor, flag fv_conservation when |residual| exceeds threshold_pct."""
    snaps: dict[str, dict] = {}
    if holdings_df is None or len(holdings_df) == 0 or "report_date" not in holdings_df.columns:
        return snaps
    fv = pd.to_numeric(holdings_df.get("fair_value", pd.Series(dtype=float)), errors="coerce").fillna(0.0)
    sums = fv.groupby(holdings_df["report_date"].astype(str)).sum()
    for q, vsum in sums.items():
        snap = {"quarter": q, "flags": [], "fv_at_risk": 0.0}
        anchor = anchors.get(q)
        if anchor is not None and float(anchor) != 0.0:
            resid = float(vsum) - float(anchor)
            snap["conservation"] = {"value_sum": float(vsum), "anchor_value": float(anchor)}
            if abs(100.0 * resid / float(anchor)) > threshold_pct:
                snap["flags"] = ["fv_conservation"]
                snap["fv_at_risk"] = abs(resid)
        snaps[q] = snap
    return snaps


def gate_conservation_packet(
    *, cik: str, target_quarter: str, baseline_df: pd.DataFrame, trial_df: pd.DataFrame,
    anchors: dict[str, float], threshold_pct: float = 1.0, **gate_kwargs,
):
    """Build baseline+trial conservation snapshots and run the B3 held-out gate."""
    baseline = build_conservation_snapshots(baseline_df, anchors, threshold_pct=threshold_pct)
    trial = build_conservation_snapshots(trial_df, anchors, threshold_pct=threshold_pct)
    return gate_correction(cik=cik, target_quarter=target_quarter,
                           target_flags=["fv_conservation"], baseline=baseline, trial=trial,
                           **gate_kwargs)


# --------------------------------------------------------------------------- value gate (2026-08-13)

# Fields the value gate audits for off-target invariance and canonical comparison.
_VALUE_GATE_COLUMNS = [
    "report_date", "issuer_name", "bdc_investment_identifier", "instrument_description",
    "fair_value", "cost", "principal_amount", "interest_rate", "pik_rate", "basis_spread",
    "asset_class", "index_classification", "exposure_type",
]
# Post-fix plausibility bounds for rate-family fields (percentage scale).
_FIELD_BOUNDS = {"interest_rate": (0.0, 60.0), "pik_rate": (0.0, 30.0),
                 "basis_spread": (0.0, 30.0)}
_FV_TOUCHING = {"missing_position_add"}  # plus unit_rescale when field == fair_value

# Cross-field magnitude plausibility (round-4 predicate). The q4b2exp_v3 magnitude
# pulls showed the failure mode: a quarter-scoped but UNSELECTED rescale/remap can push
# an entire quarter's values 10x-1000x away from the fund's own norm while staying
# inside the absolute _FIELD_BOUNDS (1572694 principal x1000 on every row for a 2-row
# FX defect; 1646614 rates /100; 1508655 pct_of_net_assets remapped into
# interest_rate). The un-gameable reference is the fund's OFF-target quarters, which a
# scoped correction structurally cannot touch: the post-fix target-quarter per-field
# average (and per-row principal/FV ratio median) must land within one order of
# magnitude of the median of the off-target per-quarter statistics -- unless the
# baseline target quarter was already at least that far out, in which case the fix is
# repairing a magnitude defect, not creating one.
_MAGNITUDE_NUMERIC_FIELDS = {"interest_rate", "pik_rate", "basis_spread",
                             "principal_amount", "shares_held", "fair_value", "cost",
                             "pct_of_net_assets"}
_MAGNITUDE_LOG10_TOL = 1.0      # 10x -- the repo's order-of-magnitude convention
_MAGNITUDE_MIN_VALUES = 3       # a quarter statistic needs >= this many non-zero values
_MAGNITUDE_MIN_NORM_QUARTERS = 2  # off-target quarters needed to establish a fund norm
_MAGNITUDE_IMPROVE_EPS = 0.05   # log10 slack: "not worse than baseline" tolerance


def _quarter_field_means(df: pd.DataFrame, field: str) -> dict[str, float]:
    """{report_date: mean(|field|)} over non-null non-zero values, per quarter with
    >= _MAGNITUDE_MIN_VALUES observations."""
    if field not in df.columns or "report_date" not in df.columns or not len(df):
        return {}
    vals = pd.to_numeric(df[field], errors="coerce").abs()
    ok = vals.notna() & (vals > 0)
    if not ok.any():
        return {}
    grouped = vals[ok].groupby(df.loc[ok, "report_date"].astype(str))
    return {q: float(s.mean()) for q, s in grouped if len(s) >= _MAGNITUDE_MIN_VALUES}


def _quarter_ratio_medians(df: pd.DataFrame) -> dict[str, float]:
    """{report_date: median(|principal_amount| / |fair_value|)} per row, per quarter
    with >= _MAGNITUDE_MIN_VALUES rows carrying both. The ratio is scale-free across
    portfolio growth, so it stays a stable norm even when a fund's per-quarter dollar
    averages legitimately move."""
    need = {"principal_amount", "fair_value", "report_date"}
    if not need <= set(df.columns) or not len(df):
        return {}
    pa = pd.to_numeric(df["principal_amount"], errors="coerce").abs()
    fv = pd.to_numeric(df["fair_value"], errors="coerce").abs()
    ok = pa.notna() & fv.notna() & (pa > 0) & (fv > 0)
    if not ok.any():
        return {}
    ratio = pa[ok] / fv[ok]
    grouped = ratio.groupby(df.loc[ok, "report_date"].astype(str))
    return {q: float(s.median()) for q, s in grouped if len(s) >= _MAGNITUDE_MIN_VALUES}


def _magnitude_fields(correction: dict) -> list[str]:
    """Numeric holdings fields a stage-2 correction writes to (magnitude-relevant)."""
    fix_class = str(correction.get("fix_class") or "")
    template = correction.get("template") or {}
    if fix_class in {"rate_rescale", "unit_rescale"}:
        fields = [str(template.get("field") or "")]
    elif fix_class == "column_remap":
        fields = [str(template.get("from_field") or ""), str(template.get("to_field") or "")]
    elif fix_class == "all_pik_normalization":
        fields = ["pik_rate"] + (["interest_rate"] if template.get("set_interest_to_cash") else [])
    else:
        fields = []
    return [f for f in fields if f in _MAGNITUDE_NUMERIC_FIELDS]


def _changed_row_means(
    base_df: pd.DataFrame, trial_df: pd.DataFrame, field: str, tq: str,
) -> tuple[float | None, float | None, int]:
    """(baseline_mean, trial_mean, n_changed) over target-quarter rows whose ``field``
    value the fix changed. Requires index alignment (trial derived from base via
    ``apply_scoped``); the caller passes the gate's own replay frame to guarantee it.
    Means are over non-zero absolute values; None when < _MAGNITUDE_MIN_VALUES."""
    if field not in base_df.columns or field not in trial_df.columns:
        return None, None, 0
    if "report_date" not in base_df.columns:
        return None, None, 0
    in_q = base_df["report_date"].astype(str) == tq
    b = pd.to_numeric(base_df.loc[in_q, field], errors="coerce")
    t = pd.to_numeric(trial_df[field].reindex(base_df.index), errors="coerce").loc[in_q]
    changed = (b != t) & ~(b.isna() & t.isna())
    tv = t[changed].abs()
    tv = tv[tv > 0]
    bv = b[changed].abs()
    bv = bv[bv > 0]
    t_mean = float(tv.mean()) if len(tv) >= _MAGNITUDE_MIN_VALUES else None
    b_mean = float(bv.mean()) if len(bv) else None
    return b_mean, t_mean, int(changed.sum())


def check_magnitude_plausibility(
    *, baseline_df: pd.DataFrame, trial_df: pd.DataFrame, correction: dict,
    target_quarter: str,
) -> tuple[bool, list[str]]:
    """Cross-field magnitude predicate for stage-2 value corrections.

    Three legs per touched field, all judged against the fund norm (median of the
    OFF-target per-quarter statistics, which a scoped fix cannot touch):
     - target-quarter average of the field;
     - average over the CHANGED rows only -- a blended quarter (many small remapped
       values mixed with surviving in-band values) can sit inside the 10x band while
       the rows the fix actually wrote are an order of magnitude off (the 1508655
       pct_of_net_assets -> interest_rate shape);
     - per-row principal/FV ratio median when principal/FV is touched (scale-free
       under portfolio growth).

    Returns ``(ok, reasons)``. Skips (passes) any leg where the fund norm cannot be
    established (< _MAGNITUDE_MIN_NORM_QUARTERS off-target quarters with data) or the
    target quarter has no post-fix values for the field (a vacated from_field is a
    remap consequence, not a magnitude break); those cases stay covered by
    replay-equivalence, _FIELD_BOUNDS sanity, and the conservation gate."""
    import math
    import statistics

    tq = str(target_quarter)
    reasons: list[str] = []

    def _norm(base_stats: dict[str, float]) -> tuple[float, int] | None:
        off = [v for q, v in base_stats.items() if q != tq and v > 0]
        if len(off) < _MAGNITUDE_MIN_NORM_QUARTERS:
            return None
        norm = float(statistics.median(off))
        return (norm, len(off)) if norm > 0 else None

    def _judge(label: str, norm_info: tuple[float, int] | None,
               base_val: float | None, trial_val: float | None) -> None:
        if norm_info is None or trial_val is None or trial_val <= 0:
            return
        norm, n_off = norm_info
        dev_trial = abs(math.log10(trial_val / norm))
        if dev_trial <= _MAGNITUDE_LOG10_TOL:
            return
        if (base_val is not None and base_val > 0
                and dev_trial <= abs(math.log10(base_val / norm)) + _MAGNITUDE_IMPROVE_EPS):
            return  # baseline was already at least this far out: repairing, not breaking
        reasons.append(
            f"{label} in {tq} lands {10 ** dev_trial:,.0f}x from the fund norm "
            f"({trial_val:,.4g} vs norm {norm:,.4g} from {n_off} off-target quarter(s))")

    fields = _magnitude_fields(correction)
    for f in fields:
        base_stats = _quarter_field_means(baseline_df, f)
        trial_stats = _quarter_field_means(trial_df, f)
        norm_info = _norm(base_stats)
        _judge(f"post-fix {f} quarter average", norm_info,
               base_stats.get(tq), trial_stats.get(tq))
        cr_base, cr_trial, _n = _changed_row_means(baseline_df, trial_df, f, tq)
        _judge(f"post-fix {f} changed-row average", norm_info, cr_base, cr_trial)
    if "principal_amount" in fields or "fair_value" in fields:
        base_r = _quarter_ratio_medians(baseline_df)
        _judge("post-fix principal/FV row-ratio median", _norm(base_r),
               base_r.get(tq), _quarter_ratio_medians(trial_df).get(tq))
    return (not reasons), reasons


def _canonical_value_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Comparison-stable projection: shared audit columns, numerics coerced+rounded,
    strings stripped, sorted by everything. Robust to CSV round-trip dtype noise."""
    cols = [c for c in _VALUE_GATE_COLUMNS if c in df.columns]
    out = pd.DataFrame(index=range(len(df)))
    for c in cols:
        num = pd.to_numeric(df[c], errors="coerce")
        if num.notna().sum() >= max(1, int(0.5 * df[c].notna().sum())):
            out[c] = num.round(4).values
        else:
            out[c] = df[c].fillna("").astype(str).str.strip().values
    return out.sort_values(cols, kind="mergesort", na_position="last").reset_index(drop=True)


# --------------------------------------------------------------------------- provenance gate (2026-08-25)

# Provenance/anchor columns an applier must NEVER write. These carry the
# re-verifier's anchor state (pipeline/provenance_reverify.py) plus the
# corrected_fields stamp, which production applies OUTSIDE the applier
# (pipeline/agent_promoted.py mark_corrected_fields). Any applier diff here is
# a defect, not a correction. source_row_id may be absent from holdings frames
# (recon-side id); only columns present in the baseline are inspected.
_PROVENANCE_COLUMNS = [
    "row_id", "source_row_id", "src_context_id", "src_context_count",
    "src_facts", "src_transforms", "src_filled_fields", "src_conflict_fields",
    "src_field_overrides", "corrected_fields",
]


def _norm_str(s: pd.Series) -> pd.Series:
    """mark_corrected_fields comparison normalization -- the gate's notion of
    'changed' must equal the production stamp's notion."""
    return s.astype("string").str.strip().fillna("")


def check_provenance_integrity(
    baseline_df: pd.DataFrame, expected_df: pd.DataFrame,
) -> tuple[dict[str, bool], list[str]]:
    """Provenance predicates over the gate's own replay frame:

    - provenance_invariant: _PROVENANCE_COLUMNS byte-identical on rows that
      survive the applier (index intersection; appliers preserve labels).
      A provenance column dropped by the applier also fails.
    - changed_fields_tracked: every other changed column is in
      CORRECTED_TRACKED_FIELDS, so the production corrected_fields stamp
      records it and the re-verifier excuses it; a changed untracked column
      would surface post-promotion as unexplained ledger drift.

    Rows added by the applier (new index labels) are exempt -- production
    stamps them '_row:added'. Judged on expected_df (applier(baseline)), not
    the staged trial: promotion re-applies the correction JSON in production,
    so the applier's own behavior is what ships.
    """
    from pipeline.agent_promoted import CORRECTED_TRACKED_FIELDS

    checks = {"provenance_invariant": True, "changed_fields_tracked": True}
    reasons: list[str] = []
    common = baseline_df.index.intersection(expected_df.index)

    prov_bad: list[str] = []
    untracked: list[str] = []
    for col in baseline_df.columns:
        if col not in expected_df.columns:
            if col in _PROVENANCE_COLUMNS:
                prov_bad.append(f"{col} (dropped)")
            continue
        b = _norm_str(baseline_df.loc[common, col])
        e = _norm_str(expected_df.loc[common, col])
        if bool((b != e).any()):
            if col in _PROVENANCE_COLUMNS:
                prov_bad.append(col)
            elif col not in CORRECTED_TRACKED_FIELDS:
                untracked.append(col)

    if prov_bad:
        checks["provenance_invariant"] = False
        reasons.append(f"applier modified provenance column(s): {prov_bad}")
    if untracked:
        checks["changed_fields_tracked"] = False
        reasons.append(
            f"applier changed untracked column(s) {untracked}: the production "
            f"corrected_fields stamp would miss them (unexplained reverifier drift)")
    return checks, reasons


def gate_value_packet(
    *, cik: str, target_quarter: str, baseline_df: pd.DataFrame, trial_df: pd.DataFrame,
    correction: dict, grounding_df: pd.DataFrame | None = None,
) -> dict:
    """B3 gate for stage-2 VALUE corrections (and missing_position_add).

    The conservation gate sees only aggregates, which a rate rescale or column remap
    never moves -- so value fixes need per-row predicates:

    - replay_equivalence: trial frame must equal applier(baseline) exactly under the
      canonical projection. This subsumes off-target invariance AND expected-change
      verification in one deterministic check: the promoted correction may do exactly
      what the applier does to the baseline, nothing else.
    - field_sanity: post-fix values of the changed rate-family field inside plausibility
      bounds; fair_value magnitudes sane.
    - fv_change_scoped: for non-FV fix classes, total FV identical to baseline (< $1
      drift); FV-touching classes defer to the conservation gate run alongside.
    - magnitude_plausible (round-4): the fix must leave the target quarter's per-field
      averages and principal/FV row ratio within one order of magnitude of the fund's
      off-target-quarter norm (see check_magnitude_plausibility).
    - provenance_invariant: the applier must not write or drop provenance/anchor
      columns (src_*, row_id, corrected_fields); production stamps corrected_fields
      outside the applier, and the re-verifier's anchor state must survive.
    - changed_fields_tracked: every column the applier changes must be in
      CORRECTED_TRACKED_FIELDS so the production corrected_fields stamp records
      it; an untracked change would surface as unexplained reverifier drift.
    - grounding_verified (missing_position_add only): every position's source_row_id
      must exist in the grounding frame for this CIK with fair_value within 0.5%.
      Missing grounding data FAILS (fail-closed; no fabricated positions).

    Replay uses ``apply_scoped`` (not the bare applier) so the expected frame matches
    the production application path: a scoped correction replayed over a multi-quarter
    baseline must not touch off-scope quarters.
    """
    from pipeline.agent_b2_appliers import POST_STAGING_APPLIERS, apply_scoped

    fix_class = str(correction.get("fix_class") or "")
    template = correction.get("template") or {}
    checks: dict[str, bool] = {}
    reasons: list[str] = []

    applier = POST_STAGING_APPLIERS.get(fix_class)
    if applier is None:
        return {"cik": cik, "target_quarter": target_quarter, "verdict": "FAIL",
                "checks": {}, "reasons": [f"no applier for fix_class {fix_class!r}"]}

    expected_df, replay_audit = apply_scoped(baseline_df, correction)
    if replay_audit.get("status") != "ok":
        return {"cik": cik, "target_quarter": target_quarter, "verdict": "FAIL",
                "checks": {"replay_ok": False},
                "reasons": [f"applier replay error: {replay_audit.get('message')}"]}
    if not int(replay_audit.get("rows_changed") or 0):
        checks["replay_ok"] = False
        reasons.append("correction is a no-op on the baseline frame (stale or mis-selected)")

    exp_c, got_c = _canonical_value_frame(expected_df), _canonical_value_frame(trial_df)
    replay_eq = exp_c.shape == got_c.shape and exp_c.equals(got_c)
    checks["replay_equivalence"] = replay_eq
    if not replay_eq:
        reasons.append(
            f"trial != applier(baseline): expected {exp_c.shape[0]} rows, got {got_c.shape[0]}"
            if exp_c.shape != got_c.shape else
            "trial frame diverges from applier(baseline) beyond the correction itself")

    field = str(template.get("field") or "")
    sane = True
    if field in _FIELD_BOUNDS and field in trial_df.columns:
        lo, hi = _FIELD_BOUNDS[field]
        vals = pd.to_numeric(trial_df[field], errors="coerce").dropna()
        bad = int(((vals < lo) | (vals > hi)).sum())
        if bad:
            sane = False
            reasons.append(f"{bad} post-fix {field} value(s) outside ({lo}, {hi}]")
    if "fair_value" in trial_df.columns:
        fv = pd.to_numeric(trial_df["fair_value"], errors="coerce").abs()
        if int((fv > 1e12).sum()):
            sane = False
            reasons.append("post-fix |fair_value| exceeds $1T sanity bound")
    checks["field_sanity"] = sane

    # Judged on the gate's own replay frame (row-aligned with baseline by
    # construction); replay_equivalence pins trial_df to it canonically.
    mag_ok, mag_reasons = check_magnitude_plausibility(
        baseline_df=baseline_df, trial_df=expected_df, correction=correction,
        target_quarter=target_quarter)
    checks["magnitude_plausible"] = mag_ok
    reasons.extend(mag_reasons)

    prov_checks, prov_reasons = check_provenance_integrity(baseline_df, expected_df)
    checks.update(prov_checks)
    reasons.extend(prov_reasons)

    fv_touching = fix_class in _FV_TOUCHING or (
        fix_class == "unit_rescale" and field == "fair_value")
    base_fv = pd.to_numeric(baseline_df.get("fair_value"), errors="coerce").fillna(0).sum()
    trial_fv = pd.to_numeric(trial_df.get("fair_value"), errors="coerce").fillna(0).sum()
    if fv_touching:
        checks["fv_change_scoped"] = True  # conservation gate owns the FV judgement
    else:
        scoped = abs(float(base_fv) - float(trial_fv)) < 1.0
        checks["fv_change_scoped"] = scoped
        if not scoped:
            reasons.append(f"non-FV fix moved total FV by {float(trial_fv) - float(base_fv):,.0f}")

    if fix_class == "missing_position_add":
        grounded = False
        positions = list(template.get("positions") or [])
        if grounding_df is not None and len(grounding_df) and "source_row_id" in grounding_df.columns:
            gid = grounding_df["source_row_id"].astype(str)
            gfv = pd.to_numeric(grounding_df.get("fair_value"), errors="coerce")
            misses = []
            for p in positions:
                sid, want = str(p.get("source_row_id") or ""), float(p.get("fair_value") or 0)
                hit = grounding_df.index[gid == sid]
                ok = any(abs(float(gfv.loc[i] or 0) - want) <= max(1000.0, abs(want) * 0.005)
                         for i in hit)
                if not ok:
                    misses.append(sid)
            grounded = not misses
            if misses:
                reasons.append(f"position source_row_id(s) not grounded in staging: {misses}")
        else:
            reasons.append("no grounding frame supplied for missing_position_add (fail-closed)")
        checks["grounding_verified"] = grounded
    else:
        checks["grounding_verified"] = True

    checks.setdefault("replay_ok", True)
    verdict = "PASS" if all(checks.values()) else "FAIL"
    return {"cik": cik, "target_quarter": target_quarter, "verdict": verdict,
            "gate_kind": "value", "fix_class": fix_class, "checks": checks,
            "reasons": reasons or ["all value-gate predicates clear"]}


def promote_passes(gate_results: list[dict], *, corrections_dir: Path, overrides_dir: Path,
                   wrapper_dir: Path = PROD_WRAPPER_DIR, batch_id: str | None = None,
                   allow_overwrite: bool = False,
                   fleet_thresholds_path: Path | None = None) -> list[dict]:
    """Promote only PASS staged corrections into their PRODUCTION consumer store.

    Layer routing (gap 1): a wrapper-patch correction (e.g. subtotal_filter) applies the
    PATCHED WRAPPER in place into ``wrapper_dir`` (data/overrides/bdc_xbrl_wrappers --
    the store production staging already reads), with provenance; re-promotion is a
    recorded no-op, never a duplicate provenance append. Every other correction copies
    the leaf to ``overrides_dir`` (data/overrides/agent_b2_corrections), which
    ``build_unified_holdings`` consumes at raw staging. Returns the promoted records.

    Guards (2026-08-21):
      - HARD refuse-overwrite: promotion never overwrites an existing LIVE leaf unless
        ``allow_overwrite`` is passed explicitly (sanctioned re-author after an operator
        pull). Refusals are recorded as status ``refused_overwrite``, never silent.
      - Fleet acceptance (flag-gated by the thresholds file's ``enforce`` block, OFF at
        ship): when ``enforce.promote_requires_pass`` is true and ``batch_id`` is given,
        promotion requires a PASS ``fleet_acceptance_<batch_id>.json`` artifact."""
    corrections_dir, overrides_dir = Path(corrections_dir), Path(overrides_dir)
    if batch_id:
        _require_fleet_acceptance(batch_id, fleet_thresholds_path)
    promoted: list[dict] = []
    for g in gate_results:
        if g.get("verdict") != "PASS":
            continue
        cik, mech = str(g.get("cik")), str(g.get("mechanism"))
        src = corrections_dir / cik / f"{mech}.json"
        if not src.exists():
            continue
        try:
            leaf = json.loads(src.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            leaf = {}
        fc = str(leaf.get("fix_class") or "")
        applier = WRAPPER_PATCH_APPLIERS.get(fc)
        if applier is not None:
            prov = {k: leaf.get(k) for k in ("source_review_ids", "confidence")
                    if leaf.get(k) is not None}
            prov["promoted_gate"] = {"mechanism": mech, "verdict": "PASS"}
            audit = applier(cik, leaf.get("template") or {},
                            out_wrapper_dir=Path(wrapper_dir),
                            source_wrapper_dir=Path(wrapper_dir),
                            provenance=prov, write_if_noop=False)
            promoted.append({"cik": cik, "mechanism": mech, "layer": "wrapper_patch",
                             "src": str(src), "dst": audit.get("out_path"),
                             "status": audit.get("status"), "audit": audit})
        else:
            dst = overrides_dir / cik / f"{mech}.json"
            if dst.exists() and not allow_overwrite:
                # HARD data-protection guard: dispatch preflight skips existing packets,
                # but nothing at PROMOTE time prevented a same-keyed staged leaf from
                # silently overwriting a live rule via a path that bypassed dispatch.
                # Sanctioned re-authors (operator pulled the old leaf first, or passes
                # --allow-overwrite deliberately) are the only overwrite route.
                promoted.append({"cik": cik, "mechanism": mech, "layer": "post_staging",
                                 "src": str(src), "dst": str(dst),
                                 "status": "refused_overwrite"})
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            promoted.append({"cik": cik, "mechanism": mech, "layer": "post_staging",
                             "src": str(src), "dst": str(dst), "status": "ok"})
    return promoted


def _require_fleet_acceptance(batch_id: str, thresholds_path: Path | None = None) -> None:
    """Raise unless fleet acceptance allows promotion for this batch.

    No-op while the thresholds file's ``enforce.promote_requires_pass`` is false
    (advisory mode -- the first fleet validates the evaluator itself)."""
    from scripts import fleet_acceptance as fa
    try:
        thresholds = fa.load_thresholds(thresholds_path)
    except (OSError, json.JSONDecodeError):
        return  # no thresholds file -> advisory-off behavior
    if not thresholds.get("enforce", {}).get("promote_requires_pass"):
        return
    artifact = fa.acceptance_artifact_path(batch_id)
    if not artifact.exists():
        raise RuntimeError(
            f"fleet acceptance enforce.promote_requires_pass is ON and no artifact "
            f"exists for batch {batch_id}: run python -m scripts.fleet_acceptance "
            f"--batch-id {batch_id} first ({artifact})")
    result = json.loads(artifact.read_text(encoding="utf-8-sig"))
    if result.get("verdict") != "PASS":
        failing = [c["id"] for c in result.get("checks", []) if not c.get("pass")]
        raise RuntimeError(
            f"fleet acceptance verdict is {result.get('verdict')} for batch "
            f"{batch_id}; failing checks: {', '.join(failing) or '(none listed)'}. "
            f"Stop, diagnose, re-fleet -- do not widen the bar.")


# --------------------------------------------------------------------------- apply orchestration

def flavor_of(fix_class: str) -> str:
    """Which remediation layer owns a fix_class."""
    if fix_class in WRAPPER_PATCH_FIX_CLASSES:
        return "wrapper_patch"
    if fix_class in POST_STAGING_FIX_CLASSES:
        return "post_staging"
    if fix_class in RULE_TRACK_FIX_CLASSES:
        return "rule_track"
    return "needs_human"


def route_corrections(corrections: list[dict]) -> dict[str, list[dict]]:
    """Bucket validated corrections by remediation flavor (pure)."""
    buckets: dict[str, list[dict]] = {"wrapper_patch": [], "post_staging": [],
                                      "rule_track": [], "needs_human": []}
    for c in corrections:
        buckets[flavor_of(str(c.get("fix_class") or ""))].append(c)
    return buckets


def load_corrections(corrections_dir: Path, cik: str) -> list[dict]:
    """Load staged correction leaves for one CIK (corrections/<cik>/<mechanism>.json).
    Escalation leaves (*.escalation.json) are diagnoses for the human/template-authoring
    basket, never applied -- excluded here."""
    d = Path(corrections_dir) / str(cik)
    out: list[dict] = []
    if not d.exists():
        return out
    for p in sorted(q for q in d.glob("*.json")
                    if not q.name.endswith(".escalation.json")):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return out


def prepare_trial_wrappers(
    cik: str, corrections: list[dict], *, out_wrapper_dir: Path,
    source_wrapper_dir: Path | None = None,
) -> list[dict]:
    """Run the implemented wrapper-patch appliers for a CIK's wrapper-domain corrections,
    writing trial wrappers to ``out_wrapper_dir``. Returns per-correction audits; an
    unimplemented wrapper-patch fix_class is recorded, never silently skipped."""
    audits: list[dict] = []
    for c in corrections:
        fc = str(c.get("fix_class") or "")
        if fc not in WRAPPER_PATCH_FIX_CLASSES:
            continue
        applier = WRAPPER_PATCH_APPLIERS.get(fc)
        if applier is None:
            audits.append({"fix_class": fc, "status": "not_implemented",
                           "message": "wrapper-patch applier not yet built"})
            continue
        kwargs = {} if source_wrapper_dir is None else {"source_wrapper_dir": Path(source_wrapper_dir)}
        prov = {k: c.get(k) for k in ("source_review_ids", "confidence") if c.get(k) is not None}
        audits.append(applier(cik, c.get("template") or {}, out_wrapper_dir=Path(out_wrapper_dir),
                              provenance=prov or None, **kwargs))
    return audits


def build_trial_command(
    cik: str, *, wrapper_dir: Path | None = None, corrections_dir: Path | None = None,
    stage: int | None = None, python: str = sys.executable,
) -> list[str]:
    """Assemble the rebuild_unified_cik_trial invocation that produces trial holdings
    (pure -- the caller decides whether to run it)."""
    cmd = [python, str(TRIAL_REBUILD), "--cik", str(cik)]
    if wrapper_dir is not None:
        cmd += ["--wrapper-dir", str(wrapper_dir)]
    if corrections_dir is not None:
        cmd += ["--corrections", str(corrections_dir)]
    if stage is not None:
        cmd += ["--stage", str(stage)]
    return cmd


def apply_packet(
    batch_id: str, cik: str, *, stage: int | None = None, base_dir: Path = DEFAULT_BASE,
    corrections_dir: Path = DEFAULT_CORRECTIONS, run: bool = False,
) -> dict:
    """Route a CIK's corrections, materialize trial wrappers for the wrapper-patch ones, and
    assemble (optionally run) the trial-rebuild command. The rebuild itself is heavy
    (cached pipeline) -- default is to PREPARE + return the command for an operator to run."""
    corrections = load_corrections(corrections_dir, cik)
    if stage is not None:
        corrections = [c for c in corrections if stage_for(str(c.get("fix_class") or "")) == stage]
    # Gate-side source verification (2026-08-21): a source_anchored_value leaf must
    # survive the filing re-parse (cell + row-fingerprint witnesses + table health +
    # bridge co-sign) HERE too, not only at dispatcher intake -- the apply path may be
    # run on leaves that never went through this batch's dispatcher. Fail closed.
    source_anchor_refusals: list[dict] = []
    kept: list[dict] = []
    for c in corrections:
        if str(c.get("fix_class") or "") != "source_anchored_value":
            kept.append(c)
            continue
        from pipeline.source_anchor_verify import verify_leaf
        vrep = verify_leaf(c)
        if vrep["ok"]:
            kept.append(c)
        else:
            source_anchor_refusals.append(
                {"cik": cik, "fix_class": "source_anchored_value",
                 "errors": vrep["errors"][:6]})
    corrections = kept
    routed = route_corrections(corrections)
    trial_wrapper_dir = base_dir / "batch" / batch_id / "trial_wrappers" / str(cik)
    wrapper_audits = prepare_trial_wrappers(cik, routed["wrapper_patch"],
                                            out_wrapper_dir=trial_wrapper_dir)
    has_wrapper = any(a.get("status") == "ok" for a in wrapper_audits)
    cmd = build_trial_command(
        cik, wrapper_dir=trial_wrapper_dir if has_wrapper else None,
        corrections_dir=Path(corrections_dir) if routed["post_staging"] else None, stage=stage)
    result = {"cik": cik, "stage": stage,
              "n_wrapper_patch": len(routed["wrapper_patch"]),
              "n_post_staging": len(routed["post_staging"]),
              "n_needs_human": len(routed["needs_human"]),
              "source_anchor_refusals": source_anchor_refusals,
              "wrapper_audits": wrapper_audits, "trial_command": cmd, "ran": False}
    if run:
        proc = subprocess.run(cmd, capture_output=True, text=True)
        result["ran"] = True
        result["returncode"] = proc.returncode
    return result


# --------------------------------------------------------------------------- CLI glue

def _read_meta(source_worklist: Path) -> dict[str, dict]:
    meta: dict[str, dict] = {}
    with open(source_worklist, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            rid = (r.get("review_id") or "").strip()
            if rid:
                meta[rid] = {"cik": r.get("cik"), "report_date": r.get("report_date"),
                             "rule_name": r.get("rule_name")}
    return meta


def discover(batch_id: str, *, base_dir: Path = DEFAULT_BASE, verdicts_dir: Path = DEFAULT_VERDICTS,
             source_worklist: Path | None = None) -> dict:
    if source_worklist is None or not Path(source_worklist).exists():
        raise FileNotFoundError("discover needs --source-worklist (the B1 batch worklist mapping review_id->cik)")
    meta = _read_meta(Path(source_worklist))
    verdicts: dict[str, dict] = {}
    for rid in sorted(meta):
        p = Path(verdicts_dir) / f"{rid}.json"
        if not p.exists():
            continue
        try:
            verdicts[p.stem] = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
    packets = group_real_errors(verdicts, meta)
    batch_dir = base_dir / "batch" / batch_id
    batch_dir.mkdir(parents=True, exist_ok=True)
    out = batch_dir / "worklist.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=WORKLIST_COLUMNS)
        w.writeheader()
        for p in packets:
            w.writerow({"cik": p["cik"], "fix_class": p["fix_class"], "stage": p["stage"],
                        "mechanism": p["mechanism"],
                        "fix_class_derived": p.get("fix_class_derived", False),
                        "quarters": ";".join(p["quarters"]),
                        "rule_names": ";".join(p["rule_names"]), "n_findings": p["n_findings"],
                        "source_review_ids": ";".join(p["review_ids"])})
    return {"batch_id": batch_id, "n_packets": len(packets),
            "n_actionable": sum(1 for p in packets if p["fix_class"]), "worklist": str(out)}


def is_diagnosis_refusal(value_gate_result: dict) -> bool:
    """True when a value-gate FAIL implicates the B1 DIAGNOSIS, not B2 authoring.

    The v3-era 'defect_signature' check name is legacy; on the current gate the
    wrong-diagnosis signal is the magnitude predicate refusing (the field the fix
    'repairs' was already plausible) or a reason naming the rate signature."""
    if value_gate_result.get("verdict") != "FAIL":
        return False
    if value_gate_result.get("checks", {}).get("magnitude_plausible") is False:
        return True
    reasons = value_gate_result.get("reasons") or []
    return any(("rate signature" in str(r).lower()) or ("magnitude" in str(r).lower())
               for r in reasons)


def append_readjudication(entries: list[dict], path: Path = READJUDICATION_WORKLIST) -> int:
    """Append wrong-diagnosis rows to the re-adjudication worklist (append-only).

    Dedupe key: (review_id, fix_class) pairs derived by splitting each row's
    ``source_review_ids`` on ';'. Rows whose every pair is already present are
    dropped. Never touches verdict files."""
    seen: set[tuple[str, str]] = set()
    if path.exists():
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                for rid in str(row.get("source_review_ids", "")).split(";"):
                    if rid:
                        seen.add((rid, row.get("fix_class", "")))
    fresh = []
    for e in entries:
        pairs = [(rid, e.get("fix_class", ""))
                 for rid in str(e.get("source_review_ids", "")).split(";") if rid]
        if pairs and all(p in seen for p in pairs):
            continue
        seen.update(pairs)
        fresh.append({c: e.get(c, "") for c in READJUDICATION_COLUMNS})
    if not fresh:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.exists()
    with path.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=READJUDICATION_COLUMNS)
        if new_file:
            w.writeheader()
        for row in fresh:
            w.writerow(row)
    return len(fresh)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Agent B2 remediation driver (discover/gate/promote).")
    sub = ap.add_subparsers(dest="mode", required=True)
    d = sub.add_parser("discover")
    d.add_argument("batch_id")
    d.add_argument("--source-worklist", type=Path, required=True,
                   help="B1 batch worklist.csv mapping review_id -> cik/report_date/rule_name")
    d.add_argument("--verdicts-dir", type=Path, default=DEFAULT_VERDICTS)

    a = sub.add_parser("apply", help="Route a CIK's corrections + assemble the trial rebuild.")
    a.add_argument("batch_id")
    a.add_argument("--cik", required=True)
    a.add_argument("--stage", type=int, default=None)
    a.add_argument("--corrections-dir", type=Path, default=DEFAULT_CORRECTIONS)
    a.add_argument("--run", action="store_true", help="Actually run the (heavy) trial rebuild.")

    g = sub.add_parser("gate", help="Gate one packet from baseline vs trial holdings CSVs.")
    g.add_argument("--cik", required=True)
    g.add_argument("--target-quarter", required=True)
    g.add_argument("--baseline-holdings", type=Path, required=True)
    g.add_argument("--trial-holdings", type=Path, required=True)
    g.add_argument("--conservation", type=Path, default=DEFAULT_CONSERVATION)
    g.add_argument("--threshold-pct", type=float, default=1.0)
    g.add_argument("--correction", type=Path, default=None,
                   help="Correction leaf JSON: stage-2 value classes run the per-row "
                        "value gate (replay-equivalence etc.) IN ADDITION to the "
                        "conservation gate; combined verdict is the AND.")
    g.add_argument("--grounding", type=Path, default=None,
                   help="Frame with source_row_id+fair_value for missing_position_add "
                        "grounding (csv/parquet). Fail-closed when absent.")
    g.add_argument("--batch-id", default="",
                   help="Batch id recorded on re-adjudication worklist rows.")
    g.add_argument("--readju-worklist", type=Path, default=READJUDICATION_WORKLIST,
                   help="Wrong-diagnosis refusals append here (append-only; "
                        "verdicts are never touched).")

    dx = sub.add_parser("diagnose", help="Anchor-scored battery for a Stage-3 symptom packet "
                                         "(replaces the guessed mechanism with a measured decision).")
    dx.add_argument("--cik", required=True)
    dx.add_argument("--target-quarter", required=True)
    dx.add_argument("--holdings", type=Path, required=True, help="per-CIK gate-counted holdings csv/parquet")
    dx.add_argument("--raw-holdings", type=Path, default=None, help="bdc_holdings.parquet (raw cross-reference)")
    dx.add_argument("--conservation", type=Path, default=DEFAULT_CONSERVATION)

    args = ap.parse_args(argv)
    if args.mode == "discover":
        print(json.dumps(discover(args.batch_id, source_worklist=args.source_worklist,
                                  verdicts_dir=args.verdicts_dir), indent=2))
        return 0
    if args.mode == "apply":
        print(json.dumps(apply_packet(args.batch_id, args.cik, stage=args.stage,
                                      corrections_dir=args.corrections_dir, run=args.run), indent=2))
        return 0
    if args.mode == "gate":
        anchors = load_conservation_anchors(args.conservation, args.cik)
        # Filter BOTH frames to the CIK -- the baseline may be the full production holdings.
        base_df = filter_holdings_cik(pd.read_csv(args.baseline_holdings, low_memory=False), args.cik)
        trial_df = filter_holdings_cik(pd.read_csv(args.trial_holdings, low_memory=False), args.cik)
        res = gate_conservation_packet(cik=args.cik, target_quarter=args.target_quarter,
                                       baseline_df=base_df, trial_df=trial_df, anchors=anchors,
                                       threshold_pct=args.threshold_pct)
        out = {"cik": res.cik, "target_quarter": res.target_quarter,
               "verdict": res.verdict, "checks": res.checks, "reasons": res.reasons}
        if args.correction is not None:
            correction = json.loads(Path(args.correction).read_text(encoding="utf-8-sig"))
            grounding_df = None
            if args.grounding is not None and Path(args.grounding).exists():
                gp = Path(args.grounding)
                grounding_df = (pd.read_parquet(gp) if gp.suffix == ".parquet"
                                else pd.read_csv(gp, low_memory=False))
            vres = gate_value_packet(cik=args.cik, target_quarter=args.target_quarter,
                                     baseline_df=base_df, trial_df=trial_df,
                                     correction=correction, grounding_df=grounding_df)
            out["value_gate"] = {k: vres[k] for k in ("verdict", "checks", "reasons")}
            out["verdict"] = "PASS" if (res.verdict == "PASS"
                                        and vres["verdict"] == "PASS") else "FAIL"
            if is_diagnosis_refusal(vres):
                reasons = vres.get("reasons") or []
                n = append_readjudication([{
                    "cik": args.cik,
                    "fix_class": correction.get("fix_class", ""),
                    "source_review_ids": ";".join(correction.get("source_review_ids") or []),
                    "batch_id": args.batch_id,
                    "gated_utc": datetime.now(timezone.utc).isoformat(),
                    "reason": str(reasons[0]) if reasons else "magnitude_plausible false",
                }], path=args.readju_worklist)
                if n:
                    print(f"[gate] appended re-adjudication worklist row for "
                          f"{args.cik}/{correction.get('fix_class', '')}", file=sys.stderr)
        print(json.dumps(out, indent=2))
        return 0 if out["verdict"] == "PASS" else 1
    if args.mode == "diagnose":
        packet = {"cik": args.cik, "quarters": [args.target_quarter], "needs_diagnosis": True,
                  "fix_class": "subtotal_filter", "fix_class_derived": True, "mechanism": "subtotal_leak"}
        dx_res = diagnose_packet(packet, holdings_path=args.holdings, conservation_path=args.conservation,
                                 raw_path=args.raw_holdings, target_quarter=args.target_quarter)
        resolved = annotate_with_diagnosis(packet, dx_res)
        print(json.dumps({"selector": select_mechanism(dx_res),
                          "resolved_packet": {k: resolved.get(k) for k in
                                              ("cik", "fix_class", "stage", "fix_class_derived", "diagnosis")}},
                         indent=2, default=str))
        return 0 if not resolved.get("diagnosis", {}).get("action") == "escalate" else 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
