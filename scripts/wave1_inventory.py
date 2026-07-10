"""Wave-1 promotion inventory (gap 1, spec section 8.1 operational step).

Enumerates every un-promoted gate-PASS agent fix waiting for the first override wave:

- staged investigator rules under data/output/agent_investigate/<cik>/rules/, joined to
  the CIK's manifest target_quarter and its LATEST B3 gate verdict from
  data/output/agent_investigate/batch/*/b3_gate.<cik>.<quarter>.json;
- staged B2 correction leaves under data/output/agent_b2/corrections/<cik>/;
- already-promoted anchor overrides under data/overrides/agent_anchor/ (Layer D
  consumes these directly -- listed for completeness of the wave's rebuild scope).

Writes data/output/agent_investigate/wave1_inventory.csv (one row per CIK) and prints a
summary. PASS rows are the first wave's size and the coverage of the per-CIK
trial-vs-production parity check that must precede the wave commit. Read-only over the
stores; cache-only; no network. ASCII-only.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline import config
from pipeline.agent_promoted import normalize_cik10

INVESTIGATE_BASE = config.OUTPUT_DIR / "agent_investigate"
B2_CORRECTIONS = config.OUTPUT_DIR / "agent_b2" / "corrections"
OUT_FILE = INVESTIGATE_BASE / "wave1_inventory.csv"

COLUMNS = ["cik", "target_quarter", "gate_verdict", "gate_batch", "gate_mtime",
           "n_rules", "rule_types", "rule_fv_impact_total", "n_escalations",
           "escalation_categories", "n_b2_correction_leaves", "b2_fix_classes",
           "anchor_override_quarters", "promoted_rules_present", "wave1_action"]


def _read_json(path: Path):
    try:
        # utf-8-sig: sandbox workers sometimes write JSON with a UTF-8 BOM.
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None


def latest_gates() -> dict[str, dict]:
    """{cik10: {verdict, quarter, batch, mtime}} -- newest b3_gate json per CIK."""
    out: dict[str, dict] = {}
    batch_dir = INVESTIGATE_BASE / "batch"
    for p in sorted(batch_dir.glob("*/b3_gate.*.json")) if batch_dir.exists() else []:
        leaf = _read_json(p)
        if not leaf:
            continue
        cik = normalize_cik10(leaf.get("cik"))
        rec = {"verdict": str(leaf.get("verdict") or ""),
               "quarter": str(leaf.get("target_quarter") or ""),
               "batch": p.parent.name, "mtime": p.stat().st_mtime}
        if cik and (cik not in out or rec["mtime"] > out[cik]["mtime"]):
            out[cik] = rec
    return out


def rule_fv_impact(rule: dict) -> float:
    mi = rule.get("measured_impact")
    if not isinstance(mi, dict):
        return 0.0
    return sum(abs(float(q.get("fv") or 0)) for q in mi.values() if isinstance(q, dict))


def build_inventory() -> list[dict]:
    gates = latest_gates()
    anchor_overrides: dict[str, list[str]] = {}
    if config.AGENT_ANCHOR_OVERRIDES_DIR.exists():
        for p in sorted(config.AGENT_ANCHOR_OVERRIDES_DIR.glob("*/*.json")):
            anchor_overrides.setdefault(normalize_cik10(p.parent.name), []).append(p.stem)
    b2_leaves: dict[str, list[str]] = {}
    if B2_CORRECTIONS.exists():
        for p in sorted(B2_CORRECTIONS.glob("*/*.json")):
            b2_leaves.setdefault(normalize_cik10(p.parent.name), []).append(p.stem)
    promoted_rules = {normalize_cik10(p.name)
                      for p in config.AGENT_INVESTIGATE_RULES_DIR.glob("*")
                      if p.is_dir()} if config.AGENT_INVESTIGATE_RULES_DIR.exists() else set()

    ciks: set[str] = set(gates) | set(anchor_overrides) | set(b2_leaves)
    staged: dict[str, dict] = {}
    for d in sorted(INVESTIGATE_BASE.glob("*")) if INVESTIGATE_BASE.exists() else []:
        if not d.is_dir() or d.name == "batch":
            continue
        rules = [r for r in (_read_json(p) for p in sorted((d / "rules").glob("*.json"))) if r]
        escs = [e for e in (_read_json(p) for p in sorted((d / "escalations").glob("*.json"))) if e]
        if not rules and not escs:
            continue
        cik = normalize_cik10(d.name)
        manifest = _read_json(d / "manifest.json") or {}
        staged[cik] = {"rules": rules, "escalations": escs,
                       "target_quarter": str(manifest.get("target_quarter") or "")}
        ciks.add(cik)

    rows: list[dict] = []
    for cik in sorted(ciks):
        st = staged.get(cik, {})
        g = gates.get(cik, {})
        rules = st.get("rules", [])
        escs = st.get("escalations", [])
        verdict = g.get("verdict", "")
        if rules and verdict == "PASS":
            action = "promote_rules"
        elif rules and verdict == "FAIL":
            action = "hold_gate_fail"
        elif rules:
            action = "hold_no_gate_record"
        else:
            action = "rebuild_scope_only"
        rows.append({
            "cik": cik,
            "target_quarter": st.get("target_quarter") or g.get("quarter", ""),
            "gate_verdict": verdict,
            "gate_batch": g.get("batch", ""),
            "gate_mtime": g.get("mtime", ""),
            "n_rules": len(rules),
            "rule_types": ";".join(sorted({str(r.get("rule_type")) for r in rules})),
            "rule_fv_impact_total": round(sum(rule_fv_impact(r) for r in rules), 2),
            "n_escalations": len(escs),
            "escalation_categories": ";".join(sorted({str(e.get("category") or "other")
                                                      for e in escs})),
            "n_b2_correction_leaves": len(b2_leaves.get(cik, [])),
            "b2_fix_classes": ";".join(b2_leaves.get(cik, [])),
            "anchor_override_quarters": ";".join(anchor_overrides.get(cik, [])),
            "promoted_rules_present": cik in promoted_rules,
            "wave1_action": action,
        })
    return rows


def main() -> int:
    rows = build_inventory()
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_FILE, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)

    by_action: dict[str, list[dict]] = {}
    for r in rows:
        by_action.setdefault(r["wave1_action"], []).append(r)
    print(f"wave-1 inventory: {len(rows)} CIKs -> {OUT_FILE}")
    for action in sorted(by_action):
        grp = by_action[action]
        n_rules = sum(r["n_rules"] for r in grp)
        fv = sum(r["rule_fv_impact_total"] for r in grp)
        print(f"  {action:22s}: {len(grp):3d} CIKs, {n_rules:3d} rules, "
              f"authored FV impact {fv:,.0f}")
    holds = by_action.get("hold_gate_fail", []) + by_action.get("hold_no_gate_record", [])
    if holds:
        print("  held back:")
        for r in holds:
            print(f"    {r['cik']} {r['target_quarter']} verdict={r['gate_verdict'] or 'none'} "
                  f"rules={r['n_rules']} esc={r['escalation_categories'] or '-'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
