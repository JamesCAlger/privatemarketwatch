"""Findings ledger: one lifecycle state per finding, and the loop-until-dry decision.

Generalizes ``check_tier_coverage`` (which proves one frozen slice went through Agent
B) to the FULL finding lifecycle across the review queue, both verdict stores, the
staged/promoted/archived correction stores, and the wrapper provenance store. Every
finding (union of current review queue + adjudicated verdicts) gets exactly one state:

  Terminal (no further agent work):
    adjudicated_false_alarm   false_alarm / NO_PATCH_NEEDED
    remediated_promoted       real_error with a promoted correction referencing it
    resolved_upstream         real_error adjudicated, finding no longer in the queue
  Terminal for agents (human basket):
    needs_human               ambiguous / anchor_bad / ESCALATE / PATCH_PROPOSED
                              with no promotable route
  Actionable (the dispatch pool for the next round):
    open                      in queue, no valid adjudication yet          -> B1
    real_error_unremediated   adjudicated real, no correction staged       -> B2
    remediation_pulled        correction was promoted then pulled/archived -> B2 re-author
    remediation_staged        staged leaf awaiting its gate                -> B3 gate
    evidence_backlog          INSUFFICIENT_EVIDENCE / source_unavailable   -> cache fix

The DRY decision: a quarter-pass round is dry when the actionable pool
(open + real_error_unremediated + remediation_pulled + remediation_staged) is empty --
that is ``run_quarter_pass``'s loop-until-dry terminal condition. ``--compare`` diffs
two ledgers to show what a round actually moved.

Cache-only, read-only on production; writes only the requested outputs. ASCII-only.

Usage:
  python scripts/findings_ledger.py --out data/output/agent_b2/findings_ledger.csv
  python scripts/findings_ledger.py --out ... --compare <prior_ledger.csv>
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.check_tier_coverage import VERDICT_DIRS, load_verdict  # noqa: E402

DEFAULT_QUEUE = ROOT / "data" / "output" / "review_queue" / "review_queue.csv"
DEFAULT_STAGED = ROOT / "data" / "output" / "agent_b2" / "corrections"
DEFAULT_PROMOTED = ROOT / "data" / "overrides" / "agent_b2_corrections"
DEFAULT_ARCHIVE = ROOT / "data" / "output" / "agent_b2" / "corrections_archive"
DEFAULT_WRAPPERS = ROOT / "data" / "overrides" / "bdc_xbrl_wrappers"
DEFAULT_OUT = ROOT / "data" / "output" / "agent_b2" / "findings_ledger.csv"

FALSE_ALARM_VERDICTS = {"false_alarm", "NO_PATCH_NEEDED"}
REAL_ERROR_VERDICTS = {"real_error"}
HUMAN_VERDICTS = {"ambiguous", "anchor_bad", "ESCALATE", "PATCH_PROPOSED"}
EVIDENCE_VERDICTS = {"INSUFFICIENT_EVIDENCE"}

ACTIONABLE_STATES = ("open", "real_error_unremediated", "remediation_pulled",
                     "remediation_staged")

# Closure-mode states deliberately distinguish a finding that has disappeared from a
# live queue from one whose disappearance was checked by the post-remediation
# battery.  The historic ledger did not retain a frozen population, so it could not
# make that distinction.
CLOSURE_ACTIONABLE_STATES = (
    "open", "real_error_unremediated", "remediation_pulled", "remediation_staged",
    "b1_route_missing", "b1_re_adjudication_required", "b2_execution_unproven",
    "b3_pass_pending_promotion", "promoted_pending_verification", "unverified_absence",
)


def _leaf_review_ids(root: Path) -> set[str]:
    """source_review_ids referenced by any correction leaf under ``root`` (recursive)."""
    ids: set[str] = set()
    if not root.exists():
        return ids
    for p in root.rglob("*.json"):
        try:
            leaf = json.loads(p.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(leaf, dict):
            ids.update(str(r) for r in (leaf.get("source_review_ids") or []) if r)
    return ids


def _wrapper_provenance_ids(wrapper_dir: Path) -> set[str]:
    """source_review_ids recorded in promoted wrapper patches (b2_provenance)."""
    ids: set[str] = set()
    if not wrapper_dir.exists():
        return ids
    for p in wrapper_dir.glob("*.json"):
        try:
            w = json.loads(p.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        for prov in (w.get("b2_provenance") or []) if isinstance(w, dict) else []:
            ids.update(str(r) for r in (prov.get("source_review_ids") or []) if r)
    return ids


def classify_finding(
    rid: str, *, in_queue: bool, verdict_status: str,
    staged_ids: set[str], promoted_ids: set[str], pulled_ids: set[str],
    seeded: bool = False, has_fix_route: bool = True, closure_mode: bool = False,
) -> str:
    """Pure state assignment for one finding. ``verdict_status`` is
    check_tier_coverage.load_verdict's status ('MISSING' when no verdict file)."""
    if verdict_status.startswith("verdict_"):
        verdict = verdict_status[len("verdict_"):]
        if verdict in FALSE_ALARM_VERDICTS:
            return "adjudicated_false_alarm"
        if verdict in EVIDENCE_VERDICTS:
            return "evidence_backlog"
        if verdict in REAL_ERROR_VERDICTS:
            if rid in promoted_ids:
                # A B3 pass/promotion is not proof that the next deterministic
                # queue no longer contains this finding.  Closure mode preserves
                # that necessary post-rebuild verification step.
                return "promoted_pending_verification" if closure_mode else "remediated_promoted"
            if rid in staged_ids:
                return "remediation_staged"
            if rid in pulled_ids:
                return "remediation_pulled"
            if not in_queue:
                return "unverified_absence" if closure_mode and seeded else "resolved_upstream"
            if closure_mode and not has_fix_route:
                return "b1_route_missing"
            return "real_error_unremediated"
        if verdict in HUMAN_VERDICTS:
            return "needs_human"
        return "needs_human"  # unknown-but-valid vocabulary: fail toward a human
    if verdict_status == "no_source_not_covered":
        return "evidence_backlog"
    # MISSING / invalid_verdict / placeholder_autodrafted -> not adjudicated
    if in_queue:
        return "open"
    return "unverified_absence" if closure_mode and seeded else "gone_unadjudicated"


