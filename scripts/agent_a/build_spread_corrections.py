"""Generate the audited basis_spread correction override from the P3 staged conflicts.

Selects ONLY the conflicts where the spread+SOFR=all-in reconciliation decisively favors
Agent A (verdict 'agentA') AND the values are plausible (A spread 2-12%, all-in 6-20% --
excludes A-parsed-the-floor artifacts). Emits a reversible, evidence-bearing override:
data/overrides/identifier_spread_corrections.json. Read-only on production.
"""
import csv
import json

from pipeline import config

SRC = config.OUTPUT_DIR / "agent_a" / "p3_staged_conflicts.csv"
OUT = config.DATA_DIR / "overrides" / "identifier_spread_corrections.json"


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def main():
    seen = set()
    records = []
    with open(SRC, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["field"] != "basis_spread" or r.get("reconcile_verdict") != "agentA":
                continue
            a = _f(r["agentA_value"])
            cash = _f(r.get("cash_all_in_pct"))
            if a is None or cash is None or not (2.0 <= a <= 12.0) or not (6.0 <= cash <= 20.0):
                continue  # exclude floor-mis-parse / anomalous-all-in artifacts
            key = (r["cik"], r["report_date"], r["identifier"])
            if key in seen:
                continue
            seen.add(key)
            records.append({
                "cik": r["cik"],
                "report_date": r["report_date"],
                "identifier": r["identifier"],
                "field": "basis_spread",
                "new_value_decimal": round(a / 100.0, 6),     # bdc_holdings stores decimal
                "old_value_xbrl": _f(r["production_value"]),
                "agentA_value_pct": a,
                "mechanism": "agentA_spread_reconciled",
                "evidence": {
                    "sofr_90day_pct": _f(r.get("sofr_pct")),
                    "cash_all_in_pct": cash,
                    "a_residual": _f(r.get("a_residual")),
                    "xbrl_residual": _f(r.get("xbrl_residual")),
                },
                "confidence": "high" if (_f(r.get("xbrl_residual")) or 0) - (_f(r.get("a_residual")) or 0) >= 0.30 else "medium",
            })

    payload = {
        "schema_version": "identifier-spread-corrections.v1",
        "doc": ("Per-position basis_spread overrides where the freeform identifier spread "
                "reconciles with all-in+SOFR and the XBRL tag does not. Reversible: "
                "old_value_xbrl recorded. SOFR90 is a ~3M Term-SOFR proxy."),
        "match_key": ["cik", "report_date", "identifier"],
        "corrections": records,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    hi = sum(1 for c in records if c["confidence"] == "high")
    print(f"Wrote {len(records)} spread corrections ({hi} high / {len(records)-hi} medium) -> {OUT}")


if __name__ == "__main__":
    main()
