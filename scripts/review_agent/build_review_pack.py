"""Build the human gold-review pack for the 45-bundle B trial.

Emits, per bundle, a BLINDED review sheet (the claim + the exact evidence_cli
commands to roam raw source + a per-class checklist) -- the agent's verdict is
deliberately NOT included, so the human labels blind (avoids anchoring; preserves
e_FP/e_FN validity). Also writes a labels template CSV and a protocol guide.

After the human fills gold_labels.csv, diff it against verdicts/ for truth-relative
precision and the agent's e_FP/e_FN.

Usage:
    python scripts/review_agent/build_review_pack.py
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TRIAL = REPO / "data/output/shadow/trial_2026-06-18"
BUNDLES = TRIAL / "sample/review_bundles"
MANIFEST = TRIAL / "sample/sample_manifest.csv"
GOLD = TRIAL / "gold"
SHEETS = GOLD / "sheets"

ASSERTED = {
    "fv_conservation": "Sum of this fund-quarter's position fair values does NOT reconcile to the independent fund-level total investments at fair value.",
    "pik_le_interest_rate": "A position has a PIK rate GREATER than its total interest rate (PIK should be <= interest).",
    "C113": "A position has an interest_rate OUTSIDE the plausible range 0-25%.",
}

CHECKLIST = {
    "fv_conservation": (
        "1. Run `totals`; read the filing's own \"Total investments, at fair value\".\n"
        "2. If it ~= anchor_value -> REAL_ERROR (mechanism: extraction_gap if undershoot; "
        "subtotal_leak / comparative_leak / dimension_double_count if overshoot).\n"
        "3. If it ~= value_sum -> FALSE_ALARM (mechanism: anchor_bad).\n"
        "4. For overshoots, also look for a leaked subtotal or prior-period comparative rows."
    ),
    "pik_le_interest_rate": (
        "1. Roam \"PIK,payment in kind\"; grid the SOI table; read the position's interest vs PIK.\n"
        "2. If the filing shows a split \"X% cash, Y% PIK\" and PIK merely exceeds the CASH leg "
        "(but not the all-in) -> FALSE_ALARM (the pipeline stored only the cash leg).\n"
        "3. If PIK genuinely exceeds the all-in coupon, or a value is mis-parsed -> REAL_ERROR."
    ),
    "C113": (
        "1. Find the position whose stated rate exceeds 25%.\n"
        "2. Structured/CLO subordinated \"effective interest\" yield, or a legit high-yield / "
        "venture / PIK-floor instrument -> FALSE_ALARM (range too tight).\n"
        "3. A non-coupon figure lifted into the rate (e.g. an EOT/balloon payment) or a standard-"
        "debt mis-scale -> REAL_ERROR."
    ),
}

MECHANISMS = {
    "fv_conservation": "extraction_gap | subtotal_leak | comparative_leak | dimension_double_count | anchor_bad | genuine_value_defect | unknown",
    "pik_le_interest_rate": "genuine_value_defect | unit_scale | rate_scale | extraction_gap | false_alarm_cash_leg | unknown",
    "C113": "rate_scale | genuine_value_defect | false_alarm_rule_range | unknown",
}


def _cons(bundle: dict) -> dict | None:
    for ev in bundle.get("evidence_items", []):
        if ev.get("evidence_id") == "source_artifact_rows":
            for r in ev.get("data", []) or []:
                if r.get("value_sum") is not None and r.get("anchor_value") is not None:
                    return {k: r.get(k) for k in
                            ("value_sum", "anchor_value", "residual_pct", "status", "anchor_used")}
    return None


def _sheet(rid: str, m: dict, bundle: dict) -> str:
    rule = m["rule_name"]
    bpath = f"data/output/shadow/trial_2026-06-18/sample/review_bundles/{rid}.json"
    cli = f"python scripts/review_agent/evidence_cli.py --bundle {bpath}"
    cons = _cons(bundle) if rule == "fv_conservation" else None
    lines = [
        f"# Gold review: {rid}",
        "",
        f"- rule: **{rule}**  | cik: {m['cik']}  | report_date: {m['report_date']}  | lane: {m['lane']}",
        "",
        "## Claim (the question -- do NOT assume it is correct)",
        ASSERTED.get(rule, f"Rule {rule} fired."),
    ]
    if cons:
        lines += [
            "",
            f"- value_sum (pipeline)   = {cons['value_sum']}",
            f"- anchor_value           = {cons['anchor_value']}  (anchor: {cons['anchor_used']})",
            f"- residual_pct           = {cons['residual_pct']}  ({cons['status']})",
        ]
    lines += [
        "",
        "## Roam raw source (cache-only; the same tool the agent used)",
        "```",
        f"{cli} claim",
        f"{cli} overview",
        f"{cli} tables",
        f"{cli} grid --table N --start 0 --count 100",
        f"{cli} roam --query \"term1,term2\"",
        f"{cli} totals",
        "```",
        "",
        "## How to decide",
        CHECKLIST.get(rule, ""),
        "",
        "## Record your verdict (label BLIND -- decide before consulting any other source)",
        f"- mechanism options: {MECHANISMS.get(rule, 'unknown')}",
        "- Fill the matching row in `gold_labels.csv`: true_verdict (real_error|false_alarm|ambiguous),",
        "  localized (true|false), true_mechanism, note (cite table/row you used).",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    rows = list(csv.DictReader(open(MANIFEST)))
    SHEETS.mkdir(parents=True, exist_ok=True)
    for m in rows:
        rid = m["review_id"]
        bundle = json.loads((BUNDLES / f"{rid}.json").read_text())
        (SHEETS / f"{rid}.md").write_text(_sheet(rid, m, bundle), encoding="utf-8")

    # labels template (blank verdict columns)
    with open(GOLD / "gold_labels.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["review_id", "rule_name", "cik", "report_date",
                    "true_verdict", "localized", "true_mechanism", "note"])
        for m in rows:
            w.writerow([m["review_id"], m["rule_name"], m["cik"], m["report_date"],
                        "", "", "", ""])

    guide = (
        "# B-trial gold review protocol\n\n"
        "Goal: human truth labels for all 45 bundles -> converts the agent-relative\n"
        "precision into truth-relative, and measures the agent's e_FP / e_FN.\n\n"
        "RULES:\n"
        "1. Label BLIND. Decide each verdict from raw source (via evidence_cli) BEFORE\n"
        "   looking at the agent's verdict (in ../verdicts/). Anchoring deflates the\n"
        "   measured error.\n"
        "2. Verdict vocab: real_error | false_alarm | ambiguous.\n"
        "3. real_error requires a citation (table/row) OR (conservation) an explicit\n"
        "   anchor-disagreement (which filing total the data matches). Put it in `note`.\n"
        "4. ambiguous is valid when raw source can't settle it -- do not force a call.\n\n"
        "STEPS: open sheets/<review_id>.md, run the listed commands, decide, fill the\n"
        "matching row in gold_labels.csv. When done, hand back gold_labels.csv.\n"
    )
    (GOLD / "REVIEW_GUIDE.md").write_text(guide, encoding="utf-8")

    print(f"wrote {len(rows)} sheets to {SHEETS}")
    print(f"wrote {GOLD / 'gold_labels.csv'} (blank template)")
    print(f"wrote {GOLD / 'REVIEW_GUIDE.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
