"""Cross-batch B2 correction-fleet metrics rollup.

Derives, from on-disk artifacts only (no network, no writes outside the
single output CSV), a per-batch metrics table for B2 correction fleets:

  - dispatch accounting: manifest rows (NOTE: manifest.json is overwritten by
    each dispatch wave into the same batch dir, so it only reflects the LAST
    wave; prompts/wrappers/logs counts give the true cumulative dispatch),
    skipped_* entries with reasons, dispatch failures.
  - authoring validity: worker stdout completion + validate.txt verdicts
    (OK / FAIL / MISSING). validate.txt reflects the validator AS OF dispatch
    time; round-1 q4b2exp validators accepted leaves later found schema-unusable,
    so archive-based counts are also emitted.
  - gate outcomes: every apply_gate*.jsonl in the batch dir, per-check
    pass/fail counts and categorized refusal reasons. Two gate schemas exist:
    the leaf/replay gate (replay_ok, replay_equivalence, off_scope_invariance,
    defect_signature, field_sanity, grounding_verified, conservation) and the
    value-packet gate (target_cleared, no_new_flags, fv_at_risk_non_increasing,
    residual_improved, no_over_deletion, bands_hold, held_out_coverage).
  - lifecycle: current staged corrections, live promoted store, and
    corrections_archive dirs (failure-class counts).
  - findings ledger reconciliation for a target report_date, including
    in-cohort split against a wrapper-cohort manifest.
  - production fix-application audit summary (status counts, drift).

Usage:
  python scripts/b2_run_metrics.py
  python scripts/b2_run_metrics.py --batches q4b2t4a q4b2t4b q4b2exp q4b2exp2 \
      --report-date 2025-12-31 --out data/output/agent_b2/b2_run_metrics.csv

Output: long-format CSV with columns
  section, batch_id, metric, value, detail
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_BATCHES = ["q4b2t4a", "q4b2t4b", "q4b2exp", "q4b2exp2"]
DEFAULT_BATCH_ROOT = REPO_ROOT / "data" / "output" / "agent_b2" / "batch"
DEFAULT_ARCHIVE_ROOT = REPO_ROOT / "data" / "output" / "agent_b2" / "corrections_archive"
DEFAULT_STAGED_DIR = REPO_ROOT / "data" / "output" / "agent_b2" / "corrections"
DEFAULT_LIVE_DIR = REPO_ROOT / "data" / "overrides" / "agent_b2_corrections"
DEFAULT_LEDGER = REPO_ROOT / "data" / "output" / "agent_b2" / "findings_ledger.csv"
DEFAULT_COHORT = (
    REPO_ROOT
    / "data"
    / "overrides"
    / "wrapper_cohorts"
    / "v2_70_gate_verified_wrapper_manifest.json"
)
DEFAULT_AUDIT = REPO_ROOT / "data" / "output" / "agent_fix_application_audit.csv"
DEFAULT_OUT = REPO_ROOT / "data" / "output" / "agent_b2" / "b2_run_metrics.csv"

# Reason string -> failure category. First match wins; order matters.
REASON_CATEGORIES = [
    ("row_selector matched no rows", "selector_noop"),
    ("row_selector has no matchable keys", "selector_unusable"),
    ("bad from/to fields", "bad_field_names"),
    ("missing period/report_date columns", "missing_scope_columns"),
    ("no-op on baseline", "noop_stale"),
    ("no-op on trial base", "selector_noop_stale"),
    ("introduced new flag", "new_flags_introduced"),
    ("BELOW anchor", "over_deletion"),
    ("absent from trial snapshots", "missing_trial_snapshot"),
    ("applier replay error", "applier_error_other"),
    ("applier errors", "applier_error_other"),
    ("trial != composed", "replay_equivalence_mismatch"),
    ("rate signature", "defect_signature_refusal"),
    ("magnitude", "magnitude_refusal"),
    ("target flag(s) still present", "target_not_cleared"),
    ("residual did not improve", "residual_not_improved"),
    ("off-scope", "off_scope_violation"),
    ("conservation", "conservation_refusal"),
]


def read_text_any(path: Path) -> str:
    """Read a small text file whose encoding varies by producer.

    Worker validate.txt files are UTF-16 LE with BOM (PowerShell 5.1 Out-File
    default); JSON/JSONL artifacts are UTF-8 with or without BOM.
    """
    raw = path.read_bytes()
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16", errors="replace")
    return raw.decode("utf-8-sig", errors="replace")


def categorize_reason(reason: str) -> str:
    for needle, cat in REASON_CATEGORIES:
        if needle in reason:
            return cat
    return "other"


def rows_for_batch(batch_dir: Path, batch_id: str):
    rows = []

    def add(metric, value, detail=""):
        rows.append(
            {
                "section": "batch",
                "batch_id": batch_id,
                "metric": metric,
                "value": value,
                "detail": detail,
            }
        )

    # Wave-stamped manifests (manifest.NNN.json, dispatch_preflight 2026-08-21) are the
    # durable per-wave records; plain manifest.json is a latest-wave pointer duplicating
    # the last wave. Legacy batches (all Q4) have only the plain file.
    wave_files = sorted(batch_dir.glob("manifest.[0-9][0-9][0-9].json"))
    manifest_files = wave_files or (
        [batch_dir / "manifest.json"] if (batch_dir / "manifest.json").exists() else []
    )
    if manifest_files:
        skipped_totals: dict[str, int] = {}
        skipped_reasons: dict[str, set] = {}
        total_rows = 0
        last = None
        for mf in manifest_files:
            manifest = json.loads(mf.read_text(encoding="utf-8-sig"))
            last = manifest
            total_rows += len(manifest.get("rows", []))
            if wave_files:
                add(
                    "manifest_wave_rows",
                    len(manifest.get("rows", [])),
                    f"wave {manifest.get('wave', mf.name)}",
                )
            for key, entries in sorted(manifest.items()):
                if not key.startswith("skipped_"):
                    continue
                skipped_totals[key] = skipped_totals.get(key, 0) + len(entries)
                skipped_reasons.setdefault(key, set()).update(
                    str(e.get("reason", ""))[:120]
                    for e in entries
                    if isinstance(e, dict)
                )
        add("manifest_created_at", last.get("created_at", ""))
        add("manifest_total_waves", len(manifest_files),
            "wave-stamped" if wave_files else "legacy single manifest (last wave only)")
        add("manifest_total_rows", total_rows,
            "" if wave_files else "manifest was overwritten per dispatch wave; last wave only")
        add("manifest_last_wave_rows", len(last.get("rows", [])))
        add("manifest_n_dispatch_last_wave", last.get("n_dispatch", ""))
        for key in sorted(skipped_totals):
            add(key, skipped_totals[key], "; ".join(sorted(skipped_reasons[key])))
    else:
        add("manifest_missing", 1)

    prompts = sorted((batch_dir / "prompts").glob("*.md")) if (batch_dir / "prompts").exists() else []
    wrappers = sorted((batch_dir / "wrappers").glob("*.ps1")) if (batch_dir / "wrappers").exists() else []
    add("prompts_generated", len(prompts))
    add("packets_dispatched", len(wrappers), "wrapper scripts = workers actually launched")
    undispatched = sorted(
        {p.stem for p in prompts} - {w.stem for w in wrappers}
    )
    if undispatched:
        add("prompts_not_dispatched", len(undispatched), "; ".join(undispatched))

    logs_dir = batch_dir / "logs"
    stdout_files = sorted(logs_dir.glob("*.stdout.jsonl")) if logs_dir.exists() else []
    add("worker_stdout_logs", len(stdout_files))
    completed = 0
    for f in stdout_files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if '"turn.completed"' in text:
            completed += 1
    add("workers_turn_completed", completed, "stdout contains turn.completed")

    validate_files = sorted(logs_dir.glob("*.validate.txt")) if logs_dir.exists() else []
    v_ok = v_missing = v_fail = 0
    fail_names = []
    for f in validate_files:
        text = read_text_any(f).strip()
        if text.startswith("OK"):
            v_ok += 1
        elif "MISSING correction file" in text:
            v_missing += 1
            fail_names.append(f.name.replace(".validate.txt", "") + ":missing")
        else:
            v_fail += 1
            fail_names.append(f.name.replace(".validate.txt", "") + ":invalid")
    add("validate_ok", v_ok, "validator verdict as of dispatch time")
    add("validate_missing_output", v_missing)
    add("validate_invalid", v_fail, "; ".join(fail_names[:20]))
    if validate_files:
        add(
            "authoring_validity_pct",
            round(100.0 * v_ok / len(validate_files), 1),
            "validate_ok / validate files; dispatch-time validator only",
        )

    df_path = batch_dir / "dispatch_failures.txt"
    if df_path.exists():
        lines = [
            ln.strip()
            for ln in df_path.read_text(encoding="utf-8", errors="replace").splitlines()
            if ln.strip()
        ]
        add("dispatch_failures", len(lines), "; ".join(ln.split(";")[0] for ln in lines)[:200])

    for gate_path in sorted(batch_dir.glob("apply_gate*.jsonl")):
        gate_name = gate_path.stem.replace("_log", "")
        entries = []
        for ln in gate_path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
            ln = ln.strip().lstrip("\ufeff")
            if not ln:
                continue
            try:
                entries.append(json.loads(ln))
            except json.JSONDecodeError:
                add(f"{gate_name}_unparseable_line", 1, ln[:120])
        verdicts = Counter(e.get("verdict", "?") for e in entries)
        add(f"{gate_name}_entries", len(entries), "one entry per CIK packet")
        add(f"{gate_name}_pass", verdicts.get("PASS", 0))
        add(f"{gate_name}_fail", verdicts.get("FAIL", 0))
        n_leaves = sum(int(e.get("n_leaves", 1) or 1) for e in entries)
        add(f"{gate_name}_leaves", n_leaves, "sum of n_leaves (1 if absent)")
        check_fail = Counter()
        check_seen = Counter()
        reason_cats = Counter()
        for e in entries:
            for check, ok in (e.get("checks") or {}).items():
                check_seen[check] += 1
                if not ok:
                    check_fail[check] += 1
            for reason in e.get("reasons") or []:
                if e.get("verdict") == "FAIL":
                    reason_cats[categorize_reason(str(reason))] += 1
        for check in sorted(check_seen):
            add(
                f"{gate_name}_check_fail__{check}",
                check_fail.get(check, 0),
                f"of {check_seen[check]} evaluated",
            )
        for cat, n in reason_cats.most_common():
            add(f"{gate_name}_refusal__{cat}", n)

    return rows


def rows_for_archives(archive_root: Path, prefixes):
    rows = []
    if not archive_root.exists():
        return rows
    for d in sorted(archive_root.iterdir()):
        name = d.name
        if prefixes and not any(name.startswith(p) for p in prefixes):
            continue
        if d.is_file():
            rows.append(
                {
                    "section": "archive",
                    "batch_id": "",
                    "metric": name,
                    "value": 1,
                    "detail": "single-file archive",
                }
            )
            continue
        n_json = len(list(d.rglob("*.json")))
        has_readme = (d / "README.md").exists()
        rows.append(
            {
                "section": "archive",
                "batch_id": "",
                "metric": name,
                "value": n_json,
                "detail": "correction json leaves" + ("; README present" if has_readme else ""),
            }
        )
    return rows


def rows_for_stores(staged_dir: Path, live_dir: Path):
    rows = []
    for label, root in (("staged_corrections", staged_dir), ("live_promoted_corrections", live_dir)):
        n = len(list(root.rglob("*.json"))) if root.exists() else 0
        rows.append(
            {
                "section": "store",
                "batch_id": "",
                "metric": label,
                "value": n,
                "detail": str(root.relative_to(REPO_ROOT)),
            }
        )
    return rows


def rows_for_ledger(ledger_path: Path, cohort_path: Path, report_date: str):
    rows = []
    if not ledger_path.exists():
        return rows
    cohort_ciks = set()
    if cohort_path.exists():
        cohort = json.loads(cohort_path.read_text(encoding="utf-8-sig"))
        cohort_ciks = {e["cik"] for e in cohort.get("entries", [])}

    n_total = 0
    states = Counter()
    verdict_status = Counter()
    state_fv = Counter()
    in_cohort_by_state = Counter()
    with ledger_path.open(encoding="utf-8-sig", newline="") as fh:
        for rec in csv.DictReader(fh):
            if rec.get("report_date") != report_date:
                continue
            n_total += 1
            state = rec.get("state", "?")
            states[state] += 1
            verdict_status[rec.get("verdict_status", "?")] += 1
            try:
                state_fv[state] += float(rec.get("fv_at_risk_m") or 0.0)
            except ValueError:
                pass
            if rec.get("cik") in cohort_ciks:
                in_cohort_by_state[state] += 1

    def add(metric, value, detail=""):
        rows.append(
            {
                "section": f"ledger_{report_date}",
                "batch_id": "",
                "metric": metric,
                "value": value,
                "detail": detail,
            }
        )

    add("findings_total", n_total)
    for vs, n in verdict_status.most_common():
        add(f"verdict_status__{vs}", n)
    add(
        "findings_with_b1_verdict",
        sum(
            n
            for vs, n in verdict_status.items()
            if vs not in ("MISSING", "placeholder_autodrafted", "?", "")
        ),
        "verdict_status not MISSING/blank/placeholder_autodrafted",
    )
    for state in sorted(states):
        add(
            f"state__{state}",
            states[state],
            f"fv_at_risk_m_sum={state_fv[state]:.1f}; in_cohort={in_cohort_by_state.get(state, 0)}",
        )
    return rows


def rows_for_audit(audit_path: Path):
    rows = []
    if not audit_path.exists():
        return rows
    status = Counter()
    drift = Counter()
    layer = Counter()
    n = 0
    with audit_path.open(encoding="utf-8-sig", newline="") as fh:
        for rec in csv.DictReader(fh):
            n += 1
            status[rec.get("status", "?")] += 1
            layer[rec.get("layer", "?")] += 1
            d = (rec.get("drift") or "").strip()
            if d:
                drift[d] += 1

    def add(metric, value, detail=""):
        rows.append(
            {
                "section": "fix_application_audit",
                "batch_id": "",
                "metric": metric,
                "value": value,
                "detail": detail,
            }
        )

    add("rules_total", n)
    for s, c in status.most_common():
        add(f"status__{s}", c)
    for l, c in layer.most_common():
        add(f"layer__{l}", c)
    if drift:
        for d, c in drift.most_common():
            add(f"drift__{d}", c)
    else:
        add("drift_flags", 0, "no non-empty drift values")
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--batches", nargs="+", default=DEFAULT_BATCHES)
    ap.add_argument("--batch-root", type=Path, default=DEFAULT_BATCH_ROOT)
    ap.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    ap.add_argument(
        "--archive-prefixes",
        nargs="*",
        default=["q4b2", "promoted_q4b2"],
        help="only archive dirs starting with one of these; empty = all",
    )
    ap.add_argument("--staged-dir", type=Path, default=DEFAULT_STAGED_DIR)
    ap.add_argument("--live-dir", type=Path, default=DEFAULT_LIVE_DIR)
    ap.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    ap.add_argument("--cohort-manifest", type=Path, default=DEFAULT_COHORT)
    ap.add_argument("--report-date", default="2025-12-31")
    ap.add_argument("--audit", type=Path, default=DEFAULT_AUDIT)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args(argv)

    all_rows = []
    for batch_id in args.batches:
        batch_dir = args.batch_root / batch_id
        if not batch_dir.exists():
            print(f"[b2_run_metrics] WARNING batch dir missing: {batch_dir}")
            continue
        print(f"[b2_run_metrics] batch {batch_id}")
        all_rows.extend(rows_for_batch(batch_dir, batch_id))

    print("[b2_run_metrics] archives")
    all_rows.extend(rows_for_archives(args.archive_root, args.archive_prefixes))
    print("[b2_run_metrics] stores")
    all_rows.extend(rows_for_stores(args.staged_dir, args.live_dir))
    print(f"[b2_run_metrics] ledger {args.report_date}")
    all_rows.extend(rows_for_ledger(args.ledger, args.cohort_manifest, args.report_date))
    print("[b2_run_metrics] fix application audit")
    all_rows.extend(rows_for_audit(args.audit))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=["section", "batch_id", "metric", "value", "detail"]
        )
        writer.writeheader()
        writer.writerows(all_rows)
    print(f"[b2_run_metrics] wrote {len(all_rows)} rows -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
