"""B-trial claim builder: per bundle -> a blinded CLAIM the adjudicator gets.

Reads the sampled bundles and emits claims.json: one record per bundle carrying
ONLY the question (rule, cik, date, and the rule-specific specifics needed to
adjudicate) -- never the pipeline's verdict/confidence/mechanism. The conservation
claim carries value_sum/anchor/residual (the question); pik/C113 carry a seed
issuer list to start roaming. This is the CLAIM half of the evidence package; the
raw-source half is reached at adjudication time via evidence_cli.py.

Usage:
    python scripts/review_agent/build_claims.py
"""

from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SAMPLE = REPO / "data/output/shadow/trial_2026-06-18/sample"
BUNDLES = SAMPLE / "review_bundles"
MANIFEST = SAMPLE / "sample_manifest.csv"
OUT = SAMPLE / "claims.json"


def _bundle(rid: str) -> dict:
    return json.loads((BUNDLES / f"{rid}.json").read_text())


def _seed_issuers(bundle: dict, n: int = 8) -> list[str]:
    for ev in bundle.get("evidence_items", []):
        if ev.get("evidence_id") == "holdings_slice":
            out = []
            for r in ev.get("data", []) or []:
                nm = r.get("issuer_name") or r.get("investment_identifier")
                if nm:
                    out.append(str(nm)[:120])
                if len(out) >= n:
                    break
            return out
    return []


def _cons_fields(bundle: dict) -> dict | None:
    for ev in bundle.get("evidence_items", []):
        if ev.get("evidence_id") == "source_artifact_rows":
            for r in ev.get("data", []) or []:
                if r.get("value_sum") is not None and r.get("anchor_value") is not None:
                    return {k: r.get(k) for k in
                            ("value_sum", "anchor_value", "residual_pct",
                             "status", "anchor_used")}
    return None


def main() -> int:
    import csv
    rows = list(csv.DictReader(open(MANIFEST)))
    claims = []
    for m in rows:
        rid = m["review_id"]
        b = _bundle(rid)
        rel = f"data/output/shadow/trial_2026-06-18/sample/review_bundles/{rid}.json"
        claim = {
            "review_id": rid,
            "rule_name": m["rule_name"],
            "klass": m["klass"],
            "cik": b.get("cik"),
            "report_date": b.get("report_date"),
            "bundle_path": rel,
            "cons": _cons_fields(b) if m["rule_name"] == "fv_conservation" else None,
            "seed_issuers": _seed_issuers(b) if m["rule_name"] != "fv_conservation"
            else _seed_issuers(b, 6),
        }
        claims.append(claim)
    OUT.write_text(json.dumps(claims, indent=2))
    print(f"wrote {OUT} ({len(claims)} claims)")
    by = {}
    for c in claims:
        by[c["rule_name"]] = by.get(c["rule_name"], 0) + 1
    for k, v in sorted(by.items()):
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