def _read_csv_rows(path: Path) -> list[dict]:
    if not Path(path).exists():
        return []
    with open(path, newline="", encoding="utf-8-sig") as f:
        return [dict(row) for row in csv.DictReader(f)]


def _manifest_ciks(path: Path | None) -> set[str] | None:
    if path is None:
        return None
    raw = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    entries = raw.get("entries", raw) if isinstance(raw, dict) else raw
    return {str(e.get("cik") or "").zfill(10) for e in entries if e.get("cik")}


def _in_scope(row: dict, *, quarter: str | None, cohort: set[str] | None) -> bool:
    if quarter and str(row.get("report_date") or "") != quarter:
        return False
    if cohort is not None and str(row.get("cik") or "").zfill(10) not in cohort:
        return False
    return True


def _has_fix_route(verdict_path: Path | None) -> bool:
    """A real-error verdict must name a concrete fix class in closure mode."""
    if verdict_path is None:
        return False
    try:
        raw = json.loads(verdict_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return False
    if any(str(f.get("fix_class") or "").strip() for f in raw.get("findings") or []):
        return True
    # Some early verdicts expressed the route only at packet level.  A mechanism is
    # deliberately insufficient: it can be a symptom, not an executable fix route.
    return bool(str(raw.get("fix_class") or "").strip())


def build_ledger(
    *, queue_path: Path = DEFAULT_QUEUE, staged_dir: Path = DEFAULT_STAGED,
    promoted_dir: Path = DEFAULT_PROMOTED, archive_dir: Path = DEFAULT_ARCHIVE,
    wrapper_dir: Path = DEFAULT_WRAPPERS, verdict_dirs=VERDICT_DIRS,
    seed_paths: Iterable[Path] = (), quarter: str | None = None,
    manifest_path: Path | None = None, closure_mode: bool = False,
) -> list[dict]:
    """Build the lifecycle ledger.

    ``seed_paths`` freezes a population for a closure round.  Seeded records are
    retained even when absent from the current queue, and closure mode fails closed
    on that absence.  ``quarter`` + ``manifest_path`` make the requested scope a
    first-class operation rather than a report-side filter.
    """
    cohort = _manifest_ciks(manifest_path)
    queue_rows: dict[str, dict] = {}
    for r in _read_csv_rows(Path(queue_path)):
        rid = (r.get("review_id") or "").strip()
        if rid and _in_scope(r, quarter=quarter, cohort=cohort):
            queue_rows[rid] = r

    seed_rows: dict[str, dict] = {}
    for p in seed_paths:
        for r in _read_csv_rows(Path(p)):
            rid = (r.get("review_id") or "").strip()
            if rid and _in_scope(r, quarter=quarter, cohort=cohort):
                seed_rows.setdefault(rid, r)

    verdict_paths: dict[str, Path] = {}
    for vdir in verdict_dirs:
        if Path(vdir).exists():
            for p in Path(vdir).glob("*.json"):
                verdict_paths.setdefault(p.stem, p)

    staged_ids = _leaf_review_ids(Path(staged_dir))
    promoted_ids = _leaf_review_ids(Path(promoted_dir)) | _wrapper_provenance_ids(Path(wrapper_dir))
    pulled_ids = _leaf_review_ids(Path(archive_dir)) - promoted_ids - staged_ids

    ledger = []
    universe = set(queue_rows) | set(seed_rows)
    # In scoped closure mode, do not accidentally pull every historic verdict into
    # a quarter-only artifact.  Existing unscoped behavior remains unchanged.
    if quarter is None and cohort is None:
        universe |= set(verdict_paths)
    for rid in sorted(universe):
        vstatus, vdetail = ("MISSING", "")
        if rid in verdict_paths:
            vstatus, vdetail = load_verdict(verdict_paths[rid])
        state = classify_finding(
            rid, in_queue=rid in queue_rows, verdict_status=vstatus,
            staged_ids=staged_ids, promoted_ids=promoted_ids, pulled_ids=pulled_ids,
            seeded=rid in seed_rows, has_fix_route=_has_fix_route(verdict_paths.get(rid)),
            closure_mode=closure_mode)
        q = queue_rows.get(rid, seed_rows.get(rid, {}))
        ledger.append({
            "review_id": rid, "state": state, "in_queue": rid in queue_rows,
            "population_origin": ("frozen_and_live" if rid in queue_rows and rid in seed_rows
                                  else "live" if rid in queue_rows else "frozen"),
            "verdict_status": vstatus, "verdict_detail": vdetail,
            "has_fix_route": _has_fix_route(verdict_paths.get(rid)),
            "cik": q.get("cik", ""), "rule_name": q.get("rule_name", ""),
            "report_date": q.get("report_date", ""), "lane": q.get("lane", ""),
            "engine": q.get("engine", ""), "fv_at_risk_m": q.get("fv_at_risk_m", ""),
            # fv_at_risk_m is engine-sparse (only aggregate_header / derivative_role /
            # source_recon populate it in the queue); fund_quarter_fv_m is the queue's
            # exposure weight carried for ALL rows -- use it for FV-by-lifecycle-state
            # accounting.
            "fund_quarter_fv_m": q.get("fund_quarter_fv_m", ""),
        })
    return ledger


def summarize(ledger: list[dict], *, closure_mode: bool = False) -> dict:
    """State counts + the dry decision. ``open`` findings count as actionable only in
    the blocker lane -- the review lane is a triage pool, not the fleet-dispatch pool
    (27.5K review-lane opens would otherwise make the loop unconvergeable by
    construction). The post-adjudication states are lane-independent."""
    counts: dict[str, int] = {}
    open_by_lane: dict[str, int] = {}
    for row in ledger:
        counts[row["state"]] = counts.get(row["state"], 0) + 1
        if row["state"] == "open":
            lane = str(row.get("lane") or "(none)")
            open_by_lane[lane] = open_by_lane.get(lane, 0) + 1
    active_states = CLOSURE_ACTIONABLE_STATES if closure_mode else ACTIONABLE_STATES
    if closure_mode:
        # A frozen closure population is deliberately stronger than the normal
        # fleet loop: every unadjudicated finding must be accounted for, including
        # review-lane records.
        actionable = sum(counts.get(s, 0) for s in active_states)
    else:
        actionable = (open_by_lane.get("blocker", 0)
                      + sum(counts.get(s, 0) for s in active_states if s != "open"))
    return {"n_findings": len(ledger), "states": dict(sorted(counts.items())),
            "open_by_lane": dict(sorted(open_by_lane.items())),
            "n_actionable": actionable, "dry": actionable == 0,
            "actionable_states": [s if s != "open" else "open(blocker lane)"
                                  for s in active_states]}


def compare(prior: list[dict], current: list[dict]) -> dict:
    """Round-over-round transitions: what the last round actually moved."""
    prev = {r["review_id"]: r["state"] for r in prior}
    transitions: dict[str, int] = {}
    for r in current:
        old = prev.get(r["review_id"], "(new)")
        if old != r["state"]:
            key = f"{old} -> {r['state']}"
            transitions[key] = transitions.get(key, 0) + 1
    gone = sum(1 for rid in prev if rid not in {r["review_id"] for r in current})
    return {"n_transitions": sum(transitions.values()), "transitions": dict(sorted(transitions.items())),
            "n_dropped_findings": gone, "changed": bool(transitions) or bool(gone)}


def write_ledger(ledger: list[dict], out: Path, *,
                 compare_path: Path | None = None, closure_mode: bool = False) -> dict:
    """Write ledger CSV + summary JSON sidecar; returns the summary (with
    ``round_delta`` when a prior ledger is given)."""
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(ledger[0].keys()) if ledger else
                           ["review_id", "state"])
        w.writeheader()
        w.writerows(ledger)
    summary = summarize(ledger, closure_mode=closure_mode)
    if compare_path and Path(compare_path).exists():
        with open(compare_path, newline="", encoding="utf-8-sig") as f:
            prior = list(csv.DictReader(f))
        summary["round_delta"] = compare(prior, ledger)
    out.with_suffix(".summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build the findings lifecycle ledger.")
    ap.add_argument("--queue", type=Path, default=DEFAULT_QUEUE)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--compare", type=Path, default=None,
                    help="prior ledger CSV; prints round-over-round transitions")
    ap.add_argument("--seed", type=Path, action="append", default=[],
                    help="frozen population CSV retained even if absent from live queue")
    ap.add_argument("--quarter", default=None, help="restrict to report_date")
    ap.add_argument("--manifest", type=Path, default=None,
                    help="restrict to manifest CIKs")
    ap.add_argument("--closure-mode", action="store_true",
                    help="fail closed on frozen absence and missing B1 fix routes")
    args = ap.parse_args(argv)

    ledger = build_ledger(queue_path=args.queue, seed_paths=args.seed,
                          quarter=args.quarter, manifest_path=args.manifest,
                          closure_mode=args.closure_mode)
    summary = write_ledger(ledger, args.out, compare_path=args.compare,
                           closure_mode=args.closure_mode)
    print(json.dumps(summary, indent=2))
    print(f"ledger: {args.out}")
    # exit 0 dry, 1 not-dry (loop drivers key off this; both are valid outcomes)
    return 0 if summary["dry"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
