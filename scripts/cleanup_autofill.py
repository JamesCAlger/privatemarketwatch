"""Clean up auto-filled filings that cause validation failures.

For each FAIL CIK with fv_fill issues, reverts auto-filled filings that produce
zero extraction. Keeps auto-filled filings that extract correctly.

Strategy:
1. For each FAIL CIK, quick-test each auto-filled filing's extraction
2. If a filing produces 0 FV, revert it to tables=[]
3. Re-save the template
"""
import json
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.html_extract import extract_filing, load_template, _extract_tables, _parse_dollar
from pipeline.config import BDC_HTML_CACHE_DIR

import pandas as pd


def _load_filings_index():
    idx_path = Path("data/output/bdc_filings_index.csv")
    if idx_path.exists():
        return pd.read_csv(idx_path, dtype=str)
    return pd.DataFrame()


def _is_auto_filled(override: dict) -> bool:
    """Check if a filing override was auto-filled (has tables but no column overrides)."""
    has_tables = bool(override.get("tables"))
    has_columns = bool(override.get("columns") or override.get("columns_by_width") or
                       override.get("header_row") is not None)
    return has_tables and not has_columns


def quick_test_filing(cik: str, acc_dashed: str, template: dict, override: dict) -> dict:
    """Quick-test extraction for a single filing. Returns stats."""
    cik_stripped = cik.lstrip("0")
    acc_nodashes = acc_dashed.replace("-", "")
    html_path = BDC_HTML_CACHE_DIR / cik_stripped / f"{acc_nodashes}.html"

    if not html_path.exists():
        return {"status": "no_html", "fv_count": 0, "total": 0}

    try:
        with open(html_path, "r", encoding="utf-8", errors="replace") as f:
            html = f.read()

        # Build filing_meta
        filing_meta = {
            "accession_number": acc_dashed,
            "report_date": "2020-01-01",  # placeholder
            "form_type": "10-Q",
        }

        holdings, stats = extract_filing(html, filing_meta, template)
        # extract_filing returns raw strings; parse FV to detect real numeric values
        non_subtotal = [h for h in holdings if not h.get("is_subtotal")]
        fv_count = 0
        for h in non_subtotal:
            fv_raw = h.get("fair_value", "")
            parsed = _parse_dollar(fv_raw)
            if parsed is not None and parsed != 0:
                fv_count += 1
        total = len(non_subtotal)
        return {
            "status": "ok",
            "total": total,
            "fv_count": fv_count,
            "fv_fill": fv_count / total if total else 0,
        }
    except Exception as e:
        return {"status": "error", "error": str(e)[:100], "fv_count": 0, "total": 0}


def cleanup_cik(cik: str, template: dict, results: dict) -> dict:
    """Clean up auto-filled filings for a CIK. Returns stats."""
    filings = template.get("filings", {})
    stats = {"tested": 0, "reverted": 0, "kept": 0, "not_autofill": 0}

    for acc_dashed, override in list(filings.items()):
        if not _is_auto_filled(override):
            stats["not_autofill"] += 1
            continue

        tables = override.get("tables", [])
        if not tables:
            continue

        stats["tested"] += 1
        result = quick_test_filing(cik, acc_dashed, template, override)

        if result["total"] == 0 or result["fv_fill"] < 0.05:
            # Revert: zero out tables
            override["tables"] = []
            if "table_periods" in override:
                del override["table_periods"]
            stats["reverted"] += 1
        else:
            stats["kept"] += 1

    return stats


def main():
    # Load batch validation results
    with open("data/output/batch_validate_results.json") as f:
        val_results = json.load(f)

    template_dir = Path("data/raw/filing_templates")

    # Focus on FAIL CIKs
    fail_ciks = [cik for cik, r in val_results.items() if r["status"] == "FAIL"]
    print(f"Processing {len(fail_ciks)} FAIL CIKs...")

    total_stats = {"tested": 0, "reverted": 0, "kept": 0}
    modified = []

    for i, cik in enumerate(sorted(fail_ciks, key=lambda x: int(x))):
        tp = template_dir / f"{cik}.json"
        if not tp.exists():
            continue

        with open(tp) as f:
            template = json.load(f)
        if template.get("version") != "3.0":
            continue

        result = cleanup_cik(cik, template, val_results)

        if result["reverted"] > 0:
            modified.append(cik)
            with open(tp, "w") as f:
                json.dump(template, f, indent=2)
                f.write("\n")

        for k in total_stats:
            total_stats[k] += result.get(k, 0)

        if result["tested"] > 0:
            sys.stdout.write(f"[{i+1}/{len(fail_ciks)}] CIK {cik:>10}: "
                           f"tested={result['tested']}, kept={result['kept']}, "
                           f"reverted={result['reverted']}\n")
            sys.stdout.flush()

    print(f"\nSummary:")
    print(f"  Tested: {total_stats['tested']}")
    print(f"  Kept: {total_stats['kept']}")
    print(f"  Reverted: {total_stats['reverted']}")
    print(f"  Modified CIKs: {len(modified)}")


if __name__ == "__main__":
    main()
