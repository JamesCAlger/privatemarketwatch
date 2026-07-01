"""Agent B2 remediation driver: discover -> (apply -> retriage -> gate) -> promote.

The deterministic orchestration for B2/B3. The PURE, unit-tested core lives here:
 - ``group_real_errors`` -- group real_error verdicts into (cik, fix_class) packets,
   stage-ordered, joined to their bundle metadata (cik/report_date/rule).
 - ``build_conservation_snapshots`` -- re-triage Tier-0 conservation deterministically from a
   holdings frame + the independent anchor (recompute value_sum vs stored anchor_value).
 - ``gate_conservation_packet`` -- build baseline+trial snapshots and run the B3 held-out gate.
 - ``promote_passes`` -- copy only PASS staged corrections to the production overrides.

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
from pathlib import Path

import pandas as pd

from pipeline import config
from pipeline.agent_b2_diagnose import diagnose, select_mechanism, _load_raw_cik
from pipeline.agent_b2_wrapper_patch import apply_subtotal_filter
from pipeline.agent_b_held_out import gate_correction
from pipeline.correction_leaf import stage_for

DEFAULT_BASE = config.OUTPUT_DIR / "agent_b2"
DEFAULT_VERDICTS = config.OUTPUT_DIR / "review_queue" / "verdicts"
DEFAULT_CORRECTIONS = DEFAULT_BASE / "corrections"
DEFAULT_OVERRIDES = config.PROJECT_ROOT / "data" / "overrides" / "agent_b2_corrections"
DEFAULT_CONSERVATION = config.OUTPUT_DIR / "shadow" / "conservation_gate_results.csv"
TRIAL_REBUILD = config.PROJECT_ROOT / "scripts" / "rebuild_unified_cik_trial.py"

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

WRAPPER_PATCH_FIX_CLASSES = {"subtotal_filter", "classification_fix", "column_remap"}
POST_STAGING_FIX_CLASSES = {"dedup", "comparative_period_filter", "spv_lookthrough",
                            "rate_rescale", "unit_rescale", "all_pik_normalization",
                            "missing_position_add"}
RULE_TRACK_FIX_CLASSES = {"rule_scope", "anchor_fix"}
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


def promote_passes(gate_results: list[dict], *, corrections_dir: Path, overrides_dir: Path) -> list[dict]:
    """Copy only PASS staged corrections to the production overrides (mirrors Agent A's
    promote: staged -> data/overrides/...). Returns the promoted records."""
    corrections_dir, overrides_dir = Path(corrections_dir), Path(overrides_dir)
    promoted: list[dict] = []
    for g in gate_results:
        if g.get("verdict") != "PASS":
            continue
        cik, mech = str(g.get("cik")), str(g.get("mechanism"))
        src = corrections_dir / cik / f"{mech}.json"
        if not src.exists():
            continue
        dst = overrides_dir / cik / f"{mech}.json"
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        promoted.append({"cik": cik, "mechanism": mech, "src": str(src), "dst": str(dst)})
    return promoted


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
    """Load staged correction leaves for one CIK (corrections/<cik>/<mechanism>.json)."""
    d = Path(corrections_dir) / str(cik)
    out: list[dict] = []
    if not d.exists():
        return out
    for p in sorted(d.glob("*.json")):
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
        print(json.dumps({"cik": res.cik, "target_quarter": res.target_quarter,
                          "verdict": res.verdict, "checks": res.checks, "reasons": res.reasons}, indent=2))
        return 0 if res.verdict == "PASS" else 1
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
