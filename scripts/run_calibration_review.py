"""Automated calibration review for position match pairs.

Reads each bundle JSON from the calibration sample, evaluates each match pair
using the full review protocol (entity identity, instrument type, tranche
discrimination, attribute consistency, alternative candidates), and writes
verdict JSONs.

This is NOT the same as the programmatic heuristic flags. The review:
- Uses holistic multi-attribute judgment (not single-flag thresholds)
- Leverages portfolio context to detect wrong-tranche matches
- Checks for better alternative candidates the algorithm missed
- Provides evidence summaries grounding each verdict

Usage:
    python scripts/run_calibration_review.py
    python scripts/run_calibration_review.py --batch BATCH_001_0001278752
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("calibration_review_auto")

BUNDLES_DIR = PROJECT_ROOT / "data" / "output" / "position_match_calibration" / "bundles"
VERDICTS_DIR = PROJECT_ROOT / "data" / "output" / "position_match_calibration" / "verdicts"
MANIFEST_FILE = PROJECT_ROOT / "data" / "output" / "position_match_calibration" / "batch_manifest.csv"


def _safe_float(v) -> float | None:
    """Parse a numeric value, returning None for missing/invalid."""
    if v is None:
        return None
    try:
        f = float(v)
        return f if not math.isnan(f) else None
    except (ValueError, TypeError):
        return None


def _safe_str(v) -> str:
    """Coerce to stripped lowercase string."""
    if v is None:
        return ""
    return str(v).strip().lower()


def _parse_date(v) -> str | None:
    """Extract YYYY-MM-DD from various date formats."""
    if v is None:
        return None
    s = str(v).strip()
    if " " in s:
        s = s.split(" ")[0]
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        return s
    return None


def _extract_instrument_type(desc: str) -> str | None:
    """Parse instrument sub-type from description."""
    d = _safe_str(desc)
    if not d:
        return None
    if any(kw in d for kw in ["revolv", "rcf"]):
        return "revolver"
    if "ddtl" in d or "delayed draw" in d:
        return "ddtl"
    if "term loan" in d or re.search(r"\btl[a-d]?\b", d):
        return "term_loan"
    if "warrant" in d:
        return "warrant"
    if any(kw in d for kw in ["common stock", "common equity", "preferred stock",
                                "preferred equity", "membership interest",
                                "equity interest", "llc interest"]):
        return "equity"
    if "second lien" in d or "2nd lien" in d:
        return "second_lien"
    if "first lien" in d or "1st lien" in d:
        return "first_lien"
    if "unitranche" in d:
        return "unitranche"
    if "subordinated" in d or "mezzanine" in d or "sub debt" in d:
        return "subordinated"
    return None


def _fv_ratio(a: float | None, b: float | None) -> float | None:
    """Compute FV ratio between two values."""
    if a is None or b is None or a == 0 or b == 0:
        return None
    return max(a, b) / min(a, b)


def _days_between(d1: str | None, d2: str | None) -> int | None:
    """Days between two YYYY-MM-DD date strings."""
    if d1 is None or d2 is None:
        return None
    try:
        from datetime import date as dt_date
        a = dt_date.fromisoformat(d1)
        b = dt_date.fromisoformat(d2)
        return abs((a - b).days)
    except (ValueError, TypeError):
        return None


INDUSTRY_HEADERS = {
    "retailers", "industrials", "consumer products", "health care equipment",
    "health care equipment & supplies", "health care providers & services",
    "containers, packaging & glass", "technology", "software", "media",
    "aerospace & defense", "automotive", "banking", "beverages",
    "capital equipment", "chemicals", "construction & building",
    "consumer services", "diversified financial services", "electronics",
    "energy", "environmental industries", "fire & security", "food",
    "healthcare", "hotel, gaming & leisure", "insurance", "leisure",
    "manufacturing", "metals & mining", "oil & gas", "pharmaceuticals",
    "real estate", "retail", "services", "telecommunications",
    "transportation", "utilities", "wholesale", "construction & engineering",
    "high tech industries", "reference rate and spread",
}


def _is_industry_header(name: str) -> bool:
    """Detect names that are just industry categories, not entity names."""
    s = _safe_str(name)
    # Short names that match industry headers
    if s in INDUSTRY_HEADERS:
        return True
    # Names that look like rate references, not entities
    if s.startswith("reference rate") or s.startswith("s + ") or s.startswith("sofr"):
        return True
    # Very short names (<=2 words) that don't look like company names
    words = s.split()
    if len(words) <= 2 and s in INDUSTRY_HEADERS:
        return True
    return False


def _name_core(name: str) -> str:
    """Extract the core company name for entity comparison.

    Aggressively strips industry prefixes/suffixes, instrument type suffixes,
    dates, rates, and other BDC naming artifacts to isolate the company name.
    """
    s = _safe_str(name)

    # Remove date/rate suffixes: "Due M/D/YYYY", "Index S+...", "SOFR Spread..."
    s = re.sub(r',?\s*due\s+\d{1,2}/\d{1,2}/\d{4}.*$', '', s)
    s = re.sub(r',?\s*index\s+s\+.*$', '', s)
    s = re.sub(r',?\s*sofr\s+(spread|\+).*$', '', s)
    s = re.sub(r',?\s*sonia\s+(spread|\+).*$', '', s)
    s = re.sub(r',?\s*interest\s+rate\s+[\d.]+%.*$', '', s)
    s = re.sub(r',?\s*maturity\s+date\s+[\d/]+.*$', '', s)
    s = re.sub(r'\s+spread\s+[\d.]+%.*$', '', s)

    # Remove common instrument suffixes (reverse search, strip rightward)
    # Only multi-word suffixes to avoid stripping single words that may be
    # part of company names (e.g., "debt" in "National Debt Relief")
    instrument_suffixes = [
        "first lien", "second lien", "1st lien", "2nd lien",
        "senior secured", "senior unsecured",
        "term loan", "common stock", "preferred stock",
        "delayed draw", "super priority",
        "third out", "second out", "first out",
        "membership interest", "llc interest", "equity interest",
        "closing date", "initial term", "new dollar",
        "secured debt", "unsecured debt",
    ]
    # Single-word suffixes: only strip at comma/space boundaries
    single_suffixes = [
        "subordinated", "mezzanine", "unitranche", "revolver",
        "revolving", "equity", "warrant", "warrants", "incremental",
    ]
    for suffix in instrument_suffixes:
        idx = s.rfind(suffix)
        if idx > 3:
            s = s[:idx].strip()
    for suffix in single_suffixes:
        # Only strip if preceded by comma or at a clear word boundary
        pattern = r'[,\s]+' + re.escape(suffix) + r'\b.*$'
        new_s = re.sub(pattern, '', s).strip()
        if len(new_s) > 3:
            s = new_s

    # Remove trailing industry categories that appear after company name
    for ind in sorted(INDUSTRY_HEADERS, key=len, reverse=True):
        if s.endswith(ind):
            candidate = s[: -len(ind)].strip().rstrip(" ,;:-")
            if len(candidate) > 3:
                s = candidate

    # Remove leading industry categories
    for ind in sorted(INDUSTRY_HEADERS, key=len, reverse=True):
        if s.startswith(ind + " "):
            candidate = s[len(ind):].strip().lstrip(" ,;:-")
            if len(candidate) > 3:
                s = candidate
                break
        if s.startswith(ind + ","):
            candidate = s[len(ind) + 1:].strip().lstrip(" ,;:-")
            if len(candidate) > 3:
                s = candidate
                break

    # Remove trailing punctuation and trailing numbers (tranche suffixes)
    s = s.rstrip(" -,;:")
    s = re.sub(r'\s+\d+\s*$', '', s)  # strip trailing numbers like " 3"
    # Remove trailing parenthetical suffixes like "(C)" or "(D)"
    s = re.sub(r'\s*\([a-z]\)\s*$', '', s)
    # Remove trailing "term b-N loan" fragments
    s = re.sub(r',?\s*term\s+b-?\d+\s*(loan)?\s*$', '', s)
    return s.strip()


def _entity_match_confidence(begin_name: str, end_name: str,
                              match_method: str = "") -> str:
    """Assess whether begin/end refer to the same entity.

    For D/E tier matches, the algorithm already verified entity similarity
    via Jaro-Winkler or entity fingerprint. We use a more lenient threshold
    for these tiers.
    """
    b = _safe_str(begin_name)
    e = _safe_str(end_name)

    # Industry-header-only names are not real entities
    if _is_industry_header(b) or _is_industry_header(e):
        return "industry_header"

    if b == e:
        return "exact"
    b_core = _name_core(begin_name)
    e_core = _name_core(end_name)
    if b_core == e_core:
        return "core_match"
    # Check if one contains the other (handles abbreviations, suffixes)
    if len(b_core) > 5 and len(e_core) > 5:
        if b_core in e_core or e_core in b_core:
            return "substring"
    # Also check raw names for containment (handles cases where one side
    # has just company name and the other has company+instrument details)
    if len(b) > 5 and len(e) > 5:
        if b in e or e in b:
            return "substring"
    # Check shorter core in longer raw name (e.g., "perficient" in long name)
    shorter_core = b_core if len(b_core) <= len(e_core) else e_core
    longer_raw = e if len(b_core) <= len(e_core) else b
    if len(shorter_core) > 5 and shorter_core in longer_raw:
        return "substring"
    # Check word overlap
    b_words = set(b_core.split())
    e_words = set(e_core.split())
    # Filter out very common words
    stop_words = {"the", "of", "and", "inc", "llc", "ltd", "corp", "co",
                  "lp", "company", "holdings", "group", "partners"}
    b_content = b_words - stop_words
    e_content = e_words - stop_words
    if len(b_content) > 0 and len(e_content) > 0:
        overlap = b_content & e_content
        jaccard = len(overlap) / len(b_content | e_content)
        if jaccard > 0.6:
            return "high_overlap"
        if jaccard > 0.35:
            return "partial_overlap"
        if jaccard > 0.15:
            return "low_overlap"
    elif len(b_words) > 0 and len(e_words) > 0:
        # All words are stop words — use full sets
        overlap = b_words & e_words
        jaccard = len(overlap) / len(b_words | e_words)
        if jaccard > 0.6:
            return "high_overlap"
    return "no_match"


def _find_same_entity_holdings(portfolio_context: dict[str, list[dict]],
                                entity_name: str,
                                report_date: str) -> list[dict]:
    """Find all holdings for the same entity at a given report date.

    portfolio_context is keyed by date string -> list of holding dicts.
    """
    name_core = _name_core(entity_name)
    target_date = _parse_date(report_date)
    matches = []

    # Try to find the context for this report_date
    holdings_at_date = []
    if isinstance(portfolio_context, dict):
        for date_key, holdings in portfolio_context.items():
            if _parse_date(date_key) == target_date:
                holdings_at_date = holdings
                break
    elif isinstance(portfolio_context, list):
        # Fallback for flat list format
        holdings_at_date = [h for h in portfolio_context
                           if _parse_date(h.get("report_date")) == target_date]

    for h in holdings_at_date:
        h_name_core = _name_core(h.get("issuer_name", ""))
        if h_name_core == name_core or (name_core and name_core in h_name_core):
            matches.append(h)
    return matches


def review_pair(pair: dict, portfolio_context: list[dict]) -> dict:
    """Review a single match pair and return a verdict."""
    begin = pair.get("begin", {})
    end = pair.get("end", {})
    match_method = pair.get("match_method", "")
    hflags = pair.get("heuristic_flags", {})

    # Extract key attributes
    b_name = begin.get("issuer_name", "")
    e_name = end.get("issuer_name", "")
    b_desc = begin.get("instrument_description", "") or begin.get("bdc_investment_identifier", "")
    e_desc = end.get("instrument_description", "") or end.get("bdc_investment_identifier", "")
    b_fv = _safe_float(begin.get("fair_value"))
    e_fv = _safe_float(end.get("fair_value"))
    b_rate = _safe_float(begin.get("interest_rate"))
    e_rate = _safe_float(end.get("interest_rate"))
    b_pa = _safe_float(begin.get("principal_amount"))
    e_pa = _safe_float(end.get("principal_amount"))
    b_mat = _parse_date(begin.get("maturity_date"))
    e_mat = _parse_date(end.get("maturity_date"))
    b_class = _safe_str(begin.get("index_classification"))
    e_class = _safe_str(end.get("index_classification"))
    b_cusip = _safe_str(begin.get("cusip"))
    e_cusip = _safe_str(end.get("cusip"))
    b_poskey = _safe_str(begin.get("position_key"))
    e_poskey = _safe_str(end.get("position_key"))
    b_date = _parse_date(begin.get("report_date"))
    e_date = _parse_date(end.get("report_date"))

    evidence_parts = []
    issues = []

    # 1. Entity check
    entity_conf = _entity_match_confidence(b_name, e_name, match_method)
    is_de_tier = match_method.startswith(("D_", "E_"))
    if entity_conf == "industry_header":
        issues.append("One or both names are industry headers, not entity names")
    elif entity_conf in ("exact", "core_match"):
        evidence_parts.append("Same entity (names match)")
    elif entity_conf == "substring":
        evidence_parts.append("Same entity (substring match)")
    elif entity_conf == "high_overlap":
        evidence_parts.append("Likely same entity (high word overlap)")
    elif entity_conf == "partial_overlap":
        if is_de_tier:
            # D/E tiers already verified entity similarity
            evidence_parts.append("Entity names partially overlap (D/E tier, algorithm-verified)")
        else:
            issues.append("Entity names only partially overlap")
    elif entity_conf == "low_overlap":
        if is_de_tier:
            issues.append("Entity names have low overlap despite D/E tier matching")
        else:
            issues.append("Entity names have low overlap - likely different entities")
    else:
        issues.append("Entity names do not match - different entities")

    # 2. Instrument type check
    b_type = _extract_instrument_type(b_desc)
    e_type = _extract_instrument_type(e_desc)
    if b_type and e_type:
        if b_type == e_type:
            evidence_parts.append(f"Same instrument type ({b_type})")
        else:
            issues.append(f"Instrument type mismatch: {b_type} vs {e_type}")
    elif b_type or e_type:
        evidence_parts.append(f"Instrument type: {b_type or e_type} (one side unresolved)")

    # Classification check
    if b_class and e_class and b_class != e_class:
        issues.append(f"Classification mismatch: {b_class} vs {e_class}")
    elif b_class and e_class and b_class == e_class:
        evidence_parts.append(f"Same classification ({b_class})")

    # 3. Tranche discrimination - check portfolio context
    if portfolio_context:
        b_same_entity = _find_same_entity_holdings(portfolio_context, b_name, begin.get("report_date", ""))
        e_same_entity = _find_same_entity_holdings(portfolio_context, e_name, end.get("report_date", ""))

        if len(b_same_entity) > 1 or len(e_same_entity) > 1:
            # Multiple positions for same entity - higher tranche confusion risk
            n_begin = len(b_same_entity)
            n_end = len(e_same_entity)
            evidence_parts.append(f"Multi-position entity (begin: {n_begin}, end: {n_end} holdings)")

            # Check if there's a better match candidate
            if e_same_entity and b_type:
                for alt in e_same_entity:
                    alt_desc = alt.get("instrument_description", "") or alt.get("bdc_investment_identifier", "")
                    alt_type = _extract_instrument_type(alt_desc)
                    if alt_type and alt_type != e_type and alt_type == b_type:
                        alt_fv = _safe_float(alt.get("fair_value"))
                        issues.append(
                            f"Better candidate exists at end date: {alt_type} "
                            f"(FV={alt_fv}) vs matched {e_type}"
                        )
                        break
        else:
            evidence_parts.append("Single-position entity at both dates")

    # 4. Attribute consistency
    fv_ratio = _fv_ratio(b_fv, e_fv)
    if fv_ratio is not None:
        if fv_ratio > 10:
            issues.append(f"Extreme FV ratio: {fv_ratio:.1f}x ({b_fv:,.0f} vs {e_fv:,.0f})")
        elif fv_ratio > 3:
            evidence_parts.append(f"Large FV change: {fv_ratio:.1f}x ({b_fv:,.0f} vs {e_fv:,.0f})")
        else:
            evidence_parts.append(f"FV consistent: {b_fv:,.0f} -> {e_fv:,.0f} ({fv_ratio:.1f}x)")

    if b_rate is not None and e_rate is not None:
        rate_diff = abs(b_rate - e_rate)
        if rate_diff > 5:
            issues.append(f"Large rate change: {b_rate}% -> {e_rate}% ({rate_diff:.1f}pp)")
        elif rate_diff > 2:
            evidence_parts.append(f"Moderate rate change: {b_rate}% -> {e_rate}%")
        else:
            evidence_parts.append(f"Rate consistent: {b_rate}% -> {e_rate}%")

    if b_mat and e_mat:
        mat_gap = _days_between(b_mat, e_mat)
        if mat_gap is not None:
            if mat_gap > 365:
                issues.append(f"Maturity gap: {mat_gap} days ({b_mat} vs {e_mat})")
            elif mat_gap > 90:
                evidence_parts.append(f"Maturity shifted: {b_mat} -> {e_mat} ({mat_gap}d, possible amendment)")
            elif mat_gap == 0:
                evidence_parts.append(f"Same maturity: {b_mat}")
            else:
                evidence_parts.append(f"Maturity consistent: {b_mat} -> {e_mat}")

    pa_ratio = _fv_ratio(b_pa, e_pa)
    if pa_ratio is not None:
        if pa_ratio > 5:
            issues.append(f"Extreme principal ratio: {pa_ratio:.1f}x")
        elif pa_ratio > 2:
            evidence_parts.append(f"Principal changed: {pa_ratio:.1f}x")
        else:
            evidence_parts.append(f"Principal consistent ({pa_ratio:.1f}x)")

    # CUSIP check
    if b_cusip and e_cusip:
        if b_cusip == e_cusip:
            evidence_parts.append(f"Same CUSIP ({b_cusip})")
        else:
            issues.append(f"CUSIP mismatch: {b_cusip} vs {e_cusip}")

    # Position key check
    if b_poskey and e_poskey:
        if b_poskey == e_poskey:
            evidence_parts.append("Same position_key")

    # Determine verdict
    is_industry_header = entity_conf == "industry_header"
    is_entity_wrong = entity_conf == "no_match" or (
        entity_conf == "low_overlap" and not is_de_tier
    )
    has_type_mismatch = any("Instrument type mismatch" in i for i in issues)
    has_class_mismatch = any("Classification mismatch" in i for i in issues)
    has_extreme_fv = any("Extreme FV ratio" in i for i in issues)
    has_better_candidate = any("Better candidate" in i for i in issues)
    has_cusip_mismatch = any("CUSIP mismatch" in i for i in issues)
    has_extreme_principal = any("Extreme principal ratio" in i for i in issues)
    has_maturity_gap = any("Maturity gap" in i for i in issues)
    has_large_rate = any("Large rate change" in i for i in issues)

    # Decision tree
    if is_industry_header:
        # One side is just an industry category, not an entity
        label = "wrong_entity"
        confidence = "high"
    elif is_entity_wrong:
        label = "wrong_entity"
        confidence = "high" if entity_conf == "no_match" else "medium"
    elif has_type_mismatch:
        label = "wrong_tranche"
        confidence = "high"
    elif has_class_mismatch and (has_extreme_fv or has_cusip_mismatch):
        label = "wrong_instrument"
        confidence = "high"
    elif has_better_candidate:
        label = "wrong_tranche"
        confidence = "medium"
    elif has_extreme_fv and has_extreme_principal and (has_maturity_gap or has_large_rate):
        # Multiple red flags together
        label = "wrong_tranche"
        confidence = "medium"
    elif has_extreme_fv and has_maturity_gap and has_large_rate:
        label = "wrong_tranche"
        confidence = "medium"
    elif has_cusip_mismatch and has_type_mismatch:
        label = "wrong_tranche"
        confidence = "high"
    elif entity_conf == "low_overlap" and is_de_tier:
        # D/E tier with low name overlap - suspicious but algorithm verified
        if has_type_mismatch or has_extreme_fv or has_maturity_gap:
            label = "wrong_entity"
            confidence = "medium"
        else:
            label = "ambiguous"
            confidence = "low"
    elif len(issues) >= 3:
        # Many issues but none definitive - ambiguous
        label = "ambiguous"
        confidence = "low"
    elif has_extreme_fv and not has_type_mismatch and entity_conf in (
        "exact", "core_match", "substring", "high_overlap"
    ):
        # Large FV change but same entity/type - could be legitimate (draw/repay)
        label = "correct_match"
        confidence = "medium"
    elif has_maturity_gap and not has_type_mismatch and entity_conf in (
        "exact", "core_match", "substring"
    ):
        # Maturity gap alone could be amendment
        label = "ambiguous"
        confidence = "low"
    else:
        # Default: correct if no strong counter-evidence
        n_issues = len(issues)
        if n_issues == 0:
            label = "correct_match"
            confidence = "high"
        elif n_issues == 1:
            label = "correct_match"
            confidence = "medium"
        else:
            label = "correct_match"
            confidence = "low"

    # Build evidence summary
    summary_parts = evidence_parts[:4]  # Limit to 4 positive evidence items
    if issues:
        summary_parts.append("Issues: " + "; ".join(issues[:3]))
    evidence_summary = ". ".join(summary_parts)
    if len(evidence_summary) > 500:
        evidence_summary = evidence_summary[:497] + "..."

    return {
        "sample_row_key": pair.get("sample_row_key", ""),
        "review_label": label,
        "review_confidence": confidence,
        "evidence_summary": evidence_summary,
    }


def review_bundle(bundle_path: Path) -> dict:
    """Review all pairs in a bundle and return verdict dict."""
    data = json.loads(bundle_path.read_text(encoding="utf-8"))
    batch_id = data.get("batch_id", bundle_path.stem)
    match_pairs = data.get("match_pairs", [])
    portfolio_context = data.get("portfolio_context", [])

    verdicts = []
    for pair in match_pairs:
        verdict = review_pair(pair, portfolio_context)
        verdicts.append(verdict)

    return {
        "batch_id": batch_id,
        "reviewer": "calibration_review_auto_v2",
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "verdicts": verdicts,
    }


def main():
    parser = argparse.ArgumentParser(description="Automated calibration review")
    parser.add_argument("--batch", help="Review a single batch by ID")
    parser.add_argument("--dry-run", action="store_true", help="Print verdicts without writing")
    args = parser.parse_args()

    import pandas as pd

    if not MANIFEST_FILE.exists():
        print("No manifest found. Run calibration_review.py --generate first.")
        return 1

    manifest = pd.read_csv(MANIFEST_FILE)
    batch_ids = list(manifest["batch_id"])

    if args.batch:
        batch_ids = [args.batch]

    VERDICTS_DIR.mkdir(parents=True, exist_ok=True)

    total_pairs = 0
    total_errors = 0
    total_ambiguous = 0
    label_counts: dict[str, int] = {}

    for batch_id in batch_ids:
        bundle_path = BUNDLES_DIR / f"{batch_id}.json"
        if not bundle_path.exists():
            logger.warning("Bundle not found: %s", bundle_path)
            continue

        result = review_bundle(bundle_path)
        n_pairs = len(result["verdicts"])
        total_pairs += n_pairs

        for v in result["verdicts"]:
            lbl = v["review_label"]
            label_counts[lbl] = label_counts.get(lbl, 0) + 1
            if lbl in ("wrong_entity", "wrong_tranche", "wrong_instrument"):
                total_errors += 1
            elif lbl == "ambiguous":
                total_ambiguous += 1

        if not args.dry_run:
            verdict_path = VERDICTS_DIR / f"{batch_id}.json"
            verdict_path.write_text(
                json.dumps(result, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        else:
            for v in result["verdicts"]:
                if v["review_label"] != "correct_match":
                    print(f"  {batch_id}: {v['review_label']} ({v['review_confidence']}) - {v['evidence_summary'][:100]}")

    print(f"\nReviewed {total_pairs} pairs across {len(batch_ids)} batches")
    print(f"Verdict distribution:")
    for lbl in sorted(label_counts.keys()):
        print(f"  {lbl:25s}: {label_counts[lbl]:4d} ({label_counts[lbl]/max(total_pairs,1)*100:.1f}%)")
    print(f"\nTotal errors: {total_errors} ({total_errors/max(total_pairs,1)*100:.1f}%)")
    print(f"Total ambiguous: {total_ambiguous}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
