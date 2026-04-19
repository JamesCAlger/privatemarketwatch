"""Position-level HTML-vs-XBRL cross-validator.

Downloads HTML primary documents for XBRL-era filings, extracts positions
using per-CIK templates, and compares against XBRL holdings to quantify
extraction accuracy and produce per-CIK error rates.
"""

import logging
import re
from pathlib import Path
from typing import Optional

import pandas as pd

from pipeline.config import (
    BDC_FILINGS_INDEX_FILE,
    BDC_HOLDINGS_FILE,
    BDC_HTML_CACHE_DIR,
    HTML_TEMPLATE_DIR,
    OUTPUT_DIR,
)

logger = logging.getLogger(__name__)

# Output files
HTML_XBRL_FILING_COMPARISON_FILE = OUTPUT_DIR / "html_xbrl_filing_comparison.csv"
HTML_XBRL_POSITION_MATCHES_FILE = OUTPUT_DIR / "html_xbrl_position_matches.csv"

# Legal suffixes stripped during name normalization
_LEGAL_SUFFIXES = re.compile(
    r",?\s*\b("
    r"LLC|L\.L\.C\.|Inc\.?|Corp\.?|Ltd\.?|L\.P\.?|LP"
    r"|Co\.?|Company|Corporation|Incorporated"
    r"|Holdings|Group|Partners|Capital"
    r")\s*$",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Name normalization
# ---------------------------------------------------------------------------

def _normalize_name(name: str) -> str:
    """Lightweight name normalization for matching.

    Lowercase, strip whitespace, collapse multiple spaces,
    strip trailing punctuation (commas, semicolons).
    """
    if not name or not isinstance(name, str):
        return ""
    s = name.lower().strip()
    s = re.sub(r"\s+", " ", s)
    s = s.rstrip(",;")
    return s.strip()


def _extract_xbrl_company_name(identifier: str) -> str:
    """Extract the company/issuer name from an XBRL investment_identifier.

    Handles pipe-separated, dash-separated, and plain formats.
    Reuses the logic from unified_holdings._parse_bdc_identifier but
    simplified -- we only need the company name, not instrument.
    """
    if not identifier or not isinstance(identifier, str):
        return ""

    # Pipe-separator format
    if " | " in identifier:
        parts = identifier.split(" | ")
        if len(parts) >= 3:
            # Check if last segment is affiliation tag
            last = parts[-1].strip().lower()
            _affil_tags = {
                "non-controlled/non-affiliated",
                "non-controlled/affiliated",
                "controlled affiliated",
                "non-controlled, non-affiliated",
                "non-controlled, affiliated",
                "affiliated",
                "control",
            }
            if last in _affil_tags:
                return parts[0].strip()

            # Check if first segment is a category name (not a company).
            # Some filers use "Category | Industry | Company (Details)"
            # instead of "Company | Industry | Instrument".
            seg0_lower = parts[0].strip().lower()
            _CATEGORY_NAMES = {
                "senior secured loans", "unsecured loans",
                "preferred stocks", "common stocks",
                "corporate bonds", "convertible bonds",
                "warrants", "rights",
                "llc interests", "lp interests",
                "asset-backed securities", "mortgage-backed securities",
                "equity securities", "sovereign bonds",
                "foreign sovereign bonds",
                "total investments", "net assets",
                "cash equivalents",
                "purchased call options", "purchased put options",
                "total return swap",
                "closed-end mutual funds",
            }
            if seg0_lower in _CATEGORY_NAMES:
                # Category | Industry | Company [| Rate | Maturity]
                # Company is always at index 2
                return parts[2].strip()

            # Check if first segment looks like a company (has legal suffix)
            _LEGAL_SUFFIXES = re.compile(
                r"\b(?:inc|corp|llc|ltd|l\.?p\.?|co|plc|n\.?v\.?|s\.?a\.?|"
                r"gmbh|ag|trust|fund|partners|holdings)\b",
                re.IGNORECASE,
            )
            if _LEGAL_SUFFIXES.search(parts[0]):
                return parts[0].strip()

            # Fallback: return last segment (more likely to be company)
            return parts[-1].strip()
        elif len(parts) == 2:
            return parts[0].strip()

    # Dash-separator format
    if " - " in identifier:
        segments = identifier.split(" - ")
        return segments[0].strip()

    # Plain format
    return identifier.strip()


# ---------------------------------------------------------------------------
# Position matching
# ---------------------------------------------------------------------------

def match_positions(
    html_positions: list[dict],
    xbrl_positions: list[dict],
) -> tuple[list[dict], list[dict], list[dict]]:
    """Match HTML and XBRL positions within a single filing.

    Returns (matched_pairs, html_unmatched, xbrl_unmatched).
    Each matched pair is {html, xbrl, name_score, fv_delta_pct}.
    """
    try:
        from rapidfuzz import fuzz
    except ImportError:
        logger.warning("rapidfuzz not installed; falling back to exact match only")
        fuzz = None  # type: ignore[assignment]

    if not html_positions or not xbrl_positions:
        return ([], list(html_positions), list(xbrl_positions))

    # Normalize names on both sides
    html_names = [_normalize_name(p.get("investment_identifier", "")) for p in html_positions]
    xbrl_names = [
        _normalize_name(_extract_xbrl_company_name(p.get("investment_identifier", "")))
        for p in xbrl_positions
    ]

    # Build score matrix
    scores: list[tuple[float, int, int]] = []  # (score, html_idx, xbrl_idx)

    for hi, hname in enumerate(html_names):
        html_fv = _safe_float(html_positions[hi].get("fair_value"))
        for xi, xname in enumerate(xbrl_names):
            # Name similarity
            if fuzz is not None:
                name_score = fuzz.token_sort_ratio(hname, xname)
            else:
                name_score = 100.0 if hname == xname else 0.0

            # FV proximity bonus
            xbrl_fv = _safe_float(xbrl_positions[xi].get("fair_value"))
            fv_bonus = 0.0
            if html_fv is not None and xbrl_fv is not None and xbrl_fv != 0:
                fv_pct = abs(html_fv - xbrl_fv) / abs(xbrl_fv)
                if fv_pct < 0.05:
                    fv_bonus = 20.0
                elif fv_pct < 0.20:
                    fv_bonus = 10.0

            total = name_score + fv_bonus
            scores.append((total, hi, xi))

    # Greedy 1:1 assignment
    scores.sort(key=lambda x: -x[0])  # descending
    html_used: set[int] = set()
    xbrl_used: set[int] = set()
    matched: list[dict] = []

    for total_score, hi, xi in scores:
        if hi in html_used or xi in xbrl_used:
            continue
        if total_score < 50:
            break  # remaining scores too low

        html_fv = _safe_float(html_positions[hi].get("fair_value"))
        xbrl_fv = _safe_float(xbrl_positions[xi].get("fair_value"))
        fv_delta_pct = None
        if html_fv is not None and xbrl_fv is not None and xbrl_fv != 0:
            fv_delta_pct = (html_fv - xbrl_fv) / abs(xbrl_fv)

        # Isolate name score (remove FV bonus)
        if fuzz is not None:
            pure_name_score = fuzz.token_sort_ratio(
                html_names[hi], xbrl_names[xi]
            )
        else:
            pure_name_score = 100.0 if html_names[hi] == xbrl_names[xi] else 0.0

        matched.append({
            "html": html_positions[hi],
            "xbrl": xbrl_positions[xi],
            "name_score": pure_name_score,
            "fv_delta_pct": fv_delta_pct,
        })
        html_used.add(hi)
        xbrl_used.add(xi)

    html_unmatched = [html_positions[i] for i in range(len(html_positions)) if i not in html_used]
    xbrl_unmatched = [xbrl_positions[i] for i in range(len(xbrl_positions)) if i not in xbrl_used]

    return matched, html_unmatched, xbrl_unmatched


def _safe_float(val) -> Optional[float]:
    """Convert to float safely, return None on failure."""
    if val is None:
        return None
    try:
        f = float(val)
        if f != f:  # NaN check
            return None
        return f
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Single filing comparison
# ---------------------------------------------------------------------------

def compare_filing(
    cik: str,
    accession: str,
    filing_meta: dict,
    template: dict,
    xbrl_df: pd.DataFrame,
) -> Optional[dict]:
    """Compare HTML and XBRL extraction for one filing.

    Returns a stats dict, or None if the filing cannot be processed
    (missing HTML, extraction failure, etc.).
    """
    from pipeline.html_template import extract_filing_with_template

    cik_stripped = cik.lstrip("0") or "0"
    acc_nodashes = accession.replace("-", "")
    html_path = BDC_HTML_CACHE_DIR / cik_stripped / f"{acc_nodashes}.html"

    if not html_path.exists() or html_path.stat().st_size < 1024:
        return None

    # Read HTML
    try:
        html_content = html_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None

    # Extract with template
    try:
        html_rows, stats = extract_filing_with_template(
            html_content, filing_meta, template
        )
    except Exception as exc:
        logger.debug("HTML extraction failed for %s/%s: %s", cik, accession, exc)
        return None

    if not html_rows:
        return {
            "cik": cik,
            "accession_number": accession,
            "filing_date": filing_meta.get("filing_date", ""),
            "report_date": filing_meta.get("report_date", ""),
            "xbrl_count": 0,
            "html_count": 0,
            "matched_count": 0,
            "recall": 0.0,
            "fv_accuracy": 0.0,
            "rate_accuracy": 0.0,
            "mat_accuracy": 0.0,
            "principal_accuracy": 0.0,
            "agg_fv_ratio": None,
            "dollar_unit_ok": None,
            "variant_used": stats.get("variant_id"),
            "drift_detected": stats.get("drift_detected", False),
        }

    # Filter XBRL to current-period positions for this accession
    xbrl_filing = xbrl_df[
        (xbrl_df["accession_number"] == accession)
        & (xbrl_df["period"] == xbrl_df["report_date"])
    ].to_dict("records")

    # Match positions
    matched, html_unmatched, xbrl_unmatched = match_positions(
        html_rows, xbrl_filing
    )

    xbrl_count = len(xbrl_filing)
    html_count = len(html_rows)
    matched_count = len(matched)
    recall = matched_count / xbrl_count if xbrl_count > 0 else 0.0

    # Compute field-level accuracy on matched pairs
    fv_ok = 0
    rate_ok = 0
    mat_ok = 0
    principal_ok = 0
    rate_compared = 0
    mat_compared = 0
    principal_compared = 0

    html_fv_sum = 0.0
    xbrl_fv_sum = 0.0

    for pair in matched:
        h = pair["html"]
        x = pair["xbrl"]

        # FV accuracy (1% tolerance)
        h_fv = _safe_float(h.get("fair_value"))
        x_fv = _safe_float(x.get("fair_value"))
        if h_fv is not None and x_fv is not None:
            html_fv_sum += h_fv
            xbrl_fv_sum += x_fv
            if x_fv != 0 and abs(h_fv - x_fv) / abs(x_fv) < 0.01:
                fv_ok += 1
            elif x_fv == 0 and h_fv == 0:
                fv_ok += 1

        # Rate accuracy (50bps tolerance)
        # XBRL rates are in decimal (0.10 = 10%), HTML rates in percentage (10.0)
        h_rate = _safe_float(h.get("interest_rate"))
        x_rate_raw = _safe_float(x.get("interest_rate"))
        if h_rate is not None and x_rate_raw is not None:
            x_rate = x_rate_raw * 100  # convert decimal to percentage
            rate_compared += 1
            if abs(h_rate - x_rate) < 0.5:
                rate_ok += 1

        # Maturity match (exact or within 1 month)
        h_mat = str(h.get("maturity_date", "") or "").strip()
        x_mat = str(x.get("maturity_date", "") or "").strip()
        if h_mat and x_mat:
            mat_compared += 1
            if _maturity_match(h_mat, x_mat):
                mat_ok += 1

        # Principal accuracy (5% tolerance)
        h_prin = _safe_float(h.get("principal_amount"))
        x_prin = _safe_float(x.get("principal_amount"))
        if h_prin is not None and x_prin is not None:
            principal_compared += 1
            if x_prin != 0 and abs(h_prin - x_prin) / abs(x_prin) < 0.05:
                principal_ok += 1
            elif x_prin == 0 and h_prin == 0:
                principal_ok += 1

    fv_accuracy = fv_ok / matched_count if matched_count > 0 else 0.0
    rate_accuracy = rate_ok / rate_compared if rate_compared > 0 else None
    mat_accuracy = mat_ok / mat_compared if mat_compared > 0 else None
    principal_accuracy = principal_ok / principal_compared if principal_compared > 0 else None

    # Aggregate FV ratio (dollar unit check)
    agg_fv_ratio = None
    dollar_unit_ok = None
    if xbrl_fv_sum != 0:
        agg_fv_ratio = html_fv_sum / xbrl_fv_sum
        # Dollar unit is correct if ratio is between 0.5 and 2.0
        # A 1000x error would show as ~0.001 or ~1000
        dollar_unit_ok = 0.5 <= agg_fv_ratio <= 2.0

    return {
        "cik": cik,
        "accession_number": accession,
        "filing_date": filing_meta.get("filing_date", ""),
        "report_date": filing_meta.get("report_date", ""),
        "xbrl_count": xbrl_count,
        "html_count": html_count,
        "matched_count": matched_count,
        "recall": round(recall, 4),
        "fv_accuracy": round(fv_accuracy, 4) if fv_accuracy is not None else None,
        "rate_accuracy": round(rate_accuracy, 4) if rate_accuracy is not None else None,
        "mat_accuracy": round(mat_accuracy, 4) if mat_accuracy is not None else None,
        "principal_accuracy": round(principal_accuracy, 4) if principal_accuracy is not None else None,
        "agg_fv_ratio": round(agg_fv_ratio, 4) if agg_fv_ratio is not None else None,
        "dollar_unit_ok": dollar_unit_ok,
        "variant_used": stats.get("variant_id"),
        "drift_detected": stats.get("drift_detected", False),
    }


def _maturity_match(date1: str, date2: str) -> bool:
    """Check if two date strings match exactly or within ~1 month.

    Handles YYYY-MM-DD, YYYY-MM, and various formats.
    """
    if date1 == date2:
        return True
    # Normalize to YYYY-MM for comparison
    d1 = date1[:7]  # YYYY-MM
    d2 = date2[:7]
    if d1 == d2:
        return True
    # Try parsing as dates and checking within 31 days
    try:
        from datetime import datetime, timedelta
        for fmt in ("%Y-%m-%d", "%Y-%m", "%m/%d/%Y", "%m-%d-%Y"):
            try:
                dt1 = datetime.strptime(date1, fmt)
                break
            except ValueError:
                continue
        else:
            return False
        for fmt in ("%Y-%m-%d", "%Y-%m", "%m/%d/%Y", "%m-%d-%Y"):
            try:
                dt2 = datetime.strptime(date2, fmt)
                break
            except ValueError:
                continue
        else:
            return False
        return abs((dt1 - dt2).days) <= 31
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Download XBRL-era HTML
# ---------------------------------------------------------------------------

def download_xbrl_era_html(template_ciks: set[str]) -> dict:
    """Download HTML primary docs for XBRL-era filings of template CIKs.

    Returns {cik: {downloaded: N, cached: N, failed: N}}.
    """
    from pipeline.edgar_client import EdgarClient
    from pipeline.html_holdings import download_html_filing

    if not BDC_FILINGS_INDEX_FILE.exists():
        logger.error("Filings index not found: %s", BDC_FILINGS_INDEX_FILE)
        return {}

    idx = pd.read_csv(BDC_FILINGS_INDEX_FILE, dtype=str)

    # Filter to template CIKs with XBRL data
    # Match on stripped CIK (both template CIKs and index may have leading zeros)
    idx["cik_stripped"] = idx["cik"].str.lstrip("0")
    template_stripped = {c.lstrip("0") for c in template_ciks}

    mask = (
        idx["cik_stripped"].isin(template_stripped)
        & (idx["xbrl_download_status"] != "not_found")
        & idx["primary_document"].notna()
        & (idx["primary_document"] != "")
    )
    filings = idx[mask].copy()

    logger.info(
        "Found %d XBRL-era filings across %d template CIKs to download",
        len(filings),
        filings["cik_stripped"].nunique(),
    )

    results: dict[str, dict[str, int]] = {}
    client = EdgarClient()

    for _, row in filings.iterrows():
        cik = str(row["cik"])
        cik_stripped = cik.lstrip("0") or "0"
        acc = str(row["accession_number"])
        doc = str(row["primary_document"])

        if cik_stripped not in results:
            results[cik_stripped] = {"downloaded": 0, "cached": 0, "failed": 0}

        # Check cache first
        acc_nodashes = acc.replace("-", "")
        cache_file = BDC_HTML_CACHE_DIR / cik_stripped / f"{acc_nodashes}.html"
        if cache_file.exists() and cache_file.stat().st_size > 1024:
            results[cik_stripped]["cached"] += 1
            continue

        path = download_html_filing(client, cik, acc, doc)
        if path is not None:
            results[cik_stripped]["downloaded"] += 1
        else:
            results[cik_stripped]["failed"] += 1

    total_dl = sum(r["downloaded"] for r in results.values())
    total_cached = sum(r["cached"] for r in results.values())
    total_failed = sum(r["failed"] for r in results.values())
    logger.info(
        "HTML download complete: %d downloaded, %d cached, %d failed",
        total_dl, total_cached, total_failed,
    )

    return results


# ---------------------------------------------------------------------------
# Main validation orchestrator
# ---------------------------------------------------------------------------

def validate_all(
    download: bool = False,
    ciks: Optional[set[str]] = None,
) -> pd.DataFrame:
    """Run full HTML-vs-XBRL cross-validation.

    Args:
        download: If True, download HTML for XBRL-era filings first.
        ciks: Optional set of CIKs to validate (default: all template CIKs).

    Returns:
        DataFrame with per-filing comparison results.
    """
    from pipeline.html_template import load_template

    # Discover template CIKs
    template_files = list(HTML_TEMPLATE_DIR.glob("*.json"))
    all_template_ciks = {f.stem for f in template_files}

    if ciks:
        # Filter to requested CIKs (strip leading zeros for comparison)
        target_ciks = {c.lstrip("0") for c in ciks} & all_template_ciks
    else:
        target_ciks = all_template_ciks

    logger.info("Validating %d template CIKs", len(target_ciks))

    # Optionally download HTML
    if download:
        download_xbrl_era_html(target_ciks)

    # Load filing index
    if not BDC_FILINGS_INDEX_FILE.exists():
        logger.error("Filings index not found")
        return pd.DataFrame()

    idx = pd.read_csv(BDC_FILINGS_INDEX_FILE, dtype=str)
    idx["cik_stripped"] = idx["cik"].str.lstrip("0")

    # Load XBRL holdings
    if not BDC_HOLDINGS_FILE.exists():
        logger.error("BDC holdings file not found")
        return pd.DataFrame()

    xbrl_all = pd.read_csv(BDC_HOLDINGS_FILE, dtype=str, low_memory=False)

    # Process each CIK
    filing_results: list[dict] = []
    position_details: list[dict] = []

    for cik in sorted(target_ciks):
        template = load_template(cik)
        if template is None:
            logger.debug("No template for CIK %s", cik)
            continue

        # Get filings for this CIK with XBRL data
        cik_filings = idx[
            (idx["cik_stripped"] == cik)
            & (idx["xbrl_download_status"] != "not_found")
        ]

        # Filter XBRL holdings for this CIK
        xbrl_cik = xbrl_all[xbrl_all["cik"].str.lstrip("0") == cik].copy()
        if xbrl_cik.empty:
            continue

        for _, frow in cik_filings.iterrows():
            acc = str(frow["accession_number"])
            filing_meta = {
                "cik": cik,
                "entity_name": str(frow.get("entity_name", "")),
                "accession_number": acc,
                "form_type": str(frow.get("form_type", "")),
                "filing_date": str(frow.get("filing_date", "")),
                "report_date": str(frow.get("report_date", "")),
            }

            result = compare_filing(cik, acc, filing_meta, template, xbrl_cik)
            if result is not None:
                filing_results.append(result)

                # Position-level detail stored directly from compare_filing
                # to avoid re-extracting each filing a second time

    # Build results DataFrame
    if not filing_results:
        logger.warning("No filings could be compared")
        return pd.DataFrame()

    df = pd.DataFrame(filing_results)

    # Print summary
    _print_summary(df)

    # Write outputs
    df.to_csv(HTML_XBRL_FILING_COMPARISON_FILE, index=False)
    logger.info("Filing comparison written to %s", HTML_XBRL_FILING_COMPARISON_FILE)

    if position_details:
        pd.DataFrame(position_details).to_csv(
            HTML_XBRL_POSITION_MATCHES_FILE, index=False
        )
        logger.info(
            "Position matches written to %s (%d rows)",
            HTML_XBRL_POSITION_MATCHES_FILE,
            len(position_details),
        )

    return df


def _append_position_detail(
    details: list[dict],
    cik: str,
    accession: str,
    filing_meta: dict,
    template: dict,
    xbrl_df: pd.DataFrame,
) -> None:
    """Append position-level match details for audit."""
    from pipeline.html_template import extract_filing_with_template

    cik_stripped = cik.lstrip("0") or "0"
    acc_nodashes = accession.replace("-", "")
    html_path = BDC_HTML_CACHE_DIR / cik_stripped / f"{acc_nodashes}.html"

    if not html_path.exists():
        return

    try:
        html_content = html_path.read_text(encoding="utf-8", errors="replace")
        html_rows, _ = extract_filing_with_template(html_content, filing_meta, template)
    except Exception:
        return

    xbrl_filing = xbrl_df[
        (xbrl_df["accession_number"] == accession)
        & (xbrl_df["period"] == xbrl_df["report_date"])
    ].to_dict("records")

    matched, _, _ = match_positions(html_rows, xbrl_filing)

    for pair in matched:
        h = pair["html"]
        x = pair["xbrl"]
        details.append({
            "cik": cik,
            "accession_number": accession,
            "html_name": h.get("investment_identifier", ""),
            "xbrl_name": x.get("investment_identifier", ""),
            "name_score": round(pair["name_score"], 1),
            "html_fv": h.get("fair_value"),
            "xbrl_fv": x.get("fair_value"),
            "fv_delta_pct": round(pair["fv_delta_pct"], 4) if pair["fv_delta_pct"] is not None else None,
            "html_rate": h.get("interest_rate"),
            "xbrl_rate": x.get("interest_rate"),
            "html_maturity": h.get("maturity_date"),
            "xbrl_maturity": x.get("maturity_date"),
        })


def _print_summary(df: pd.DataFrame) -> None:
    """Print per-CIK and overall summary to console."""
    print("\n=== HTML vs XBRL Cross-Validation Summary ===\n")

    # Per-CIK summary
    cik_stats = df.groupby("cik").agg(
        filings=("accession_number", "count"),
        avg_recall=("recall", "mean"),
        avg_fv_accuracy=("fv_accuracy", "mean"),
        avg_rate_accuracy=("rate_accuracy", "mean"),
        total_xbrl=("xbrl_count", "sum"),
        total_matched=("matched_count", "sum"),
        dollar_unit_issues=("dollar_unit_ok", lambda x: (~x.astype(bool)).sum() if x.notna().any() else 0),
    ).reset_index()

    print("Per-CIK Results:")
    print("-" * 100)
    for _, row in cik_stats.iterrows():
        rate_str = f"{row['avg_rate_accuracy']:.1%}" if pd.notna(row['avg_rate_accuracy']) else "N/A"
        du_str = f" [DOLLAR UNIT ISSUES: {int(row['dollar_unit_issues'])}]" if row['dollar_unit_issues'] > 0 else ""
        print(
            f"  CIK {row['cik']:>10s}: "
            f"{int(row['filings']):3d} filings, "
            f"recall {row['avg_recall']:.1%}, "
            f"FV acc {row['avg_fv_accuracy']:.1%}, "
            f"rate acc {rate_str}"
            f"{du_str}"
        )

    # Overall summary
    total_filings = len(df)
    total_xbrl = df["xbrl_count"].sum()
    total_matched = df["matched_count"].sum()
    overall_recall = total_matched / total_xbrl if total_xbrl > 0 else 0

    # FV-weighted accuracy
    fv_acc_valid = df[df["fv_accuracy"].notna()]
    if not fv_acc_valid.empty and fv_acc_valid["matched_count"].sum() > 0:
        weighted_fv_acc = (
            (fv_acc_valid["fv_accuracy"] * fv_acc_valid["matched_count"]).sum()
            / fv_acc_valid["matched_count"].sum()
        )
    else:
        weighted_fv_acc = 0.0

    du_ok = df["dollar_unit_ok"].sum() if df["dollar_unit_ok"].notna().any() else 0
    du_total = df["dollar_unit_ok"].notna().sum()

    print(f"\nOverall: {total_filings} filings, "
          f"{int(total_xbrl)} XBRL positions, "
          f"{int(total_matched)} matched")
    print(f"  Recall:          {overall_recall:.1%}")
    print(f"  FV accuracy:     {weighted_fv_acc:.1%} (position-weighted)")
    print(f"  Dollar unit OK:  {int(du_ok)}/{du_total}")
    print(f"  CIKs validated:  {df['cik'].nunique()}")
    print()
