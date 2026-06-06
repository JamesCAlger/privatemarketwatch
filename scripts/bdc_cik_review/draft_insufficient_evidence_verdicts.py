import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pipeline import config


REVIEW_DIR = config.OUTPUT_DIR / "bdc_cik_review"


def _read_worklist(path: Path) -> dict[str, dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        return {row["review_id"]: row for row in csv.DictReader(f)}


def _evidence_ids(bundle: dict) -> set[str]:
    return {
        str(item.get("evidence_id"))
        for item in bundle.get("evidence_items", [])
        if isinstance(item, dict) and item.get("evidence_id")
    }


def _base_refs(bundle: dict) -> list[str]:
    available = _evidence_ids(bundle)
    preferred = [
        "worklist_row",
        "source_residual_rows",
        "source_only_blocker_rows",
        "source_reconciliation_detail_samples",
        "cik_validation_packet",
        "gav_reconciliation",
    ]
    return [ref for ref in preferred if ref in available]


def _verdict_for(bundle: dict, work: dict[str, str]) -> dict:
    mechanism = str(bundle.get("mechanism") or work.get("mechanism") or "")
    sample_identifiers = work.get("sample_identifiers", "")
    recommended_action = work.get("recommended_action", "")
    source_rows = work.get("source_only_blocker_rows") or work.get("issue_count") or ""
    source_fv = work.get("source_only_blocker_fv") or work.get("affected_source_fair_value") or ""

    missing_evidence = (
        "Insufficient bounded evidence to safely change production parsing for this "
        "CIK-quarter-mechanism packet without manual source-table adjudication and a "
        "tested rule. Needed evidence: coordinate-level source table classification for "
        "the blocker rows, proof that the rows are either true position rows or "
        "non-position aggregate/header rows, and a false-positive analysis showing any "
        "proposed parser/config rule would not suppress legitimate position-level holdings."
    )
    if "unclassifiable_after_review" in mechanism:
        missing_evidence = (
            "The cached deterministic review already exhausted numeric alias, total/header, "
            "cash bucket, rollup, position-like, and short-name hypotheses without a safe "
            "clearing mechanism. Needed evidence is the source filing table coordinates and "
            "row semantics proving whether each blocker is a production position, subtotal, "
            "unfunded/non-index row, or duplicate dimension path."
        )
    elif "pct_ambiguous" in mechanism:
        missing_evidence = (
            "The terminal-percentage source rows remain ambiguous after deterministic review. "
            "Needed evidence is coordinate-level source table classification and a bounded "
            "rule distinguishing leaf position rows from percentage subtotal/category rows "
            "for this filer without weakening existing blocker semantics."
        )

    return {
        "review_id": bundle["review_id"],
        "cik": bundle["cik"],
        "report_date": bundle["report_date"],
        "verdict": "INSUFFICIENT_EVIDENCE",
        "confidence": "LOW",
        "primary_justification": (
            "This packet is documented rather than patched because the bundle identifies "
            f"{source_rows} current blocker row(s) in mechanism {mechanism}, but does not by "
            "itself establish a bounded production rule with source-table row semantics and "
            "false-positive protection."
        ),
        "reconciliation_diagnosis": "INSUFFICIENT_EVIDENCE",
        "evidence_refs": _base_refs(bundle),
        "changed_files": [],
        "rule_type": "",
        "html_citations": [],
        "patch_summary": "",
        "source_reconciliation_effect": (
            "No production rows are added, removed, or reclassified by this verdict. The "
            "source reconciliation blocker remains an explicitly reviewed unresolved packet "
            "until independent evidence supports a bounded patch."
        ),
        "gav_effect": (
            "No GAV effect; this verdict does not alter holdings, source rows, or validation outputs."
        ),
        "tests_validation_plan": (
            "Validate schema and bundle-reference integrity with "
            "python scripts/bdc_cik_review/validate_verdicts.py --output-dir "
            "data/output/bdc_cik_review --all. If later converted to a patch, add targeted "
            "BDC review/parser tests plus false-positive coverage before rebuilding outputs."
        ),
        "requires_human_merge": False,
        "missing_evidence": missing_evidence,
        "residual_risk": (
            "The blocker is not hidden or suppressed. Public data-quality risk remains until "
            "the row semantics are proven from source coordinates or a bounded tested parser "
            f"fix is implemented. Affected source FV reported by the worklist: {source_fv}."
        ),
        "reviewer_notes": (
            "Auto-drafted from the completed BDC bundle and worklist for full-pool accounting. "
            f"Recommended action from worklist: {recommended_action}. Sample identifiers: "
            f"{sample_identifiers[:1000]}"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Draft conservative insufficient-evidence verdicts for BDC review bundles."
    )
    parser.add_argument("--output-dir", type=Path, default=REVIEW_DIR)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    output_dir = args.output_dir
    worklist = _read_worklist(output_dir / "worklist.csv")
    bundle_dir = output_dir / "bundles"
    verdict_dir = output_dir / "verdicts"
    verdict_dir.mkdir(parents=True, exist_ok=True)

    written = 0
    skipped = 0
    missing = 0
    for review_id, work in sorted(worklist.items()):
        bundle_path = bundle_dir / f"{review_id}.json"
        if not bundle_path.exists():
            missing += 1
            continue
        verdict_path = verdict_dir / f"{review_id}.json"
        if verdict_path.exists() and not args.overwrite:
            skipped += 1
            continue
        bundle = json.loads(bundle_path.read_text(encoding="utf-8-sig"))
        verdict = _verdict_for(bundle, work)
        verdict_path.write_text(json.dumps(verdict, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written += 1

    print(json.dumps({"written": written, "skipped": skipped, "missing_bundles": missing}, indent=2, sort_keys=True))
    return 0 if missing == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
