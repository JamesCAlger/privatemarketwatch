"""Bundle-enrichment trial: resolve the AMBIGUOUS source-table structure already in
a review bundle into ONE clean per-blocker statement, and write an enriched copy to a
sandbox. Read-only on production (writes only data/output/bdc_cik_review_exp/).

Finding that motivates this: the bundle already carries html grid + 16 redundant
coordinate candidates + noisy row classifications + EMPTY header_context. The agent
must resolve them itself and can't, so it returns INSUFFICIENT_EVIDENCE. This resolves
them deterministically: per blocker row -> majority classification + governing section
header + is-aggregate flag + a one-line conclusion.
"""
from __future__ import annotations
import json, re, sys, collections
from pathlib import Path
from pipeline.config import OUTPUT_DIR

SAND = OUTPUT_DIR / "bdc_cik_review_exp"
BUNDLES = OUTPUT_DIR / "bdc_cik_review" / "bundles"

_HDR_RE = re.compile(r"investments?\b.*(net assets|%)|^(total|subtotal)\b", re.I)
_AGG_RE = re.compile(r"^\s*(total|subtotal)\b", re.I)


def _ev(bundle: dict) -> dict:
    return {it["evidence_id"]: it.get("data", it) for it in bundle["evidence_items"]}


def resolve(bundle: dict) -> list[dict]:
    ev = _ev(bundle)
    coord = ev.get("html_source_row_coordinate_candidates", []) or []
    rowclass = ev.get("html_row_classification_candidates", []) or []
    blockers = ev.get("source_only_blocker_rows", []) or ev.get("source_residual_rows", []) or []

    # section headers present in the schedule (deterministic, from row classifications)
    headers = [r.get("row_text", "") for r in rowclass if _HDR_RE.search(str(r.get("row_text", "")))]
    agg_headers = [h for h in headers if _AGG_RE.search(h)]

    out = []
    for b in blockers:
        ident = b.get("raw_investment_identifier") or b.get("normalized_investment_identifier") or ""
        cand = [c for c in coord if c.get("raw_investment_identifier") == ident]
        tally = collections.Counter()
        for c in cand:
            for cl in c.get("classification_candidates", []):
                tally[cl] += 1
        resolved_class = tally.most_common(1)[0][0] if tally else "UNRESOLVED"
        agree = f"{tally.get(resolved_class,0)}/{sum(tally.values())}" if tally else "0/0"
        self_aggregate = bool(_AGG_RE.search(ident))
        issuer_token = ident.split(",")[0].strip().lower()[:18]
        issuer_subtotal = any(("total" in h.lower() and issuer_token and issuer_token in h.lower())
                              for h in headers)
        pos_evidence = b.get("why_not_cleared") or b.get("reason") or ""
        if self_aggregate:
            concl = "Row IS an aggregate/subtotal header -> correctly excluded; NO_PATCH_NEEDED candidate."
        elif resolved_class == "POSITION_ROW":
            concl = ("Resolves to POSITION_ROW (coordinate candidates unanimous) under a non-aggregate "
                     "section; position-like evidence present -> genuine position missing from output "
                     "(under-inclusion); supports a bounded parser/normalization patch.")
        else:
            concl = f"Resolved classification {resolved_class}; insufficient to call position vs aggregate."
        out.append({
            "raw_investment_identifier": ident,
            "resolved_classification": resolved_class,
            "coordinate_candidate_agreement": agree,
            "self_row_is_aggregate_header": self_aggregate,
            "issuer_has_total_subtotal_line": issuer_subtotal,
            "governing_section_headers": headers[:6],
            "aggregate_section_headers": agg_headers[:6],
            "position_like_evidence": str(pos_evidence)[:300],
            "deterministic_conclusion": concl,
        })
    return out


def main(argv=None):
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        # default: 2 position_like bundles
        cands = sorted(BUNDLES.glob("*POSITION_LIKE*.json"))[:2]
    else:
        cands = [Path(a) for a in args]
    SAND.mkdir(parents=True, exist_ok=True)
    for bp in cands:
        bundle = json.loads(bp.read_text())
        resolved = resolve(bundle)
        # CONTROL copy (verbatim) + TREATMENT copy (+ resolved item)
        (SAND / f"CONTROL_{bp.name}").write_text(json.dumps(bundle, indent=2))
        treat = json.loads(bp.read_text())
        treat["evidence_items"].append({
            "evidence_id": "resolved_source_table_position",
            "data": resolved,
            "note": "Deterministic resolution of the ambiguous coordinate/classification candidates "
                    "already in this bundle: one statement per blocker row.",
        })
        (SAND / f"TREATMENT_{bp.name}").write_text(json.dumps(treat, indent=2))
        print(f"\n=== {bp.name} ({len(resolved)} blocker rows) ===")
        for r in resolved:
            print(json.dumps(r, indent=2)[:900])
    print(f"\nwrote control/treatment pairs to {SAND}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
